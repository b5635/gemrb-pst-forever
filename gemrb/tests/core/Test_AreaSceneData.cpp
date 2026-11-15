// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "../../core/AreaSceneData.h"
#include "../../core/HiResArt.h"

#include "System/VFS.h"

#include <cstdint>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include <gtest/gtest.h>

namespace GemRB {

static void WriteBytes(const path_t& path, const std::vector<uint8_t>& data)
{
	std::ofstream file(path.c_str(), std::ios::binary);
	file.write(reinterpret_cast<const char*>(data.data()), std::streamsize(data.size()));
}

static void WriteU32(std::vector<uint8_t>& out, uint32_t value)
{
	out.push_back(uint8_t(value));
	out.push_back(uint8_t(value >> 8));
	out.push_back(uint8_t(value >> 16));
	out.push_back(uint8_t(value >> 24));
}

static void WriteF32(std::vector<uint8_t>& out, float value)
{
	uint32_t bits = 0;
	std::memcpy(&bits, &value, sizeof(bits));
	WriteU32(out, bits);
}

static std::vector<uint8_t> MapBytes(const char magic[4], uint32_t w, uint32_t h, uint32_t texel, float unit, const std::vector<uint8_t>& payload)
{
	std::vector<uint8_t> out;
	out.insert(out.end(), magic, magic + 4);
	WriteU32(out, 1);
	WriteU32(out, w);
	WriteU32(out, h);
	WriteU32(out, texel);
	WriteF32(out, unit);
	WriteU32(out, 0);
	WriteU32(out, 0);
	out.insert(out.end(), payload.begin(), payload.end());
	return out;
}

TEST(AreaSceneData, ParseValid)
{
	const char* text =
		"# GemRB baked scene lights\n"
		"version 1\n"
		"size 100 80\n"
		"unknown 1 2 3\n"
		"light 10.0000 20.0000 30.0000 120.0000 1.0000 0.4000 0.1000 0.8000 fire 1\n"
		"light 50.5000 60.2500 12.0000 80.0000 0.2000 0.3000 1.0000 0.4000 pool 0\n";
	AreaSceneData data;
	ASSERT_TRUE(AreaSceneData::ParseLights(text, data));
	ASSERT_EQ(data.lights.size(), 2u);
	EXPECT_FALSE(data.hasKey);
	EXPECT_FLOAT_EQ(data.lights[0].x, 10.0f);
	EXPECT_FLOAT_EQ(data.lights[0].y, 20.0f);
	EXPECT_FLOAT_EQ(data.lights[0].z, 30.0f);
	EXPECT_FLOAT_EQ(data.lights[0].radius, 120.0f);
	EXPECT_FLOAT_EQ(data.lights[0].r, 1.0f);
	EXPECT_FLOAT_EQ(data.lights[0].g, 0.4f);
	EXPECT_FLOAT_EQ(data.lights[0].b, 0.1f);
	EXPECT_FLOAT_EQ(data.lights[0].strength, 0.8f);
	EXPECT_EQ(data.lights[0].kind, BakedLight::Kind::Fire);
	EXPECT_TRUE(data.lights[0].castsShadow);
	EXPECT_EQ(data.lights[1].kind, BakedLight::Kind::Pool);
	EXPECT_FALSE(data.lights[1].castsShadow);
	EXPECT_FLOAT_EQ(data.lights[1].x, 50.5f);
}

TEST(AreaSceneData, SkipsMalformedKeepsRest)
{
	const char* text =
		"version 1\n"
		"light 1 2 3\n"
		"light 10 20 30 100 1 0.5 0.2 0.8 fire 1\n"
		"light 4 5 6 70 1 1 1 1 nope 1\n";
	AreaSceneData data;
	ASSERT_TRUE(AreaSceneData::ParseLights(text, data));
	ASSERT_EQ(data.lights.size(), 1u);
	EXPECT_EQ(data.lights[0].kind, BakedLight::Kind::Fire);
	EXPECT_FLOAT_EQ(data.lights[0].x, 10.0f);
}

TEST(AreaSceneData, RejectsMissingVersion)
{
	AreaSceneData data;
	EXPECT_FALSE(AreaSceneData::ParseLights("light 10 20 30 100 1 0 0 1 fire 1\n", data));
	EXPECT_TRUE(data.lights.empty());
	EXPECT_FALSE(AreaSceneData::ParseLights("version 2\nlight 10 20 30 100 1 0 0 1 fire 1\n", data));
}

TEST(AreaSceneData, ReadMapAcceptsAndRejects)
{
	path_t dir = PathJoin("tools", "lighting", "work", "area-scene-test");
	ASSERT_TRUE(MakeDirectories(dir)) << dir;
	std::vector<uint8_t> payload(3 * 2 * 2);
	for (size_t i = 0; i < payload.size(); ++i) payload[i] = uint8_t(i + 1);
	path_t good = PathJoin(dir, "height.bin");
	WriteBytes(good, MapBytes("GLH1", 3, 2, 2, 0.0625f, payload));

	SceneMap map;
	ASSERT_TRUE(AreaSceneData::ReadMap(good, "GLH1", 2, map));
	EXPECT_EQ(map.w, 3);
	EXPECT_EQ(map.h, 2);
	EXPECT_EQ(map.texel, 2);
	EXPECT_FLOAT_EQ(map.unit, 0.0625f);
	ASSERT_EQ(map.data.size(), payload.size());
	EXPECT_EQ(map.data[0], 1);
	EXPECT_EQ(map.data[11], 12);

	path_t wrong = PathJoin(dir, "wrong.bin");
	WriteBytes(wrong, MapBytes("GLN1", 3, 2, 2, 0.0625f, payload));
	SceneMap bad;
	EXPECT_FALSE(AreaSceneData::ReadMap(wrong, "GLH1", 2, bad));
	EXPECT_TRUE(bad.data.empty());
	EXPECT_EQ(bad.w, 0);

	path_t trunc = PathJoin(dir, "trunc.bin");
	std::vector<uint8_t> shortBuf(20, 1);
	std::memcpy(shortBuf.data(), "GLH1", 4);
	WriteBytes(trunc, shortBuf);
	SceneMap truncated;
	EXPECT_FALSE(AreaSceneData::ReadMap(trunc, "GLH1", 2, truncated));
	EXPECT_TRUE(truncated.data.empty());
}

TEST(AreaSceneData, ForAreaLoadsOnce)
{
	path_t root = PathJoin("tools", "lighting", "work", "area-scene-test");
	path_t dir = PathJoin(root, "lighting", "AR0202");
	ASSERT_TRUE(MakeDirectories(dir)) << dir;
	path_t lightsPath = PathJoin(dir, "lights.txt");
	{
		std::ofstream file(lightsPath.c_str());
		file << "version 1\n"
		     << "light 8 16 12 90 1 0.2 0.1 0.5 fire 1\n";
	}
	HiResArt::SetRoot(root);
	ResRef wed = "AR0202";
	const AreaSceneData* scene = AreaSceneData::ForArea(wed);
	ASSERT_NE(scene, nullptr);
	ASSERT_EQ(scene->lights.size(), 1u);
	EXPECT_EQ(scene->lights[0].kind, BakedLight::Kind::Fire);
	EXPECT_FLOAT_EQ(scene->lights[0].x, 8.0f);
	uint32_t gen = scene->generation;
	const AreaSceneData* again = AreaSceneData::ForArea(wed);
	EXPECT_EQ(again, scene);
	EXPECT_EQ(again->generation, gen);

	ResRef other = "AR0201";
	const AreaSceneData* empty = AreaSceneData::ForArea(other);
	ASSERT_NE(empty, nullptr);
	EXPECT_TRUE(empty->lights.empty());
	EXPECT_NE(empty->generation, gen);
	HiResArt::SetRoot("");
}

}
