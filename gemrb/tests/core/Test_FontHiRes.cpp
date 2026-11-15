// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "GUI/TextSystem/Font.h"

#include "Sprite2D.h"

#include <cstdint>
#include <cstdlib>
#include <cstring>

#include <gtest/gtest.h>

namespace GemRB {

class FontHiResTest : public testing::Test {
protected:
	static Holder<Sprite2D> Indexed(int w, int h, uint8_t value)
	{
		auto px = static_cast<uint8_t*>(malloc(size_t(w) * h));
		memset(px, value, size_t(w) * h);
		auto pal = MakeHolder<Palette>();
		PixelFormat fmt = PixelFormat::Paletted8Bit(pal, true, 0);
		return MakeHolder<Sprite2D>(Region(0, 0, w, h), px, fmt);
	}

	static const Sprite2D* Finish(Font& font)
	{
		font.EnsurePages();
		return font.FirstPage();
	}
};

TEST_F(FontHiResTest, IndexedTwinScalesThePage)
{
	auto pal = MakeHolder<Palette>();
	Font font(pal, 4, 0, false);
	auto spr = FontHiResTest::Indexed(4, 4, 255);
	spr->hiRes = FontHiResTest::Indexed(8, 8, 200);

	font.CreateGlyphForCharSprite(u'A', spr);
	EXPECT_NE(spr->hiRes.get(), nullptr);

	const Sprite2D* sheet = FontHiResTest::Finish(font);
	ASSERT_NE(sheet, nullptr);
	ASSERT_NE(sheet->hiRes.get(), nullptr);
	EXPECT_EQ(sheet->hiRes->Frame.w, 2048);
	EXPECT_EQ(sheet->hiRes->Frame.h, 8);

	const auto* hi = static_cast<const uint8_t*>(static_cast<const Sprite2D*>(sheet->hiRes.get())->LockSprite());
	EXPECT_EQ(hi[0], 200);
	const auto* low = static_cast<const uint8_t*>(static_cast<const Sprite2D*>(sheet)->LockSprite());
	EXPECT_EQ(low[0], 255);
	// the rest of the first row, past the 8px glyph, stays the colour key
	EXPECT_EQ(hi[8], 0);
}

TEST_F(FontHiResTest, MissingOrWrongTwinIsIgnored)
{
	auto pal = MakeHolder<Palette>();
	Font font(pal, 4, 0, false);
	auto spr = FontHiResTest::Indexed(4, 4, 255);
	spr->hiRes = FontHiResTest::Indexed(6, 6, 200);

	font.CreateGlyphForCharSprite(u'A', spr);
	const Sprite2D* sheet = FontHiResTest::Finish(font);
	ASSERT_NE(sheet, nullptr);
	EXPECT_EQ(sheet->hiRes.get(), nullptr);
}

}
