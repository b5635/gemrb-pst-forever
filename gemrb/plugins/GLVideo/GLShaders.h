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
                      // texMode 3 (soft shapes): x: profile, y: ring half width, z: glow width, w: glow alpha

uniform int u_texMode; // 0 colour, 1 rgba, 2 indexed, 3 soft shape (v_uv = ellipse space, 1 = radius)
uniform sampler2D u_rgba;
uniform usampler2D u_index;
uniform sampler2D u_palette;
uniform sampler2D u_stencil;
uniform int u_stencilChannel; // -1 off
uniform int u_dither;
uniform float u_stencilA; // stencil texel = fragCoord * A + B
uniform vec2 u_stencilB;
uniform int u_smooth;
uniform vec2 u_post; // brightness add, contrast mul
uniform float u_objDepth; // ground line of the object (scene y), see SceneLighting
uniform int u_depthPremul;
uniform vec4 u_outline; // phase 5 hover outline: colour (a > 0 = outline pass)
uniform float u_outlineRadius; // texels

layout(location = 0) out vec4 o_color;
layout(location = 1) out vec4 o_depth; // only written while a depth map is attached and wanted

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

// alpha of a texel, 0 outside the texture (outline pass)
float alphaAt(ivec2 p, ivec2 size)
{
	if (any(lessThan(p, ivec2(0))) || any(greaterThanEqual(p, size))) return 0.0;
	// creature BAMs keep their baked-in ground shadow in palette index 1: not part of the body
	if (u_texMode == 2 && int(texelFetch(u_index, p, 0).r) == 1) return 0.0;
	return fetch(p, size).a;
}

float stencilCover()
{
	if (u_stencilChannel < 0) return 1.0;
	ivec2 sp = ivec2(floor(gl_FragCoord.xy * u_stencilA + u_stencilB));
	float s = texelFetch(u_stencil, clamp(sp, ivec2(0), textureSize(u_stencil, 0) - 1), 0)[u_stencilChannel];
	if (u_dither == 1 && s > 0.25 && s < 0.75) {
		// checker in stencil (map) pixels, so it keeps the original pattern size when scaled
		return float((sp.x + sp.y) & 1);
	}
	return 1.0 - s;
}

// soft shapes (phase 5): 0 antialiased disc, 1 soft blob, 2 ring with glow
vec4 softShape()
{
	float d = length(v_uv);
	float px = max(fwidth(d), 0.0001);
	int profile = int(v_param.x);
	float a;
	if (profile == 0) {
		a = 1.0 - smoothstep(1.0 - px, 1.0 + px, d);
	} else if (profile == 1) {
		float t = clamp(1.0 - d * d, 0.0, 1.0);
		a = t * t;
	} else {
		float e = abs(d - 1.0);
		float hw = max(v_param.y, px * 0.5);
		float core = 1.0 - smoothstep(hw - px, hw + px, e);
		float g = v_param.z > 0.0 ? exp(-(e * e) / (v_param.z * v_param.z)) * v_param.w : 0.0;
		// the glow sits mostly inside the ring
		if (d > 1.0) g *= 0.5;
		a = max(core, g);
	}
	return vec4(v_color.rgb, v_color.a * a);
}

void main()
{
	vec4 c;
	if (u_texMode == 3) {
		o_color = softShape();
		o_color.a *= stencilCover();
		o_depth = vec4(0.0);
		return;
	}
	if (u_texMode != 0 && u_outline.a > 0.0) {
		// outline pass: covered by a neighbour within the radius, not covered here
		ivec2 size = texSize();
		ivec2 p = ivec2(floor(v_uv));
		float here = alphaAt(p, size);
		float near = 0.0;
		for (int i = 0; i < 12; ++i) {
			float ang = float(i) * 0.5235988;
			vec2 o = vec2(cos(ang), sin(ang)) * u_outlineRadius;
			near = max(near, alphaAt(ivec2(floor(v_uv + o)), size));
			near = max(near, alphaAt(ivec2(floor(v_uv + o * 0.5)), size));
		}
		float a = clamp(step(0.5, near) - step(0.5, here), 0.0, 1.0) * u_outline.a;
		o_color = vec4(u_outline.rgb, a * stencilCover());
		o_depth = vec4(0.0);
		return;
	}
	if (u_texMode == 0) {
		c = v_color;
	} else {
		ivec2 size = texSize();
		vec2 pos = v_uv - 0.5;
		ivec2 p = ivec2(floor(pos));
		vec2 f = fract(pos);
		if (u_smooth == 1) {
			// sharpen only while magnifying; when minifying plain bilinear shimmers less
			vec2 px = max(fwidth(v_uv), vec2(0.0001));
			vec2 sharp = clamp((f - 0.5) / px + 0.5, 0.0, 1.0);
			f = mix(sharp, f, step(1.0, px));
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

	c.a *= stencilCover();

	c.rgb = clamp((c.rgb + u_post.x) * u_post.y, 0.0, 1.0);
	o_color = c;
	// covered (alpha >= 0.5) pixels own the depth; blending keeps it cheap for edges
	float cov = step(0.5, c.a);
	o_depth = u_depthPremul == 1 ? vec4(u_objDepth * cov, 0.0, 0.0, cov) : vec4(u_objDepth, 0.0, 0.0, cov);
}
)GLSL";
// Scene lighting (phase 4), same vertex shader as the sprites.
// mode 0: one point light, additive into the light buffer. Without geometry it
//         is a flat ellipse on the screen. With geometry every pixel is put
//         back into 3D from the generated depth map (ground line per pixel:
//         walls from their polygons' base lines, sprites from their feet) and
//         gets a normal generated from the art's luminance (bump) on top of its
//         surface orientation (floor faces up, walls/sprites face the viewer).
// mode 1: multiplies a copy of the scene by the light buffer; very bright
//         pixels keep part of their brightness.
// mode 2: writes wall polygon rows into the wall depth map (v_uv.x = ground y).
static const char* const LightFS = R"GLSL(
#version 330 core
in vec2 v_uv;
in vec4 v_color;
flat in vec4 v_param;

uniform int u_mode;
uniform sampler2D u_scene; // copy of the scene region, physical px (region relative)
uniform sampler2D u_light;
uniform sampler2D u_spriteDepth; // scene buffer physical px
uniform sampler2D u_wallDepth; // region relative
uniform vec2 u_sceneSize;
uniform float u_keep;
uniform float u_maxLight;

uniform int u_geom;
uniform vec4 u_lightPos; // ground x, ground y, height, radius (scene map units)
uniform vec3 u_lightColor;
uniform vec3 u_map; // physical = map * x + (y, z)
uniform vec2 u_regionOrigin; // physical px of the region's top left
uniform float u_lightToPhys; // physical px per light buffer px
uniform float u_bump;
uniform float u_normalStrength;
uniform int u_debug; // GEMRB_LIGHT_DEBUG: red = vertical surface, green = falloff, blue = normal x

out vec4 o_color;

float luma(ivec2 p)
{
	p = clamp(p, ivec2(0), textureSize(u_scene, 0) - 1);
	return dot(texelFetch(u_scene, p, 0).rgb, vec3(0.299, 0.587, 0.114));
}

float lambert(vec3 n, vec3 l)
{
	return clamp((dot(n, l) + 0.4) / 1.4, 0.0, 1.0); // wrapped, so shading stays soft
}

void main()
{
	if (u_mode == 2) {
		o_color = vec4(v_uv.x, 0.0, 0.0, 1.0);
		return;
	}
	if (u_mode == 0) {
		vec2 phys = gl_FragCoord.xy * u_lightToPhys + u_regionOrigin;
		vec2 m = (phys - u_map.yz) / u_map.x;
		if (u_geom == 0) {
			vec2 d = vec2(m.x - u_lightPos.x, (m.y - (u_lightPos.y - u_lightPos.z)) / 0.72) / u_lightPos.w;
			float r2 = dot(d, d);
			if (r2 >= 1.0) discard;
			float f = 1.0 - r2;
			o_color = vec4(u_lightColor * (f * f), 1.0);
			return;
		}
		ivec2 rp = ivec2(floor(phys - u_regionOrigin));
		// depth: ground line under this pixel
		float ground = m.y;
		vec4 wd = texelFetch(u_wallDepth, clamp(rp, ivec2(0), textureSize(u_wallDepth, 0) - 1), 0);
		if (wd.a > 0.5) ground = max(ground, wd.r);
		vec4 sd = texelFetch(u_spriteDepth, clamp(ivec2(floor(phys)), ivec2(0), textureSize(u_spriteDepth, 0) - 1), 0);
		if (sd.a > 0.5) ground = sd.r / sd.a;
		float h = max(ground - m.y, 0.0);
		bool vertical = h > 2.0;
		vec3 P = vec3(m.x, ground, h);
		vec3 L = u_lightPos.xyz - P;
		float dist = length(vec3(L.x, L.y / 0.72, L.z)) / u_lightPos.w;
		if (dist >= 1.0) discard;
		float att = 1.0 - dist * dist;
		att *= att;
		// normal from the art: brighter = higher, sampled one map unit apart
		int k = max(1, int(u_map.x + 0.5));
		float gx = (luma(rp + ivec2(k, 0)) - luma(rp - ivec2(k, 0))) * 0.5 * u_bump;
		float gy = (luma(rp + ivec2(0, k)) - luma(rp - ivec2(0, k))) * 0.5 * u_bump;
		vec3 n = vertical ? normalize(vec3(-gx, 1.0, gy)) : normalize(vec3(-gx, -gy, 1.0));
		vec3 l = normalize(L);
		// relative to an unbumped floor, so overall falloff matches the flat lights
		float ratio = clamp(lambert(n, l) / max(lambert(vec3(0.0, 0.0, 1.0), l), 0.25), 0.0, 2.5);
		if (u_debug == 1) {
			o_color = vec4(vertical ? 0.5 : 0.0, att * 0.5, (n.x * 0.5 + 0.5) * att, 1.0);
			return;
		}
		o_color = vec4(u_lightColor * att * mix(1.0, ratio, u_normalStrength), 1.0);
		return;
	}
	vec4 c = texelFetch(u_scene, ivec2(floor(v_uv)), 0);
	vec3 l = texture(u_light, v_uv / u_sceneSize).rgb;
	if (u_debug == 1) {
		o_color = vec4(l, 1.0);
		return;
	}
	// soft shoulder towards the cap, so overlapping lights don't clip hard
	vec3 over = max(l - 1.0, vec3(0.0));
	l = min(l, vec3(1.0)) + over / (1.0 + over / max(u_maxLight - 1.0, 0.001));
	vec3 lit = c.rgb * l;
	float hi = smoothstep(0.72, 1.0, max(c.r, max(c.g, c.b)));
	lit = mix(lit, max(lit, c.rgb), hi * u_keep);
	o_color = vec4(min(lit, vec3(1.0)), c.a);
}
)GLSL";
// Scene post pass (phase 5), same vertex shader.
// mode 0: bright pass (soft knee threshold), sampling u_src bilinearly
// mode 1: 9 tap gaussian along u_dir (texels of u_src)
// mode 2: scene + bloom, colour grading, vignette (v_uv = scene texels)
static const char* const PostFS = R"GLSL(
#version 330 core
in vec2 v_uv;
in vec4 v_color;
flat in vec4 v_param;

uniform int u_mode;
uniform sampler2D u_src;
uniform sampler2D u_bloom;
uniform vec2 u_srcSize;
uniform vec2 u_dir;
uniform float u_threshold;
uniform float u_bloomStrength;
uniform int u_grade;
uniform float u_saturation;
uniform float u_contrast;
uniform vec3 u_lift;
uniform vec3 u_gain;
uniform float u_vignette;

out vec4 o_color;

float luma(vec3 c) { return dot(c, vec3(0.299, 0.587, 0.114)); }

void main()
{
	if (u_mode == 0) {
		vec3 c = texture(u_src, v_uv / u_srcSize).rgb;
		float l = max(c.r, max(c.g, c.b));
		float knee = 0.18;
		float soft = clamp(l - u_threshold + knee, 0.0, 2.0 * knee);
		soft = soft * soft / (4.0 * knee + 0.0001);
		float w = max(soft, l - u_threshold) / max(l, 0.0001);
		o_color = vec4(c * w, 1.0);
		return;
	}
	if (u_mode == 1) {
		vec2 uv = v_uv / u_srcSize;
		vec2 d = u_dir / u_srcSize;
		vec3 c = texture(u_src, uv).rgb * 0.2270270;
		c += (texture(u_src, uv + d * 1.3846154).rgb + texture(u_src, uv - d * 1.3846154).rgb) * 0.3162162;
		c += (texture(u_src, uv + d * 3.2307692).rgb + texture(u_src, uv - d * 3.2307692).rgb) * 0.0702703;
		o_color = vec4(c, 1.0);
		return;
	}
	vec4 s = texelFetch(u_src, ivec2(floor(v_uv)), 0);
	vec2 uv = v_uv / u_srcSize;
	vec3 c = s.rgb;
	if (u_bloomStrength > 0.0) {
		vec3 b = texture(u_bloom, uv).rgb * u_bloomStrength;
		c = c + b * (1.0 - c * 0.5); // screen-ish, keeps highlights from clipping flat
	}
	if (u_grade == 1) {
		float l = luma(c);
		c = mix(vec3(l), c, u_saturation);
		c = (c - 0.5) * u_contrast + 0.5;
		// lift tints the shadows, gain the highlights
		c = c * u_gain + u_lift * (1.0 - c);
	}
	if (u_vignette > 0.0) {
		vec2 dv = (uv - 0.5) * vec2(1.0, 0.85);
		float v = smoothstep(0.35, 0.95, length(dv) * 1.3);
		c *= 1.0 - v * u_vignette;
	}
	o_color = vec4(clamp(c, 0.0, 1.0), s.a);
}
)GLSL";
}

#endif
