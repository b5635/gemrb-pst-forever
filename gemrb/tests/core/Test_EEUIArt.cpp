// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "../../core/HiResArt.h"

#include "GUI/MapControl.h"

#include <cstdint>
#include <cstdlib>

#include <gtest/gtest.h>

namespace GemRB {

// ARGB32 in memory as the importers make it
static Holder<Sprite2D> MakeSprite(int w, int h, int x, int y, uint32_t (*pixel)(int, int))
{
	auto* data = static_cast<uint32_t*>(malloc(size_t(w) * h * 4));
	for (int j = 0; j < h; ++j) {
		for (int i = 0; i < w; ++i) {
			data[j * w + i] = pixel(i, j);
		}
	}
	return MakeHolder<Sprite2D>(Region(x, y, w, h), data, PixelFormat::ARGB32Bit(), uint16_t(w * 4));
}

static uint32_t Px(const Sprite2D& spr, int x, int y)
{
	const auto* data = static_cast<const uint32_t*>(spr.LockSprite());
	return data[y * spr.Frame.w + x];
}

static uint32_t Opaque(int, int)
{
	return 0xFF000000u | (200u << 16) | (100u << 8) | 50u;
}

TEST(EEUIArt, FromFullResGeometry)
{
	auto full = MakeSprite(7, 5, 0, 0, Opaque);
	auto low = HiResArt::FromFullRes(full, 3);
	ASSERT_TRUE(low);
	ASSERT_TRUE(low->hiRes);
	EXPECT_EQ(low->Frame.w, 3);
	EXPECT_EQ(low->Frame.h, 2);
	EXPECT_EQ(low->hiRes->Frame.w, 9);
	EXPECT_EQ(low->hiRes->Frame.h, 6);
	// integer scale >= 2 on both axes: what the GL driver accepts as a twin
	EXPECT_EQ(low->hiRes->Frame.w / low->Frame.w, 3);
	EXPECT_EQ(low->hiRes->Frame.h / low->Frame.h, 3);
}

TEST(EEUIArt, FromFullResPaddingAndAlpha)
{
	auto full = MakeSprite(7, 5, 0, 0, Opaque);
	auto low = HiResArt::FromFullRes(full, 3);
	ASSERT_TRUE(low && low->hiRes);
	const Sprite2D& hi = *low->hiRes;
	// padding on the right and bottom is transparent, the source is copied unchanged
	EXPECT_EQ(Px(hi, 6, 4), Opaque(0, 0));
	EXPECT_EQ(Px(hi, 7, 0) >> 24, 0u);
	EXPECT_EQ(Px(hi, 8, 5) >> 24, 0u);
	EXPECT_EQ(Px(hi, 0, 5) >> 24, 0u);
	// the first logical pixel covers 9 opaque texels, colour unchanged
	EXPECT_EQ(Px(*low, 0, 0), Opaque(0, 0));
	// the last column covers 1 source column of 3: alpha 1/3, colour still the source colour
	uint32_t corner = Px(*low, 2, 0);
	EXPECT_EQ(corner & 0x00FFFFFFu, Opaque(0, 0) & 0x00FFFFFFu);
	EXPECT_EQ(corner >> 24, 85u);
	// the bottom-right block holds 1 column x 2 rows = 2 of 9 texels: alpha 510 / 9 rounded
	EXPECT_EQ(Px(*low, 2, 1) >> 24, 57u);
}

static uint32_t Checker(int x, int y)
{
	return ((x + y) & 1) ? 0xFFFFFFFFu : 0xFF000000u;
}

TEST(EEUIArt, FromFullResAveragesColour)
{
	auto full = MakeSprite(4, 4, 0, 0, Checker);
	auto low = HiResArt::FromFullRes(full, 2);
	ASSERT_TRUE(low);
	uint32_t p = Px(*low, 0, 0);
	EXPECT_EQ(p >> 24, 255u);
	EXPECT_NEAR(double((p >> 16) & 0xFF), 128.0, 1.0);
}

TEST(EEUIArt, FromFullResOffsetRounding)
{
	// BAM centres are divided by k and rounded: 100/3 = 33.3 -> 33, 101/3 -> 34, -100/3 -> -33
	EXPECT_EQ(HiResArt::FromFullRes(MakeSprite(6, 6, 100, 101, Opaque), 3)->Frame.x, 33);
	EXPECT_EQ(HiResArt::FromFullRes(MakeSprite(6, 6, 100, 101, Opaque), 3)->Frame.y, 34);
	EXPECT_EQ(HiResArt::FromFullRes(MakeSprite(6, 6, -100, 0, Opaque), 3)->Frame.x, -33);
}

TEST(EEUIArt, FromFullResLeavesOtherInputAlone)
{
	auto full = MakeSprite(6, 6, 0, 0, Opaque);
	EXPECT_EQ(HiResArt::FromFullRes(full, 1), full);
	EXPECT_EQ(HiResArt::FromFullRes(nullptr, 3), nullptr);
}

TEST(EEUIArt, MapFitKeepsAspectAndCentres)
{
	// 800x600 map in a 400x400 control: 400x300, centred vertically
	Region r = MapControl::FitRegion(Size(800, 600), Size(400, 400));
	EXPECT_EQ(r.w, 400);
	EXPECT_EQ(r.h, 300);
	EXPECT_EQ(r.x, 0);
	EXPECT_EQ(r.y, 50);
	// a tall map in a wide control: limited by height
	r = MapControl::FitRegion(Size(300, 600), Size(500, 300));
	EXPECT_EQ(r.h, 300);
	EXPECT_EQ(r.w, 150);
	EXPECT_EQ(r.x, 175);
	EXPECT_EQ(r.y, 0);
	// the game<->map mapping uses the region size: a point survives the round trip
	const Size mapsize(2000, 1500);
	r = MapControl::FitRegion(Size(480, 360), Size(780, 600));
	const Point game(1234, 987);
	Point onMap(int(game.x * double(r.w) / mapsize.w), int(game.y * double(r.h) / mapsize.h));
	Point back(int(onMap.x * double(mapsize.w) / r.w), int(onMap.y * double(mapsize.h) / r.h));
	EXPECT_NEAR(back.x, game.x, 2.0 * mapsize.w / r.w); // two truncations
	EXPECT_NEAR(back.y, game.y, 2.0 * mapsize.h / r.h);
}

}
