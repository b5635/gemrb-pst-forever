// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

// Phase 5 presentation polish, all of it drawing only (game state never sees it):
// contact and light-cast shadows, selection rings, hit sparks and impact flashes,
// ambient motes and embers, smooth / impact screen shake and the per-area post
// pass settings (bloom, grading, vignette). Only active with drivers that
// support scene transforms (VideoDriver=opengl); every part has a GemRB.cfg toggle.

#ifndef SCENEPOLISH_H
#define SCENEPOLISH_H

#include "exports.h"
#include "globals.h"

#include "Region.h"
#include "Sprite2D.h"

#include <vector>

namespace GemRB {

class Actor;
class Map;
class Palette;
class Selectable;
struct SceneLighting;
struct ScenePost;

class GEM_EXPORT ScenePolish {
public:
	struct ShadowPart {
		Holder<Sprite2D> frame;
		Holder<Palette> palette;
		Point pos; // where the frame is drawn (drawing units)
	};

	static ScenePolish& Get();

	// per frame, after the scene lights are known and before the map's objects are drawn
	void BeginFrame(const Map* map, const Region& viewport);
	// a glowing area animation seen while collecting lights (embers rise from warm ones)
	void AddFireEmitter(const Region& sprite, float r, float g, float b, float strength);
	// impact flashes as scene lights
	void AddLights(SceneLighting& out, const Region& viewport) const;

	// soft shadow under the feet plus silhouettes cast away from the strongest lights;
	// feet in drawing units, lightFeet in scene light coordinates
	void DrawShadows(const std::vector<ShadowPart>& parts, const Point& feet, float lightFeetX, float lightFeetY,
			 float contactRadius, float alpha, const SceneLighting* lights, BlitFlags flags) const;
	// returns false when the ring is not drawn this way (original circle then)
	bool DrawRing(const Selectable* sel, const Point& centre, const Color& color, bool selected, bool hovered) const;
	void DrawParticles(const Region& viewport) const;
	void BuildPost(const Map* map, ScenePost& post) const;

	// game events
	void OnDamage(const Actor* target, int damage, int damagetype, bool critical);
	void AddTrauma(float amount);
	// smooth camera shake for this frame, map units; false = none
	bool ShakeOffset(float& x, float& y);
	// script shakes are drawn by ShakeOffset instead of moving the logical viewport
	static bool SmoothShake();

	const SceneLighting* FrameLights() const { return frameLights; }
	void SetFrameLights(const SceneLighting* l) { frameLights = l; }

private:
	enum class Kind : uint8_t {
		Spark,
		Ember,
		Mote
	};
	struct Particle {
		float x, y, z; // ground point (map units) and height
		float vx, vy, vz; // map units / s
		float age, life; // s
		float size;
		float r, g, b, a;
		Kind kind;
	};
	struct Flash {
		float x, y, z, radius;
		float r, g, b;
		float age, life;
	};
	struct Emitter {
		Region sprite;
		float r, g, b, strength;
	};

	std::vector<Particle> particles;
	std::vector<Flash> flashes;
	std::vector<Emitter> emitters;
	const Map* area = nullptr;
	tick_t lastTick = 0;
	float emberDebt = 0.0f;
	float trauma = 0.0f;
	float time = 0.0f; // s, for the shake noise
	tick_t lastShakeTick = 0;
	const SceneLighting* frameLights = nullptr;

	static bool Enabled();
	void Simulate(float dt);
	void SpawnAmbient(const Map* map, const Region& viewport, float dt);
};

}

#endif
