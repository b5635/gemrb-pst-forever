// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef GLSPRITE2D_H
#define GLSPRITE2D_H

#include "Sprite2D.h"

#include <GL/glew.h>

namespace GemRB {

// A sprite that keeps its pixels on the CPU (the engine reads them for hit tests)
// and mirrors them into a GL texture on first use. Paletted sprites are uploaded
// as raw 8 bit indices; the palette is applied in the fragment shader, so tints,
// palette swaps and greyscale cost nothing.
class GLSprite2D : public Sprite2D {
	mutable GLuint texture = 0;
	mutable bool dirty = true;

public:
	GLSprite2D(const Region&, void* pixels, const PixelFormat& fmt) noexcept;
	GLSprite2D(const GLSprite2D& other) noexcept;
	~GLSprite2D() noexcept override;

	Holder<Sprite2D> copy() const override;

	void* LockSprite() override;
	const void* LockSprite() const override;
	void UnlockSprite() override;
	bool ConvertFormatTo(const PixelFormat&) noexcept override;

	bool IsIndexed() const { return format.Bpp == 1; }
	// returns the texture, uploading pending changes; 'uploaded' tells the caller GL state changed
	GLuint GetTexture(bool& uploaded) const;
	void Invalidate() const { dirty = true; }
	bool NeedsReupload() const { return dirty && texture; }
};

// converts any engine pixel format to tightly packed RGBA8 (R first in memory)
void ConvertToRGBA8(const void* src, int w, int h, int srcPitch, const PixelFormat& fmt, uint32_t* dst);

}

#endif
