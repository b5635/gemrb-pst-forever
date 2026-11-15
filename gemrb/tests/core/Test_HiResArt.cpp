// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "../../core/HiResArt.h"

#include "System/VFS.h"

#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <vector>

#include <gtest/gtest.h>

namespace GemRB {

static uint32_t Adler32(const uint8_t* data, size_t len)
{
	uint32_t a = 1;
	uint32_t b = 0;
	for (size_t i = 0; i < len; ++i) {
		a = (a + data[i]) % 65521u;
		b = (b + a) % 65521u;
	}
	return (b << 16) | a;
}

static uint32_t Crc32(const uint8_t* data, size_t n)
{
	static uint32_t table[256];
	static bool ready = false;
	if (!ready) {
		for (uint32_t i = 0; i < 256; ++i) {
			uint32_t c = i;
			for (int k = 0; k < 8; ++k) {
				c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
			}
			table[i] = c;
		}
		ready = true;
	}
	uint32_t c = 0xFFFFFFFFu;
	for (size_t i = 0; i < n; ++i) {
		c = table[(c ^ data[i]) & 0xFFu] ^ (c >> 8);
	}
	return c ^ 0xFFFFFFFFu;
}

static void Be32(std::vector<uint8_t>& out, uint32_t value)
{
	out.push_back(uint8_t(value >> 24));
	out.push_back(uint8_t(value >> 16));
	out.push_back(uint8_t(value >> 8));
	out.push_back(uint8_t(value));
}

static void Chunk(std::vector<uint8_t>& out, const char* type, const uint8_t* data, size_t n)
{
	Be32(out, uint32_t(n));
	size_t at = out.size();
	out.insert(out.end(), type, type + 4);
	out.insert(out.end(), data, data + n);
	Be32(out, Crc32(out.data() + at, 4 + n));
}

// 8-bit non-interlaced RGBA, one stored zlib block. HiResArt reads this without libpng.
static void WriteStoredPng(const path_t& path, int w, int h)
{
	std::vector<uint8_t> raw;
	raw.reserve(size_t(h) * (1 + w * 4));
	for (int y = 0; y < h; ++y) {
		raw.push_back(0);
		for (int x = 0; x < w; ++x) {
			raw.push_back(uint8_t(x));
			raw.push_back(uint8_t(y));
			raw.push_back(200);
			raw.push_back(255);
		}
	}
	std::vector<uint8_t> zlib;
	zlib.push_back(0x78);
	zlib.push_back(0x01);
	zlib.push_back(0x01);
	uint16_t len = uint16_t(raw.size());
	zlib.push_back(uint8_t(len));
	zlib.push_back(uint8_t(len >> 8));
	uint16_t nlen = uint16_t(~len);
	zlib.push_back(uint8_t(nlen));
	zlib.push_back(uint8_t(nlen >> 8));
	zlib.insert(zlib.end(), raw.begin(), raw.end());
	Be32(zlib, Adler32(raw.data(), raw.size()));

	uint8_t ihdr[13] = {};
	ihdr[0] = uint8_t(w >> 24);
	ihdr[1] = uint8_t(w >> 16);
	ihdr[2] = uint8_t(w >> 8);
	ihdr[3] = uint8_t(w);
	ihdr[4] = uint8_t(h >> 24);
	ihdr[5] = uint8_t(h >> 16);
	ihdr[6] = uint8_t(h >> 8);
	ihdr[7] = uint8_t(h);
	ihdr[8] = 8;
	ihdr[9] = 6;

	std::vector<uint8_t> png = { 137, 80, 78, 71, 13, 10, 26, 10 };
	Chunk(png, "IHDR", ihdr, 13);
	Chunk(png, "IDAT", zlib.data(), zlib.size());
	uint8_t end = 0;
	Chunk(png, "IEND", &end, 0);

	std::ofstream file(path.c_str(), std::ios::binary);
	file.write(reinterpret_cast<const char*>(png.data()), std::streamsize(png.size()));
}

// 8-bit indexed, stored zlib, 256-entry PLTE. Colour of index i is (i, 40, 200).
static void WriteStoredIndexedPng(const path_t& path, int w, int h)
{
	std::vector<uint8_t> raw;
	raw.reserve(size_t(h) * (1 + w));
	for (int y = 0; y < h; ++y) {
		raw.push_back(0);
		for (int x = 0; x < w; ++x) {
			raw.push_back(uint8_t((x + y) & 255));
		}
	}
	std::vector<uint8_t> zlib;
	zlib.push_back(0x78);
	zlib.push_back(0x01);
	zlib.push_back(0x01);
	uint16_t len = uint16_t(raw.size());
	zlib.push_back(uint8_t(len));
	zlib.push_back(uint8_t(len >> 8));
	uint16_t nlen = uint16_t(~len);
	zlib.push_back(uint8_t(nlen));
	zlib.push_back(uint8_t(nlen >> 8));
	zlib.insert(zlib.end(), raw.begin(), raw.end());
	Be32(zlib, Adler32(raw.data(), raw.size()));

	uint8_t ihdr[13] = {};
	ihdr[0] = uint8_t(w >> 24);
	ihdr[1] = uint8_t(w >> 16);
	ihdr[2] = uint8_t(w >> 8);
	ihdr[3] = uint8_t(w);
	ihdr[4] = uint8_t(h >> 24);
	ihdr[5] = uint8_t(h >> 16);
	ihdr[6] = uint8_t(h >> 8);
	ihdr[7] = uint8_t(h);
	ihdr[8] = 8;
	ihdr[9] = 3;

	std::vector<uint8_t> plte(256 * 3);
	for (int i = 0; i < 256; ++i) {
		plte[i * 3] = uint8_t(i);
		plte[i * 3 + 1] = 40;
		plte[i * 3 + 2] = 200;
	}

	std::vector<uint8_t> png = { 137, 80, 78, 71, 13, 10, 26, 10 };
	Chunk(png, "IHDR", ihdr, 13);
	Chunk(png, "PLTE", plte.data(), plte.size());
	Chunk(png, "IDAT", zlib.data(), zlib.size());
	uint8_t end = 0;
	Chunk(png, "IEND", &end, 0);

	std::ofstream file(path.c_str(), std::ios::binary);
	file.write(reinterpret_cast<const char*>(png.data()), std::streamsize(png.size()));
}

static Holder<Sprite2D> MakeIndexed(int w, int h)
{
	auto fmt = PixelFormat::Paletted8Bit(MakeHolder<Palette>());
	auto* pixels = static_cast<uint8_t*>(calloc(size_t(w) * h, 1));
	return MakeHolder<Sprite2D>(Region(0, 0, w, h), pixels, fmt);
}

TEST(HiResArt, Attach)
{
	// relative: MakeDirectories rejects "C:" as the first component of an absolute path
	path_t root = PathJoin("tools", "upscale", "work", "hires-test");
	path_t dir = PathJoin(root, "gui", "mos");
	ASSERT_TRUE(MakeDirectories(dir)) << dir;
	// both files exist before the first lookup, so the directory cache sees them
	WriteStoredPng(PathJoin(dir, "BOX.png"), 8, 8);
	WriteStoredPng(PathJoin(dir, "BAD.png"), 6, 6);
	WriteStoredIndexedPng(PathJoin(dir, "BOX.idx.png"), 8, 8);
	HiResArt::SetRoot(root);

	Holder<Sprite2D> spr = MakeIndexed(4, 4);
	HiResArt::Attach(spr, "gui/mos/NOPE.png");
	EXPECT_EQ(spr->hiRes.get(), nullptr);

	HiResArt::Attach(spr, "gui/mos/BAD.png");
	EXPECT_EQ(spr->hiRes.get(), nullptr);

	HiResArt::Attach(spr, "gui/mos/BOX.png");
	ASSERT_NE(spr->hiRes.get(), nullptr);
	EXPECT_EQ(spr->hiRes->Frame.x, 0);
	EXPECT_EQ(spr->hiRes->Frame.y, 0);
	EXPECT_EQ(spr->hiRes->Frame.w, 8);
	EXPECT_EQ(spr->hiRes->Frame.h, 8);
	ASSERT_NE(spr->hiResIndex.get(), nullptr);
	EXPECT_EQ(spr->hiResIndex->Format().Bpp, 1);
	EXPECT_EQ(spr->hiResIndex->Frame.w, 8);
	EXPECT_EQ(spr->hiResIndex->Frame.h, 8);

	Holder<Sprite2D> copy = spr->copy();
	EXPECT_EQ(copy->hiRes.get(), spr->hiRes.get());
	EXPECT_EQ(copy->hiResIndex.get(), spr->hiResIndex.get());

	const Sprite2D* view = spr.get();
	view->LockSprite();
	EXPECT_NE(spr->hiRes.get(), nullptr);
	EXPECT_NE(spr->hiResIndex.get(), nullptr);
	spr->LockSprite();
	EXPECT_EQ(spr->hiRes.get(), nullptr);
	EXPECT_EQ(spr->hiResIndex.get(), nullptr);

	HiResArt::Attach(spr, "gui/mos/BOX.png");
	ASSERT_NE(spr->hiRes.get(), nullptr);
	ASSERT_NE(spr->hiResIndex.get(), nullptr);
	spr->SetPalette(spr->GetPalette());
	EXPECT_NE(spr->hiRes.get(), nullptr);
	EXPECT_NE(spr->hiResIndex.get(), nullptr);
	spr->SetPalette(MakeHolder<Palette>());
	EXPECT_NE(spr->hiRes.get(), nullptr);
	EXPECT_NE(spr->hiResIndex.get(), nullptr);

	EXPECT_EQ(HiResArt::Stem("ar0202.tis"), "AR0202");
	EXPECT_EQ(HiResArt::Stem("  Foo.BAM  "), "FOO");
}

}
