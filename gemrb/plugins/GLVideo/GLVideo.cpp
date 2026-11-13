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

GLVideoBuffer::GLVideoBuffer(const Region& r, Video::BufferFormat fmt, GLVideoDriver* drv)
	: VideoBuffer(r), driver(drv), format(fmt)
{
	glGenTextures(1, &texture);
	glBindTexture(GL_TEXTURE_2D, texture);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, std::max(r.w, 1), std::max(r.h, 1), 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glGenFramebuffers(1, &fbo);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
	glClearColor(0, 0, 0, 0);
	glDisable(GL_SCISSOR_TEST);
	glClear(GL_COLOR_BUFFER_BIT);
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

	glBindTexture(GL_TEXTURE_2D, texture);
	glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
	glTexSubImage2D(GL_TEXTURE_2D, 0, dest.x, dest.y, dest.w, dest.h, GL_RGBA, GL_UNSIGNED_BYTE, rgba.data());
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
	uni.stencilOrigin = glGetUniformLocation(program, "u_stencilOrigin");
	uni.smooth = glGetUniformLocation(program, "u_smooth");
	uni.post = glGetUniformLocation(program, "u_post");
	glUseProgram(program);
	glUniform1i(uni.rgba, 0);
	glUniform1i(uni.index, 1);
	glUniform1i(uni.palette, 2);
	glUniform1i(uni.stencil, 3);

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

	uint32_t white = 0xffffffff;
	glGenTextures(1, &whiteTex);
	glBindTexture(GL_TEXTURE_2D, whiteTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, &white);

	// logical screen composite target
	glGenTextures(1, &screenTex);
	glBindTexture(GL_TEXTURE_2D, screenTex);
	glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, screenSize.w, screenSize.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
	glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
	glGenFramebuffers(1, &screenFbo);
	glBindFramebuffer(GL_FRAMEBUFFER, screenFbo);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, screenTex, 0);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
		Log(ERROR, "GLVideo", "Screen framebuffer incomplete");
		return false;
	}
	return true;
}

VideoBuffer* GLVideoDriver::NewVideoBuffer(const Region& r, BufferFormat fmt)
{
	Flush();
	return new GLVideoBuffer(r, fmt, this);
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
	glUniform2f(uni.stencilOrigin, float(st.stencilOrigin.x), float(st.stencilOrigin.y));
	glUniform1i(uni.smooth, st.smooth ? 1 : 0);
	glUniform2f(uni.post, st.brightness, st.contrast);

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

GLBatchState GLVideoDriver::TargetState() const
{
	GLBatchState st;
	const GLVideoBuffer* target = static_cast<const GLVideoBuffer*>(drawingBuffer);
	assert(target);
	st.fbo = target->fbo;
	st.targetSize = target->Size();
	Region bufRgn(Point(), target->Size());
	st.scissor = screenClip.Intersect(bufRgn);
	if (st.scissor.size.IsInvalid()) st.scissor = Region(0, 0, 0, 0);
	return st;
}

void GLVideoDriver::PushQuad(float x0, float y0, float x1, float y1, float u0, float v0, float u1, float v1, const Color& c, float pal, float grey, float ckey)
{
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
	GLVertex v[4] = {
		{ ax + nx, ay + ny, 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
		{ bx + nx, by + ny, 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
		{ ax - nx, ay - ny, 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
		{ bx - nx, by - ny, 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 },
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

void GLVideoDriver::DrawSprite(const Holder<Sprite2D>& spr, const Region& src, const Region& dst, BlitFlags flags, const Color& tint)
{
	if (!spr || src.w <= 0 || src.h <= 0 || dst.w <= 0 || dst.h <= 0) return;
	const GLSprite2D* gspr = dynamic_cast<const GLSprite2D*>(spr.get());
	if (!gspr) {
		Log(WARNING, "GLVideo", "Skipping a sprite not created by this driver");
		return;
	}

	if (spr->renderFlags & BlitFlags::MIRRORX) flags ^= BlitFlags::MIRRORX;
	if (spr->renderFlags & BlitFlags::MIRRORY) flags ^= BlitFlags::MIRRORY;
	flags |= spr->renderFlags & BlitFlags::BLEND_MASK;
	if (!spr->HasTransparency()) flags &= ~BlitFlags::BLENDED;

	GLBatchState st = TargetState();
	if (st.scissor.w <= 0 || st.scissor.h <= 0) return;
	if (!dst.IntersectsRegion(st.scissor)) return;

	float pal = -1;
	float ckey = -1;
	if (gspr->IsIndexed()) {
		const Holder<Palette>& palette = spr->GetPalette();
		if (!palette) return;
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
	if (!tex) return;

	st.texMode = gspr->IsIndexed() ? 2 : 1;
	st.texture = tex;
	st.blend = BlendForFlags(flags);

	if ((flags & BlitFlags::STENCIL_MASK) && stencilBuffer) {
		const GLVideoBuffer* sb = static_cast<const GLVideoBuffer*>(stencilBuffer.get());
		st.stencilTex = sb->texture;
		st.stencilOrigin = sb->Origin();
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
	SetBatch(st);

	Color c = ColorWhite;
	if (flags & BlitFlags::COLOR_MOD) {
		c.r = tint.r;
		c.g = tint.g;
		c.b = tint.b;
	}
	if (flags & BlitFlags::ALPHA_MOD) c.a = tint.a;
	if (flags & BlitFlags::HALFTRANS) c.a /= 2;

	float grey = 0;
	if (flags & BlitFlags::GREY) {
		grey = 1;
	} else if (flags & BlitFlags::SEPIA) {
		grey = 2;
	}

	float u0 = float(src.x), u1 = float(src.x + src.w);
	float v0 = float(src.y), v1 = float(src.y + src.h);
	if (flags & BlitFlags::MIRRORX) std::swap(u0, u1);
	if (flags & BlitFlags::MIRRORY) std::swap(v0, v1);
	PushQuad(float(dst.x), float(dst.y), float(dst.x + dst.w), float(dst.y + dst.h), u0, v0, u1, v1, c, pal, grey, ckey);
}

void GLVideoDriver::DrawTexture(const GLVideoBuffer* buf, const Region& src, const Region& dst, BlitFlags flags, const Color& tint)
{
	GLBatchState st = TargetState();
	if (st.scissor.w <= 0 || st.scissor.h <= 0) return;
	st.texMode = 1;
	st.texture = buf->texture;
	st.blend = BlendForFlags(flags);
	if ((flags & BlitFlags::STENCIL_MASK) && stencilBuffer) {
		const GLVideoBuffer* sb = static_cast<const GLVideoBuffer*>(stencilBuffer.get());
		st.stencilTex = sb->texture;
		st.stencilOrigin = sb->Origin();
		st.stencilChannel = (flags & BlitFlags::STENCIL_RED) ? 0 : (flags & BlitFlags::STENCIL_GREEN) ? 1 :
			(flags & BlitFlags::STENCIL_BLUE)                                                     ? 2 :
														3;
		st.dither = (flags & BlitFlags::STENCIL_DITHER) ? 1 : 0;
	}
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
	float u0 = float(src.x), u1 = float(src.x + src.w);
	float v0 = float(src.y), v1 = float(src.y + src.h);
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
		vertices.push_back({ verts[i * 2], verts[i * 2 + 1], 0, 0, c.r, c.g, c.b, c.a, -1, 0, -1, 0 });
	}
}

void GLVideoDriver::ClearBuffer(GLVideoBuffer* buf, const Region& rgn)
{
	GLBatchState st;
	st.fbo = buf->fbo;
	st.targetSize = buf->Size();
	st.scissor = Region(Point(), buf->Size());
	st.blend = GLBlend::None;
	SetBatch(st);
	PushColorRect(rgn, Color(0, 0, 0, 0));
}

// ---------------------------------------------------------------- presentation

void GLVideoDriver::CompositeBuffer(const GLVideoBuffer* buf)
{
	GLBatchState st;
	st.fbo = screenFbo;
	st.targetSize = screenSize;
	st.scissor = Region(Point(), screenSize);
	st.texMode = 1;
	st.texture = buf->texture;
	st.blend = GLBlend::Alpha;
	st.smooth = false;
	SetBatch(st);
	const Region& r = buf->Rect();
	PushQuad(float(r.x), float(r.y), float(r.x + r.w), float(r.y + r.h), 0, 0, float(r.w), float(r.h), ColorWhite);
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
	st.smooth = true;
	st.brightness = brightness;
	st.contrast = contrast;
	SetBatch(st);
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glDisable(GL_SCISSOR_TEST);
	glClearColor(0, 0, 0, 1);
	glClear(GL_COLOR_BUFFER_BIT);
	const Region& p = presentRect;
	PushQuad(float(p.x), float(p.y), float(p.x + p.w), float(p.y + p.h), 0, 0, float(screenSize.w), float(screenSize.h), ColorWhite);
	Flush();
	batchValid = false;

	DevScreenshot();
	SDL_GL_SwapWindow(window);

	// palette rows are per frame
	paletteRows.clear();
	nextPaletteRow = 0;
}

// dev hook: GEMRB_GL_SHOT="file.bmp;seconds" writes the presented frame once, focus-independent
void GLVideoDriver::DevScreenshot()
{
	static const char* spec = getenv("GEMRB_GL_SHOT");
	static bool done = false;
	static uint32_t start = GetMilliseconds();
	if (!spec || done) return;
	std::string str(spec);
	size_t sep = str.rfind(';');
	float secs = sep == std::string::npos ? 30.0f : float(atof(str.c_str() + sep + 1));
	if (GetMilliseconds() - start < uint32_t(secs * 1000)) return;
	done = true;
	std::string path = str.substr(0, sep);
	int w = windowPixels.w, h = windowPixels.h;
	std::vector<uint8_t> px(size_t(w) * h * 4);
	glBindFramebuffer(GL_FRAMEBUFFER, 0);
	glReadBuffer(GL_BACK);
	glPixelStorei(GL_PACK_ALIGNMENT, 4);
	glReadPixels(0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, px.data()); // bottom-up, exactly what BMP wants
	FILE* f = fopen(path.c_str(), "wb");
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
	Log(MESSAGE, "GLVideo", "Wrote dev screenshot {}", path);
}

Holder<Sprite2D> GLVideoDriver::GetScreenshot(Region r, const VideoBufferPtr& buf)
{
	Flush();
	GLuint fbo = screenFbo;
	Size srcSize = screenSize;
	if (buf) {
		fbo = static_cast<const GLVideoBuffer*>(buf.get())->fbo;
		srcSize = buf->Size();
	}
	if (r.w <= 0 || r.h <= 0) {
		r = Region(Point(), srcSize);
	}
	r = r.Intersect(Region(Point(), srcSize));
	std::vector<uint32_t> px(size_t(r.w) * r.h);
	glBindFramebuffer(GL_FRAMEBUFFER, fbo);
	glPixelStorei(GL_PACK_ALIGNMENT, 4);
	glReadPixels(r.x, r.y, r.w, r.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
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
