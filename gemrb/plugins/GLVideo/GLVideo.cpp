// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

// OpenGL 3.3 video driver (SDL2 for window, context and input).
// Every draw goes through one batched shader; paletted sprites keep their
// 8 bit indices on the GPU and are coloured in the fragment shader.

#include "GLVideo.h"

#include "GLShaders.h"
#include "Geometry.h"
#include "Interface.h"
#include "Palette.h"
#include "Polygon.h"

#include "Logging/Logging.h"
#include "Video/RLE.h"

#include <cmath>
#include <cstdarg>

using namespace GemRB;

// ---------------------------------------------------------------- helpers

static GLuint CompileShader(GLenum type, const char* src)
{
	GLuint s = glCreateShader(type);
	glShaderSource(s, 1, &src, nullptr);
	glCompileShader(s);
	GLint ok = 0;
	glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
	if (!ok) {
		char log[2048];
		glGetShaderInfoLog(s, sizeof(log), nullptr, log);
		Log(ERROR, "GLVideo", "Shader compile failed: {}", log);
		glDeleteShader(s);
		return 0;
	}
	return s;
}

static GLuint LinkProgram(const char* vs, const char* fs)
{
	GLuint v = CompileShader(GL_VERTEX_SHADER, vs);
	GLuint f = CompileShader(GL_FRAGMENT_SHADER, fs);
	if (!v || !f) return 0;
	GLuint p = glCreateProgram();
	glAttachShader(p, v);
	glAttachShader(p, f);
	glLinkProgram(p);
	glDeleteShader(v);
	glDeleteShader(f);
	GLint ok = 0;
	glGetProgramiv(p, GL_LINK_STATUS, &ok);
	if (!ok) {
		char log[2048];
		glGetProgramInfoLog(p, sizeof(log), nullptr, log);
		Log(ERROR, "GLVideo", "Program link failed: {}", log);
		glDeleteProgram(p);
		return 0;
	}
	return p;
}

static inline int GetModState(int modstate)
{
	int value = 0;
	if (modstate & KMOD_SHIFT) value |= GEM_MOD_SHIFT;
	if (modstate & KMOD_CTRL) value |= GEM_MOD_CTRL;
	if (modstate & KMOD_ALT) value |= GEM_MOD_ALT;
	return value;
}

// ---------------------------------------------------------------- video buffers

static Size PhysSize(const Size& s, float scale)
{
	return Size(std::max(1, int(std::lround(s.w * scale))), std::max(1, int(std::lround(s.h * scale))));
}

// colour texture + FBO, cleared to transparent
static void CreateTarget(Size size, GLuint& tex, GLuint& fbo)
{
	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, size.w, size.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
	glClearColor(0, 0, 0, 0);
	glDisable(GL_SCISSOR_TEST);
	glClear(GL_COLOR_BUFFER_BIT);
}

GLVideoBuffer::GLVideoBuffer(const Region& r, Video::BufferFormat fmt, GLVideoDriver* drv, float s)
	: VideoBuffer(r), driver(drv), format(fmt), scale(s), physSize(PhysSize(r.size, s))
{
	CreateTarget(physSize, texture, fbo);
}

void GLVideoBuffer::Rescale(float newScale)
{
	::GemRB::Size newPhys = PhysSize(rect.size, newScale);
	if (newPhys == physSize) {
		scale = newScale;
		return;
	}
	driver->Flush();
	GLuint newTex = 0, newFbo = 0;
	CreateTarget(newPhys, newTex, newFbo);
	driver->CopyTexture(newFbo, newPhys, Region(Point(), newPhys), texture, Region(Point(), physSize), true);
	glDeleteFramebuffers(1, &fbo);
	glDeleteTextures(1, &texture);
	texture = newTex;
	fbo = newFbo;
	physSize = newPhys;
	scale = newScale;
}

GLVideoBuffer::~GLVideoBuffer()
{
	driver->Flush();
	glDeleteFramebuffers(1, &fbo);
	glDeleteTextures(1, &texture);
}

void GLVideoBuffer::Clear(const Region& rgn)
{
	driver->ClearBuffer(this, rgn);
}

static inline uint32_t PackRGBA(uint8_t r, uint8_t g, uint8_t b, uint8_t a)
{
	return uint32_t(r) | (uint32_t(g) << 8) | (uint32_t(b) << 16) | (uint32_t(a) << 24);
}

static inline uint8_t ClampByte(int v)
{
	return uint8_t(v < 0 ? 0 : (v > 255 ? 255 : v));
}

void GLVideoBuffer::CopyPixels(const Region& dest, const void* pixelBuf, const int* pitch, ...)
{
	if (dest.w <= 0 || dest.h <= 0) return;
	driver->Flush();
	std::vector<uint32_t> rgba(size_t(dest.w) * dest.h);
	va_list args;
	va_start(args, pitch);

	switch (format) {
		case Video::BufferFormat::YV12:
			{
				const uint8_t* yP = static_cast<const uint8_t*>(pixelBuf);
				int yS = *pitch;
				const uint8_t* uP = va_arg(args, const uint8_t*);
				int uS = *va_arg(args, int*);
				const uint8_t* vP = va_arg(args, const uint8_t*);
				int vS = *va_arg(args, int*);
				for (int y = 0; y < dest.h; ++y) {
					for (int x = 0; x < dest.w; ++x) {
						int Y = yP[y * yS + x] - 16;
						int U = uP[(y / 2) * uS + x / 2] - 128;
						int V = vP[(y / 2) * vS + x / 2] - 128;
						int C = 298 * Y;
						rgba[y * dest.w + x] = PackRGBA(ClampByte((C + 409 * V + 128) >> 8),
										ClampByte((C - 100 * U - 208 * V + 128) >> 8),
										ClampByte((C + 516 * U + 128) >> 8), 255);
					}
				}
			}
			break;
		case Video::BufferFormat::RGBPAL8:
			{
				const Palette* pal = va_arg(args, const Palette*);
				int stride = pitch ? *pitch : dest.w;
				const uint8_t* src = static_cast<const uint8_t*>(pixelBuf);
				for (int y = 0; y < dest.h; ++y) {
					for (int x = 0; x < dest.w; ++x) {
						const Color& c = pal->GetColorAt(src[y * stride + x]);
						rgba[y * dest.w + x] = PackRGBA(c.r, c.g, c.b, 255);
					}
				}
			}
			break;
		case Video::BufferFormat::RGB555:
			{
				int stride = pitch ? *pitch : dest.w * 2;
				const uint8_t* src = static_cast<const uint8_t*>(pixelBuf);
				for (int y = 0; y < dest.h; ++y) {
					const uint16_t* row = reinterpret_cast<const uint16_t*>(src + y * stride);
					for (int x = 0; x < dest.w; ++x) {
						uint16_t p = row[x];
						uint8_t r = (p >> 10) & 0x1f, g = (p >> 5) & 0x1f, b = p & 0x1f;
						rgba[y * dest.w + x] = PackRGBA(uint8_t((r << 3) | (r >> 2)), uint8_t((g << 3) | (g >> 2)), uint8_t((b << 3) | (b >> 2)), 255);
					}
				}
			}
			break;
		case Video::BufferFormat::RGBA8888:
			{
				// SDL_PIXELFORMAT_RGBA8888: packed 32 bit, R in the high byte
				int stride = pitch ? *pitch : dest.w * 4;
				const uint8_t* src = static_cast<const uint8_t*>(pixelBuf);
				for (int y = 0; y < dest.h; ++y) {
					const uint32_t* row = reinterpret_cast<const uint32_t*>(src + y * stride);
					for (int x = 0; x < dest.w; ++x) {
						uint32_t p = row[x];
						rgba[y * dest.w + x] = PackRGBA(p >> 24, p >> 16, p >> 8, p);
					}
				}
			}
			break;
		default:
			{
				// DISPLAY formats: we treat them as our own RGBA8
				int stride = pitch ? *pitch : dest.w * 4;
				const uint8_t* src = static_cast<const uint8_t*>(pixelBuf);
				for (int y = 0; y < dest.h; ++y) {
					memcpy(&rgba[y * dest.w], src + y * stride, dest.w * 4);
				}
			}
			break;
	}
	va_end(args);

	glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
	if (physSize == rect.size) {
		glBindTexture(GL_TEXTURE_2D, texture);
		glTexSubImage2D(GL_TEXTURE_2D, 0, dest.x, dest.y, dest.w, dest.h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
		return;
	}
	// scaled buffer: upload at the source size, then resample into place
	GLuint tmp = 0;
	glGenTextures(1, &tmp);
	glBindTexture(GL_TEXTURE_2D, tmp);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, dest.w, dest.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
	Region dst(int(std::floor(dest.x * scale)), int(std::floor(dest.y * scale)), int(std::lround(dest.w * scale)), int(std::lround(dest.h * scale)));
	driver->CopyTexture(fbo, physSize, dst, tmp, Region(0, 0, dest.w, dest.h), true);
	glDeleteTextures(1, &tmp);
}

bool GLVideoBuffer::RenderOnDisplay(void*) const
{
	driver->CompositeBuffer(this);
	return true;
}

// ---------------------------------------------------------------- driver setup

GLVideoDriver::~GLVideoDriver() noexcept
{
	if (gameController) SDL_GameControllerClose(gameController);
	// buffers own GL objects; release them while the context still exists.
	// the context itself is left to process teardown, because sprites holding
	// textures can outlive the driver
	DestroyBuffers();
	if (window) SDL_DestroyWindow(window);
	SDL_QuitSubSystem(SDL_INIT_GAMECONTROLLER | SDL_INIT_JOYSTICK | SDL_INIT_VIDEO);
}

int GLVideoDriver::Init()
{
	if (SDL_InitSubSystem(SDL_INIT_VIDEO) == -1) {
		Log(ERROR, "GLVideo", "InitSubSystem failed: {}", SDL_GetError());
		return GEM_ERROR;
	}
	SDL_ShowCursor(SDL_DISABLE);

	if (core->config.GamepadSupport && SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) == 0) {
		for (int i = 0; i < SDL_NumJoysticks(); ++i) {
			if (SDL_IsGameController(i)) {
				gameController = SDL_GameControllerOpen(i);
				if (gameController) break;
			}
		}
	}
	return GEM_OK;
}

int GLVideoDriver::CreateDriverDisplay(const char* title, bool vsync)
{
	Log(MESSAGE, "GLVideo", "Creating OpenGL 3.3 display {}x{}", screenSize.w, screenSize.h);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
	SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
	SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);

	window = SDL_CreateWindow(title, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, screenSize.w, screenSize.h,
				  SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE | SDL_WINDOW_OPENGL | SDL_WINDOW_ALLOW_HIGHDPI);
	if (!window) {
		Log(ERROR, "GLVideo", "couldn't create window: {}", SDL_GetError());
		return GEM_ERROR;
	}
	glContext = SDL_GL_CreateContext(window);
	if (!glContext) {
		Log(ERROR, "GLVideo", "couldn't create OpenGL 3.3 context: {}", SDL_GetError());
		return GEM_ERROR;
	}
	SDL_GL_MakeCurrent(window, glContext);
	glewExperimental = GL_TRUE;
	GLenum err = glewInit();
	if (err != GLEW_OK) {
		Log(ERROR, "GLVideo", "glewInit failed: {}", reinterpret_cast<const char*>(glewGetErrorString(err)));
		return GEM_ERROR;
	}
	glGetError(); // glew may leave GL_INVALID_ENUM behind on core profiles

	if (vsync) {
		// adaptive vsync first, plain vsync if that is unsupported
		if (SDL_GL_SetSwapInterval(-1) != 0) SDL_GL_SetSwapInterval(1);
	} else {
		SDL_GL_SetSwapInterval(0);
	}

	Log(MESSAGE, "GLVideo", "OpenGL {} on {}", reinterpret_cast<const char*>(glGetString(GL_VERSION)), reinterpret_cast<const char*>(glGetString(GL_RENDERER)));

	highRes = core->GetDictionary().Get("GLHighResolution", 1) != 0;
	if (!CreateResources()) return GEM_ERROR;

	SDL_DisplayMode dm {};
	if (SDL_GetCurrentDisplayMode(0, &dm) == 0 && dm.refresh_rate > 0) {
		refreshRate = dm.refresh_rate;
	}
	SDL_StopTextInput();
	UpdatePresentRect();
	return GEM_OK;
}

bool GLVideoDriver::CreateResources()
{
	program = LinkProgram(SpriteVS, SpriteFS);
	if (!program) return false;
	uni.targetSize = glGetUniformLocation(program, "u_targetSize");
	uni.flipY = glGetUniformLocation(program, "u_flipY");
	uni.texMode = glGetUniformLocation(program, "u_texMode");
	uni.rgba = glGetUniformLocation(program, "u_rgba");
	uni.index = glGetUniformLocation(program, "u_index");
	uni.palette = glGetUniformLocation(program, "u_palette");
	uni.stencil = glGetUniformLocation(program, "u_stencil");
	uni.stencilChannel = glGetUniformLocation(program, "u_stencilChannel");
	uni.dither = glGetUniformLocation(program, "u_dither");
	uni.stencilA = glGetUniformLocation(program, "u_stencilA");
	uni.stencilB = glGetUniformLocation(program, "u_stencilB");
	uni.smooth = glGetUniformLocation(program, "u_smooth");
	uni.post = glGetUniformLocation(program, "u_post");
	uni.objDepth = glGetUniformLocation(program, "u_objDepth");
	uni.depthPremul = glGetUniformLocation(program, "u_depthPremul");
	uni.outline = glGetUniformLocation(program, "u_outline");
	uni.outlineRadius = glGetUniformLocation(program, "u_outlineRadius");
	glUseProgram(program);
	glUniform1i(uni.rgba, 0);
	glUniform1i(uni.index, 1);
	glUniform1i(uni.palette, 2);
	glUniform1i(uni.stencil, 3);

	lightProgram = LinkProgram(SpriteVS, LightFS);
	if (lightProgram) {
		luni.targetSize = glGetUniformLocation(lightProgram, "u_targetSize");
		luni.flipY = glGetUniformLocation(lightProgram, "u_flipY");
		luni.mode = glGetUniformLocation(lightProgram, "u_mode");
		luni.scene = glGetUniformLocation(lightProgram, "u_scene");
		luni.light = glGetUniformLocation(lightProgram, "u_light");
		luni.sceneSize = glGetUniformLocation(lightProgram, "u_sceneSize");
		luni.keep = glGetUniformLocation(lightProgram, "u_keep");
		luni.maxLight = glGetUniformLocation(lightProgram, "u_maxLight");
		luni.spriteDepth = glGetUniformLocation(lightProgram, "u_spriteDepth");
		luni.wallDepth = glGetUniformLocation(lightProgram, "u_wallDepth");
		luni.geom = glGetUniformLocation(lightProgram, "u_geom");
		luni.lightPos = glGetUniformLocation(lightProgram, "u_lightPos");
		luni.lightColor = glGetUniformLocation(lightProgram, "u_lightColor");
		luni.map = glGetUniformLocation(lightProgram, "u_map");
		luni.regionOrigin = glGetUniformLocation(lightProgram, "u_regionOrigin");
		luni.lightToPhys = glGetUniformLocation(lightProgram, "u_lightToPhys");
		luni.bump = glGetUniformLocation(lightProgram, "u_bump");
		luni.normalStrength = glGetUniformLocation(lightProgram, "u_normalStrength");
		luni.debug = glGetUniformLocation(lightProgram, "u_debug");
		glUseProgram(lightProgram);
		glUniform1i(luni.scene, 0);
		glUniform1i(luni.light, 1);
		glUniform1i(luni.spriteDepth, 2);
		glUniform1i(luni.wallDepth, 3);
		glUseProgram(program);
	} else {
		Log(WARNING, "GLVideo", "Lighting shader unavailable, scene lighting disabled");
	}

	postProgram = LinkProgram(SpriteVS, PostFS);
	if (postProgram) {
		puni.targetSize = glGetUniformLocation(postProgram, "u_targetSize");
		puni.flipY = glGetUniformLocation(postProgram, "u_flipY");
		puni.mode = glGetUniformLocation(postProgram, "u_mode");
		puni.src = glGetUniformLocation(postProgram, "u_src");
		puni.bloom = glGetUniformLocation(postProgram, "u_bloom");
		puni.srcSize = glGetUniformLocation(postProgram, "u_srcSize");
		puni.dir = glGetUniformLocation(postProgram, "u_dir");
		puni.threshold = glGetUniformLocation(postProgram, "u_threshold");
		puni.bloomStrength = glGetUniformLocation(postProgram, "u_bloomStrength");
		puni.grade = glGetUniformLocation(postProgram, "u_grade");
		puni.saturation = glGetUniformLocation(postProgram, "u_saturation");
		puni.contrast = glGetUniformLocation(postProgram, "u_contrast");
		puni.lift = glGetUniformLocation(postProgram, "u_lift");
		puni.gain = glGetUniformLocation(postProgram, "u_gain");
		puni.vignette = glGetUniformLocation(postProgram, "u_vignette");
		glUseProgram(postProgram);
		glUniform1i(puni.src, 0);
		glUniform1i(puni.bloom, 1);
		glUseProgram(program);
	} else {
		Log(WARNING, "GLVideo", "Post shader unavailable, bloom/grading/vignette disabled");
	}

	glGenVertexArrays(1, &vao);
	glBindVertexArray(vao);
	glGenBuffers(1, &vbo);
	glBindBuffer(GL_ARRAY_BUFFER, vbo);
	glEnableVertexAttribArray(0);
	glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, sizeof(GLVertex), reinterpret_cast<void*>(offsetof(GLVertex, x)));
	glEnableVertexAttribArray(1);
	glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(GLVertex), reinterpret_cast<void*>(offsetof(GLVertex, u)));
	glEnableVertexAttribArray(2);
	glVertexAttribPointer(2, 4, GL_UNSIGNED_BYTE, GL_TRUE, sizeof(GLVertex), reinterpret_cast<void*>(offsetof(GLVertex, r)));
	glEnableVertexAttribArray(3);
	glVertexAttribPointer(3, 4, GL_FLOAT, GL_FALSE, sizeof(GLVertex), reinterpret_cast<void*>(offsetof(GLVertex, pal)));

	glGenTextures(1, &paletteTex);
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 256, PaletteRows, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

	const float zero4[4] = { 0, 0, 0, 0 };
	glGenTextures(1, &zeroTex);
	glBindTexture(GL_TEXTURE_2D, zeroTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, 1, 1, 0, GL_RGBA, GL_FLOAT, zero4);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);

	uint32_t white = 0xffffffff;
	glGenTextures(1, &whiteTex);
	glBindTexture(GL_TEXTURE_2D, whiteTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, &white);

	// screen composite target (physical size, follows the render scale)
	screenPhys = screenSize;
	CreateTarget(screenPhys, screenTex, screenFbo);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
		Log(ERROR, "GLVideo", "Screen framebuffer incomplete");
		return false;
	}
	return true;
}

void GLVideoDriver::ResizeScreenTarget()
{
	Flush();
	glDeleteFramebuffers(1, &screenFbo);
	glDeleteTextures(1, &screenTex);
	CreateTarget(screenPhys, screenTex, screenFbo);
}

Region GLVideoDriver::ToPhys(const Region& r, float scale)
{
	int x0 = int(std::floor(r.x * scale));
	int y0 = int(std::floor(r.y * scale));
	int x1 = int(std::ceil((r.x + r.w) * scale));
	int y1 = int(std::ceil((r.y + r.h) * scale));
	return Region(x0, y0, x1 - x0, y1 - y0);
}

Region GLVideoDriver::XfRegion(const Region& r) const
{
	float x0 = float(r.x), y0 = float(r.y), x1 = float(r.x + r.w), y1 = float(r.y + r.h);
	xf.Apply(x0, y0);
	xf.Apply(x1, y1);
	int ix0 = int(std::floor(std::min(x0, x1)));
	int iy0 = int(std::floor(std::min(y0, y1)));
	return Region(ix0, iy0, int(std::ceil(std::max(x0, x1))) - ix0, int(std::ceil(std::max(y0, y1))) - iy0);
}

void GLVideoDriver::CopyTexture(GLuint dstFbo, Size dstSize, const Region& dstRect, GLuint srcTex, const Region& srcRect, bool smooth)
{
	GLBatchState st;
	st.fbo = dstFbo;
	st.targetSize = dstSize;
	st.scissor = Region(Point(), dstSize);
	st.texMode = 1;
	st.texture = srcTex;
	st.blend = GLBlend::None;
	st.smooth = smooth;
	SetBatch(st);
	xf = GLXform();
	PushQuad(float(dstRect.x), float(dstRect.y), float(dstRect.x + dstRect.w), float(dstRect.y + dstRect.h),
		 float(srcRect.x), float(srcRect.y), float(srcRect.x + srcRect.w), float(srcRect.y + srcRect.h), ColorWhite);
	Flush();
	batchValid = false;
}

VideoBuffer* GLVideoDriver::NewVideoBuffer(const Region& r, BufferFormat fmt)
{
	Flush();
	return new GLVideoBuffer(r, fmt, this, GLVideoBuffer::FollowsRenderScale(fmt) ? renderScale : 1.0f);
}

Holder<Sprite2D> GLVideoDriver::CreateSprite(const Region& rgn, void* pixels, const PixelFormat& fmt)
{
	if (fmt.RLE) {
		void* decoded = DecodeRLEData(static_cast<uint8_t*>(pixels), rgn.size, fmt.ColorKey);
		free(pixels);
		PixelFormat newfmt = fmt;
		newfmt.RLE = false;
		return MakeHolder<GLSprite2D>(rgn, decoded, newfmt);
	}
	return MakeHolder<GLSprite2D>(rgn, pixels, fmt);
}

// ---------------------------------------------------------------- batching

void GLVideoDriver::Flush()
{
	if (!batchValid || vertices.empty()) {
		vertices.clear();
		return;
	}
	const GLBatchState& st = batch;
	glBindFramebuffer(GL_FRAMEBUFFER, st.fbo);
	if (st.fbo == 0) {
		glViewport(0, 0, windowPixels.w, windowPixels.h);
	} else {
		glViewport(0, 0, st.targetSize.w, st.targetSize.h);
	}
	glUseProgram(program);
	glUniform2f(uni.targetSize, float(st.targetSize.w), float(st.targetSize.h));
	glUniform1i(uni.flipY, st.flipY ? 1 : 0);
	glUniform1i(uni.texMode, st.texMode);
	glUniform1i(uni.stencilChannel, st.stencilChannel);
	glUniform1i(uni.dither, st.dither);
	glUniform1f(uni.stencilA, st.stencilA);
	glUniform2f(uni.stencilB, st.stencilBx, st.stencilBy);
	glUniform1i(uni.smooth, st.smooth ? 1 : 0);
	glUniform2f(uni.post, st.brightness, st.contrast);
	glUniform4f(uni.outline, st.outline.r / 255.0f, st.outline.g / 255.0f, st.outline.b / 255.0f, st.outline.a / 255.0f);
	glUniform1f(uni.outlineRadius, st.outlineRadius);
	if (depthAttachedFbo && st.fbo == depthAttachedFbo) {
		bool write = st.depthWrite && st.texMode != 0 && (st.blend == GLBlend::Alpha || st.blend == GLBlend::Premultiplied);
		glColorMaski(1, write, write, write, write);
		glUniform1f(uni.objDepth, st.objDepth);
		glUniform1i(uni.depthPremul, st.blend == GLBlend::Premultiplied ? 1 : 0);
	}

	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, st.texMode == 1 ? st.texture : whiteTex);
	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, st.texMode == 2 ? st.texture : 0);
	glActiveTexture(GL_TEXTURE2);
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glActiveTexture(GL_TEXTURE3);
	glBindTexture(GL_TEXTURE_2D, st.stencilTex);
	glActiveTexture(GL_TEXTURE0);

	if (st.scissor.w > 0 && st.scissor.h > 0 && st.fbo != 0) {
		glEnable(GL_SCISSOR_TEST);
		glScissor(st.scissor.x, st.scissor.y, st.scissor.w, st.scissor.h);
	} else {
		glDisable(GL_SCISSOR_TEST);
	}

	if (st.blend == GLBlend::None) {
		glDisable(GL_BLEND);
	} else {
		glEnable(GL_BLEND);
		glBlendEquation(GL_FUNC_ADD);
		switch (st.blend) {
			case GLBlend::Alpha:
				glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
				break;
			case GLBlend::Add:
				glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE, GL_ZERO, GL_ONE);
				break;
			case GLBlend::Mod:
				glBlendFuncSeparate(GL_ZERO, GL_SRC_COLOR, GL_ZERO, GL_ONE);
				break;
			case GLBlend::Mul:
				glBlendFuncSeparate(GL_DST_COLOR, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE);
				break;
			case GLBlend::Src:
				glBlendFuncSeparate(GL_SRC_COLOR, GL_ONE, GL_SRC_COLOR, GL_ONE);
				break;
			case GLBlend::OneMinusDst:
				glBlendFuncSeparate(GL_ONE_MINUS_DST_COLOR, GL_ONE, GL_ONE_MINUS_DST_COLOR, GL_ONE);
				break;
			case GLBlend::Dst:
				glBlendFuncSeparate(GL_DST_COLOR, GL_ONE, GL_DST_COLOR, GL_ONE);
				break;
			case GLBlend::Premultiplied:
				glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
				break;
			default:
				break;
		}
	}

	glBindVertexArray(vao);
	glBindBuffer(GL_ARRAY_BUFFER, vbo);
	glBufferData(GL_ARRAY_BUFFER, vertices.size() * sizeof(GLVertex), vertices.data(), GL_STREAM_DRAW);
	glDrawArrays(GL_TRIANGLES, 0, GLsizei(vertices.size()));
	vertices.clear();
}

void GLVideoDriver::SetBatch(const GLBatchState& state)
{
	if (!batchValid || state != batch) {
		Flush();
		batch = state;
		batchValid = true;
	}
}

// state for drawing into the current buffer; also sets the vertex transform:
// logical buffer pixels (or scene map units) -> physical target pixels
GLBatchState GLVideoDriver::TargetState()
{
	GLBatchState st;
	const GLVideoBuffer* target = static_cast<const GLVideoBuffer*>(drawingBuffer);
	assert(target);
	st.fbo = target->fbo;
	st.targetSize = target->physSize;
	float s = target->scale;
	Region bufRgn(Point(), target->Size());
	Region clip = screenClip.Intersect(bufRgn);
	if (SceneAppliesToTarget()) {
		float z = scene.zoom * s;
		baseXf.sx = baseXf.sy = z;
		baseXf.tx = (scene.rect.x + scene.offsetX) * s;
		baseXf.ty = (scene.rect.y + scene.offsetY) * s;
		xf = baseXf;
		xf.tx += scene.objectX * z;
		xf.ty += scene.objectY * z;
		clip = clip.Intersect(scene.rect);
		if (scene.objectHasDepth && depthAttachedFbo == target->fbo) {
			st.depthWrite = true;
			st.objDepth = scene.objectDepth;
		}
	} else {
		baseXf = GLXform();
		baseXf.sx = baseXf.sy = s;
		xf = baseXf;
	}
	st.scissor = clip.size.IsInvalid() ? Region(0, 0, 0, 0) : ToPhys(clip, s);
	return st;
}

void GLVideoDriver::SetupStencil(GLBatchState& st, BlitFlags flags)
{
	if (!(flags & BlitFlags::STENCIL_MASK) || !stencilBuffer) return;
	const GLVideoBuffer* sb = static_cast<const GLVideoBuffer*>(stencilBuffer.get());
	st.stencilTex = sb->texture;
	// fragment (physical target px) -> drawing units -> stencil texel
	float k = sb->scale;
	float S = baseXf.sx;
	st.stencilA = k / S;
	st.stencilBx = (-baseXf.tx / S - float(sb->Origin().x)) * k;
	st.stencilBy = (-baseXf.ty / S - float(sb->Origin().y)) * k;
	st.stencilChannel = 3;
	if (flags & BlitFlags::STENCIL_RED) {
		st.stencilChannel = 0;
	} else if (flags & BlitFlags::STENCIL_GREEN) {
		st.stencilChannel = 1;
	} else if (flags & BlitFlags::STENCIL_BLUE) {
		st.stencilChannel = 2;
	}
	st.dither = (flags & BlitFlags::STENCIL_DITHER) ? 1 : 0;
}

void GLVideoDriver::PushQuad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, const Color& c, float pal, float grey, float ckey)
{
	xf.Apply(x0, y0);
	xf.Apply(x1, y1);
	GLVertex a { x0, y0, u0, v0, c.r, c.g, c.b, c.a, pal, grey, ckey, 0 };
	GLVertex b { x1, y0, u1, v0, c.r, c.g, c.b, c.a, pal, grey, ckey, 0 };
	GLVertex d { x0, y1, u0, v1, c.r, c.g, c.b, c.a, pal, grey, ckey, 0 };
	GLVertex e { x1, y1, u1, v1, c.r, c.g, c.b, c.a, pal, grey, ckey, 0 };
	vertices.push_back(a);
	vertices.push_back(b);
	vertices.push_back(d);
	vertices.push_back(b);
	vertices.push_back(e);
	vertices.push_back(d);
}

void GLVideoDriver::PushColorRect(const Region& r, const Color& c)
{
	PushQuad(float(r.x), float(r.y), float(r.x + r.w), float(r.y + r.h), 0, 0, 1, 1, c);
}

void GLVideoDriver::PushLine(const BasePoint& p1, const BasePoint& p2, const Color& c)
{
	if (p1.y == p2.y) {
		int x0 = std::min(p1.x, p2.x), x1 = std::max(p1.x, p2.x);
		PushColorRect(Region(x0, p1.y, x1 - x0 + 1, 1), c);
		return;
	}
	if (p1.x == p2.x) {
		int y0 = std::min(p1.y, p2.y), y1 = std::max(p1.y, p2.y);
		PushColorRect(Region(p1.x, y0, 1, y1 - y0 + 1), c);
		return;
	}
	// 1px wide quad through the pixel centres, extended half a pixel at both ends
	float ax = p1.x + 0.5f, ay = p1.y + 0.5f, bx = p2.x + 0.5f, by = p2.y + 0.5f;
	float dx = bx - ax, dy = by - ay;
	float len = std::sqrt(dx * dx + dy * dy);
	dx /= len;
	dy /= len;
	ax -= dx * 0.5f;
	ay -= dy * 0.5f;
	bx += dx * 0.5f;
	by += dy * 0.5f;
	float nx = -dy * 0.5f, ny = dx * 0.5f;
	float q[4][2] = { { ax + nx, ay + ny }, { bx + nx, by + ny }, { ax - nx, ay - ny }, { bx - nx, by - ny } };
	for (auto& pt : q) xf.Apply(pt[0], pt[1]);
	GLVertex v[4] = {
		{ q[0][0], q[0][1], 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
		{ q[1][0], q[1][1], 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
		{ q[2][0], q[2][1], 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
		{ q[3][0], q[3][1], 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
	};
	vertices.push_back(v[0]);
	vertices.push_back(v[1]);
	vertices.push_back(v[2]);
	vertices.push_back(v[1]);
	vertices.push_back(v[3]);
	vertices.push_back(v[2]);
}

int GLVideoDriver::PaletteRow(const Palette* pal)
{
	PalKey key { pal, pal->GetVersion() };
	auto it = paletteRows.find(key);
	if (it != paletteRows.end()) return it->second;
	if (nextPaletteRow >= PaletteRows) {
		// atlas full: draw what we have and start over
		Flush();
		paletteRows.clear();
		nextPaletteRow = 0;
	}
	int row = nextPaletteRow++;
	glBindTexture(GL_TEXTURE_2D, paletteTex);
	glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
	static_assert(sizeof(Color) == 4, "Color must be RGBA8");
	glTexSubImage2D(GL_TEXTURE_2D, 0, 0, row, 256, 1, GL_RGBA, GL_UNSIGNED_BYTE, pal->ColorData());
	paletteRows.emplace(key, row);
	return row;
}

static GLBlend BlendForFlags(BlitFlags flags)
{
	if (flags & BlitFlags::ADD) return GLBlend::Add;
	if (flags & BlitFlags::MOD) return GLBlend::Mod;
	if (flags & BlitFlags::MUL) return GLBlend::Mul;
	if (flags & BlitFlags::SRC) return GLBlend::Src;
	if (flags & BlitFlags::ONE_MINUS_DST) return GLBlend::OneMinusDst;
	if (flags & BlitFlags::DST) return GLBlend::Dst;
	if (flags & (BlitFlags::BLENDED | BlitFlags::HALFTRANS)) return GLBlend::Alpha;
	return GLBlend::None;
}

void GLVideoDriver::ApplyColorBlend(GLBatchState& st, BlitFlags flags) const
{
	if (flags & BlitFlags::BLENDED) {
		st.blend = GLBlend::Alpha;
	} else if (flags & BlitFlags::MOD) {
		st.blend = GLBlend::Mod;
	} else {
		st.blend = GLBlend::None;
	}
}

// ---------------------------------------------------------------- sprites

void GLVideoDriver::BlitSprite(const Holder<Sprite2D>& spr, const Region& src, Region dst, BlitFlags flags, Color tint)
{
	dst.x -= spr->Frame.x;
	dst.y -= spr->Frame.y;
	DrawSprite(spr, src, dst, flags, tint);
}

void GLVideoDriver::BlitGameSprite(const Holder<Sprite2D>& spr, const Point& p, BlitFlags flags, Color tint)
{
	Region src(Point(0, 0), spr->Frame.size);
	Region dst(p - spr->Frame.origin, spr->Frame.size);
	DrawSprite(spr, src, dst, flags, tint);
}

bool GLVideoDriver::PrepareSprite(const Holder<Sprite2D>& spr, BlitFlags& flags, GLBatchState& st, float& pal, float& ckey, float& texelScale)
{
	texelScale = 1.0f;
	const GLSprite2D* gspr = dynamic_cast<const GLSprite2D*>(spr.get());
	if (!gspr) {
		Log(WARNING, "GLVideo", "Skipping a sprite not created by this driver");
		return false;
	}

	if (spr->renderFlags & BlitFlags::MIRRORX) flags ^= BlitFlags::MIRRORX;
	if (spr->renderFlags & BlitFlags::MIRRORY) flags ^= BlitFlags::MIRRORY;
	flags |= spr->renderFlags & BlitFlags::BLEND_MASK;
	if (!spr->HasTransparency()) flags &= ~BlitFlags::BLENDED;

	pal = -1;
	ckey = -1;
	// A twin is display-only. UVs stay in low-res texels and callers multiply by texelScale,
	// so the shader's fwidth still means "texels covered by this fragment".
	// An indexed twin keeps the palette of the sprite being drawn: font pages invert that
	// palette for the second pass, and both passes sample the same hi-res indices.
	const GLSprite2D* hi = spr->hiRes ? dynamic_cast<const GLSprite2D*>(spr->hiRes.get()) : nullptr;
	if (spr->hiRes && !hi) {
		static bool warnedCast = false;
		if (!warnedCast) {
			Log(WARNING, "GLVideo", "hi-res twin is not a GL sprite; drawing the original.");
			warnedCast = true;
		}
	}
	if (hi && spr->Frame.w > 0 && spr->Frame.h > 0 &&
	    hi->Frame.w >= spr->Frame.w * 2 && hi->Frame.h >= spr->Frame.h * 2 &&
	    hi->Frame.w % spr->Frame.w == 0 && hi->Frame.h % spr->Frame.h == 0 &&
	    hi->Frame.w / spr->Frame.w == hi->Frame.h / spr->Frame.h) {
		if (hi->NeedsReupload()) Flush();
		bool uploaded = false;
		GLuint tex = hi->GetTexture(uploaded);
		if (tex && hi->IsIndexed()) {
			const Holder<Palette>& palette = spr->GetPalette();
			if (palette) {
				texelScale = float(hi->Frame.w / spr->Frame.w);
				if (hi->HasTransparency()) flags |= BlitFlags::BLENDED;
				if (flags & (BlitFlags::ONE_MINUS_DST | BlitFlags::DST | BlitFlags::SRC)) {
					Color ck = palette->GetColorAt(0);
					if (ck != ColorBlack) {
						Palette tmp(*palette);
						tmp.SetColor(0, ColorBlack);
						if (nextPaletteRow >= PaletteRows) {
							Flush();
							paletteRows.clear();
							nextPaletteRow = 0;
						}
						int row = nextPaletteRow++;
						glBindTexture(GL_TEXTURE_2D, paletteTex);
						glTexSubImage2D(GL_TEXTURE_2D, 0, 0, row, 256, 1, GL_RGBA, GL_UNSIGNED_BYTE, tmp.ColorData());
						pal = float(row);
					} else {
						pal = float(PaletteRow(palette.get()));
					}
				} else {
					pal = float(PaletteRow(palette.get()));
				}
				if (spr->Format().HasColorKey) ckey = float(spr->GetColorKey());
				st.texMode = 2;
				st.texture = tex;
				st.blend = BlendForFlags(flags);
				SetupStencil(st, flags);
				return true;
			}
		} else if (tex) {
			texelScale = float(hi->Frame.w / spr->Frame.w);
			if (hi->HasTransparency()) flags |= BlitFlags::BLENDED;
			st.texMode = 1;
			st.texture = tex;
			st.blend = BlendForFlags(flags);
			SetupStencil(st, flags);
			static bool loggedTwin = false;
			if (!loggedTwin) {
				Log(MESSAGE, "GLVideo", "Drawing hi-res twin {}x{} (from {}x{}, scale {}).",
				    hi->Frame.w, hi->Frame.h, spr->Frame.w, spr->Frame.h, int(texelScale));
				loggedTwin = true;
			}
			return true;
		}
	} else if (hi) {
		static bool warnedSize = false;
		if (!warnedSize) {
			Log(WARNING, "GLVideo", "hi-res twin {}x{} is not an integer scale of {}x{}; drawing the original.",
			    hi->Frame.w, hi->Frame.h, spr->Frame.w, spr->Frame.h);
			warnedSize = true;
		}
	}
	if (gspr->IsIndexed()) {
		const Holder<Palette>& palette = spr->GetPalette();
		if (!palette) return false;
		if (flags & (BlitFlags::ONE_MINUS_DST | BlitFlags::DST | BlitFlags::SRC)) {
			// same trick as the SDL driver: index 0 must be black for these blenders
			Color ck = palette->GetColorAt(0);
			if (ck != ColorBlack) {
				Palette tmp(*palette);
				tmp.SetColor(0, ColorBlack);
				// a temporary palette can't be cached by pointer; upload into a fresh row
				if (nextPaletteRow >= PaletteRows) {
					Flush();
					paletteRows.clear();
					nextPaletteRow = 0;
				}
				int row = nextPaletteRow++;
				glBindTexture(GL_TEXTURE_2D, paletteTex);
				glTexSubImage2D(GL_TEXTURE_2D, 0, 0, row, 256, 1, GL_RGBA, GL_UNSIGNED_BYTE, tmp.ColorData());
				pal = float(row);
			} else {
				pal = float(PaletteRow(palette.get()));
			}
		} else {
			pal = float(PaletteRow(palette.get()));
		}
		if (spr->Format().HasColorKey) ckey = float(spr->GetColorKey());
	}

	// pending draws must see the old pixels, so draw them before re-uploading
	if (gspr->NeedsReupload()) Flush();
	bool uploaded = false;
	GLuint tex = gspr->GetTexture(uploaded);
	if (!tex) return false;

	st.texMode = gspr->IsIndexed() ? 2 : 1;
	st.texture = tex;
	st.blend = BlendForFlags(flags);
	SetupStencil(st, flags);
	return true;
}

static Color SpriteVertexColor(BlitFlags flags, const Color& tint)
{
	Color c = ColorWhite;
	if (flags & BlitFlags::COLOR_MOD) {
		c.r = tint.r;
		c.g = tint.g;
		c.b = tint.b;
	}
	if (flags & BlitFlags::ALPHA_MOD) c.a = tint.a;
	if (flags & BlitFlags::HALFTRANS) c.a /= 2;
	return c;
}

void GLVideoDriver::DrawSprite(const Holder<Sprite2D>& spr, const Region& src, const Region& dst, BlitFlags flags, const Color& tint)
{
	if (!spr || src.w <= 0 || src.h <= 0 || dst.w <= 0 || dst.h <= 0) return;

	GLBatchState st = TargetState();
	if (st.scissor.w <= 0 || st.scissor.h <= 0) return;
	if (!XfRegion(dst).IntersectsRegion(st.scissor)) return;

	float pal, ckey, texelScale;
	if (!PrepareSprite(spr, flags, st, pal, ckey, texelScale)) return;

	// Font pages ask for this. Their grey ramp is already the edge; bilinear fattens it.
	if (flags & BlitFlags::NEAREST) st.smooth = false;

	Color c = SpriteVertexColor(flags, tint);
	float grey = 0;
	if (flags & BlitFlags::GREY) {
		grey = 1;
	} else if (flags & BlitFlags::SEPIA) {
		grey = 2;
	}

	// smooth filtering is already on (GLBatchState.smooth). Scaling the UVs keeps the
	// outline width in logical pixels the same when the texture is the hi-res twin.
	float u0 = float(src.x) * texelScale, u1 = float(src.x + src.w) * texelScale;
	float v0 = float(src.y) * texelScale, v1 = float(src.y + src.h) * texelScale;
	if (flags & BlitFlags::MIRRORX) std::swap(u0, u1);
	if (flags & BlitFlags::MIRRORY) std::swap(v0, v1);

	// phase 5 hover outline: the quad grown by the outline width, drawn under the sprite
	if (SceneAppliesToTarget() && scene.objectOutline.a && xf.sx > 0.0f && (st.blend == GLBlend::Alpha || st.blend == GLBlend::None)) {
		const GLVideoBuffer* target = static_cast<const GLVideoBuffer*>(drawingBuffer);
		float texPerUnit = float(src.w) * texelScale / float(dst.w);
		float e = scene.outlineWidth * target->scale / xf.sx; // drawing units
		GLBatchState ost = st;
		ost.blend = GLBlend::Alpha;
		ost.outline = scene.objectOutline;
		ost.outlineRadius = e * texPerUnit;
		ost.depthWrite = false;
		SetBatch(ost);
		float eu = (u1 > u0 ? 1.0f : -1.0f) * e * texPerUnit;
		float ev = (v1 > v0 ? 1.0f : -1.0f) * e * texPerUnit;
		PushQuad(float(dst.x) - e, float(dst.y) - e, float(dst.x + dst.w) + e, float(dst.y + dst.h) + e,
			 u0 - eu, v0 - ev, u1 + eu, v1 + ev, c, pal, 0, ckey);
	}

	SetBatch(st);
	PushQuad(float(dst.x), float(dst.y), float(dst.x + dst.w), float(dst.y + dst.h), u0, v0, u1, v1, c, pal, grey, ckey);
}

bool GLVideoDriver::BlitSpriteQuad(const Holder<Sprite2D>& spr, const Holder<Palette>& palOverride, const float corners[8], const Color colors[4], BlitFlags flags)
{
	if (!spr || !SceneAppliesToTarget()) return false;
	GLBatchState st = TargetState();
	if (st.scissor.w <= 0 || st.scissor.h <= 0) return true;
	st.depthWrite = false;

	Holder<Palette> oldPal;
	Holder<Sprite2D> savedHi;
	if (palOverride) {
		savedHi = spr->hiRes;
		oldPal = spr->GetPalette();
		spr->SetPalette(palOverride);
		spr->hiRes = savedHi;
	}
	float pal, ckey, texelScale;
	bool ok = PrepareSprite(spr, flags, st, pal, ckey, texelScale);
	if (palOverride) {
		spr->SetPalette(oldPal);
		spr->hiRes = std::move(savedHi);
	}
	if (!ok) return true;
	if (st.blend == GLBlend::None) st.blend = GLBlend::Alpha;
	SetBatch(st);

	float u0 = 0, u1 = float(spr->Frame.w) * texelScale, v0 = 0, v1 = float(spr->Frame.h) * texelScale;
	if (flags & BlitFlags::MIRRORX) std::swap(u0, u1);
	if (flags & BlitFlags::MIRRORY) std::swap(v0, v1);
	const float uv[4][2] = { { u0, v0 }, { u1, v0 }, { u0, v1 }, { u1, v1 } };
	GLVertex v[4];
	for (int i = 0; i < 4; ++i) {
		float x = corners[i * 2], y = corners[i * 2 + 1];
		xf.Apply(x, y);
		const Color& c = colors[i];
		v[i] = { x, y, uv[i][0], uv[i][1], c.r, c.g, c.b, c.a, pal, 0, ckey, 0 };
	}
	vertices.insert(vertices.end(), { v[0], v[1], v[2], v[1], v[3], v[2] });
	return true;
}

bool GLVideoDriver::DrawSoftShapes(const std::vector<SoftShape>& shapes, BlitFlags flags)
{
	if (shapes.empty()) return true;
	GLBatchState st = TargetState();
	if (st.scissor.w <= 0 || st.scissor.h <= 0) return true;
	st.depthWrite = false;
	st.texMode = 3;
	st.blend = (flags & BlitFlags::ADD) ? GLBlend::Add : GLBlend::Alpha;
	SetupStencil(st, flags);
	SetBatch(st);
	for (const SoftShape& sh : shapes) {
		float rx = std::max(sh.rx, 0.01f), ry = std::max(sh.ry, 0.01f);
		float hw = 0, gw = 0, ext = 1.0f;
		if (sh.profile == SoftShape::Profile::Ring) {
			// widths in units of the horizontal radius (ellipse space is close enough)
			hw = sh.ringWidth * 0.5f / rx;
			gw = sh.glowWidth / rx;
			ext = 1.0f + hw + gw * 2.0f + 2.0f / rx;
		} else if (sh.profile == SoftShape::Profile::Disc) {
			ext = 1.0f + 2.0f / rx;
		}
		float x0 = sh.x - rx * ext, x1 = sh.x + rx * ext;
		float y0 = sh.y - ry * ext, y1 = sh.y + ry * ext;
		xf.Apply(x0, y0);
		xf.Apply(x1, y1);
		const Color& c = sh.color;
		float p = float(int(sh.profile));
		GLVertex a { x0, y0, -ext, -ext, c.r, c.g, c.b, c.a, p, hw, gw, sh.glowAlpha };
		GLVertex b { x1, y0, ext, -ext, c.r, c.g, c.b, c.a, p, hw, gw, sh.glowAlpha };
		GLVertex d { x0, y1, -ext, ext, c.r, c.g, c.b, c.a, p, hw, gw, sh.glowAlpha };
		GLVertex e { x1, y1, ext, ext, c.r, c.g, c.b, c.a, p, hw, gw, sh.glowAlpha };
		vertices.insert(vertices.end(), { a, b, d, b, e, d });
	}
	return true;
}

void GLVideoDriver::DrawTexture(const GLVideoBuffer* buf, const Region& src, const Region& dst, BlitFlags flags, const Color& tint)
{
	GLBatchState st = TargetState();
	if (st.scissor.w <= 0 || st.scissor.h <= 0) return;
	st.texMode = 1;
	st.texture = buf->texture;
	st.blend = BlendForFlags(flags);
	SetupStencil(st, flags);
	SetBatch(st);
	Color c = ColorWhite;
	if (flags & BlitFlags::COLOR_MOD) {
		c.r = tint.r;
		c.g = tint.g;
		c.b = tint.b;
	}
	if (flags & BlitFlags::ALPHA_MOD) c.a = tint.a;
	if (flags & BlitFlags::HALFTRANS) c.a /= 2;
	float grey = (flags & BlitFlags::GREY) ? 1.0f : (flags & BlitFlags::SEPIA) ? 2.0f :
										     0.0f;
	float k = buf->scale;
	float u0 = src.x * k, u1 = (src.x + src.w) * k;
	float v0 = src.y * k, v1 = (src.y + src.h) * k;
	if (flags & BlitFlags::MIRRORX) std::swap(u0, u1);
	if (flags & BlitFlags::MIRRORY) std::swap(v0, v1);
	PushQuad(float(dst.x), float(dst.y), float(dst.x + dst.w), float(dst.y + dst.h), u0, v0, u1, v1, c, -1, grey, -1);
}

void GLVideoDriver::BlitVideoBuffer(const VideoBufferPtr& buf, const Point& p, BlitFlags flags, Color tint)
{
	const GLVideoBuffer* gb = static_cast<const GLVideoBuffer*>(buf.get());
	const Region& r = buf->Rect();
	DrawTexture(gb, Region(0, 0, r.w, r.h), Region(r.origin + p, r.size), flags, tint);
}

void GLVideoDriver::BlitVideoBufferFully(const VideoBufferPtr& buf, BlitFlags flags, Color tint)
{
	const GLVideoBuffer* gb = static_cast<const GLVideoBuffer*>(buf.get());
	DrawTexture(gb, Region(Point(), buf->Size()), drawingBuffer->Rect(), flags, tint);
}

// ---------------------------------------------------------------- primitives

void GLVideoDriver::DrawRectImp(const Region& rgn, const Color& color, bool fill, BlitFlags flags)
{
	GLBatchState st = TargetState();
	ApplyColorBlend(st, flags);
	SetBatch(st);
	if (fill) {
		PushColorRect(rgn, color);
	} else {
		PushColorRect(Region(rgn.x, rgn.y, rgn.w, 1), color);
		PushColorRect(Region(rgn.x, rgn.y + rgn.h - 1, rgn.w, 1), color);
		PushColorRect(Region(rgn.x, rgn.y + 1, 1, rgn.h - 2), color);
		PushColorRect(Region(rgn.x + rgn.w - 1, rgn.y + 1, 1, rgn.h - 2), color);
	}
}

void GLVideoDriver::DrawPointImp(const BasePoint& p, const Color& color, BlitFlags flags)
{
	GLBatchState st = TargetState();
	ApplyColorBlend(st, flags);
	SetBatch(st);
	PushColorRect(Region(p.x, p.y, 1, 1), color);
}

void GLVideoDriver::DrawPointsImp(const std::vector<BasePoint>& points, const Color& color, BlitFlags flags)
{
	if (points.empty()) return;
	GLBatchState st = TargetState();
	ApplyColorBlend(st, flags);
	SetBatch(st);
	for (const auto& p : points) {
		PushColorRect(Region(p.x, p.y, 1, 1), color);
	}
}

void GLVideoDriver::DrawCircleImp(const Point& origin, uint16_t r, const Color& color, BlitFlags flags)
{
	DrawPointsImp(PlotCircle(origin, r, 0xff), color, flags);
}

void GLVideoDriver::DrawEllipseImp(const Region& rect, const Color& color, BlitFlags flags)
{
	DrawPointsImp(PlotEllipse(rect), color, flags);
}

void GLVideoDriver::DrawLineImp(const BasePoint& start, const BasePoint& end, const Color& color, BlitFlags flags)
{
	GLBatchState st = TargetState();
	ApplyColorBlend(st, flags);
	SetBatch(st);
	PushLine(start, end, color);
}

void GLVideoDriver::DrawLinesImp(const std::vector<Point>& points, const Color& color, BlitFlags flags)
{
	if (points.size() < 2) return;
	GLBatchState st = TargetState();
	ApplyColorBlend(st, flags);
	SetBatch(st);
	for (size_t i = 1; i < points.size(); ++i) {
		PushLine(points[i - 1], points[i], color);
	}
}

void GLVideoDriver::DrawPolygonImp(const Gem_Polygon* poly, const Point& origin, const Color& color, bool fill, BlitFlags flags)
{
	if (fill) {
		GLBatchState st = TargetState();
		ApplyColorBlend(st, flags);
		SetBatch(st);
		for (const auto& lineSegments : poly->rasterData) {
			for (const auto& segment : lineSegments) {
				Point p1(segment.first + origin);
				Point p2(segment.second + origin);
				PushLine(p1, p2, color);
			}
		}
	} else {
		std::vector<Point> points(poly->Count() + 1);
		size_t i = 0;
		for (; i < poly->Count(); ++i) {
			points[i] = poly->vertices[i] - poly->BBox.origin + origin;
		}
		points[i] = points[0];
		DrawLinesImp(points, color, flags);
	}
}

void GLVideoDriver::DrawRawGeometry(const std::vector<float>& verts, const std::vector<Color>& colors, BlitFlags blitFlags)
{
	if (verts.size() < 6) return;
	GLBatchState st = TargetState();
	st.blend = (blitFlags & BlitFlags::BLENDED) ? GLBlend::Alpha : GLBlend::None;
	SetBatch(st);
	size_t n = verts.size() / 2;
	for (size_t i = 0; i < n; ++i) {
		const Color& c = colors[i];
		float x = verts[i * 2], y = verts[i * 2 + 1];
		xf.Apply(x, y);
		vertices.push_back({ x, y, 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 });
	}
}

void GLVideoDriver::ClearBuffer(GLVideoBuffer* buf, const Region& rgn)
{
	GLBatchState st;
	st.fbo = buf->fbo;
	st.targetSize = buf->physSize;
	st.scissor = Region(Point(), buf->physSize);
	st.blend = GLBlend::None;
	SetBatch(st);
	xf = GLXform();
	xf.sx = xf.sy = buf->scale;
	PushColorRect(rgn, Color(0, 0, 0, 0));
}

// ---------------------------------------------------------------- presentation

void GLVideoDriver::CompositeBuffer(const GLVideoBuffer* buf)
{
	GLBatchState st;
	st.fbo = screenFbo;
	st.targetSize = screenPhys;
	st.scissor = Region(Point(), screenPhys);
	st.texMode = 1;
	st.texture = buf->texture;
	st.blend = GLBlend::Alpha;
	// same physical scale on both sides: plain copy, unless the buffer didn't follow the render scale
	st.smooth = buf->scale != renderScale;
	SetBatch(st);
	xf = GLXform();
	xf.sx = xf.sy = renderScale;
	const Region& r = buf->Rect();
	PushQuad(float(r.x), float(r.y), float(r.x + r.w), float(r.y + r.h), 0, 0, float(buf->physSize.w), float(buf->physSize.h), ColorWhite);
}

void GLVideoDriver::UpdatePresentRect()
{
	int w = 0, h = 0;
	SDL_GL_GetDrawableSize(window, &w, &h);
	windowPixels = Size(w, h);
	// keep aspect, letterbox the rest
	float scale = std::min(float(w) / screenSize.w, float(h) / screenSize.h);
	int pw = int(std::lround(screenSize.w * scale));
	int ph = int(std::lround(screenSize.h * scale));
	presentRect = Region((w - pw) / 2, (h - ph) / 2, pw, ph);

	// render everything at the presented size, so zoomed and scaled art is
	// filtered once, at the final resolution (never below the logical size)
	float newScale = highRes ? Clamp(scale, 1.0f, 4.0f) : 1.0f;
	if (newScale == renderScale) return;
	renderScale = newScale;
	Size phys = PhysSize(screenSize, renderScale);
	if (phys != screenPhys) {
		screenPhys = phys;
		if (screenTex) ResizeScreenTarget();
	}
	for (VideoBuffer* vb : buffers) {
		auto* gb = static_cast<GLVideoBuffer*>(vb);
		if (gb->FollowsRenderScale()) gb->Rescale(renderScale);
	}
	Log(MESSAGE, "GLVideo", "Render scale {:.3f} ({}x{})", renderScale, screenPhys.w, screenPhys.h);
}

Point GLVideoDriver::WindowToScreen(float x, float y) const
{
	// mouse events come in window points; convert to drawable pixels, then to the logical screen
	int ww = 1, wh = 1;
	SDL_GetWindowSize(window, &ww, &wh);
	float px = x * windowPixels.w / float(std::max(ww, 1));
	float py = y * windowPixels.h / float(std::max(wh, 1));
	float sx = (px - presentRect.x) * screenSize.w / float(std::max(presentRect.w, 1));
	float sy = (py - presentRect.y) * screenSize.h / float(std::max(presentRect.h, 1));
	return Point(int(std::floor(sx)), int(std::floor(sy)));
}

void GLVideoDriver::SwapBuffers(VideoBuffers& bufs)
{
	Flush();
	UpdatePresentRect();

	glBindFramebuffer(GL_FRAMEBUFFER, screenFbo);
	glDisable(GL_SCISSOR_TEST);
	glClearColor(0, 0, 0, 1);
	glClear(GL_COLOR_BUFFER_BIT);
	for (auto* buf : bufs) {
		buf->RenderOnDisplay(nullptr);
	}

	// present: logical screen -> window, scaled with the sharp filter
	GLBatchState st;
	st.fbo = 0;
	st.targetSize = windowPixels;
	st.texMode = 1;
	st.texture = screenTex;
	st.blend = GLBlend::None;
	st.flipY = true;
	st.smooth = screenPhys != presentRect.size;
	st.brightness = brightness;
	st.contrast = contrast;
	SetBatch(st);
	xf = GLXform();
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glDisable(GL_SCISSOR_TEST);
	glClearColor(0, 0, 0, 1);
	glClear(GL_COLOR_BUFFER_BIT);
	const Region& p = presentRect;
	PushQuad(float(p.x), float(p.y), float(p.x + p.w), float(p.y + p.h), 0, 0, float(screenPhys.w), float(screenPhys.h), ColorWhite);
	Flush();
	batchValid = false;

	DevScreenshot();
	SDL_GL_SwapWindow(window);

	// palette rows are per frame
	paletteRows.clear();
	nextPaletteRow = 0;
}

// dev hook: GEMRB_GL_SHOT="file.bmp;seconds" writes the presented frame once, focus-independent
// ---------------------------------------------------------------- scene lighting

void GLVideoDriver::DrawLightVertices(const std::vector<GLVertex>& verts)
{
	if (verts.empty()) return;
	glBindVertexArray(vao);
	glBindBuffer(GL_ARRAY_BUFFER, vbo);
	glBufferData(GL_ARRAY_BUFFER, verts.size() * sizeof(GLVertex), verts.data(), GL_STREAM_DRAW);
	glDrawArrays(GL_TRIANGLES, 0, GLsizei(verts.size()));
}

static void PushLightQuad(std::vector<GLVertex>& v, float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, float r, float g, float b)
{
	GLVertex a { x0, y0, u0, v0, 255, 255, 255, 255, r, g, b, 0 };
	GLVertex c { x1, y0, u1, v0, 255, 255, 255, 255, r, g, b, 0 };
	GLVertex d { x0, y1, u0, v1, 255, 255, 255, 255, r, g, b, 0 };
	GLVertex e { x1, y1, u1, v1, 255, 255, 255, 255, r, g, b, 0 };
	v.insert(v.end(), { a, c, d, c, e, d });
}

static void EnsureTarget(GLuint& tex, GLuint& fbo, Size& have, const Size& want, GLint internalFormat, GLenum type, bool linear)
{
	if (tex && have == want) return;
	if (fbo) glDeleteFramebuffers(1, &fbo);
	if (tex) glDeleteTextures(1, &tex);
	glGenTextures(1, &tex);
	glBindTexture(GL_TEXTURE_2D, tex);
	glTexImage2D(GL_TEXTURE_2D, 0, internalFormat, want.w, want.h, 0, GL_RGBA, type, nullptr);
	GLint filter = linear ? GL_LINEAR : GL_NEAREST;
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filter);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filter);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
	have = want;
}

// The scene drawn so far is copied out, then drawn back multiplied by a light
// buffer: cleared to the ambient colour, every light added as a soft ellipse.
// The light buffer is half the physical resolution; it is smooth anyway.
bool GLVideoDriver::LightingWanted() const
{
	return lightProgram && core->GetDictionary().Get("Lighting", 1) && core->GetDictionary().Get("LightGeometry", 1);
}

// the scene buffer gets a second colour attachment for the sprites' depth while the scene is drawn
void GLVideoDriver::SceneBegan()
{
	if (!SupportsSceneTransform() || !LightingWanted() || !scene.buffer) return;
	const GLVideoBuffer* target = static_cast<const GLVideoBuffer*>(scene.buffer);
	Flush();
	batchValid = false;
	EnsureTarget(depthTex, depthFbo, depthSize, target->physSize, GL_RGBA16F, GL_HALF_FLOAT, false);
	glBindFramebuffer(GL_FRAMEBUFFER, target->fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, depthTex, 0);
	const GLenum bufs[2] = { GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1 };
	glDrawBuffers(2, bufs);
	const float zero4[4] = { 0, 0, 0, 0 };
	glDisable(GL_SCISSOR_TEST);
	glClearBufferfv(GL_COLOR, 1, zero4);
	glColorMaski(1, GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
	depthAttachedFbo = target->fbo;
}

void GLVideoDriver::SceneEnding()
{
	if (!depthAttachedFbo) return;
	Flush();
	batchValid = false;
	glBindFramebuffer(GL_FRAMEBUFFER, depthAttachedFbo);
	glColorMaski(1, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, 0, 0);
	const GLenum buf = GL_COLOR_ATTACHMENT0;
	glDrawBuffers(1, &buf);
	depthAttachedFbo = 0;
}

// The scene drawn so far is copied out, then drawn back multiplied by a light
// buffer: cleared to the ambient colour, every light added on top. With
// geometry the lights are evaluated per pixel in 3D from the generated depth
// and normal maps (full resolution); without, as flat ellipses at half resolution.
void GLVideoDriver::DrawSceneLighting(const SceneLighting& lighting)
{
	if (!lightProgram || !SceneAppliesToTarget()) return;
	Flush();
	batchValid = false;

	GLBatchState st = TargetState(); // also sets baseXf: map units -> physical target px
	const Region R = st.scissor.Intersect(Region(Point(), st.targetSize));
	if (R.w <= 0 || R.h <= 0) return;
	const GLVideoBuffer* target = static_cast<const GLVideoBuffer*>(drawingBuffer);
	const bool geom = lighting.geometry && depthAttachedFbo == target->fbo;

	Size lsz = geom ? R.size : Size(std::max(1, (R.w + 1) / 2), std::max(1, (R.h + 1) / 2));
	EnsureTarget(lightTex, lightFbo, lightSize, lsz, GL_RGBA16F, GL_HALF_FLOAT, true);
	EnsureTarget(copyTex, copyFbo, copySize, R.size, GL_RGBA8, GL_UNSIGNED_BYTE, false);

	// sprites are done; stop writing their depth
	if (depthAttachedFbo) {
		glBindFramebuffer(GL_FRAMEBUFFER, depthAttachedFbo);
		glColorMaski(1, GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
	}
	glDisable(GL_SCISSOR_TEST);
	glDisable(GL_BLEND);

	// 1. copy of the scene region (also the normal map's source).
	// Hi-res twins are display-only: this pass samples the framebuffer copy and coverage
	// depth, not the source sprite or tile textures.
	glBindFramebuffer(GL_READ_FRAMEBUFFER, target->fbo);
	glReadBuffer(GL_COLOR_ATTACHMENT0);
	glBindFramebuffer(GL_DRAW_FRAMEBUFFER, copyFbo);
	glBlitFramebuffer(R.x, R.y, R.x + R.w, R.y + R.h, 0, 0, R.w, R.h, GL_COLOR_BUFFER_BIT, GL_NEAREST);

	glUseProgram(lightProgram);
	glUniform1i(luni.flipY, 0);
	static const bool debug = getenv("GEMRB_LIGHT_DEBUG") != nullptr;
	glUniform1i(luni.debug, debug ? 1 : 0);
	const float S = baseXf.sx;

	// 2. wall depth map: polygon rows carrying their ground line, nearest wins
	if (geom) {
		EnsureTarget(wallTex, wallFbo, wallSize, R.size, GL_RGBA16F, GL_HALF_FLOAT, false);
		glBindFramebuffer(GL_FRAMEBUFFER, wallFbo);
		glViewport(0, 0, R.w, R.h);
		glClearColor(0, 0, 0, 0);
		glClear(GL_COLOR_BUFFER_BIT);
		if (!lighting.wallSpans.empty()) {
			glUniform1i(luni.mode, 2);
			glUniform2f(luni.targetSize, float(R.w), float(R.h));
			glEnable(GL_BLEND);
			glBlendEquation(GL_MAX);
			glBlendFunc(GL_ONE, GL_ONE);
			std::vector<GLVertex> verts;
			verts.reserve(lighting.wallSpans.size() * 6);
			for (const SceneSpan& sp : lighting.wallSpans) {
				float x0 = sp.x0, y0 = sp.y, x1 = sp.x1, y1 = sp.y + 1.0f;
				baseXf.Apply(x0, y0);
				baseXf.Apply(x1, y1);
				x0 -= float(R.x);
				x1 -= float(R.x);
				y0 -= float(R.y);
				y1 -= float(R.y);
				if (x1 < 0 || y1 < 0 || x0 > float(R.w) || y0 > float(R.h)) continue;
				GLVertex a { x0, y0, sp.base0, 0, 255, 255, 255, 255, 0, 0, 0, 0 };
				GLVertex b { x1, y0, sp.base1, 0, 255, 255, 255, 255, 0, 0, 0, 0 };
				GLVertex c { x0, y1, sp.base0, 0, 255, 255, 255, 255, 0, 0, 0, 0 };
				GLVertex d { x1, y1, sp.base1, 0, 255, 255, 255, 255, 0, 0, 0, 0 };
				verts.insert(verts.end(), { a, b, c, b, d, c });
			}
			DrawLightVertices(verts);
			glBlendEquation(GL_FUNC_ADD);
			glDisable(GL_BLEND);
		}
	}

	// 3. light buffer
	glBindFramebuffer(GL_FRAMEBUFFER, lightFbo);
	glViewport(0, 0, lsz.w, lsz.h);
	if (debug) {
		glClearColor(0, 0, 0, 1);
	} else {
		glClearColor(lighting.ambient[0], lighting.ambient[1], lighting.ambient[2], 1.0f);
	}
	glClear(GL_COLOR_BUFFER_BIT);
	glClearColor(0, 0, 0, 0);
	if (!lighting.lights.empty()) {
		glUniform1i(luni.mode, 0);
		glUniform1i(luni.geom, geom ? 1 : 0);
		glUniform2f(luni.targetSize, float(lsz.w), float(lsz.h));
		const float toPhys = float(R.w) / float(lsz.w);
		glUniform1f(luni.lightToPhys, toPhys);
		glUniform2f(luni.regionOrigin, float(R.x), float(R.y));
		glUniform3f(luni.map, S, baseXf.tx, baseXf.ty);
		glUniform1f(luni.bump, lighting.bump);
		glUniform1f(luni.normalStrength, lighting.normalStrength);
		glActiveTexture(GL_TEXTURE0);
		glBindTexture(GL_TEXTURE_2D, copyTex);
		glActiveTexture(GL_TEXTURE2);
		glBindTexture(GL_TEXTURE_2D, geom ? depthTex : zeroTex);
		glActiveTexture(GL_TEXTURE3);
		glBindTexture(GL_TEXTURE_2D, geom ? wallTex : zeroTex);
		glActiveTexture(GL_TEXTURE0);
		glEnable(GL_BLEND);
		glBlendEquation(GL_FUNC_ADD);
		glBlendFunc(GL_ONE, GL_ONE);
		std::vector<GLVertex> quad;
		for (const SceneLight& l : lighting.lights) {
			// screen footprint: the ground ellipse, plus up to one radius above it (walls, sprites)
			float gx0 = l.x - l.radius, gx1 = l.x + l.radius;
			float gy0 = l.y - l.radius * 0.72f - (geom ? l.radius : l.z), gy1 = l.y + l.radius * 0.72f;
			baseXf.Apply(gx0, gy0);
			baseXf.Apply(gx1, gy1);
			float x0 = (gx0 - float(R.x)) / toPhys, x1 = (gx1 - float(R.x)) / toPhys;
			float y0 = (gy0 - float(R.y)) / toPhys, y1 = (gy1 - float(R.y)) / toPhys;
			if (x1 < 0 || y1 < 0 || x0 > float(lsz.w) || y0 > float(lsz.h)) continue;
			glUniform4f(luni.lightPos, l.x, l.y, l.z, l.radius);
			glUniform3f(luni.lightColor, l.r, l.g, l.b);
			quad.clear();
			PushLightQuad(quad, x0, y0, x1, y1, 0, 0, 0, 0, 0, 0, 0);
			DrawLightVertices(quad);
		}
	}

	// 4. composite back, lit (the depth map is attached to this FBO: don't keep it bound)
	glActiveTexture(GL_TEXTURE2);
	glBindTexture(GL_TEXTURE_2D, 0);
	glDisable(GL_BLEND);
	glBindFramebuffer(GL_FRAMEBUFFER, target->fbo);
	glViewport(0, 0, target->physSize.w, target->physSize.h);
	glUniform1i(luni.mode, 1);
	glUniform2f(luni.targetSize, float(target->physSize.w), float(target->physSize.h));
	glUniform2f(luni.sceneSize, float(R.w), float(R.h));
	glUniform1f(luni.keep, lighting.highlightKeep);
	glUniform1f(luni.maxLight, lighting.maxLight);
	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, lightTex);
	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, copyTex);
	std::vector<GLVertex> quad;
	PushLightQuad(quad, float(R.x), float(R.y), float(R.x + R.w), float(R.y + R.h), 0, 0, float(R.w), float(R.h), 0, 0, 0);
	DrawLightVertices(quad);

	glUseProgram(program);
	batchValid = false;
}

void GLVideoDriver::DevScreenshot()
{
	static const char* spec = getenv("GEMRB_GL_SHOT");
	static bool done = false;
	static uint32_t start = GetMilliseconds();
	static unsigned frame = 0;
	std::string path;
	// on demand (tools\dev.ps1 shot): dev\shot.req holds the target .bmp path, checked every 10 frames
	if (++frame % 10 == 0) {
		if (FILE* req = fopen("dev\\shot.req", "rb")) {
			char buf[1024] = {};
			size_t n = fread(buf, 1, sizeof(buf) - 1, req);
			fclose(req);
			remove("dev\\shot.req");
			while (n && (buf[n - 1] == '\n' || buf[n - 1] == '\r' || buf[n - 1] == ' ')) buf[--n] = 0;
			path = buf;
		}
	}
	if (path.empty()) {
		if (!spec || done) return;
		std::string str(spec);
		size_t sep = str.rfind(';');
		float secs = sep == std::string::npos ? 30.0f : float(atof(str.c_str() + sep + 1));
		if (GetMilliseconds() - start < uint32_t(secs * 1000)) return;
		done = true;
		path = str.substr(0, sep);
	}
	int w = windowPixels.w, h = windowPixels.h;
	std::vector<uint8_t> px(size_t(w) * h * 4);
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glReadBuffer(GL_BACK);
	glPixelStorei(GL_PACK_ALIGNMENT, 4);
	glReadPixels(0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, px.data()); // bottom-up, exactly what BMP wants
	std::string tmpPath = path + ".tmp";
	FILE* f = fopen(tmpPath.c_str(), "wb");
	if (!f) return;
	uint32_t dataSize = uint32_t(px.size());
	uint8_t hdr[54] = { 'B', 'M' };
	auto put32 = [&hdr](int off, uint32_t v) { memcpy(hdr + off, &v, 4); };
	put32(2, 54 + dataSize);
	put32(10, 54);
	put32(14, 40);
	put32(18, uint32_t(w));
	put32(22, uint32_t(h));
	hdr[26] = 1;
	hdr[28] = 32;
	put32(34, dataSize);
	fwrite(hdr, 1, 54, f);
	fwrite(px.data(), 1, px.size(), f);
	fclose(f);
	remove(path.c_str());
	rename(tmpPath.c_str(), path.c_str());
	Log(MESSAGE, "GLVideo", "Wrote dev screenshot {}", path);
}

Holder<Sprite2D> GLVideoDriver::GetScreenshot(Region r, const VideoBufferPtr& buf)
{
	Flush();
	GLuint fbo = screenFbo;
	GLuint tex = screenTex;
	Size srcSize = screenSize;
	float scale = renderScale;
	if (buf) {
		const GLVideoBuffer* gb = static_cast<const GLVideoBuffer*>(buf.get());
		fbo = gb->fbo;
		tex = gb->texture;
		srcSize = buf->Size();
		scale = gb->scale;
	}
	if (r.w <= 0 || r.h <= 0) {
		r = Region(Point(), srcSize);
	}
	r = r.Intersect(Region(Point(), srcSize));
	if (r.w <= 0 || r.h <= 0) return nullptr;
	std::vector<uint32_t> px(size_t(r.w) * r.h);
	glPixelStorei(GL_PACK_ALIGNMENT, 4);
	if (scale == 1.0f) {
		glBindFramebuffer(GL_FRAMEBUFFER, fbo);
		glReadPixels(r.x, r.y, r.w, r.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
	} else {
		// screenshots are in logical pixels: resample the physical region first
		GLuint tmpTex = 0, tmpFbo = 0;
		CreateTarget(r.size, tmpTex, tmpFbo);
		Region src(int(std::lround(r.x * scale)), int(std::lround(r.y * scale)), int(std::lround(r.w * scale)), int(std::lround(r.h * scale)));
		CopyTexture(tmpFbo, r.size, Region(Point(), r.size), tex, src, true);
		glBindFramebuffer(GL_FRAMEBUFFER, tmpFbo);
		glReadPixels(0, 0, r.w, r.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
		glDeleteFramebuffers(1, &tmpFbo);
		glDeleteTextures(1, &tmpTex);
	}
	void* pixels = malloc(px.size() * 4);
	for (auto& p : px) p |= 0xff000000; // screenshots are opaque
	memcpy(pixels, px.data(), px.size() * 4);
	static const PixelFormat fmt(4, 0x000000ff, 0x0000ff00, 0x00ff0000, 0);
	return MakeHolder<GLSprite2D>(Region(0, 0, r.w, r.h), pixels, fmt);
}

void GLVideoDriver::SetGamma(int newBrightness, int newContrast)
{
	// same steps as the SDL2 GL backend
	brightness = float(newBrightness) * 0.0015f;
	contrast = 1.0f + float(newContrast) * 0.05f;
}

bool GLVideoDriver::SetFullscreenMode(bool set)
{
	if (SDL_SetWindowFullscreen(window, set ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0) == 0) {
		fullscreen = set;
		UpdatePresentRect();
		return true;
	}
	return false;
}

bool GLVideoDriver::ToggleGrabInput()
{
	bool isGrabbed = SDL_GetWindowGrab(window);
	SDL_SetWindowGrab(window, SDL_bool(!isGrabbed));
	return isGrabbed != bool(SDL_GetWindowGrab(window));
}

void GLVideoDriver::CaptureMouse(bool enabled)
{
	SDL_CaptureMouse(SDL_bool(enabled));
}

void GLVideoDriver::StartTextInput()
{
	if (!dPadSoftKeyboard.IsInputActive()) dPadSoftKeyboard.StartInput();
	SDL_StartTextInput();
}

void GLVideoDriver::StopTextInput()
{
	dPadSoftKeyboard.StopInput();
	SDL_StopTextInput();
}

bool GLVideoDriver::InTextInput()
{
	return SDL_IsTextInputActive();
}

bool GLVideoDriver::TouchInputEnabled()
{
	return SDL_GetNumTouchDevices() > 0;
}

void GLVideoDriver::ConfigurePointer(int pointerSpeed, int pointerAccel, int deadZoneL, int deadZoneR)
{
	gamepadControl.ConfigurePointer(pointerSpeed, pointerAccel, deadZoneL, deadZoneR);
}

// ---------------------------------------------------------------- events
// adapted from the SDL2 driver; the only real difference is that mouse
// positions are mapped from window pixels to the logical screen here

static SDL_Keycode TranslateKeycode(SDL_Keycode sym)
{
	switch (sym) {
		case SDLK_ESCAPE:
			return GEM_ESCAPE;
		case SDLK_END:
		case SDLK_KP_1:
			return GEM_END;
		case SDLK_HOME:
		case SDLK_KP_7:
			return GEM_HOME;
		case SDLK_UP:
		case SDLK_KP_8:
			return GEM_UP;
		case SDLK_DOWN:
		case SDLK_KP_2:
			return GEM_DOWN;
		case SDLK_LEFT:
		case SDLK_KP_4:
			return GEM_LEFT;
		case SDLK_RIGHT:
		case SDLK_KP_6:
			return GEM_RIGHT;
		case SDLK_DELETE:
			return GEM_DELETE;
		case SDLK_BACKSPACE:
			return GEM_BACKSP;
		case SDLK_RETURN:
		case SDLK_KP_ENTER:
			return GEM_RETURN;
		case SDLK_LALT:
		case SDLK_RALT:
			return GEM_ALT;
		case SDLK_TAB:
			return GEM_TAB;
		case SDLK_PAGEUP:
		case SDLK_KP_9:
			return GEM_PGUP;
		case SDLK_PAGEDOWN:
		case SDLK_KP_3:
			return GEM_PGDOWN;
		case SDLK_SCROLLLOCK:
			return GEM_GRAB;
		case SDLK_F1:
		case SDLK_F2:
		case SDLK_F3:
		case SDLK_F4:
		case SDLK_F5:
		case SDLK_F6:
		case SDLK_F7:
		case SDLK_F8:
		case SDLK_F9:
		case SDLK_F10:
		case SDLK_F11:
		case SDLK_F12:
			return GEM_FUNCTIONX(1) + sym - SDLK_F1;
		default:
			break;
	}
	return sym;
}

static bool BlocksEvents(const SDL_Event& event, int modState)
{
	if (event.type == SDL_MOUSEMOTION || event.type == SDL_QUIT || modState != 0) return false;
	if (core->GetDictionary().Get("AskAndExit", 2) == 1) return false;
	if (!core->InCutSceneMode(false)) return false;
	if (core->IsConsoleWindowOpen() || core->PlayingMovie()) return false;
	if (core->IsFreezed()) return false;
	return true;
}

int GLVideoDriver::PollEvents()
{
	int ret = GEM_OK;
	SDL_Event ev;
	if (SDL_NumJoysticks() > 0) ProcessAxisMotion();
	while (ret != GEM_ERROR && SDL_PollEvent(&ev)) {
		ret = ProcessEvent(ev);
	}
	return ret;
}

bool GLVideoDriver::ProcessControllerEvent(const SDL_Event& event)
{
	switch (event.type) {
		case SDL_CONTROLLERDEVICEREMOVED:
			if (gameController && SDL_GameControllerFromInstanceID(event.jdevice.which) == gameController) {
				SDL_GameControllerClose(gameController);
				gameController = nullptr;
			}
			return true;
		case SDL_CONTROLLERDEVICEADDED:
			if (!gameController) gameController = SDL_GameControllerOpen(event.jdevice.which);
			return true;
		case SDL_CONTROLLERAXISMOTION:
			gamepadControl.HandleAxisEvent(event.caxis.axis, event.caxis.value);
			return true;
		case SDL_CONTROLLERBUTTONDOWN:
		case SDL_CONTROLLERBUTTONUP:
			{
				bool handled = false;
				if (InTextInput() && event.type == SDL_CONTROLLERBUTTONDOWN) {
					handled = true;
					Event bsp = EventMgr::CreateKeyEvent(GEM_BACKSP, true);
					switch (event.cbutton.button) {
						case SDL_CONTROLLER_BUTTON_DPAD_LEFT:
							dPadSoftKeyboard.RemoveCharacter();
							EvntManager->DispatchEvent(std::move(bsp));
							break;
						case SDL_CONTROLLER_BUTTON_DPAD_RIGHT:
							dPadSoftKeyboard.AddCharacter();
							EvntManager->DispatchEvent(dPadSoftKeyboard.GetTextEvent());
							break;
						case SDL_CONTROLLER_BUTTON_DPAD_DOWN:
							dPadSoftKeyboard.NextCharacter();
							EvntManager->DispatchEvent(std::move(bsp));
							EvntManager->DispatchEvent(dPadSoftKeyboard.GetTextEvent());
							break;
						case SDL_CONTROLLER_BUTTON_DPAD_UP:
							dPadSoftKeyboard.PreviousCharacter();
							EvntManager->DispatchEvent(std::move(bsp));
							EvntManager->DispatchEvent(dPadSoftKeyboard.GetTextEvent());
							break;
						case SDL_CONTROLLER_BUTTON_LEFTSHOULDER:
						case SDL_CONTROLLER_BUTTON_RIGHTSHOULDER:
							dPadSoftKeyboard.ToggleUppercase();
							EvntManager->DispatchEvent(std::move(bsp));
							EvntManager->DispatchEvent(dPadSoftKeyboard.GetTextEvent());
							break;
						default:
							handled = false;
							break;
					}
				}
				if (!handled) {
					Event e = EventMgr::CreateControllerButtonEvent(EventButton(event.cbutton.button), event.type == SDL_CONTROLLERBUTTONDOWN);
					EvntManager->DispatchEvent(std::move(e));
				}
			}
			return true;
		default:
			return false;
	}
}

void GLVideoDriver::ProcessAxisMotion()
{
	uint32_t now = GetMilliseconds();
	uint32_t dt = now - gamepadControl.lastAxisMovementTime;
	gamepadControl.lastAxisMovementTime = now;
	const int16_t xs = (gamepadControl.xAxisLValue > gamepadControl.deadZoneL) - (gamepadControl.xAxisLValue < gamepadControl.deadZoneL);
	const int16_t ys = (gamepadControl.yAxisLValue > gamepadControl.deadZoneL) - (gamepadControl.yAxisLValue < gamepadControl.deadZoneL);
	if (xs || ys) {
		float sec = dt / 1000.f;
		gamepadControl.xAxisFloatPos += std::pow(std::abs(gamepadControl.xAxisLValue), gamepadControl.joyPointerAccel) * xs * sec * gamepadControl.GetPointerSpeed();
		gamepadControl.yAxisFloatPos += std::pow(std::abs(gamepadControl.yAxisLValue), gamepadControl.joyPointerAccel) * ys * sec * gamepadControl.GetPointerSpeed();
		gamepadControl.xAxisFloatPos = Clamp(gamepadControl.xAxisFloatPos, 0.0F, float(screenSize.w));
		gamepadControl.yAxisFloatPos = Clamp(gamepadControl.yAxisFloatPos, 0.0F, float(screenSize.h));
		EvntManager->DispatchEvent(EventMgr::CreateMouseMotionEvent(Point(int(gamepadControl.xAxisFloatPos), int(gamepadControl.yAxisFloatPos))));
	}
	struct Dir {
		bool want;
		bool& pressed;
		KeyboardKey key;
	} dirs[4] = {
		{ gamepadControl.xAxisRValue > 0, gamepadControl.gamepadScrollRightKeyPressed, GEM_RIGHT },
		{ gamepadControl.xAxisRValue < 0, gamepadControl.gamepadScrollLeftKeyPressed, GEM_LEFT },
		{ gamepadControl.yAxisRValue > 0, gamepadControl.gamepadScrollDownKeyPressed, GEM_DOWN },
		{ gamepadControl.yAxisRValue < 0, gamepadControl.gamepadScrollUpKeyPressed, GEM_UP },
	};
	for (auto& d : dirs) {
		if (d.pressed != d.want) {
			d.pressed = d.want;
			EvntManager->DispatchEvent(EventMgr::CreateKeyEvent(d.key, d.want, 0));
		}
	}
}

int GLVideoDriver::ProcessEvent(const SDL_Event& event)
{
	if (!EvntManager) return GEM_ERROR;

	int modstate = GetModState(SDL_GetModState());
	if (BlocksEvents(event, modstate)) return GEM_OK;
	if (core->config.GamepadSupport && ProcessControllerEvent(event)) return GEM_OK;

	Event e;
	switch (event.type) {
		case SDL_QUIT:
			core->AskAndExit();
			break;
		case SDL_KEYUP:
			{
				SDL_Keycode key = TranslateKeycode(event.key.keysym.sym);
				if (key != 0) {
					EvntManager->DispatchEvent(EventMgr::CreateKeyEvent(KeyboardKey(key), false, modstate));
				}
			}
			break;
		case SDL_KEYDOWN:
			{
				SDL_Keycode sym = event.key.keysym.sym;
				if ((SDL_GetModState() & KMOD_CTRL) && sym == SDLK_v && SDL_HasClipboardText()) {
					char* text = SDL_GetClipboardText();
					e = EventMgr::CreateTextEvent(text);
					SDL_free(text);
					EvntManager->DispatchEvent(std::move(e));
					break;
				}
				if (SDL_GetModState() & KMOD_NUM) {
					switch (sym) {
						case SDLK_KP_1:
							sym = SDLK_1;
							break;
						case SDLK_KP_2:
							sym = SDLK_2;
							break;
						case SDLK_KP_3:
							sym = SDLK_3;
							break;
						case SDLK_KP_4:
							sym = SDLK_4;
							break;
						case SDLK_KP_6:
							sym = SDLK_6;
							break;
						case SDLK_KP_7:
							sym = SDLK_7;
							break;
						case SDLK_KP_8:
							sym = SDLK_8;
							break;
						case SDLK_KP_9:
							sym = SDLK_9;
							break;
						default:
							break;
					}
				}
				SDL_Keycode key = TranslateKeycode(sym);
				e = EventMgr::CreateKeyEvent(KeyboardKey(key), true, modstate);
				if (e.keyboard.character) {
					if (InTextInput() && modstate == 0) break;
					e.keyboard.character = SDL_GetKeyFromScancode(event.key.keysym.scancode);
				}
				EvntManager->DispatchEvent(std::move(e));
			}
			break;
		case SDL_MOUSEMOTION:
			if (event.motion.which == SDL_TOUCH_MOUSEID) break;
			{
				Point p = WindowToScreen(float(event.motion.x), float(event.motion.y));
				if (SDL_NumJoysticks() > 0) gamepadControl.SetGamepadPosition(p.x, p.y);
				EvntManager->DispatchEvent(EventMgr::CreateMouseMotionEvent(p, modstate));
			}
			break;
		case SDL_MOUSEBUTTONDOWN:
		case SDL_MOUSEBUTTONUP:
			if (event.button.which == SDL_TOUCH_MOUSEID) break;
			if (event.button.button == SDL_BUTTON_MIDDLE && event.type == SDL_MOUSEBUTTONDOWN && SDL_HasClipboardText()) {
				char* paste = SDL_GetClipboardText();
				if (paste) {
					EvntManager->DispatchEvent(EventMgr::CreateTextEvent(paste));
					SDL_free(paste);
				}
			}
			{
				EventButton btn = SDL_BUTTON(event.button.button);
				if (btn) {
					Point p = WindowToScreen(float(event.button.x), float(event.button.y));
					EvntManager->DispatchEvent(EventMgr::CreateMouseBtnEvent(p, btn, event.type == SDL_MOUSEBUTTONDOWN, modstate));
				}
			}
			break;
		case SDL_MOUSEWHEEL:
			{
				if (event.wheel.which == SDL_TOUCH_MOUSEID) break;
				static bool unitIsPixels = false;
				if (event.wheel.y > 1 || event.wheel.x > 1) unitIsPixels = true;
				int speed = unitIsPixels ? 1 : core->GetMouseScrollSpeed();
				if (SDL_GetModState() & KMOD_SHIFT) {
					e = EventMgr::CreateMouseWheelEvent(Point(event.wheel.y * speed, event.wheel.x * speed), modstate);
				} else {
					e = EventMgr::CreateMouseWheelEvent(Point(event.wheel.x * speed, event.wheel.y * speed), modstate);
				}
				EvntManager->DispatchEvent(std::move(e));
			}
			break;
		case SDL_TEXTINPUT:
			EvntManager->DispatchEvent(EventMgr::CreateTextEvent(event.text.text));
			break;
		case SDL_FINGERDOWN:
		case SDL_FINGERUP:
			{
				TouchEvent::Finger fingers[1] = {};
				fingers[0].x = event.tfinger.x * screenSize.w;
				fingers[0].y = event.tfinger.y * screenSize.h;
				fingers[0].deltaX = event.tfinger.dx * screenSize.w;
				fingers[0].deltaY = event.tfinger.dy * screenSize.h;
				fingers[0].id = event.tfinger.fingerId;
				e = EventMgr::CreateTouchEvent(fingers, 1, event.type == SDL_FINGERDOWN, event.tfinger.pressure);
				e.mod = modstate;
				EvntManager->DispatchEvent(std::move(e));
			}
			break;
		case SDL_APP_DIDENTERFOREGROUND:
			EvntManager->DispatchEvent(EventMgr::CreateRedrawRequestEvent());
			break;
		case SDL_WINDOWEVENT:
			switch (event.window.event) {
				case SDL_WINDOWEVENT_LEAVE:
					if (core->config.GUIEnhancements & 8) core->DisableGameControl(true);
					break;
				case SDL_WINDOWEVENT_ENTER:
					if (core->config.GUIEnhancements & 8) core->DisableGameControl(false);
					break;
				case SDL_WINDOWEVENT_RESTORED:
					core->GetMusicLoop().Resume();
					break;
				case SDL_WINDOWEVENT_SIZE_CHANGED:
					UpdatePresentRect();
					EvntManager->DispatchEvent(EventMgr::CreateRedrawRequestEvent());
					break;
				default:
					break;
			}
			break;
		default:
			break;
	}
	return GEM_OK;
}

#include "plugindef.h"

GEMRB_PLUGIN(0x6C0A7E11, "OpenGL 3.3 Video Driver")
PLUGIN_DRIVER(GLVideoDriver, "opengl")
END_PLUGIN()

// ---------------------------------------------------------------- scene post pass (phase 5)

// Bloom (bright pass at half resolution, two widening separable blurs),
// colour grading and vignette over the scene region, after lighting and fog.
void GLVideoDriver::DrawScenePost(const ScenePost& post)
{
	if (!postProgram || !SceneAppliesToTarget()) return;
	if (post.bloom <= 0.0f && !post.grade && post.vignette <= 0.0f) return;
	Flush();
	batchValid = false;

	GLBatchState st = TargetState();
	const Region R = st.scissor.Intersect(Region(Point(), st.targetSize));
	if (R.w <= 0 || R.h <= 0) return;
	const GLVideoBuffer* target = static_cast<const GLVideoBuffer*>(drawingBuffer);

	EnsureTarget(postTex, postFbo, postSize, R.size, GL_RGBA8, GL_UNSIGNED_BYTE, true);
	if (depthAttachedFbo == target->fbo) {
		glBindFramebuffer(GL_FRAMEBUFFER, depthAttachedFbo);
		glColorMaski(1, GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
	}
	glDisable(GL_SCISSOR_TEST);
	glDisable(GL_BLEND);
	glBindFramebuffer(GL_READ_FRAMEBUFFER, target->fbo);
	glReadBuffer(GL_COLOR_ATTACHMENT0);
	glBindFramebuffer(GL_DRAW_FRAMEBUFFER, postFbo);
	glBlitFramebuffer(R.x, R.y, R.x + R.w, R.y + R.h, 0, 0, R.w, R.h, GL_COLOR_BUFFER_BIT, GL_NEAREST);

	glUseProgram(postProgram);
	glUniform1i(puni.flipY, 0);
	std::vector<GLVertex> quad;
	const bool bloom = post.bloom > 0.0f;
	if (bloom) {
		Size half(std::max(1, (R.w + 1) / 2), std::max(1, (R.h + 1) / 2));
		for (int i = 0; i < 2; ++i) EnsureTarget(bloomTex[i], bloomFbo[i], bloomSize[i], half, GL_RGBA16F, GL_HALF_FLOAT, true);
		glViewport(0, 0, half.w, half.h);
		glUniform2f(puni.targetSize, float(half.w), float(half.h));

		// bright pass
		glBindFramebuffer(GL_FRAMEBUFFER, bloomFbo[0]);
		glUniform1i(puni.mode, 0);
		glUniform1f(puni.threshold, post.bloomThreshold);
		glUniform2f(puni.srcSize, float(R.w), float(R.h));
		glActiveTexture(GL_TEXTURE0);
		glBindTexture(GL_TEXTURE_2D, postTex);
		PushLightQuad(quad, 0, 0, float(half.w), float(half.h), 0, 0, float(R.w), float(R.h), 0, 0, 0);
		DrawLightVertices(quad);

		// blur: ping-pong, the second round twice as wide; widths follow the render scale
		glUniform1i(puni.mode, 1);
		glUniform2f(puni.srcSize, float(half.w), float(half.h));
		quad.clear();
		PushLightQuad(quad, 0, 0, float(half.w), float(half.h), 0, 0, float(half.w), float(half.h), 0, 0, 0);
		float step = std::max(1.0f, renderScale * 0.75f);
		for (int round = 0; round < 2; ++round) {
			float k = step * float(1 + round * 2);
			glBindFramebuffer(GL_FRAMEBUFFER, bloomFbo[1]);
			glBindTexture(GL_TEXTURE_2D, bloomTex[0]);
			glUniform2f(puni.dir, k, 0.0f);
			DrawLightVertices(quad);
			glBindFramebuffer(GL_FRAMEBUFFER, bloomFbo[0]);
			glBindTexture(GL_TEXTURE_2D, bloomTex[1]);
			glUniform2f(puni.dir, 0.0f, k);
			DrawLightVertices(quad);
		}
	}

	// composite back into the scene
	glBindFramebuffer(GL_FRAMEBUFFER, target->fbo);
	glViewport(0, 0, target->physSize.w, target->physSize.h);
	glUniform2f(puni.targetSize, float(target->physSize.w), float(target->physSize.h));
	glUniform1i(puni.mode, 2);
	glUniform2f(puni.srcSize, float(R.w), float(R.h));
	glUniform1f(puni.bloomStrength, bloom ? post.bloom : 0.0f);
	glUniform1i(puni.grade, post.grade ? 1 : 0);
	glUniform1f(puni.saturation, post.saturation);
	glUniform1f(puni.contrast, post.contrast);
	glUniform3f(puni.lift, post.lift[0], post.lift[1], post.lift[2]);
	glUniform3f(puni.gain, post.gain[0], post.gain[1], post.gain[2]);
	glUniform1f(puni.vignette, post.vignette);
	glActiveTexture(GL_TEXTURE1);
	glBindTexture(GL_TEXTURE_2D, bloom ? bloomTex[0] : zeroTex);
	glActiveTexture(GL_TEXTURE0);
	glBindTexture(GL_TEXTURE_2D, postTex);
	quad.clear();
	PushLightQuad(quad, float(R.x), float(R.y), float(R.x + R.w), float(R.y + R.h), 0, 0, float(R.w), float(R.h), 0, 0, 0);
	DrawLightVertices(quad);

	glUseProgram(program);
	batchValid = false;
}
