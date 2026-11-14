// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "ScenePolish.h"

#include <gtest/gtest.h>

namespace GemRB {

using M = ScenePolish::HitMaterial;

TEST(HitMaterial, PstArmorSoundSets)
{
	EXPECT_EQ(ScenePolish::MaterialForArmor(0), M::Flesh);
	EXPECT_EQ(ScenePolish::MaterialForArmor(1), M::Leather);
	EXPECT_EQ(ScenePolish::MaterialForArmor(2), M::Armored);
	EXPECT_EQ(ScenePolish::MaterialForArmor(3), M::Stone);
	EXPECT_EQ(ScenePolish::MaterialForArmor(4), M::Bone);
	EXPECT_EQ(ScenePolish::MaterialForArmor(5), M::Flesh);
	EXPECT_EQ(ScenePolish::MaterialForArmor(6), M::Spirit);
	EXPECT_EQ(ScenePolish::MaterialForArmor(7), M::Metal);
	EXPECT_EQ(ScenePolish::MaterialForArmor(8), M::Flesh);
	EXPECT_EQ(ScenePolish::MaterialForArmor(9), M::Shadow);
	EXPECT_EQ(ScenePolish::MaterialForArmor(10), M::Fire);
	EXPECT_EQ(ScenePolish::MaterialForArmor(42), M::Flesh);
}

TEST(HitMaterial, BloodAndSparks)
{
	// cloth / flesh / leather bleed, plate over a body bleeds and sparks
	EXPECT_TRUE(ScenePolish::Bleeds(M::Flesh));
	EXPECT_TRUE(ScenePolish::Bleeds(M::Leather));
	EXPECT_TRUE(ScenePolish::Bleeds(M::Armored));
	EXPECT_TRUE(ScenePolish::Sparks(M::Armored));
	EXPECT_FALSE(ScenePolish::Sparks(M::Flesh));
	// no blood without a living body
	for (M m : { M::ArmoredBone, M::Hollow, M::Bone, M::Stone, M::Spirit, M::Metal, M::Shadow, M::Fire }) {
		EXPECT_FALSE(ScenePolish::Bleeds(m));
	}
	EXPECT_TRUE(ScenePolish::Sparks(M::ArmoredBone));
	EXPECT_TRUE(ScenePolish::Sparks(M::Hollow));
	EXPECT_TRUE(ScenePolish::Sparks(M::Metal));
	EXPECT_FALSE(ScenePolish::Sparks(M::Bone));
}

TEST(HitMaterial, TableNames)
{
	M m = M::Flesh;
	EXPECT_TRUE(ScenePolish::MaterialFromName("ARMORED_BONE", m));
	EXPECT_EQ(m, M::ArmoredBone);
	EXPECT_TRUE(ScenePolish::MaterialFromName("hollow", m));
	EXPECT_EQ(m, M::Hollow);
	EXPECT_FALSE(ScenePolish::MaterialFromName("JELLY", m));
	EXPECT_EQ(m, M::Hollow);
}

}
