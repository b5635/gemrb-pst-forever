// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef HIRESART_H
#define HIRESART_H

#include "Sprite2D.h"

#include <string>

namespace GemRB {

// Which upscaled tree a caller is allowed to read. Each one has its own toggle.
enum class HiResCategory {
	GUI,
	Areas,
	Sprites
};

// Attaches an optional RGBA twin to a sprite. The low-res pixels stay the ones
// scripts, hit tests and palette code observe. Only the OpenGL driver draws the twin.
class GEM_EXPORT HiResArt {
public:
	static bool Enabled(HiResCategory category);
	// relPath is relative to UpscalePath, with forward slashes, e.g. "areas/AR0202/0.png".
	// A missing file is ignored. A file whose size is not an integer scale >= 2 is skipped.
	// If <stem>.idx.png exists (nearest BAM indices, same size as the twin), it is put on hiResIndex.
	static void Attach(const Holder<Sprite2D>& spr, const std::string& relPath);
	// Logs how many twins the resource in progress actually received.
	static void Flush();
	// Tests point this at a temp tree. An empty path returns to the configured root.
	static void SetRoot(const std::string& path);
	// UpscalePath, or <exe dir>/upscaled. SetRoot overrides this.
	static std::string Root();
	// "ar0202.tis" -> "AR0202". Extension and trailing spaces are dropped.
	static std::string Stem(const char* filename);
};

}

#endif
