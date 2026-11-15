// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "Scriptable/InfoPoint.h"

#include <gtest/gtest.h>

namespace GemRB {

TEST(InfoPoint, ExamineFallbackResRef)
{
	EXPECT_TRUE(InfoPoint::ExamineFallbackResRef(ieStrRef(0)).IsEmpty());
	EXPECT_TRUE(InfoPoint::ExamineFallbackResRef(ieStrRef::INVALID).IsEmpty());
	EXPECT_STREQ(InfoPoint::ExamineFallbackResRef(ieStrRef(16620)).c_str(), "VV16620");
	EXPECT_STREQ(InfoPoint::ExamineFallbackResRef(ieStrRef(68032)).c_str(), "VV68032");
}

}
