// SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

/**
 * @file Video.h
 * Declares Video, base class for video output plugins.
 * @author The GemRB Project
 */

#ifndef VIDEO_H
#define VIDEO_H

#include "globals.h"

#include "Plugin.h"
#include "Sprite2D.h"

#include <deque>

namespace GemRB {

class EventMgr;
class Gem_Polygon;
class Palette;

class GEM_EXPORT VideoBuffer {
protected:
	Region rect;

public:
	explicit VideoBuffer(const Region& r)
		: rect(r) {}
	virtual ~VideoBuffer() noexcept = default;

	::GemRB::Size Size() const { return rect.size; }
	Point Origin() const { return rect.origin; }
	Region Rect() const { return rect; }

	void SetOrigin(const Point& p) { rect.origin = p; }

	virtual void Clear() { Clear({ 0, 0, rect.w, rect.h }); };
	virtual void Clear(const Region& rgn) = 0;
	// CopyPixels takes at least one void* buffer with implied pitch of Region.w, otherwise alternating pairs of buffers and their corresponding pitches
	virtual void CopyPixels(const Region& bufDest, const void* pixelBuf, const int* pitch = NULL, ...) = 0;

	virtual bool RenderOnDisplay(void* display) const = 0;
};

using VideoBufferPtr = std::shared_ptr<VideoBuffer>;

/**
 * @class Video
 * Base class for video output plugins.
 */

// Enhanced scene rendering (only drivers that report SupportsSceneTransform()).
// While a scene is active, everything drawn into the scene buffer is given in
// map units relative to the integer viewport origin; the driver maps it to the
// buffer as  logical = rect.origin + offset + p * zoom,  so the camera can sit
// between pixels and zoom freely without the core knowing about either.
struct SceneTransform {
	bool active = false;
	bool suspended = false;
	float zoom = 1.0f;
	float offsetX = 0.0f; // logical pixels, usually minus the camera's sub-pixel part * zoom
	float offsetY = 0.0f;
	Region rect; // the scene's area in the buffer, logical pixels
	const void* buffer = nullptr;
	// extra map-unit offset for the object being drawn (sub-tick interpolation)
	float objectX = 0.0f;
	float objectY = 0.0f;
	// ground line (scene y) of the object being drawn, for the lighting depth map
	bool objectHasDepth = false;
	float objectDepth = 0.0f;
};

// Dynamic lighting for the scene (phase 4). Positions are scene coordinates
// (map units relative to the scene's viewport origin). The scene is multiplied
// by ambient + the sum of all lights; bright pixels keep part of their
// original brightness (painted fires, spell effects).
struct SceneLight {
	float x = 0.0f;
	float y = 0.0f;
	float z = 0.0f; // height above the ground at (x, y), map units
	float radius = 100.0f; // map units, horizontal; vertical is squashed (isometric ground)
	float r = 1.0f, g = 1.0f, b = 1.0f; // linear multiplier contributed at the centre
};

// one raster row of a wall polygon (scene coordinates), with the ground line
// (base) of the wall at both ends: the wall's pixels are vertical surfaces
// standing on that line
struct SceneSpan {
	float x0, x1, y;
	float base0, base1;
};

struct SceneLighting {
	float ambient[3] = { 1.0f, 1.0f, 1.0f };
	float highlightKeep = 0.6f; // how much of very bright pixels escapes the ambient darkening
	float maxLight = 1.25f; // cap of ambient + lights
	// generated depth + normal maps: lights work in 3D over walls and sprites and
	// surfaces get relief from the art's own shading
	bool geometry = true;
	float bump = 6.0f; // slope per unit of luminance change
	float normalStrength = 0.8f; // 0 = flat, 1 = full normal-map shading
	std::vector<SceneLight> lights;
	std::vector<SceneSpan> wallSpans;
};

class GEM_EXPORT Video : public Plugin {
public:
	static const TypeID ID;

	enum class BufferFormat {
		DISPLAY, // whatever format the video driver thinks is best for the display
		DISPLAY_ALPHA, // the same RGB format as DISPLAY, but forces an alpha if DISPLAY doesn't provide one
		RGBPAL8, // 8 bit palettized
		RGB555, // 16 bit RGB (truecolor)
		RGBA8888, // Standard 8 bits per channel with alpha
		YV12, // YUV format for BIK videos
		MASK // DISPLAY_ALPHA used as a stencil in map units; drivers with scene transforms keep it unscaled
	};

protected:
	tick_t lastTime = 0;
	EventMgr* EvntManager = nullptr;
	Region screenClip;
	Size screenSize;
	int bpp = 0;
	bool fullscreen = false;

	unsigned char Gamma10toGamma22[256];
	unsigned char Gamma22toGamma10[256];

	using VideoBuffers = std::deque<VideoBuffer*>;

	// collection of all existing video buffers
	VideoBuffers buffers;
	// collection built by calls to PushDrawingBuffer() and cleared after SwapBuffers()
	// the collection is iterated and drawn in order during SwapBuffers()
	// Note: we can add the same buffer more than once to drawingBuffers!
	VideoBuffers drawingBuffers;
	// the current top of drawingBuffers that draw operations occur on
	VideoBuffer* drawingBuffer = nullptr;
	VideoBufferPtr stencilBuffer = nullptr;
	SceneTransform scene;

	bool SceneAppliesToTarget() const { return scene.active && !scene.suspended && scene.buffer == drawingBuffer; }
	// driver hooks around a scene (scene is already set up / still set up)
	virtual void SceneBegan() {}
	virtual void SceneEnding() {}

	Region ClippedDrawingRect(const Region& target, const Region* clip = NULL) const;
	virtual void Wait(uint32_t) = 0;
	void DestroyBuffer(VideoBuffer*);
	void DestroyBuffers();

private:
	virtual VideoBuffer* NewVideoBuffer(const Region&, BufferFormat) = 0;
	virtual void SwapBuffers(VideoBuffers&) = 0;
	virtual int PollEvents() = 0;
	virtual int CreateDriverDisplay(const char* title, bool vsync) = 0;

	// the actual drawing implementations
	virtual void DrawRectImp(const Region& rgn, const Color& color, bool fill, BlitFlags flags) = 0;
	virtual void DrawPointImp(const BasePoint&, const Color& color, BlitFlags flags) = 0;
	virtual void DrawPointsImp(const std::vector<BasePoint>& points, const Color& color, BlitFlags flags) = 0;
	virtual void DrawCircleImp(const Point& origin, uint16_t r, const Color& color, BlitFlags flags) = 0;
	virtual void DrawEllipseImp(const Region& rect, const Color& color, BlitFlags flags) = 0;
	virtual void DrawPolygonImp(const Gem_Polygon* poly, const Point& origin, const Color& color, bool fill, BlitFlags flags) = 0;
	virtual void DrawLineImp(const BasePoint& start, const BasePoint& end, const Color& color, BlitFlags flags) = 0;
	virtual void DrawLinesImp(const std::vector<Point>& points, const Color& color, BlitFlags flags) = 0;

public:
	Video() noexcept;
	~Video() noexcept override;

	virtual int Init(void) = 0;

	int CreateDisplay(const Size&, int bpp, bool fullscreen, const char* title, bool vsync);
	virtual void SetWindowTitle(const char* title) = 0;

	/** Toggles GemRB between fullscreen and windowed mode. */
	bool ToggleFullscreenMode();
	virtual bool SetFullscreenMode(bool set) = 0;
	bool GetFullscreenMode() const;
	/** Swaps displayed and back buffers */
	int SwapBuffers(int fpscap = 30);
	VideoBufferPtr CreateBuffer(const Region&, BufferFormat = BufferFormat::DISPLAY);
	void PushDrawingBuffer(const VideoBufferPtr&);
	void PopDrawingBuffer();
	void SetStencilBuffer(const VideoBufferPtr&);
	/** Grabs and releases mouse cursor within GemRB window */
	virtual bool ToggleGrabInput() = 0;
	virtual void CaptureMouse(bool enabled) = 0;
	const Size& GetScreenSize() const { return screenSize; }
	virtual int GetDisplayRefreshRate() const = 0;
	virtual int GetVirtualRefreshCap() const = 0;

	virtual void StartTextInput() = 0;
	virtual void StopTextInput() = 0;
	virtual bool InTextInput() = 0;

	virtual bool TouchInputEnabled() = 0;
	virtual bool CanDrawRawGeometry() const { return false; }

	// see SceneTransform; drivers without support ignore all of this
	virtual bool SupportsSceneTransform() const { return false; }
	void BeginScene(float zoom, float offsetX, float offsetY, const Region& rect);
	void EndScene();
	// temporarily draw in plain buffer coordinates (UI text over the map...)
	void SuspendScene(bool suspend) { scene.suspended = suspend; }
	void SetObjectOffset(float x, float y)
	{
		scene.objectX = x;
		scene.objectY = y;
	}
	void SetObjectDepth(float groundY)
	{
		scene.objectHasDepth = true;
		scene.objectDepth = groundY;
	}
	void ClearObjectDepth() { scene.objectHasDepth = false; }
	const SceneTransform& GetScene() const { return scene; }
	// applies SceneLighting to what has been drawn into the active scene so far
	virtual void DrawSceneLighting(const SceneLighting& /*lighting*/) {}
	virtual void ConfigurePointer(int pointerSpeed, int pointerAccel, int deadZoneL, int deadZoneR) = 0;

	virtual Holder<Sprite2D> CreateSprite(const Region&, void* pixels, const PixelFormat&) = 0;

	void BlitSprite(const Holder<Sprite2D>& spr, Point p,
			const Region* clip = nullptr, BlitFlags = BlitFlags::NONE);

	virtual void BlitSprite(const Holder<Sprite2D>& spr, const Region& src, Region dst,
				BlitFlags flags, Color tint = Color()) = 0;

	virtual void BlitGameSprite(const Holder<Sprite2D>& spr, const Point& p,
				    BlitFlags flags, Color tint = Color()) = 0;

	void BlitGameSpriteWithPalette(const Holder<Sprite2D>& spr, const Holder<Palette>& pal, const Point& p,
				       BlitFlags flags, Color tint);

	virtual void BlitVideoBuffer(const VideoBufferPtr& buf, const Point& p, BlitFlags flags,
				     Color tint = Color()) = 0;
	virtual void BlitVideoBufferFully(const VideoBufferPtr& buf, BlitFlags flags,
					  Color tint = Color()) = 0;

	/** Return GemRB window screenshot.
	 * It's generated from the momentary back buffer */
	virtual Holder<Sprite2D> GetScreenshot(Region r, const VideoBufferPtr& buf = nullptr) = 0;
	/** This function Draws the Border of a Rectangle as described by the Region parameter. The Color used to draw the rectangle is passes via the Color parameter. */
	void DrawRect(const Region& rgn, const Color& color, bool fill = true, BlitFlags flags = BlitFlags::NONE);

	void DrawPoint(const BasePoint&, const Color& color, BlitFlags flags = BlitFlags::NONE);
	void DrawPoints(const std::vector<BasePoint>& points, const Color& color, BlitFlags flags = BlitFlags::NONE);

	// draw a circle at origin with radius r
	void DrawCircle(const Point& origin, uint16_t r, const Color& color, BlitFlags flags = BlitFlags::NONE);
	// Draw an ellipse bounded by rect
	void DrawEllipse(const Region& rect, const Color& color, BlitFlags flags = BlitFlags::NONE);
	/** Draws a polygon on the screen */
	void DrawPolygon(const Gem_Polygon* poly, const Point& origin, const Color& color, bool fill = false, BlitFlags flags = BlitFlags::NONE);
	/** Draws a line segment */
	void DrawLine(const BasePoint& p1, const BasePoint& p2, const Color& color, BlitFlags flags = BlitFlags::NONE);
	void DrawLines(const std::vector<Point>& points, const Color& color, BlitFlags flags = BlitFlags::NONE);
	virtual void DrawRawGeometry(
		const std::vector<float>& /*vertices*/,
		const std::vector<Color>& /*colors*/,
		BlitFlags /*blitFlags*/
	) {};
	/** Sets Event Manager */
	void SetEventMgr(EventMgr* evnt);

	/** Sets Clip Rectangle */
	void SetScreenClip(const Region* clip, bool toScreen = true);
	/** Gets Clip Rectangle */
	const Region& GetScreenClip() const { return screenClip; }
	// the screen clip in the units of the current drawing target (map units inside a scene)
	Region DrawingClip() const;

	virtual void SetGamma(int brightness, int contrast) = 0;

	/** Scales down a sprite by a ratio */
	Holder<Sprite2D> SpriteScaleDown(const Holder<Sprite2D>& sprite, unsigned int ratio);

	Color SpriteGetPixelSum(const Holder<Sprite2D>& sprite, unsigned short xbase, unsigned short ybase, unsigned int ratio) const;
};

extern GEM_EXPORT PluginHolder<Video> VideoDriver;

}

#endif
