// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef AREASCENEDATA_H
#define AREASCENEDATA_H

#include "exports.h"
#include "ie_types.h"

#include <cstdint>
#include <string>
#include <vector>

namespace GemRB {

struct BakedLight {
	float x = 0, y = 0, z = 0, radius = 0, r = 1, g = 1, b = 1, strength = 1;
	enum class Kind : uint8_t { Fire, Magic, Steady, Pool } kind = Kind::Steady;
	bool castsShadow = false;
};

struct SceneMap {
	int w = 0, h = 0, texel = 2;
	float unit = 1.0f;
	std::vector<uint8_t> data; // u16 for height, rgb8 for normals, u8 for ao
};

class GEM_EXPORT AreaSceneData {
public:
	std::vector<BakedLight> lights;
	bool hasKey = false;
	float keyDir[2] {};
	float keyStrength = 0;
	float keyAmbient[3] { 1, 1, 1 };
	SceneMap height, normal, ao; // empty when the file is missing (phase 2/3)
	uint32_t generation = 0; // changes whenever another area is loaded (GL re-upload)

	// cached: loads <Root()>/lighting/<WED>/ on first use, keeps only the current area
	static const AreaSceneData* ForArea(const ResRef& wed);
	// exposed for the unit tests
	static bool ParseLights(const std::string& text, AreaSceneData& out);
	static bool ReadMap(const std::string& path, const char magic[4], int bytesPerTexel, SceneMap& out);
	// nearest texel, clamped; GLSL heightAt samples the uploaded float texture the same way
	static float HeightAt(const SceneMap& map, float areaX, float areaY);
};

}

#endif
