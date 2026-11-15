// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "DisplayMessage.h"

#include <gtest/gtest.h>

namespace GemRB {

TEST(DisplayMessageTest, PstFeedbackOffsetFollowsPartySpecifics)
{
	// strings.2da flag 2: TNO, Morte, Annah, Dak'kon, Grace, Nordom, Ignus, Vhailor, anyone else
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(2, 2), 0); // TNO -> CRITICAL_HIT 35709
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(9, 2), 1); // Morte
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(8, 2), 2); // Annah
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(7, 2), 3); // Dak'kon
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(6, 2), 4); // Fall-from-Grace
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(4, 2), 5); // Nordom
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(5, 2), 6); // Ignus
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(3, 2), 7); // Vhailor
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(0, 2), 8); // anyone else
	EXPECT_EQ(DisplayMessage::PstFeedbackOffset(1, 1), 6); // flag 1 fallback (Ignus)
}

}
