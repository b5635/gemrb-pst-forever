// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "ScenePolish.h"

#include "damages.h"
#include "ie_stats.h"

#include "CharAnimations.h"
#include "DataFileMgr.h"
#include "Game.h"
#include "GameData.h"
#include "GlobalTimer.h"
#include "TableMgr.h"
#include "Interface.h"
#include "Map.h"

#include "Scriptable/Actor.h"
#include "Scriptable/Selectable.h"
#include "Strings/CString.h"
#include "Video/Video.h"

#include <algorithm>
#include <cmath>
#include <random>

namespace GemRB {

namespace {
	// our own generator: presentation must never consume the game's random numbers
	std::minstd_rand& Rng()
	{
		static std::minstd_rand rng(0x5eed);
		return rng;
	}

	float Rand(float lo, float hi)
	{
		std::uniform_real_distribution<float> d(lo, hi);
		return d(Rng());
	}

	template<size_t N>
	int Setting(const char (&key)[N], int def)
	{
		return int(core->GetDictionary().Get(key, def));
	}

	uint8_t ToByte(float v)
	{
		return uint8_t(std::max(0.0f, std::min(255.0f, v * 255.0f + 0.5f)));
	}

	constexpr size_t MaxParticles = 2500;
	constexpr size_t MaxDecals = 400;
	constexpr float Gravity = 520.0f;
}

ScenePolish& ScenePolish::Get()
{
	static ScenePolish instance;
	return instance;
}

bool ScenePolish::Enabled()
{
	return VideoDriver && VideoDriver->SupportsSceneTransform() && VideoDriver->GetScene().active;
}

bool ScenePolish::SmoothShake()
{
	return VideoDriver && VideoDriver->SupportsSceneTransform() && Setting("SmoothShake", 1) != 0;
}

// ---------------------------------------------------------------- frame update

void ScenePolish::BeginFrame(const Map* map, const Region& viewport)
{
	tick_t now = GetMilliseconds();
	float dt = lastTick ? float(std::min<tick_t>(now - lastTick, 100)) / 1000.0f : 0.0f;
	lastTick = now;
	if (map != area) {
		particles.clear();
		flashes.clear();
		area = map;
		dt = 0.0f;
	}
	critTarget = nullptr;
	Simulate(dt);
	SpawnAmbient(map, viewport, dt);
	emitters.clear();
}

void ScenePolish::AddFireEmitter(const Region& sprite, float r, float g, float b, float strength)
{
	emitters.push_back({ sprite, r, g, b, strength });
}

void ScenePolish::Simulate(float dt)
{
	if (dt <= 0.0f) return;
	for (auto& p : particles) {
		p.age += dt;
		switch (p.kind) {
			case Kind::Spark:
				p.vz -= 420.0f * dt;
				p.vx *= 1.0f - 2.5f * dt;
				p.vy *= 1.0f - 2.5f * dt;
				break;
			case Kind::Blood:
			case Kind::Chip:
				p.vz -= Gravity * dt;
				p.vx *= 1.0f - 0.8f * dt;
				p.vy *= 1.0f - 0.8f * dt;
				break;
			case Kind::Dust:
				p.vx *= 1.0f - 3.0f * dt;
				p.vy *= 1.0f - 3.0f * dt;
				p.vz *= 1.0f - 1.5f * dt;
				p.size += 3.5f * dt;
				break;
			case Kind::Smoke:
				p.vx *= 1.0f - 2.0f * dt;
				p.vy *= 1.0f - 2.0f * dt;
				p.vx += Rand(-20.0f, 20.0f) * dt;
				p.size += 4.0f * dt;
				break;
			case Kind::Shield:
				p.vx *= 1.0f - 4.0f * dt;
				p.vz *= 1.0f - 4.0f * dt;
				break;
			case Kind::Wisp:
				p.vx *= 1.0f - 1.5f * dt;
				p.vy *= 1.0f - 1.5f * dt;
				p.vx += Rand(-30.0f, 30.0f) * dt;
				p.vz += 20.0f * dt;
				break;
			case Kind::Stain:
			case Kind::Debris:
				continue; // lying still on the floor (age counted above)
			case Kind::Ember:
				// rise, slow down, wander
				p.vz *= 1.0f - 0.6f * dt;
				p.vx += Rand(-40.0f, 40.0f) * dt;
				break;
			case Kind::Mote:
				p.vx += Rand(-3.0f, 3.0f) * dt;
				p.vy += Rand(-2.0f, 2.0f) * dt;
				p.vz += Rand(-3.0f, 3.0f) * dt;
				break;
		}
		p.x += p.vx * dt;
		p.y += p.vy * dt;
		p.z += p.vz * dt;
		if (p.kind == Kind::Spark && p.z < 0.0f) {
			// bounce once, dimmer
			p.z = 0.0f;
			p.vz = -p.vz * 0.3f;
			p.a *= 0.6f;
		} else if ((p.kind == Kind::Blood || p.kind == Kind::Chip) && p.z <= 0.0f) {
			Land(p);
		}
	}
	TrimDecals();
	particles.erase(std::remove_if(particles.begin(), particles.end(), [](const Particle& p) { return p.age >= p.life; }), particles.end());
	for (auto& f : flashes) f.age += dt;
	flashes.erase(std::remove_if(flashes.begin(), flashes.end(), [](const Flash& f) { return f.age >= f.life; }), flashes.end());
}

void ScenePolish::SpawnAmbient(const Map* map, const Region& vp, float dt)
{
	if (!map || dt <= 0.0f) return;

	// embers from warm glowing animations (fires, braziers)
	if (Setting("AmbientParticles", 1)) {
		for (const Emitter& e : emitters) {
			if (e.r < e.b * 1.25f || e.g > e.r * 0.95f) continue; // warm ones only
			if (!e.sprite.IntersectsRegion(vp)) continue;
			float rate = std::min(14.0f, float(e.sprite.w) / 14.0f) * std::min(1.0f, e.strength * 3.0f);
			emberDebt += rate * dt;
			while (emberDebt >= 1.0f && particles.size() < MaxParticles) {
				emberDebt -= 1.0f;
				Particle p {};
				p.kind = Kind::Ember;
				p.x = float(e.sprite.x) + float(e.sprite.w) * Rand(0.3f, 0.7f);
				p.y = float(e.sprite.y + e.sprite.h) - float(e.sprite.h) * 0.15f + Rand(-2.0f, 2.0f);
				p.z = float(e.sprite.h) * Rand(0.25f, 0.6f);
				p.vx = Rand(-10.0f, 10.0f);
				p.vy = Rand(-2.0f, 2.0f);
				p.vz = Rand(25.0f, 60.0f);
				p.life = Rand(0.9f, 2.2f);
				p.size = Rand(0.7f, 1.4f);
				p.r = 1.0f;
				p.g = Rand(0.45f, 0.7f);
				p.b = 0.15f;
				p.a = Rand(0.55f, 0.9f);
				particles.push_back(p);
			}
		}
		emberDebt = std::min(emberDebt, 1.0f);

		// floating dust / ash in the air, a fixed density over the view
		int motes = 0;
		for (const auto& p : particles) motes += p.kind == Kind::Mote;
		float density = (map->AreaType & AT_OUTDOOR) ? 22.0f : 36.0f;
		int want = int(density * float(vp.w) * float(vp.h) / (800.0f * 600.0f));
		for (int i = motes; i < want && particles.size() < MaxParticles; ++i) {
			Particle p {};
			p.kind = Kind::Mote;
			p.x = float(vp.x) + Rand(0.0f, float(vp.w));
			p.y = float(vp.y) + Rand(0.0f, float(vp.h) + 120.0f);
			p.z = Rand(8.0f, 120.0f);
			p.vx = Rand(-5.0f, 5.0f);
			p.vy = Rand(-2.5f, 2.5f);
			p.vz = Rand(-2.0f, 3.0f);
			p.life = Rand(6.0f, 13.0f);
			// fresh ones start mid-life on the first fill so the view isn't empty
			p.age = motes == 0 ? Rand(0.0f, p.life * 0.8f) : 0.0f;
			p.size = Rand(0.8f, 1.8f);
			if (map->AreaType & AT_OUTDOOR) {
				float grey = Rand(0.75f, 0.9f);
				p.r = grey;
				p.g = grey * 0.97f;
				p.b = grey * 0.92f;
				p.a = Rand(0.10f, 0.20f);
			} else {
				p.r = 1.0f;
				p.g = 0.9f;
				p.b = 0.72f;
				p.a = Rand(0.12f, 0.24f);
			}
			particles.push_back(p);
		}
		// motes that drifted far out of view are recycled
		const Region keep(vp.x - 200, vp.y - 200, vp.w + 400, vp.h + 520);
		particles.erase(std::remove_if(particles.begin(), particles.end(), [&keep](const Particle& p) {
					return p.kind == Kind::Mote && !keep.PointInside(Point(int(p.x), int(p.y)));
				}),
				particles.end());
	} else {
		particles.erase(std::remove_if(particles.begin(), particles.end(), [](const Particle& p) { return p.kind == Kind::Ember || p.kind == Kind::Mote; }), particles.end());
	}
}

bool ScenePolish::Room() const
{
	return particles.size() < MaxParticles;
}

void ScenePolish::Land(Particle& p) const
{
	float linger = float(std::max(2, std::min(600, Setting("BloodLinger", 30))));
	if (p.kind == Kind::Blood) {
		// splat: a flat stain, a little bigger than the drop, that dries darker
		p.kind = Kind::Stain;
		p.size *= Rand(1.3f, 2.4f);
		p.r *= 0.8f;
		p.a = Rand(0.6f, 0.85f);
	} else if (!p.landed) {
		// chips bounce once
		p.landed = true;
		p.z = 0.0f;
		p.vz = -p.vz * 0.3f;
		p.vx *= 0.45f;
		p.vy *= 0.45f;
		return;
	} else {
		p.kind = Kind::Debris;
	}
	p.z = 0.0f;
	p.vx = p.vy = p.vz = 0.0f;
	p.age = 0.0f;
	p.life = linger * Rand(0.85f, 1.15f);
}

void ScenePolish::TrimDecals()
{
	size_t decals = 0;
	for (const auto& p : particles) decals += p.kind == Kind::Stain || p.kind == Kind::Debris;
	if (decals <= MaxDecals) return;
	// oldest first (they were pushed earlier)
	size_t drop = decals - MaxDecals;
	particles.erase(std::remove_if(particles.begin(), particles.end(), [&drop](const Particle& p) {
				if (drop && (p.kind == Kind::Stain || p.kind == Kind::Debris)) {
					--drop;
					return true;
				}
				return false;
			}),
			particles.end());
}

void ScenePolish::AddLights(SceneLighting& out, const Region& vp) const
{
	for (const Flash& f : flashes) {
		float t = f.age / f.life;
		float k = (1.0f - t) * (1.0f - t);
		SceneLight l;
		l.x = f.x - float(vp.x);
		l.y = f.y - float(vp.y);
		l.z = f.z;
		l.radius = f.radius * (0.8f + 0.2f * t);
		l.r = f.r * k;
		l.g = f.g * k;
		l.b = f.b * k;
		out.lights.push_back(l);
	}
}

// ---------------------------------------------------------------- drawing

void ScenePolish::DrawParticles(const Region& vp) const
{
	if (!Enabled() || particles.empty()) return;
	std::vector<SoftShape> blended, added;
	blended.reserve(particles.size());
	added.reserve(particles.size());
	for (const auto& p : particles) {
		if (p.kind == Kind::Stain || p.kind == Kind::Debris) continue; // DrawGroundDecals
		float t = p.age / p.life;
		float fade;
		bool additive = false;
		switch (p.kind) {
			case Kind::Mote:
				fade = std::sin(t * 3.14159265f);
				additive = true;
				break;
			case Kind::Ember:
				fade = (1.0f - t) * (0.75f + 0.25f * std::sin(p.age * 23.0f + p.x));
				additive = true;
				break;
			case Kind::Wisp:
				fade = std::sin(t * 3.14159265f);
				additive = true;
				break;
			case Kind::Spark:
				fade = 1.0f - t * t;
				additive = true;
				break;
			case Kind::Shield:
				// snaps on, then fades out fast
				fade = std::min(1.0f, t * 12.0f) * (1.0f - t) * (1.0f - t);
				additive = true;
				break;
			case Kind::Blood:
			case Kind::Chip:
				fade = 1.0f;
				break;
			case Kind::Dust:
				fade = (1.0f - t) * std::min(1.0f, t * 8.0f + 0.3f);
				break;
			default: // Smoke
				fade = std::sin(t * 3.14159265f);
				break;
		}
		SoftShape s;
		s.profile = SoftShape::Profile::Blob;
		s.x = p.x - float(vp.x);
		s.y = p.y - float(vp.y) - p.z;
		float size = p.kind == Kind::Spark ? p.size * (1.0f - 0.5f * t) : p.size;
		s.rx = size * 1.6f;
		s.ry = size * 1.6f;
		if (p.kind == Kind::Blood || p.kind == Kind::Chip) {
			s.profile = SoftShape::Profile::Disc;
			s.rx = size;
			s.ry = size;
		}
		s.color = Color(ToByte(p.r), ToByte(p.g), ToByte(p.b), ToByte(p.a * fade));
		(additive ? added : blended).push_back(s);
	}
	if (!blended.empty()) VideoDriver->DrawSoftShapes(blended, BlitFlags::NONE);
	if (!added.empty()) VideoDriver->DrawSoftShapes(added, BlitFlags::ADD);
}

void ScenePolish::DrawGroundDecals(const Region& vp) const
{
	if (!Enabled() || particles.empty()) return;
	std::vector<SoftShape> shapes;
	for (const auto& p : particles) {
		if (p.kind != Kind::Stain && p.kind != Kind::Debris) continue;
		float t = p.age / p.life;
		float fade = t < 0.75f ? 1.0f : (1.0f - t) / 0.25f;
		SoftShape s;
		s.profile = SoftShape::Profile::Disc;
		s.x = p.x - float(vp.x);
		s.y = p.y - float(vp.y);
		if (p.kind == Kind::Stain) {
			// spreads a touch as it soaks in, dries darker
			float spread = 1.0f + 0.25f * std::min(1.0f, p.age * 2.0f);
			s.rx = p.size * 1.5f * spread;
			s.ry = s.rx * 0.5f;
			float dry = 1.0f - 0.35f * std::min(1.0f, p.age / 6.0f);
			s.color = Color(ToByte(p.r * dry), ToByte(p.g * dry), ToByte(p.b * dry), ToByte(p.a * fade));
		} else {
			s.rx = p.size;
			s.ry = p.size * 0.6f;
			s.color = Color(ToByte(p.r), ToByte(p.g), ToByte(p.b), ToByte(p.a * fade));
		}
		shapes.push_back(s);
	}
	if (!shapes.empty()) VideoDriver->DrawSoftShapes(shapes, BlitFlags::NONE);
}

void ScenePolish::DrawShadows(const std::vector<ShadowPart>& parts, const Point& feet, float lfx, float lfy,
			      float contactRadius, float alpha, const SceneLighting* lights, BlitFlags flags) const
{
	if (!Enabled() || alpha <= 0.0f) return;

	if (Setting("ContactShadows", 0)) {
		SoftShape s;
		s.profile = SoftShape::Profile::Blob;
		s.x = float(feet.x);
		s.rx = contactRadius;
		s.ry = contactRadius * 0.5f;
		// the back edge sits on the feet; the rest falls toward the camera
		s.y = float(feet.y) + s.ry * 1.15f;
		// the blob falls off as (1-d^2)^2, so a low peak disappears into the floor
		s.color = Color(0, 0, 0, ToByte(0.9f * alpha));
		VideoDriver->DrawSoftShapes({ s }, flags);
	}

	if (parts.empty() || !Setting("LightShadows", 1)) return;

	const float fy = float(feet.y);
	// height above the feet maps onto the ground along (dirX, dirY).
	// sideways casts keep a little depth so the silhouette stays readable
	auto project = [&](float dirX, float dirY, float k, float a) {
		if (a <= 0.0f) return;
		float sx = k * dirX;
		float sy = k * dirY * 0.72f - 0.15f * (1.0f - std::abs(dirY));
		uint8_t aBase = ToByte(a * alpha);
		uint8_t aTip = ToByte(a * alpha * 0.5f);
		for (const ShadowPart& part : parts) {
			if (!part.frame) continue;
			const Region& fr = part.frame->Frame;
			float x0 = float(part.pos.x - fr.x), y0 = float(part.pos.y - fr.y);
			float x1 = x0 + float(fr.w), y1 = y0 + float(fr.h);
			float corners[8];
			const float cx[4] = { x0, x1, x0, x1 };
			const float cy[4] = { y0, y0, y1, y1 };
			for (int i = 0; i < 4; ++i) {
				float h = fy - cy[i];
				corners[i * 2] = cx[i] + h * sx;
				corners[i * 2 + 1] = fy + h * sy;
			}
			const Color top(0, 0, 0, aTip), bottom(0, 0, 0, aBase);
			const Color colors[4] = { top, top, bottom, bottom };
			VideoDriver->BlitSpriteQuad(part.frame, part.palette, corners, colors, flags | BlitFlags::BLENDED);
		}
	};

	// default: painted light from up-screen, shadow toward the camera. AreaKeyLight
	// replaces that with the fitted per-area direction when the lights file has a key line.
	if (lights && lights->hasKey) {
		const float k = std::max(0.4f, std::min(1.0f, lights->keyStrength));
		project(lights->keyDir[0], lights->keyDir[1], 0.85f, 0.62f * k);
	} else {
		project(0.0f, 1.0f, 0.85f, 0.62f);
	}

	// a real fire, spell or projectile adds one more cast, away from itself
	if (!lights) return;
	float bestA = 0.0f, bestK = 0.0f, bestX = 0.0f, bestY = 0.0f;
	for (const SceneLight& l : lights->lights) {
		if (!l.castsShadow) continue;
		float dx = lfx - l.x;
		float dy = (lfy - l.y) / 0.72f;
		float dist = std::sqrt(dx * dx + dy * dy);
		if (dist < 8.0f || dist >= l.radius) continue;
		float f = 1.0f - (dist / l.radius) * (dist / l.radius);
		float intensity = f * f * (l.r + l.g + l.b) / 3.0f;
		float a = std::min(0.55f, intensity * 2.0f);
		if (a <= bestA) continue;
		bestA = a;
		bestK = std::max(0.35f, std::min(1.15f, dist / std::max(l.z, 20.0f)));
		bestX = dx / dist;
		bestY = dy / dist;
	}
	project(bestX, bestY, bestK, bestA);
}

bool ScenePolish::DrawRing(const Selectable* sel, const Point& centre, const Color& color, bool selected, bool hovered) const
{
	if (!Enabled() || !Setting("SelectionRings", 1)) return false;
	float base = float(sel->CircleSize2Radius()) * sel->sizeFactor;
	float rx = std::max(13.0f, base * 4.0f);
	float ry = rx * 0.75f;
	float pulse = hovered ? 0.82f + 0.18f * std::sin(float(GetMilliseconds() % 100000) * 0.008f) : 1.0f;

	std::vector<SoftShape> shapes;
	// dark backing ring, so it reads on bright floors
	SoftShape back;
	back.profile = SoftShape::Profile::Ring;
	back.x = float(centre.x);
	back.y = float(centre.y);
	back.rx = rx;
	back.ry = ry;
	back.ringWidth = selected ? 4.0f : 3.0f;
	back.color = Color(0, 0, 0, 70);
	shapes.push_back(back);

	SoftShape ring = back;
	ring.ringWidth = selected ? 1.8f : 1.3f;
	ring.glowWidth = selected ? 3.5f : (hovered ? 2.5f : 0.0f);
	ring.glowAlpha = selected ? 0.35f : 0.25f;
	Color c = color;
	if (selected) {
		c.r = uint8_t(std::min(255, c.r + (255 - c.r) / 4));
		c.g = uint8_t(std::min(255, c.g + (255 - c.g) / 4));
		c.b = uint8_t(std::min(255, c.b + (255 - c.b) / 4));
	}
	c.a = uint8_t(float(selected || hovered ? 235 : 190) * pulse);
	ring.color = c;
	shapes.push_back(ring);
	return VideoDriver->DrawSoftShapes(shapes, BlitFlags::NONE);
}

void ScenePolish::BuildPost(const Map* map, ScenePost& post) const
{
	if (!map) return;
	post.bloom = Setting("Bloom", 1) ? std::max(0, std::min(200, Setting("BloomStrength", 55))) / 100.0f : 0.0f;
	post.bloomThreshold = 0.70f;
	post.vignette = std::max(0, std::min(100, Setting("Vignette", 35))) / 100.0f;
	post.grade = Setting("ColorGrading", 1) != 0;
	if (!post.grade) return;
	// Sigil: smoggy rust outdoors, warm lamplight indoors, cold stone below ground
	auto set3 = [](float* d, float a, float b, float c) {
		d[0] = a;
		d[1] = b;
		d[2] = c;
	};
	if (map->AreaType & AT_DUNGEON) {
		post.saturation = 0.88f;
		post.contrast = 1.07f;
		set3(post.lift, 0.0f, 0.010f, 0.030f);
		set3(post.gain, 1.03f, 1.0f, 0.96f);
	} else if (map->AreaType & AT_OUTDOOR) {
		post.saturation = 0.94f;
		post.contrast = 1.04f;
		set3(post.lift, 0.026f, 0.014f, 0.004f);
		set3(post.gain, 1.03f, 1.0f, 0.95f);
	} else {
		post.saturation = 0.96f;
		post.contrast = 1.05f;
		set3(post.lift, 0.020f, 0.009f, 0.0f);
		set3(post.gain, 1.04f, 1.0f, 0.94f);
	}
}

// ---------------------------------------------------------------- combat maneuvers

ScenePolish::Particle ScenePolish::Burst(Kind kind, float x, float y, float z, float ang, float speed, float vz) const
{
	Particle p {};
	p.kind = kind;
	p.x = x;
	p.y = y;
	p.z = z;
	p.vx = std::cos(ang) * speed;
	p.vy = std::sin(ang) * speed * 0.5f; // the floor is seen at a slant
	p.vz = vz;
	return p;
}

static float BodyHeight(const Actor* actor)
{
	Region box = actor->DrawingRegion();
	return std::max(24.0f, std::min(100.0f, float(actor->Pos.y - box.y)));
}

void ScenePolish::SpawnDustPuff(const Point& pos)
{
	if (!Setting("HitParticles", 1)) return;
	const float gx = float(pos.x), gy = float(pos.y);
	// a fast, flat ring rolling out from the feet ...
	const int ring = 26;
	for (int i = 0; i < ring && Room(); ++i) {
		float ang = 6.2831853f * float(i) / float(ring) + Rand(-0.12f, 0.12f);
		Particle p = Burst(Kind::Dust, gx, gy, Rand(0.5f, 3.0f), ang, Rand(150.0f, 210.0f), Rand(2.0f, 10.0f));
		p.life = Rand(0.4f, 0.6f);
		p.size = Rand(2.5f, 4.0f);
		p.r = Rand(0.66f, 0.74f);
		p.g = Rand(0.58f, 0.64f);
		p.b = Rand(0.42f, 0.48f);
		p.a = 0.5f;
		particles.push_back(p);
	}
	// ... and behind it a slower, thicker cloud that settles
	for (int i = 0; i < 8 && Room(); ++i) {
		Particle p = Burst(Kind::Dust, gx + Rand(-4.0f, 4.0f), gy + Rand(-2.0f, 2.0f), Rand(1.0f, 4.0f),
				   Rand(0.0f, 6.2831853f), Rand(20.0f, 60.0f), Rand(6.0f, 16.0f));
		p.life = Rand(0.6f, 0.85f);
		p.size = Rand(4.5f, 6.5f);
		p.r = 0.68f;
		p.g = 0.6f;
		p.b = 0.45f;
		p.a = 0.4f;
		particles.push_back(p);
	}
}

void ScenePolish::SpawnSmokePuff(const Point& pos, const Point& from, bool burst)
{
	if (!Setting("HitParticles", 1)) return;
	const float gx = float(pos.x), gy = float(pos.y);
	// kicked up behind the runner; all around when standing still (the first stride)
	const float dx = float(pos.x - from.x), dy = float(pos.y - from.y) * 2.0f;
	const bool moving = dx * dx + dy * dy > 0.5f;
	const float back = moving ? std::atan2(-dy, -dx) : 0.0f;
	const int n = burst ? 16 : 6;
	for (int i = 0; i < n && Room(); ++i) {
		float ang = moving ? back + Rand(-0.9f, 0.9f) : Rand(0.0f, 6.2831853f);
		float speed = burst ? Rand(50.0f, 110.0f) : Rand(30.0f, 70.0f);
		Particle p = Burst(Kind::Smoke, gx + Rand(-3.0f, 3.0f), gy + Rand(-1.5f, 1.5f), Rand(1.0f, 4.0f), ang, speed,
				   Rand(12.0f, 30.0f));
		p.life = Rand(0.45f, 0.75f);
		p.size = burst ? Rand(3.5f, 5.5f) : Rand(2.5f, 4.0f);
		float shade = Rand(0.62f, 0.72f);
		p.r = shade;
		p.g = shade * 0.97f;
		p.b = shade * 0.92f;
		p.a = burst ? 0.5f : 0.38f;
		particles.push_back(p);
	}
}

void ScenePolish::SpawnBlockSparks(const Actor* blocker, const Actor* attacker)
{
	if (!blocker || !Setting("HitParticles", 1)) return;
	// where the blades meet: a third of the way toward the attacker, at weapon height
	const Point& b = blocker->Pos;
	const Point& a = attacker ? attacker->Pos : b;
	const float gx = float(b.x) + float(a.x - b.x) * 0.35f;
	const float gy = float(b.y) + float(a.y - b.y) * 0.35f;
	const float z = BodyHeight(blocker) * 0.6f;
	const float toward = a == b ? Rand(0.0f, 6.2831853f) : std::atan2(float(a.y - b.y) * 2.0f, float(a.x - b.x));
	// two fans glancing off to either side of the line between them, a few back at the attacker
	for (int i = 0; i < 22 && Room(); ++i) {
		float side = (i & 1) ? 1.5708f : -1.5708f;
		float ang = i < 18 ? toward + side + Rand(-0.6f, 0.6f) : toward + Rand(-0.4f, 0.4f);
		Particle p = Burst(Kind::Spark, gx, gy, z + Rand(-4.0f, 4.0f), ang, Rand(110.0f, 260.0f), Rand(20.0f, 150.0f));
		p.life = Rand(0.2f, 0.5f);
		p.size = Rand(0.6f, 1.2f);
		p.r = 1.0f;
		p.g = Rand(0.82f, 1.0f);
		p.b = Rand(0.45f, 0.75f);
		p.a = 1.0f;
		particles.push_back(p);
	}
	// the white-hot point of contact
	if (Room()) {
		Particle p = Burst(Kind::Spark, gx, gy, z, 0.0f, 0.0f, 0.0f);
		p.life = 0.1f;
		p.size = 5.0f;
		p.r = 1.0f;
		p.g = 0.97f;
		p.b = 0.85f;
		p.a = 1.0f;
		particles.push_back(p);
	}
	Flash f {};
	f.x = gx;
	f.y = gy;
	f.z = z;
	f.radius = 80.0f;
	f.r = 0.9f;
	f.g = 0.8f;
	f.b = 0.45f;
	f.life = 0.16f;
	flashes.push_back(f);
}

void ScenePolish::SpawnShieldGlow(const Actor* actor)
{
	if (!actor || !Setting("HitParticles", 1)) return;
	const float gx = float(actor->Pos.x), gy = float(actor->Pos.y);
	const float h = BodyHeight(actor);
	// an upright oval of light around the body that swells a little as it fades
	const float rx = std::max(16.0f, h * 0.38f), rz = h * 0.58f, cz = h * 0.52f;
	const int rim = 34;
	for (int i = 0; i < rim && Room(); ++i) {
		float t = 6.2831853f * float(i) / float(rim);
		Particle p {};
		p.kind = Kind::Shield;
		p.x = gx + std::cos(t) * rx;
		p.y = gy + 2.0f; // just in front of the feet
		p.z = cz + std::sin(t) * rz;
		p.vx = std::cos(t) * 14.0f;
		p.vz = std::sin(t) * 14.0f;
		p.life = Rand(0.42f, 0.5f);
		p.size = Rand(1.8f, 2.4f);
		p.r = 0.6f;
		p.g = 0.82f;
		p.b = 1.0f;
		p.a = 0.85f;
		particles.push_back(p);
	}
	// a faint wash over the middle
	for (int i = 0; i < 3 && Room(); ++i) {
		Particle p {};
		p.kind = Kind::Shield;
		p.x = gx + Rand(-3.0f, 3.0f);
		p.y = gy + 2.0f;
		p.z = cz + (float(i) - 1.0f) * rz * 0.5f;
		p.life = 0.4f;
		p.size = rx * 0.45f;
		p.r = 0.45f;
		p.g = 0.65f;
		p.b = 1.0f;
		p.a = 0.22f;
		particles.push_back(p);
	}
	Flash f {};
	f.x = gx;
	f.y = gy;
	f.z = cz;
	f.radius = 85.0f;
	f.r = 0.45f;
	f.g = 0.65f;
	f.b = 1.0f;
	f.life = 0.4f;
	flashes.push_back(f);
}

// ---------------------------------------------------------------- events

void ScenePolish::OnDamage(const Actor* target, int damage, int damagetype, bool critical)
{
	critTarget = critical ? target : nullptr;
	if (!target || damage <= 0 || !VideoDriver || !VideoDriver->SupportsSceneTransform()) return;
	const Game* game = core->GetGame();
	if (!game || target->GetCurrentArea() != game->GetCurrentArea()) return;

	float r, g, b;
	bool physical = false;
	if (damagetype & (DAMAGE_FIRE | DAMAGE_MAGICFIRE)) {
		r = 1.0f, g = 0.55f, b = 0.15f;
	} else if (damagetype & (DAMAGE_COLD | DAMAGE_MAGICCOLD)) {
		r = 0.55f, g = 0.8f, b = 1.0f;
	} else if (damagetype & DAMAGE_ELECTRICITY) {
		r = 0.7f, g = 0.85f, b = 1.0f;
	} else if (damagetype & (DAMAGE_ACID | DAMAGE_POISON)) {
		r = 0.55f, g = 1.0f, b = 0.3f;
	} else if (damagetype & DAMAGE_MAGIC) {
		r = 0.8f, g = 0.5f, b = 1.0f;
	} else {
		r = 1.0f, g = 0.85f, b = 0.55f;
		physical = true;
	}

	Region box = target->DrawingRegion();
	float height = std::max(20.0f, std::min(90.0f, float(target->Pos.y - box.y) * 0.55f));
	float gx = float(target->Pos.x), gy = float(target->Pos.y);

	// physical hits: the material effects (OnPhysicalHit) replace the old warm sparks
	if (Setting("HitParticles", 1) && !physical) {
		int n = std::max(6, std::min(22, 5 + damage / 2));
		if (critical) n = n * 3 / 2;
		for (int i = 0; i < n && particles.size() < MaxParticles; ++i) {
			Particle p {};
			p.kind = Kind::Spark;
			float ang = Rand(0.0f, 6.2831853f);
			float speed = Rand(60.0f, 170.0f);
			p.x = gx + Rand(-3.0f, 3.0f);
			p.y = gy + Rand(-2.0f, 2.0f);
			p.z = height + Rand(-6.0f, 6.0f);
			p.vx = std::cos(ang) * speed;
			p.vy = std::sin(ang) * speed * 0.6f;
			p.vz = Rand(30.0f, 150.0f);
			p.life = Rand(0.25f, 0.6f);
			p.size = Rand(0.8f, 1.5f);
			p.r = std::min(1.0f, r + 0.15f);
			p.g = std::min(1.0f, g + 0.15f);
			p.b = std::min(1.0f, b + 0.15f);
			p.a = Rand(0.7f, 1.0f);
			particles.push_back(p);
		}
		Flash f {};
		f.x = gx;
		f.y = gy;
		f.z = height;
		f.radius = std::min(150.0f, 70.0f + float(damage) * 3.0f);
		float k = critical ? 1.1f : 0.8f;
		f.r = r * k;
		f.g = g * k;
		f.b = b * k;
		f.life = critical ? 0.32f : 0.2f;
		flashes.push_back(f);
	}

	if (Setting("ImpactShake", 1)) {
		float t = 0.0f;
		if (target->InParty) {
			int maxHP = std::max(1, int(target->GetStat(IE_MAXHITPOINTS)));
			float frac = float(damage) / float(maxHP);
			if (frac >= 0.08f) t += std::min(0.6f, frac * 1.8f);
		}
		if (critical) t += 0.25f;
		if (t > 0.0f) AddTrauma(t);
	}
}

// ---------------------------------------------------------------- materials

ScenePolish::HitMaterial ScenePolish::MaterialForArmor(int armor)
{
	// PST resdata.ini "armor": the HIT_0<type><A+armor> sound set
	switch (armor) {
		case 1: return HitMaterial::Leather; // thugs, Dakkon, githzerai
		case 2: return HitMaterial::Armored; // guards, Mercykillers, Harmonium
		case 3: return HitMaterial::Stone; // golem, statues
		case 4: return HitMaterial::Bone; // Morte, skeletons
		case 6: return HitMaterial::Spirit; // Deionarra, Transcendent One
		case 7: return HitMaterial::Metal; // modrons, Nordom
		case 9: return HitMaterial::Shadow;
		case 10: return HitMaterial::Fire; // Ignus
		default: return HitMaterial::Flesh; // 0 townies, 5 fiends / zombies, 8 the Nameless One
	}
}

bool ScenePolish::MaterialFromName(const std::string& name, HitMaterial& out)
{
	static const struct {
		const char* name;
		HitMaterial m;
	} names[] = {
		{ "FLESH", HitMaterial::Flesh }, { "LEATHER", HitMaterial::Leather }, { "ARMORED", HitMaterial::Armored },
		{ "ARMORED_BONE", HitMaterial::ArmoredBone }, { "HOLLOW", HitMaterial::Hollow }, { "STONE", HitMaterial::Stone },
		{ "BONE", HitMaterial::Bone }, { "SPIRIT", HitMaterial::Spirit }, { "METAL", HitMaterial::Metal },
		{ "SHADOW", HitMaterial::Shadow }, { "FIRE", HitMaterial::Fire }
	};
	for (const auto& n : names) {
		if (stricmp(name.c_str(), n.name) == 0) {
			out = n.m;
			return true;
		}
	}
	return false;
}

ScenePolish::HitMaterial ScenePolish::MaterialOf(const Actor* actor)
{
	if (!actor) return HitMaterial::Flesh;
	unsigned int animID = actor->GetBase(IE_ANIMATION_ID);
	if (core->HasFeature(GFFlags::ONE_BYTE_ANIMID)) animID &= 0xff;

	// hitmat.2da: ANIM<id> rows refine single creatures (who is really inside the armour),
	// ARMOR<n> rows remap whole sound sets
	AutoTable table = gamedata->LoadTable("hitmat", true);
	HitMaterial m;
	auto fromTable = [&table, &m](const std::string& row) {
		if (!table) return false;
		TableMgr::index_t idx = table->GetRowIndex(row);
		return idx != TableMgr::npos && MaterialFromName(table->QueryField(idx, 0), m);
	};
	if (fromTable(fmt::format("ANIM{}", animID))) return m;

	if (const DataFileMgr* resdata = core->GetResDataINI()) {
		int armor = resdata->GetKeyAsInt(fmt::format("{}", animID), "armor", -1);
		if (armor >= 0) {
			if (fromTable(fmt::format("ARMOR{}", armor))) return m;
			return MaterialForArmor(armor);
		}
	}
	// other games: the armour animation level
	ieDword level = actor->GetStat(IE_ARMOR_TYPE);
	if (level == IE_ANI_MEDIUM_ARMOR || level == IE_ANI_HEAVY_ARMOR) return HitMaterial::Armored;
	return HitMaterial::Flesh;
}

bool ScenePolish::CustomBlood()
{
	return VideoDriver && VideoDriver->SupportsSceneTransform() && Setting("CustomBlood", 1) != 0;
}

void ScenePolish::OnPhysicalHit(const Actor* target, int severity)
{
	if (!target || !CustomBlood()) return;
	const Game* game = core->GetGame();
	if (!game || target->GetCurrentArea() != game->GetCurrentArea()) return;

	const HitMaterial mat = MaterialOf(target);
	const bool gore = severity <= 0;
	// crits are exaggerated: everything as if far more damage, plus a second spray
	const bool crit = critTarget == target;
	critTarget = nullptr;
	const float sev = (gore ? 4.0f : float(std::min(3, severity))) + (crit ? 3.0f : 0.0f);
	const float big = crit ? 0.5f : 0.0f; // extra particle size
	Region box = target->DrawingRegion();
	const float height = std::max(20.0f, std::min(90.0f, float(target->Pos.y - box.y) * 0.55f));
	const float gx = float(target->Pos.x), gy = float(target->Pos.y);
	float dir = Rand(0.0f, 6.2831853f); // main spray direction

	auto spawn = [&](Kind kind, float spreadAng, float speedLo, float speedHi, float vzLo, float vzHi) {
		Particle p {};
		p.kind = kind;
		// crits: a third of everything goes out the other side
		float ang = (crit && Rand(0.0f, 1.0f) < 0.33f ? dir + 2.6f : dir) + Rand(-spreadAng, spreadAng);
		float speed = Rand(speedLo, speedHi);
		p.x = gx + Rand(-3.0f, 3.0f);
		p.y = gy + Rand(-2.0f, 2.0f);
		p.z = height + Rand(-8.0f, 8.0f);
		p.vx = std::cos(ang) * speed;
		p.vy = std::sin(ang) * speed * 0.6f;
		p.vz = Rand(vzLo, vzHi);
		p.life = 4.0f; // until it lands
		return p;
	};

	if (Bleeds(mat)) {
		// a directional spray, a few drips straight down, a quick red mist
		int n = int(6.0f + sev * 7.0f);
		for (int i = 0; i < n && Room(); ++i) {
			// most drops land close together (a splatter), a few fly further
			bool flung = Rand(0.0f, 1.0f) < 0.25f;
			Particle p = flung ? spawn(Kind::Blood, 0.7f, 50.0f, 90.0f + sev * 15.0f, 20.0f, 110.0f)
					   : spawn(Kind::Blood, 0.9f, 8.0f, 40.0f + sev * 6.0f, -20.0f, 60.0f);
			p.size = (flung ? Rand(0.5f, 0.9f) : Rand(0.8f, 1.6f) + (gore ? 0.5f : 0.0f)) + big;
			p.r = Rand(0.42f, 0.6f);
			p.g = Rand(0.0f, 0.04f);
			p.b = Rand(0.01f, 0.04f);
			p.a = 0.95f;
			particles.push_back(p);
		}
		for (int i = 0; i < int(sev * 2.0f) && Room(); ++i) {
			Particle p = spawn(Kind::Blood, 3.2f, 0.0f, 18.0f, -10.0f, 15.0f);
			p.size = Rand(0.8f, 1.5f);
			p.r = Rand(0.4f, 0.55f);
			p.g = 0.02f;
			p.b = 0.02f;
			p.a = 0.95f;
			particles.push_back(p);
		}
		for (int i = 0; i < (crit ? 7 : 3) && Room(); ++i) {
			Particle p = spawn(Kind::Dust, 1.2f, 10.0f, 35.0f, -5.0f, 10.0f);
			p.life = Rand(0.25f, 0.45f) * (crit ? 1.6f : 1.0f);
			p.size = Rand(2.5f, 4.0f) + sev * 0.4f;
			p.r = 0.5f;
			p.g = 0.03f;
			p.b = 0.03f;
			p.a = 0.4f;
			particles.push_back(p);
		}
	}

	if (Sparks(mat)) {
		int n = int(5.0f + sev * 3.0f);
		for (int i = 0; i < n && Room(); ++i) {
			Particle p = spawn(Kind::Spark, 1.4f, 90.0f, 230.0f, 30.0f, 170.0f);
			p.life = Rand(0.15f, 0.4f);
			p.size = Rand(0.6f, 1.1f) + big * 0.5f;
			p.r = 1.0f;
			p.g = Rand(0.75f, 0.95f);
			p.b = Rand(0.35f, 0.6f);
			p.a = Rand(0.8f, 1.0f);
			particles.push_back(p);
		}
		Flash f {};
		f.x = gx;
		f.y = gy;
		f.z = height;
		f.radius = 55.0f + sev * 10.0f;
		float k = crit ? 1.6f : 1.0f;
		f.r = 0.5f * k;
		f.g = 0.4f * k;
		f.b = 0.22f * k;
		f.life = crit ? 0.22f : 0.12f;
		flashes.push_back(f);
	}

	// dust and chips that fall off and stay on the floor
	auto crumble = [&](float r, float g, float b, int chips, int puffs) {
		for (int i = 0; i < puffs && Room(); ++i) {
			Particle p = spawn(Kind::Dust, 3.2f, 8.0f, 30.0f, 3.0f, 22.0f);
			p.life = Rand(0.8f, 1.6f);
			p.size = Rand(2.5f, 4.5f);
			p.r = r * 0.9f;
			p.g = g * 0.9f;
			p.b = b * 0.9f;
			p.a = 0.32f;
			particles.push_back(p);
		}
		for (int i = 0; i < chips && Room(); ++i) {
			Particle p = spawn(Kind::Chip, 1.6f, 30.0f, 100.0f + big * 80.0f, 30.0f, 120.0f + big * 60.0f);
			p.size = Rand(0.5f, 1.2f) + big * 0.6f;
			float k = Rand(0.82f, 1.0f);
			p.r = r * k;
			p.g = g * k;
			p.b = b * k;
			p.a = 0.95f;
			particles.push_back(p);
		}
	};
	switch (mat) {
		case HitMaterial::Bone:
		case HitMaterial::ArmoredBone:
			crumble(0.9f, 0.86f, 0.74f, int(2.0f + sev * 3.0f), int(2.0f + sev));
			break;
		case HitMaterial::Stone:
			crumble(0.55f, 0.53f, 0.5f, int(2.0f + sev * 3.0f), int(2.0f + sev));
			break;
		case HitMaterial::Metal:
			crumble(0.36f, 0.38f, 0.42f, int(sev * 2.0f), 0);
			break;
		case HitMaterial::Spirit:
			for (int i = 0; i < int(6.0f + sev * 3.0f) && Room(); ++i) {
				Particle p = spawn(Kind::Wisp, 3.2f, 10.0f, 50.0f, 15.0f, 50.0f);
				p.life = Rand(0.8f, 1.5f);
				p.size = Rand(1.5f, 3.0f);
				p.r = 0.6f;
				p.g = 0.8f;
				p.b = 1.0f;
				p.a = 0.5f;
				particles.push_back(p);
			}
			break;
		case HitMaterial::Shadow:
			for (int i = 0; i < int(5.0f + sev * 2.0f) && Room(); ++i) {
				Particle p = spawn(Kind::Smoke, 3.2f, 10.0f, 40.0f, 10.0f, 30.0f);
				p.life = Rand(0.9f, 1.6f);
				p.size = Rand(3.0f, 6.0f);
				p.r = 0.03f;
				p.g = 0.02f;
				p.b = 0.05f;
				p.a = 0.45f;
				particles.push_back(p);
			}
			break;
		case HitMaterial::Fire:
			for (int i = 0; i < int(8.0f + sev * 4.0f) && Room(); ++i) {
				Particle p = spawn(Kind::Ember, 3.2f, 20.0f, 90.0f, 30.0f, 90.0f);
				p.life = Rand(0.5f, 1.2f);
				p.size = Rand(0.7f, 1.4f);
				p.r = 1.0f;
				p.g = Rand(0.45f, 0.7f);
				p.b = 0.15f;
				p.a = Rand(0.7f, 1.0f);
				particles.push_back(p);
			}
			break;
		default:
			break;
	}
}

void ScenePolish::AddTrauma(float amount)
{
	trauma = std::min(1.0f, trauma + amount);
}

bool ScenePolish::ShakeOffset(float& x, float& y)
{
	x = y = 0.0f;
	tick_t now = GetMilliseconds();
	float dt = lastShakeTick ? float(std::min<tick_t>(now - lastShakeTick, 100)) / 1000.0f : 0.0f;
	lastShakeTick = now;
	time += dt;
	trauma = std::max(0.0f, trauma - 1.6f * dt);

	float ax = 0.0f, ay = 0.0f;
	if (SmoothShake() && core->timer.IsShaking()) {
		const Point& v = core->timer.ShakeVector();
		float env = std::min(1.0f, float(core->timer.ShakeRemaining()) / 6.0f);
		ax += float(v.x) * env;
		ay += float(v.y) * env;
	}
	float tr = trauma * trauma * 6.0f;
	ax += tr;
	ay += tr;
	if (ax <= 0.01f && ay <= 0.01f) return false;
	// smooth noise: a few incommensurate sines
	const float T = time * 6.2831853f;
	x = ax * (0.6f * std::sin(T * 7.3f) + 0.4f * std::sin(T * 12.9f + 1.7f));
	y = ay * (0.6f * std::sin(T * 8.1f + 0.6f) + 0.4f * std::sin(T * 13.7f + 2.9f));
	return true;
}

}
