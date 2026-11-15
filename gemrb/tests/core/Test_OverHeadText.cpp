// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "Scriptable/OverHeadText.h"

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

}
