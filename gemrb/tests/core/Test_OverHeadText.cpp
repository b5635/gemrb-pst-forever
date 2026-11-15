// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "Scriptable/OverHeadText.h"
#include "Scriptable/Scriptable.h"

#include <gtest/gtest.h>

namespace GemRB {

TEST(OverHeadText, DurationAtLeast)
{
	EXPECT_EQ(OverHeadText::DurationAtLeast(0), OverHeadText::DefaultDurationMs);
	EXPECT_EQ(OverHeadText::DurationAtLeast(1), OverHeadText::DefaultDurationMs);
	EXPECT_EQ(OverHeadText::DurationAtLeast(OverHeadText::DefaultDurationMs), OverHeadText::DefaultDurationMs);
	EXPECT_EQ(OverHeadText::DurationAtLeast(OverHeadText::DefaultDurationMs + 1), OverHeadText::DefaultDurationMs + 1);
	EXPECT_EQ(OverHeadText::DurationAtLeast(20000), 20000);
}

TEST(OverHeadText, ShouldScroll)
{
	Point invalid { -1, -1 };
	Point queued { 0, 100 };

	EXPECT_FALSE(OverHeadText::ShouldScroll(ST_TRIGGER, queued));
	EXPECT_FALSE(OverHeadText::ShouldScroll(ST_TRIGGER, invalid));
	EXPECT_FALSE(OverHeadText::ShouldScroll(ST_AREA, queued));
	EXPECT_FALSE(OverHeadText::ShouldScroll(ST_ACTOR, invalid));
	EXPECT_TRUE(OverHeadText::ShouldScroll(ST_ACTOR, queued));
}

}
