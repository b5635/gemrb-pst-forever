// SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "Sprite2D.h"

#include "Video/RLE.h"

#include <utility>

namespace GemRB {

const TypeID Sprite2D::ID = { "Sprite2D" };

Sprite2D::Iterator Sprite2D::GetIterator(IPixelIterator::Direction xdir, IPixelIterator::Direction ydir)
{
	return GetIterator(xdir, ydir, Region(Point(), Frame.size));
}

Sprite2D::Iterator Sprite2D::GetIterator(IPixelIterator::Direction xdir, IPixelIterator::Direction ydir,
					 const Region& clip)
{
	if (renderFlags & BlitFlags::MIRRORX) xdir = IPixelIterator::Direction(int(xdir) * -1);
	if (renderFlags & BlitFlags::MIRRORY) ydir = IPixelIterator::Direction(int(ydir) * -1);
	return Iterator(pixels, pitch, format, xdir, ydir, clip);
}

Sprite2D::Iterator Sprite2D::GetIterator(IPixelIterator::Direction xdir, IPixelIterator::Direction ydir) const
{
	return GetIterator(xdir, ydir, Region(Point(), Frame.size));
}

Sprite2D::Iterator Sprite2D::GetIterator(IPixelIterator::Direction xdir, IPixelIterator::Direction ydir,
					 const Region& clip) const
{
	if (renderFlags & BlitFlags::MIRRORX) xdir = IPixelIterator::Direction(int(xdir) * -1);
	if (renderFlags & BlitFlags::MIRRORY) ydir = IPixelIterator::Direction(int(ydir) * -1);
	return Iterator(pixels, pitch, format, xdir, ydir, clip);
}

Sprite2D::Sprite2D(const Region& rgn, void* pixels, const PixelFormat& fmt, uint16_t pitch) noexcept
	: pixels(pixels), freePixels(pixels), format(fmt), pitch(pitch), Frame(rgn)
{}

Sprite2D::Sprite2D(const Region& frame, void* pixels, const PixelFormat& fmt) noexcept
	: Sprite2D(frame, pixels, fmt, frame.w)
{}

Sprite2D::Sprite2D(const Sprite2D& obj) noexcept
	: Sprite2D(obj.Frame, obj.pixels, obj.format, obj.pitch)
{
	renderFlags = obj.renderFlags;
	hiRes = obj.hiRes;
	freePixels = false;
}

Sprite2D::Sprite2D(Sprite2D&& obj) noexcept
	: Sprite2D(obj.Frame, obj.pixels, obj.format, obj.pitch)
{
	renderFlags = obj.renderFlags;
	hiRes = std::move(obj.hiRes);
}

Sprite2D::~Sprite2D() noexcept
{
	if (freePixels) {
		free(pixels);
	}
}

Color Sprite2D::GetPixel(const Point& p) const noexcept
{
	if (Region(0, 0, Frame.w, Frame.h).PointInside(p)) {
		Iterator it = GetIterator();
		it.Advance(p.y * Frame.w + p.x);
		return it.ReadRGBA();
	}
	return Color();
}

bool Sprite2D::HasTransparency() const noexcept
{
	return format.HasColorKey || format.Amask;
}

bool Sprite2D::IsPixelTransparent(const Point& p) const noexcept
{
	if (HasTransparency()) {
		return GetPixel(p).a == 0;
	}
	return false;
}

const void* Sprite2D::LockSprite() const
{
	return pixels;
}

void* Sprite2D::LockSprite()
{
	// writable access can change the pixels the twin was built from
	hiRes.reset();
	return pixels;
}

void Sprite2D::SetPalette(const Holder<Palette>& pal)
{
	assert(format.Bpp == 1);
	assert(pal != nullptr);

	if (pal == format.palette) return;
	// a different palette means the upscale no longer matches what will be drawn
	hiRes.reset();

	if (format.RLE) {
		format.palette = pal;
	} else {
		// we don't use shared palettes because it is a performance bottleneck on SDL2
		format.palette = MakeHolder<Palette>(*pal);
	}

	UpdatePalette();
}

void Sprite2D::SetColorKey(colorkey_t key)
{
	format.ColorKey = key;
	UpdateColorKey();
}

bool Sprite2D::ConvertFormatTo(const PixelFormat& newfmt) noexcept
{
	// we rely on the subclasses to handle most format conversions
	if (format.RLE && newfmt.RLE == false && newfmt.Bpp == 1) {
		uint8_t* rledata = static_cast<uint8_t*>(pixels);
		pixels = DecodeRLEData(rledata, Frame.size, format.ColorKey);
		if (freePixels) {
			free(rledata);
		} else {
			freePixels = true;
		}
		format = newfmt;
		assert(format.palette);
		hiRes.reset();
		return true;
	}
	return false;
}

}
