// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "GLSprite2D.h"

#include <cstdlib>
#include <cstring>
#include <vector>

namespace GemRB {

static void* AllocPixels(const Region& r, const PixelFormat& fmt)
{
	size_t bytes = size_t(std::max(r.w, 0)) * std::max(r.h, 0) * std::max<int>(fmt.Bpp, 1);
	return calloc(std::max<size_t>(bytes, 1), 1);
}

// fill in shift/loss from the masks: some importers only pass masks, and the
// engine's pixel iterators (GetPixel, palette gradients...) rely on the shifts
static PixelFormat Normalize(PixelFormat fmt)
{
	if (fmt.Bpp <= 1) return fmt;
	auto fill = [](uint32_t mask, uint8_t& shift, uint8_t& loss) {
		if (!mask) {
			shift = 0;
			loss = 8;
			return;
		}
		int s = 0;
		while (!((mask >> s) & 1)) ++s;
		int bits = 0;
		while ((mask >> (s + bits)) & 1) ++bits;
		shift = uint8_t(s);
		loss = uint8_t(bits >= 8 ? 0 : 8 - bits);
	};
	fill(fmt.Rmask, fmt.Rshift, fmt.Rloss);
	fill(fmt.Gmask, fmt.Gshift, fmt.Gloss);
	fill(fmt.Bmask, fmt.Bshift, fmt.Bloss);
	fill(fmt.Amask, fmt.Ashift, fmt.Aloss);
	return fmt;
}

GLSprite2D::GLSprite2D(const Region& rgn, void* px, const PixelFormat& fmt) noexcept
	: Sprite2D(rgn, px ? px : AllocPixels(rgn, fmt), Normalize(fmt), uint16_t(rgn.w * std::max<int>(fmt.Bpp, 1)))
{
	freePixels = true;
}

GLSprite2D::GLSprite2D(const GLSprite2D& other) noexcept
	: Sprite2D(other.Frame, AllocPixels(other.Frame, other.format), other.format, other.pitch)
{
	freePixels = true;
	renderFlags = other.renderFlags;
	if (other.format.palette) {
		format.palette = MakeHolder<Palette>(*other.format.palette);
	}
	memcpy(pixels, other.pixels, size_t(pitch) * Frame.h);
}

GLSprite2D::~GLSprite2D() noexcept
{
	if (texture) glDeleteTextures(1, &texture);
}

Holder<Sprite2D> GLSprite2D::copy() const
{
	return MakeHolder<GLSprite2D>(*this);
}

void* GLSprite2D::LockSprite()
{
	// writable access: assume the caller changes pixels
	dirty = true;
	return pixels;
}

const void* GLSprite2D::LockSprite() const
{
	return pixels;
}

void GLSprite2D::UnlockSprite()
{
	dirty = true;
}

bool GLSprite2D::ConvertFormatTo(const PixelFormat& newfmt) noexcept
{
	if (Sprite2D::ConvertFormatTo(newfmt)) {
		pitch = uint16_t(Frame.w);
		dirty = true;
		return true;
	}
	if (newfmt.Bpp == 4 && !format.RLE) {
		uint32_t* rgba = static_cast<uint32_t*>(malloc(size_t(Frame.w) * Frame.h * 4));
		ConvertToRGBA8(pixels, Frame.w, Frame.h, pitch, format, rgba);
		if (freePixels) free(pixels);
		pixels = rgba;
		freePixels = true;
		format = Normalize(PixelFormat(4, 0x000000ff, 0x0000ff00, 0x00ff0000, 0xff000000));
		pitch = uint16_t(Frame.w * 4);
		dirty = true;
		return true;
	}
	return false;
}

// channel position and width derived from the mask itself: not every
// PixelFormat constructor fills in the shift/loss fields
struct Channel {
	uint32_t mask = 0;
	int shift = 0;
	uint32_t max = 0;
	explicit Channel(uint32_t m)
		: mask(m)
	{
		if (!m) return;
		while (!((m >> shift) & 1)) ++shift;
		max = m >> shift;
	}
	uint8_t operator()(uint32_t px) const
	{
		if (!mask) return 0;
		uint32_t v = (px & mask) >> shift;
		if (max == 255) return uint8_t(v);
		return uint8_t((v * 255 + (max >> 1)) / max);
	}
};

void ConvertToRGBA8(const void* src, int w, int h, int srcPitch, const PixelFormat& fmt, uint32_t* dst)
{
	const Channel cr(fmt.Rmask), cg(fmt.Gmask), cb(fmt.Bmask), ca(fmt.Amask);
	const uint8_t* row = static_cast<const uint8_t*>(src);
	for (int y = 0; y < h; ++y, row += srcPitch) {
		uint32_t* out = dst + size_t(y) * w;
		for (int x = 0; x < w; ++x) {
			uint32_t px = 0;
			const uint8_t* p = row + x * fmt.Bpp;
			switch (fmt.Bpp) {
				case 1:
					px = *p;
					break;
				case 2:
					px = uint32_t(p[0]) | (uint32_t(p[1]) << 8);
					break;
				case 3:
					px = uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16);
					break;
				default:
					memcpy(&px, p, 4);
					break;
			}
			uint8_t r, g, b, a;
			if (fmt.Bpp == 1 && fmt.palette) {
				const Color& c = fmt.palette->GetColorAt(px);
				r = c.r;
				g = c.g;
				b = c.b;
				a = c.a;
			} else {
				r = cr(px);
				g = cg(px);
				b = cb(px);
				a = fmt.Amask ? ca(px) : 0xff;
			}
			if (fmt.HasColorKey && px == fmt.ColorKey) a = 0;
			out[x] = uint32_t(r) | (uint32_t(g) << 8) | (uint32_t(b) << 16) | (uint32_t(a) << 24);
		}
	}
}

GLuint GLSprite2D::GetTexture(bool& uploaded) const
{
	uploaded = false;
	if (texture && !dirty) return texture;
	if (Frame.w <= 0 || Frame.h <= 0) return 0;

	bool created = false;
	if (!texture) {
		glGenTextures(1, &texture);
		created = true;
	}
	glBindTexture(GL_TEXTURE_2D, texture);
	glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
	if (format.Bpp == 1) {
		if (created) {
			glTexImage2D(GL_TEXTURE_2D, 0, GL_R8UI, Frame.w, Frame.h, 0, GL_RED_INTEGER, GL_UNSIGNED_BYTE, pixels);
		} else {
			glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, Frame.w, Frame.h, GL_RED_INTEGER, GL_UNSIGNED_BYTE, pixels);
		}
	} else {
		std::vector<uint32_t> rgba(size_t(Frame.w) * Frame.h);
		ConvertToRGBA8(pixels, Frame.w, Frame.h, pitch, format, rgba.data());
		if (created) {
			glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, Frame.w, Frame.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
		} else {
			glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, Frame.w, Frame.h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
		}
	}
	if (created) {
		// filtering is done in the shader (after the palette lookup), so sample texels exactly
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
		glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	}
	dirty = false;
	uploaded = true;
	return texture;
}

}
