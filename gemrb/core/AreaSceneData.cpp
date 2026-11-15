// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "AreaSceneData.h"

#include "HiResArt.h"

#include "Logging/Logging.h"
#include "Streams/FileStream.h"
#include "System/VFS.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstring>
#include <sstream>

namespace GemRB {

static std::string WedName(const ResRef& wed)
{
	std::string name(wed.c_str(), wed.length());
	for (char& c : name) {
		c = char(std::toupper(static_cast<unsigned char>(c)));
	}
	return name;
}

static std::string ReadTextFile(const std::string& path)
{
	FileStream* file = FileStream::OpenFile(path);
	if (!file) return {};
	const strpos_t size = file->Size();
	std::string text(size, '\0');
	if (size) file->Read(&text[0], size);
	delete file;
	return text;
}

static uint32_t ReadU32(const uint8_t* p)
{
	return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}

static float ReadF32(const uint8_t* p)
{
	uint32_t bits = ReadU32(p);
	float value = 0.0f;
	std::memcpy(&value, &bits, sizeof(value));
	return value;
}

static BakedLight::Kind ParseKind(const std::string& kind, bool& ok)
{
	ok = true;
	if (kind == "fire") return BakedLight::Kind::Fire;
	if (kind == "magic") return BakedLight::Kind::Magic;
	if (kind == "steady") return BakedLight::Kind::Steady;
	if (kind == "pool") return BakedLight::Kind::Pool;
	ok = false;
	return BakedLight::Kind::Steady;
}

static float Clamp01(float v)
{
	return std::max(0.0f, std::min(1.0f, v));
}

bool AreaSceneData::ParseLights(const std::string& text, AreaSceneData& out)
{
	AreaSceneData parsed;
	bool sawVersion = false;
	bool warned = false;
	std::istringstream stream(text);
	std::string line;
	while (std::getline(stream, line)) {
		if (!line.empty() && line.back() == '\r') line.pop_back();
		size_t start = line.find_first_not_of(" \t");
		if (start == std::string::npos) continue;
		if (line[start] == '#') continue;
		std::istringstream in(line.substr(start));
		std::string kw;
		if (!(in >> kw)) continue;
		if (kw == "version") {
			int version = 0;
			if (!(in >> version) || version != 1) return false;
			sawVersion = true;
			continue;
		}
		if (kw == "size") {
			int w = 0, h = 0;
			in >> w >> h;
			continue;
		}
		if (kw == "key") {
			float dirX = 0, dirY = 0, strength = 0, ar = 1, ag = 1, ab = 1;
			if (!(in >> dirX >> dirY >> strength >> ar >> ag >> ab)) continue;
			parsed.hasKey = true;
			parsed.keyDir[0] = dirX;
			parsed.keyDir[1] = dirY;
			parsed.keyStrength = Clamp01(strength);
			// luma-normalised ambient can have a channel above 1
			parsed.keyAmbient[0] = std::max(0.0f, ar);
			parsed.keyAmbient[1] = std::max(0.0f, ag);
			parsed.keyAmbient[2] = std::max(0.0f, ab);
			continue;
		}
		if (kw != "light") continue;
		float x = 0, y = 0, z = 0, radius = 0, r = 0, g = 0, b = 0, strength = 0;
		std::string kindName;
		int casts = 0;
		bool kindOk = false;
		if (!(in >> x >> y >> z >> radius >> r >> g >> b >> strength >> kindName >> casts)) {
			if (!warned) {
				Log(WARNING, "AreaSceneData", "Skipping malformed light line.");
				warned = true;
			}
			continue;
		}
		BakedLight::Kind kind = ParseKind(kindName, kindOk);
		if (!kindOk) {
			if (!warned) {
				Log(WARNING, "AreaSceneData", "Skipping malformed light line.");
				warned = true;
			}
			continue;
		}
		BakedLight light;
		light.x = x;
		light.y = y;
		light.z = z;
		light.radius = std::max(10.0f, std::min(600.0f, radius));
		light.r = Clamp01(r);
		light.g = Clamp01(g);
		light.b = Clamp01(b);
		light.strength = Clamp01(strength);
		light.kind = kind;
		light.castsShadow = casts != 0;
		parsed.lights.push_back(light);
	}
	if (!sawVersion) return false;
	out.lights = std::move(parsed.lights);
	out.hasKey = parsed.hasKey;
	out.keyDir[0] = parsed.keyDir[0];
	out.keyDir[1] = parsed.keyDir[1];
	out.keyStrength = parsed.keyStrength;
	out.keyAmbient[0] = parsed.keyAmbient[0];
	out.keyAmbient[1] = parsed.keyAmbient[1];
	out.keyAmbient[2] = parsed.keyAmbient[2];
	return true;
}

bool AreaSceneData::ReadMap(const std::string& path, const char magic[4], int bytesPerTexel, SceneMap& out)
{
	out = SceneMap();
	if (bytesPerTexel <= 0) {
		Log(WARNING, "AreaSceneData", "Rejected {} (bad texel size).", path);
		return false;
	}
	FileStream* file = FileStream::OpenFile(path);
	if (!file) {
		Log(WARNING, "AreaSceneData", "Could not read {}.", path);
		return false;
	}
	const strpos_t size = file->Size();
	if (size < 32) {
		delete file;
		Log(WARNING, "AreaSceneData", "Rejected {} (truncated).", path);
		return false;
	}
	std::vector<uint8_t> buf(size);
	file->Read(buf.data(), size);
	delete file;
	if (std::memcmp(buf.data(), magic, 4) != 0) {
		Log(WARNING, "AreaSceneData", "Rejected {} (wrong magic).", path);
		return false;
	}
	const uint32_t version = ReadU32(buf.data() + 4);
	const uint32_t w = ReadU32(buf.data() + 8);
	const uint32_t h = ReadU32(buf.data() + 12);
	const uint32_t texel = ReadU32(buf.data() + 16);
	const float unit = ReadF32(buf.data() + 20);
	if (version != 1 || w == 0 || h == 0) {
		Log(WARNING, "AreaSceneData", "Rejected {} (bad header).", path);
		return false;
	}
	const uint64_t expect = 32ull + uint64_t(w) * uint64_t(h) * uint64_t(bytesPerTexel);
	if (uint64_t(size) != expect) {
		Log(WARNING, "AreaSceneData", "Rejected {} (size {}).", path, size);
		return false;
	}
	out.w = int(w);
	out.h = int(h);
	out.texel = int(texel);
	out.unit = unit;
	out.data.assign(buf.begin() + 32, buf.end());
	return true;
}

float AreaSceneData::HeightAt(const SceneMap& map, float areaX, float areaY)
{
	if (map.w <= 0 || map.h <= 0 || map.data.size() < size_t(map.w) * size_t(map.h) * 2) {
		return 0.0f;
	}
	const int texel = map.texel > 0 ? map.texel : 2;
	int tx = int(std::floor(areaX / float(texel)));
	int ty = int(std::floor(areaY / float(texel)));
	tx = std::max(0, std::min(map.w - 1, tx));
	ty = std::max(0, std::min(map.h - 1, ty));
	const uint8_t* p = map.data.data() + (size_t(ty) * size_t(map.w) + size_t(tx)) * 2;
	const uint16_t value = uint16_t(p[0]) | (uint16_t(p[1]) << 8);
	return float(value) * map.unit;
}

const AreaSceneData* AreaSceneData::ForArea(const ResRef& wed)
{
	static AreaSceneData cached;
	static ResRef cachedWed;
	static bool have = false;
	static uint32_t gen = 0;

	if (have && cachedWed == wed) return &cached;

	have = true;
	cachedWed = wed;
	cached = AreaSceneData();
	cached.generation = ++gen;

	const std::string name = WedName(wed);
	const std::string root = HiResArt::Root();
	if (!root.empty() && !name.empty()) {
		const std::string dir = PathJoin(root, "lighting", name);
		const std::string lightsPath = PathJoin(dir, "lights.txt");
		if (FileExists(lightsPath)) {
			if (!ParseLights(ReadTextFile(lightsPath), cached)) {
				Log(WARNING, "AreaSceneData", "{}: lights.txt rejected.", name);
				cached.lights.clear();
				cached.hasKey = false;
			}
		}
		const std::string heightPath = PathJoin(dir, "height.bin");
		if (FileExists(heightPath)) {
			ReadMap(heightPath, "GLH1", 2, cached.height);
		}
		const std::string normalPath = PathJoin(dir, "normal.bin");
		if (FileExists(normalPath)) {
			ReadMap(normalPath, "GLN1", 3, cached.normal);
		}
		const std::string aoPath = PathJoin(dir, "ao.bin");
		if (FileExists(aoPath)) {
			ReadMap(aoPath, "GLA1", 1, cached.ao);
		}
	}

	Log(MESSAGE, "AreaSceneData", "{}: {} baked lights, height {}, normals {}, ao {}",
	    name.empty() ? "?" : name,
	    cached.lights.size(),
	    cached.height.data.empty() ? 0 : 1,
	    cached.normal.data.empty() ? 0 : 1,
	    cached.ao.data.empty() ? 0 : 1);
	return &cached;
}

}
