// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "HiResArt.h"

#include "ImageMgr.h"
#include "Interface.h"
#include "PluginMgr.h"

#include "Logging/Logging.h"
#include "Streams/FileStream.h"
#include "System/VFS.h"
#include "Video/Video.h"

#include <cctype>
#include <cstring>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace GemRB {

static std::string rootOverride;
static std::unordered_map<std::string, std::unordered_set<std::string>> dirCache;
static bool warnedSize = false;
static bool warnedRead = false;

struct PendingReport {
	std::string key;
	int attached = 0;
};

static PendingReport pending;

static std::string Upper(std::string text)
{
	for (char& c : text) {
		c = char(std::toupper(static_cast<unsigned char>(c)));
	}
	return text;
}

static std::string Native(std::string path)
{
	for (char& c : path) {
		if (c == '/' || c == '\\') c = PathDelimiter;
	}
	return path;
}

static std::string Root()
{
	if (!rootOverride.empty()) return rootOverride;
	if (!core) return {};
	if (!core->config.UpscalePath.empty()) return core->config.UpscalePath;
	std::string base = core->config.AbsoluteGemRBPath;
	if (base.empty()) base = ".";
	return PathJoin(base, "upscaled");
}

static std::string ReportKey(const std::string& rel)
{
	std::string norm = rel;
	for (char& c : norm) {
		if (c == '\\') c = '/';
	}
	auto slash = norm.find_last_of('/');
	if (slash == std::string::npos) return norm;
	std::string parent = norm.substr(0, slash);
	std::string file = norm.substr(slash + 1);
	auto dot = file.find_last_of('.');
	if (dot != std::string::npos) file.resize(dot);
	auto folderAt = parent.find_last_of('/');
	std::string folder = folderAt == std::string::npos ? parent : parent.substr(folderAt + 1);
	if (folder == "mos" || folder == "bmp") return parent + "/" + file;
	return parent;
}

static void SplitPath(const std::string& full, std::string& dir, std::string& name)
{
	auto slash = full.find_last_of("/\\");
	if (slash == std::string::npos) {
		dir = ".";
		name = full;
		return;
	}
	dir = full.substr(0, slash);
	name = full.substr(slash + 1);
}

static bool Listed(const std::string& full)
{
	std::string dir;
	std::string name;
	SplitPath(full, dir, name);
	std::string key = Native(dir);
	auto it = dirCache.find(key);
	if (it == dirCache.end()) {
		std::unordered_set<std::string> names;
		if (DirExists(dir)) {
			DirectoryIterator iter(dir);
			if (iter) {
				do {
					std::string entry = iter.GetName();
					if (entry.empty() || entry == "." || entry == "..") continue;
					names.insert(Upper(entry));
				} while (++iter);
			}
		}
		it = dirCache.emplace(key, std::move(names)).first;
	}
	return it->second.find(Upper(name)) != it->second.end();
}

static uint32_t ReadBE32(const uint8_t* p)
{
	return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | uint32_t(p[3]);
}

static uint32_t Adler32(const uint8_t* data, size_t len)
{
	uint32_t a = 1;
	uint32_t b = 0;
	for (size_t i = 0; i < len; ++i) {
		a = (a + data[i]) % 65521u;
		b = (b + a) % 65521u;
	}
	return (b << 16) | a;
}

// Stored-block zlib only. Enough for the unit test, which writes this exact form.
// Pillow output is a normal deflate stream and goes through the PNG importer instead.
static bool InflateStored(const uint8_t* z, size_t zlen, std::vector<uint8_t>& out)
{
	if (zlen < 6) return false;
	if (((unsigned(z[0]) << 8) | z[1]) % 31u != 0) return false;
	if ((z[0] & 0x0F) != 8 || (z[1] & 0x20)) return false;
	size_t p = 2;
	while (p < zlen) {
		uint8_t header = z[p++];
		int finalBlock = header & 1;
		int type = (header >> 1) & 3;
		if (type != 0 || p + 4 > zlen) return false;
		uint16_t len = uint16_t(z[p] | (z[p + 1] << 8));
		uint16_t nlen = uint16_t(z[p + 2] | (z[p + 3] << 8));
		p += 4;
		if (uint16_t(len ^ 0xFFFF) != nlen || p + len > zlen) return false;
		out.insert(out.end(), z + p, z + p + len);
		p += len;
		if (finalBlock) {
			if (p + 4 > zlen) return false;
			uint32_t got = ReadBE32(z + p);
			return got == Adler32(out.data(), out.size());
		}
	}
	return false;
}

static std::vector<uint8_t> ReadAll(const std::string& path)
{
	FileStream* file = FileStream::OpenFile(path);
	if (!file) return {};
	std::vector<uint8_t> data(file->Size());
	if (!data.empty()) file->Read(data.data(), data.size());
	delete file;
	return data;
}

static Holder<Sprite2D> SpriteFromRGBA(int w, int h, uint8_t* pixels)
{
	PixelFormat fmt(4, 0x000000ff, 0x0000ff00, 0x00ff0000, 0xff000000);
	Region frame(0, 0, w, h);
	if (VideoDriver) return VideoDriver->CreateSprite(frame, pixels, fmt);
	return MakeHolder<Sprite2D>(frame, pixels, fmt, uint16_t(w * 4));
}

static Holder<Sprite2D> LoadStoredPng(const std::string& path)
{
	std::vector<uint8_t> bytes = ReadAll(path);
	static const uint8_t sig[8] = { 137, 80, 78, 71, 13, 10, 26, 10 };
	if (bytes.size() < 8 || std::memcmp(bytes.data(), sig, 8) != 0) return nullptr;
	int w = 0;
	int h = 0;
	bool have = false;
	std::vector<uint8_t> idat;
	size_t p = 8;
	while (p + 12 <= bytes.size()) {
		uint32_t len = ReadBE32(bytes.data() + p);
		p += 4;
		if (p + 4 + len + 4 > bytes.size()) return nullptr;
		const uint8_t* type = bytes.data() + p;
		p += 4;
		const uint8_t* data = bytes.data() + p;
		if (std::memcmp(type, "IHDR", 4) == 0) {
			if (len < 13) return nullptr;
			w = int(ReadBE32(data));
			h = int(ReadBE32(data + 4));
			// 8-bit RGBA, deflate, no filter method other than the default, not interlaced
			if (data[8] != 8 || data[9] != 6 || data[10] || data[11] || data[12]) return nullptr;
			have = true;
		} else if (std::memcmp(type, "IDAT", 4) == 0) {
			idat.insert(idat.end(), data, data + len);
		} else if (std::memcmp(type, "IEND", 4) == 0) {
			break;
		}
		p += len + 4;
	}
	if (!have || w <= 0 || h <= 0) return nullptr;
	if (size_t(w) * 4 > 65535) return nullptr;
	std::vector<uint8_t> raw;
	if (!InflateStored(idat.data(), idat.size(), raw)) return nullptr;
	size_t stride = 1 + size_t(w) * 4;
	if (raw.size() < stride * size_t(h)) return nullptr;
	uint8_t* pixels = static_cast<uint8_t*>(malloc(size_t(w) * h * 4));
	if (!pixels) return nullptr;
	for (int y = 0; y < h; ++y) {
		if (raw[y * stride] != 0) {
			free(pixels);
			return nullptr;
		}
		std::memcpy(pixels + size_t(y) * w * 4, raw.data() + y * stride + 1, size_t(w) * 4);
	}
	return SpriteFromRGBA(w, h, pixels);
}

static Holder<Sprite2D> LoadViaImporter(const std::string& path)
{
	if (!VideoDriver) return nullptr;
	const std::vector<ResourceDesc>& descs = PluginMgr::Get()->GetResourceDesc(&ImageMgr::ID);
	const ResourceDesc* png = nullptr;
	for (const ResourceDesc& desc : descs) {
		const std::string& ext = desc.GetExt();
		if (ext == "png" || ext == "PNG") {
			png = &desc;
			break;
		}
	}
	if (!png) return nullptr;
	FileStream* file = FileStream::OpenFile(path);
	if (!file) return nullptr;
	ResourceHolder<Resource> res = png->Create(file);
	if (!res) return nullptr;
	return std::static_pointer_cast<ImageMgr>(res)->GetSprite2D();
}

static Holder<Sprite2D> LoadPng(const std::string& path)
{
	Holder<Sprite2D> spr = LoadViaImporter(path);
	if (spr) return spr;
	return LoadStoredPng(path);
}

static bool ScaleOk(const Sprite2D& low, const Sprite2D& hi)
{
	if (low.Frame.w <= 0 || low.Frame.h <= 0) return false;
	if (hi.Frame.w < low.Frame.w * 2 || hi.Frame.h < low.Frame.h * 2) return false;
	if (hi.Frame.w % low.Frame.w || hi.Frame.h % low.Frame.h) return false;
	return hi.Frame.w / low.Frame.w == hi.Frame.h / low.Frame.h;
}

bool HiResArt::Enabled(HiResCategory category)
{
	if (!core || !VideoDriver || !VideoDriver->SupportsHiResArt()) return false;
	const char* key = "UpscaledGUI";
	if (category == HiResCategory::Areas) key = "UpscaledAreas";
	if (category == HiResCategory::Sprites) key = "UpscaledSprites";
	return core->GetDictionary().Get(StringView(key), 0) != 0;
}

void HiResArt::Attach(const Holder<Sprite2D>& spr, const std::string& relPath)
{
	if (!spr || relPath.empty()) return;
	std::string key = ReportKey(relPath);
	if (key != pending.key) {
		Flush();
		pending.key = key;
	}
	std::string root = Root();
	if (root.empty()) return;
	std::string full = Native(PathJoin(root, relPath));
	if (!Listed(full)) return;
	Holder<Sprite2D> hi = LoadPng(full);
	if (!hi) {
		if (!warnedRead) {
			Log(WARNING, "HiResArt", "Could not read {}, skipping further unreadable twins.", full);
			warnedRead = true;
		}
		return;
	}
	if (!ScaleOk(*spr, *hi)) {
		if (!warnedSize) {
			Log(WARNING, "HiResArt", "Skipping {} ({}x{}, not an integer scale of {}x{}).",
			    full, hi->Frame.w, hi->Frame.h, spr->Frame.w, spr->Frame.h);
			warnedSize = true;
		}
		return;
	}
	hi->Frame.x = 0;
	hi->Frame.y = 0;
	spr->hiRes = std::move(hi);
	pending.attached++;
}

void HiResArt::Flush()
{
	if (pending.attached > 0 && !pending.key.empty()) {
		Log(MESSAGE, "HiResArt", "Attached {} hi-res frame(s) for {}.", pending.attached, pending.key);
	}
	pending = PendingReport();
}

void HiResArt::SetRoot(const std::string& path)
{
	Flush();
	rootOverride = path;
	dirCache.clear();
}

std::string HiResArt::Stem(const char* filename)
{
	if (!filename || !filename[0]) return {};
	std::string text = filename;
	auto slash = text.find_last_of("/\\");
	if (slash != std::string::npos) text = text.substr(slash + 1);
	auto dot = text.find_last_of('.');
	if (dot != std::string::npos) text.resize(dot);
	while (!text.empty() && text.back() == ' ') text.pop_back();
	size_t start = 0;
	while (start < text.size() && text[start] == ' ') ++start;
	if (start) text.erase(0, start);
	return Upper(text);
}

}
