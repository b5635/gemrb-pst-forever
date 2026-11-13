// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef GLSHADERS_H
#define GLSHADERS_H

namespace GemRB {

static const char* const SpriteVS = R"GLSL(
#version 330 core
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
layout(location = 2) in vec4 a_color;
layout(location = 3) in vec4 a_param;

uniform vec2 u_targetSize;
uniform int u_flipY;

out vec2 v_uv;
out vec4 v_color;
flat out vec4 v_param;

void main()
{
	vec2 ndc = a_pos / u_targetSize * 2.0 - 1.0;
	// render targets keep row 0 at the top of the image in texel row 0;
	// only the window's default framebuffer needs a flip
	if (u_flipY == 1) ndc.y = -ndc.y;
	gl_Position = vec4(ndc, 0.0, 1.0);
	v_uv = a_uv;
	v_color = a_color;
	v_param = a_param;
}
)GLSL";

// Draws everything: flat colour, RGBA textures and 8 bit indexed textures.
// Indexed textures are looked up in a palette atlas (one 256 colour row per
// palette) and filtered *after* the lookup with a sharpened bilinear filter:
// texel centres stay crisp at 1:1, edges blend only across one screen pixel
// when scaled (same idea as the pst-forever tiles/sprite shaders).
static const char* const SpriteFS = R"GLSL(
#version 330 core
in vec2 v_uv;
in vec4 v_color;
flat in vec4 v_param; // x: palette row, y: grey mode, z: colour key index, w: unused

uniform int u_texMode; // 0 colour, 1 rgba, 2 indexed
uniform sampler2D u_rgba;
uniform usampler2D u_index;
uniform sampler2D u_palette;
uniform sampler2D u_stencil;
uniform int u_stencilChannel; // -1 off
uniform int u_dither;
uniform vec2 u_stencilOrigin;
uniform int u_smooth;
uniform vec2 u_post; // brightness add, contrast mul

out vec4 o_color;

ivec2 texSize()
{
	return u_texMode == 2 ? textureSize(u_index, 0) : textureSize(u_rgba, 0);
}

vec4 fetch(ivec2 p, ivec2 size)
{
	p = clamp(p, ivec2(0), size - 1);
	vec4 c;
	if (u_texMode == 2) {
		int idx = int(texelFetch(u_index, p, 0).r);
		if (idx == int(v_param.z)) return vec4(0.0);
		c = texelFetch(u_palette, ivec2(idx, int(v_param.x)), 0);
	} else {
		c = texelFetch(u_rgba, p, 0);
	}
	return vec4(c.rgb * c.a, c.a); // premultiplied so edges don't pick up dark fringes
}

void main()
{
	vec4 c;
	if (u_texMode == 0) {
		c = v_color;
	} else {
		ivec2 size = texSize();
		vec2 pos = v_uv - 0.5;
		ivec2 p = ivec2(floor(pos));
		vec2 f = fract(pos);
		if (u_smooth == 1) {
			vec2 px = max(fwidth(v_uv), vec2(0.0001));
			f = clamp((f - 0.5) / px + 0.5, 0.0, 1.0);
		} else {
			f = step(0.5, f);
		}
		vec4 t = mix(mix(fetch(p, size), fetch(p + ivec2(1, 0), size), f.x),
			mix(fetch(p + ivec2(0, 1), size), fetch(p + ivec2(1, 1), size), f.x), f.y);
		c = t.a > 0.0 ? vec4(t.rgb / t.a, t.a) : vec4(0.0);
		c *= v_color;
	}

	int grey = int(v_param.y);
	if (grey != 0) {
		float g = (c.r + c.g + c.b) * 0.25;
		c.rgb = grey == 1 ? vec3(g) : vec3(g + 21.0 / 255.0, g, max(0.0, g - 32.0 / 255.0));
	}

	if (u_stencilChannel >= 0) {
		float s = texelFetch(u_stencil, ivec2(gl_FragCoord.xy - u_stencilOrigin), 0)[u_stencilChannel];
		if (u_dither == 1 && s > 0.25 && s < 0.75) {
			ivec2 fc = ivec2(gl_FragCoord.xy);
			c.a *= float((fc.x + fc.y) & 1);
		} else {
			c.a *= 1.0 - s;
		}
	}

	c.rgb = clamp((c.rgb + u_post.x) * u_post.y, 0.0, 1.0);
	o_color = c;
}
)GLSL";

}

#endif
