// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "ScenePolish.h"

#include "damages.h"
#include "ie_stats.h"

#include "Game.h"
#include "GlobalTimer.h"
#include "Interface.h"
#include "Map.h"

#include "Scriptable/Actor.h"
#include "Scriptable/Selectable.h"
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

	constexpr size_t MaxParticles = 1500;
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
		}
	}
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
		particles.erase(std::remove_if(particles.begin(), particles.end(), [](const Particle& p) { return p.kind != Kind::Spark; }), particles.end());
	}
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
	std::vector<SoftShape> shapes;
	shapes.reserve(particles.size());
	for (const auto& p : particles) {
		float t = p.age / p.life;
		float fade;
		switch (p.kind) {
			case Kind::Mote:
				fade = std::sin(t * 3.14159265f);
				break;
			case Kind::Ember:
				fade = (1.0f - t) * (0.75f + 0.25f * std::sin(p.age * 23.0f + p.x));
				break;
			default:
				fade = 1.0f - t * t;
				break;
		}
		SoftShape s;
		s.profile = SoftShape::Profile::Blob;
		s.x = p.x - float(vp.x);
		s.y = p.y - float(vp.y) - p.z;
		float size = p.kind == Kind::Spark ? p.size * (1.0f - 0.5f * t) : p.size;
		s.rx = size * 1.6f;
		s.ry = size * 1.6f;
		s.color = Color(ToByte(p.r), ToByte(p.g), ToByte(p.b), ToByte(p.a * fade));
		shapes.push_back(s);
	}
	VideoDriver->DrawSoftShapes(shapes, BlitFlags::ADD);
}

void ScenePolish::DrawShadows(const std::vector<ShadowPart>& parts, const Point& feet, float lfx, float lfy,
			      float contactRadius, float alpha, const SceneLighting* lights, BlitFlags flags) const
{
	if (!Enabled() || alpha <= 0.0f) return;

	if (Setting("ContactShadows", 1)) {
		SoftShape s;
		s.profile = SoftShape::Profile::Blob;
		s.x = float(feet.x);
		s.y = float(feet.y) + 1.0f;
		s.rx = contactRadius;
		s.ry = contactRadius * 0.45f;
		s.color = Color(0, 0, 0, ToByte(0.5f * alpha));
		VideoDriver->DrawSoftShapes({ s }, flags);
	}

	if (!lights || parts.empty() || !Setting("LightShadows", 1)) return;

	// the two lights that light the feet the most
	struct Cast {
		float dirX, dirY, k, a;
	};
	Cast best[2] = { { 0, 0, 0, 0 }, { 0, 0, 0, 0 } };
	for (const SceneLight& l : lights->lights) {
		float dx = lfx - l.x;
		float dy = (lfy - l.y) / 0.72f;
		float dist = std::sqrt(dx * dx + dy * dy);
		if (dist >= l.radius || dist < 18.0f) continue; // out of reach / our own light
		float f = 1.0f - (dist / l.radius) * (dist / l.radius);
		float intensity = f * f * (l.r + l.g + l.b) / 3.0f;
		if (intensity < 0.04f) continue;
		Cast c { dx / dist, dy / dist, std::max(0.35f, std::min(1.15f, dist / std::max(l.z, 20.0f))), std::min(0.42f, intensity * 1.3f) };
		if (c.a > best[0].a) {
			best[1] = best[0];
			best[0] = c;
		} else if (c.a > best[1].a) {
			best[1] = c;
		}
	}

	const float fy = float(feet.y);
	for (const Cast& c : best) {
		if (c.a <= 0.0f) continue;
		// height above the feet maps onto the ground away from the light;
		// sideways casts keep a little depth so the silhouette stays readable
		float sx = c.k * c.dirX;
		float sy = c.k * c.dirY * 0.72f - 0.15f * (1.0f - std::abs(c.dirY));
		uint8_t aBase = ToByte(c.a * alpha);
		uint8_t aTip = ToByte(c.a * alpha * 0.3f);
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
	}
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

// ---------------------------------------------------------------- events

void ScenePolish::OnDamage(const Actor* target, int damage, int damagetype, bool critical)
{
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

	if (Setting("HitParticles", 1)) {
		int n = std::max(6, std::min(22, 5 + damage / 2));
		if (critical) n = n * 3 / 2;
		if (physical) n = n * 2 / 3;
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
		float k = physical ? 0.35f : 0.8f;
		if (critical) k += 0.3f;
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
