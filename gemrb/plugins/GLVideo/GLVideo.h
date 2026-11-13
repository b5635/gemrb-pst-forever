// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef GLVIDEO_H
#define GLVIDEO_H

#include "GLSprite2D.h"

#include "../SDLVideo/DPadSoftKeyboard.h"
#include "../SDLVideo/GamepadControl.h"
#include "GUI/EventMgr.h"
#include "Video/Video.h"

#include <GL/glew.h>
#include <SDL.h>
#include <unordered_map>
#include <vector>

namespace GemRB {

class GLVideoDriver;

// a render target: colour texture + framebuffer object
class GLVideoBuffer : public VideoBuffer {
public:
	GLVideoDriver* driver;
	GLuint texture = 0;
	GLuint fbo = 0;
	Video::BufferFormat format;
	float scale = 1.0f; // physical texels per logical pixel
	::GemRB::Size physSize;

	GLVideoBuffer(const Region& r, Video::BufferFormat fmt, GLVideoDriver* drv, float scale);
	~GLVideoBuffer() override;

	// change the physical resolution, keeping (resampled) content
	void Rescale(float newScale);
	static bool FollowsRenderScale(Video::BufferFormat fmt) { return fmt == Video::BufferFormat::DISPLAY || fmt == Video::BufferFormat::DISPLAY_ALPHA; }
	bool FollowsRenderScale() const { return FollowsRenderScale(format); }

	void Clear() override { Clear(Region(Point(), rect.size)); }
	void Clear(const Region& rgn) override;
	void CopyPixels(const Region& bufDest, const void* pixelBuf, const int* pitch = nullptr, ...) override;
	bool RenderOnDisplay(void* display) const override;
};

enum class GLBlend : uint8_t {
	None,
	Alpha,
	Add,
	Mod,
	Mul,
	Src,
	OneMinusDst,
	Dst,
	Premultiplied
};

struct GLVertex {
	float x, y; // target pixels
	float u, v; // texels
	uint8_t r, g, b, a;
	float pal, grey, ckey, extra;
};

// logical (or map unit) coordinates -> physical target pixels
struct GLXform {
	float sx = 1.0f, sy = 1.0f, tx = 0.0f, ty = 0.0f;
	void Apply(float& x, float& y) const
	{
		x = x * sx + tx;
		y = y * sy + ty;
	}
};

struct GLBatchState {
	GLuint fbo = 0;
	Size targetSize;
	GLBlend blend = GLBlend::None;
	int texMode = 0; // 0 colour only, 1 rgba, 2 indexed
	GLuint texture = 0;
	GLuint stencilTex = 0;
	int stencilChannel = -1;
	int dither = 0;
	float stencilA = 1.0f; // stencil texel = fragCoord * A + B
	float stencilBx = 0.0f;
	float stencilBy = 0.0f;
	Region scissor; // physical
	bool flipY = false;
	bool smooth = true;
	float brightness = 0.0f;
	float contrast = 1.0f;

	bool operator==(const GLBatchState& o) const
	{
		return fbo == o.fbo && targetSize == o.targetSize && blend == o.blend && texMode == o.texMode && texture == o.texture && stencilTex == o.stencilTex && stencilChannel == o.stencilChannel && dither == o.dither && stencilA == o.stencilA && stencilBx == o.stencilBx && stencilBy == o.stencilBy && scissor == o.scissor && flipY == o.flipY && smooth == o.smooth && brightness == o.brightness && contrast == o.contrast;
	}
	bool operator!=(const GLBatchState& o) const { return !(*this == o); }
};

class GLVideoDriver : public Video {
public:
	GLVideoDriver() noexcept = default;
	~GLVideoDriver() noexcept override;

	int Init() override;
	void SetWindowTitle(const char* title) override { SDL_SetWindowTitle(window, title); }
	bool SetFullscreenMode(bool set) override;
	bool ToggleGrabInput() override;
	void CaptureMouse(bool enabled) override;
	int GetDisplayRefreshRate() const override { return refreshRate; }
	int GetVirtualRefreshCap() const override { return 0; }

	void StartTextInput() override;
	void StopTextInput() override;
	bool InTextInput() override;
	bool TouchInputEnabled() override;
	bool CanDrawRawGeometry() const override { return true; }
	void ConfigurePointer(int pointerSpeed, int pointerAccel, int deadZoneL, int deadZoneR) override;

	Holder<Sprite2D> CreateSprite(const Region&, void* pixels, const PixelFormat&) override;
	void BlitSprite(const Holder<Sprite2D>& spr, const Region& src, Region dst, BlitFlags flags, Color tint = Color()) override;
	void BlitGameSprite(const Holder<Sprite2D>& spr, const Point& p, BlitFlags flags, Color tint = Color()) override;
	void BlitVideoBuffer(const VideoBufferPtr& buf, const Point& p, BlitFlags flags, Color tint = Color()) override;
	void BlitVideoBufferFully(const VideoBufferPtr& buf, BlitFlags flags, Color tint = Color()) override;
	Holder<Sprite2D> GetScreenshot(Region r, const VideoBufferPtr& buf = nullptr) override;
	void DrawRawGeometry(const std::vector<float>& vertices, const std::vector<Color>& colors, BlitFlags blitFlags) override;
	void SetGamma(int brightness, int contrast) override;

	// used by GLVideoBuffer
	void Flush();
	void ClearBuffer(GLVideoBuffer* buf, const Region& rgn);
	void CompositeBuffer(const GLVideoBuffer* buf);
	// draws srcRect (texels) of a texture into dstRect (physical pixels) of a framebuffer, no blending
	void CopyTexture(GLuint dstFbo, Size dstSize, const Region& dstRect, GLuint srcTex, const Region& srcRect, bool smooth);
	float RenderScale() const { return renderScale; }
	bool SupportsSceneTransform() const override { return true; }

private:
	SDL_Window* window = nullptr;
	SDL_GLContext glContext = nullptr;
	int refreshRate = 60;
	GamepadControl gamepadControl;
	DPadSoftKeyboard dPadSoftKeyboard;
	SDL_GameController* gameController = nullptr;

	GLuint program = 0;
	GLuint vao = 0;
	GLuint vbo = 0;
	GLuint paletteTex = 0;
	GLuint whiteTex = 0;
	struct Uniforms {
		GLint targetSize, flipY, texMode, rgba, index, palette, stencil, stencilChannel, dither, stencilA, stencilB, smooth, post;
	} uni {};

	GLuint screenTex = 0;
	GLuint screenFbo = 0;
	Size screenPhys; // physical size of the composited screen (== presentRect.size)
	Size windowPixels;
	Region presentRect; // where the logical screen lands in the window
	float renderScale = 1.0f; // physical pixels per logical pixel
	GLXform xf; // transform for the vertices being pushed
	GLXform baseXf; // xf without the per-object offset (stencils are not offset)
	bool highRes = true; // render at the window's resolution instead of the logical one

	std::vector<GLVertex> vertices;
	GLBatchState batch;
	bool batchValid = false;

	static constexpr int PaletteRows = 2048;
	struct PalKey {
		const Palette* pal;
		Hash version;
		bool operator==(const PalKey& o) const { return pal == o.pal && version == o.version; }
	};
	struct PalKeyHash {
		size_t operator()(const PalKey& k) const { return std::hash<const void*>()(k.pal) ^ (size_t(k.version.value) * 31u); }
	};
	std::unordered_map<PalKey, int, PalKeyHash> paletteRows;
	int nextPaletteRow = 0;

	float brightness = 0.0f;
	float contrast = 1.0f;

	int CreateDriverDisplay(const char* title, bool vsync) override;
	VideoBuffer* NewVideoBuffer(const Region&, BufferFormat) override;
	void SwapBuffers(VideoBuffers&) override;
	int PollEvents() override;
	void Wait(uint32_t w) override { SDL_Delay(w); }

	void DrawRectImp(const Region& rgn, const Color& color, bool fill, BlitFlags flags) override;
	void DrawPointImp(const BasePoint&, const Color& color, BlitFlags flags) override;
	void DrawPointsImp(const std::vector<BasePoint>& points, const Color& color, BlitFlags flags) override;
	void DrawCircleImp(const Point& origin, uint16_t r, const Color& color, BlitFlags flags) override;
	void DrawEllipseImp(const Region& rect, const Color& color, BlitFlags flags) override;
	void DrawPolygonImp(const Gem_Polygon* poly, const Point& origin, const Color& color, bool fill, BlitFlags flags) override;
	void DrawLineImp(const BasePoint& start, const BasePoint& end, const Color& color, BlitFlags flags) override;
	void DrawLinesImp(const std::vector<Point>& points, const Color& color, BlitFlags flags) override;

	bool CreateResources();
	void SetBatch(const GLBatchState& state);
	GLBatchState TargetState();
	void ApplyColorBlend(GLBatchState& st, BlitFlags flags) const;
	void PushQuad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, const Color& c, float pal = -1, float grey = 0, float ckey = -1);
	void PushColorRect(const Region& r, const Color& c);
	void PushLine(const BasePoint& a, const BasePoint& b, const Color& c);
	int PaletteRow(const Palette* pal);
	void DrawTexture(const GLVideoBuffer* buf, const Region& src, const Region& dst, BlitFlags flags, const Color& tint);
	void DrawSprite(const Holder<Sprite2D>& spr, const Region& src, const Region& dst, BlitFlags flags, const Color& tint);
	void UpdatePresentRect();
	void ResizeScreenTarget();
	static Region ToPhys(const Region& logical, float scale);
	Region XfRegion(const Region& r) const;
	void SetupStencil(GLBatchState& st, BlitFlags flags);
	void DevScreenshot();
	Point WindowToScreen(float x, float y) const;

	int ProcessEvent(const SDL_Event& event);
	bool ProcessControllerEvent(const SDL_Event& event);
	void ProcessAxisMotion();
};

}

#endif
