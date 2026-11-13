// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef INTERPOLATION_H
#define INTERPOLATION_H

#include "exports.h"
#include "globals.h"

namespace GemRB {

// Frame-rate independent motion. The game state advances in fixed ticks
// (Time.ticksPerSec, 15/s by default) while frames are drawn as fast as the
// display allows. Before each tick the drawn objects remember where they were;
// frames then draw them between that and their current position, using the
// scene's per-object offset (Video::SetObjectOffset). Game logic never sees any
// of this: Pos stays the logical position. Costs one tick of display latency.
//
// Only active with video drivers that support scene transforms and with
// FrameInterpolation=1 (default) in GemRB.cfg.
class GEM_EXPORT TickInterpolation {
public:
	// called by the main loop right before every game state update
	static void BeginTick(tick_t now, tick_t interval);
	// fraction of the current tick that has passed, [0, 1]
	static float Alpha();
	static bool Enabled() { return enabled; }
	static uint32_t Serial() { return serial; }

private:
	static uint32_t serial;
	static tick_t lastTick;
	static tick_t interval;
	static bool enabled;
};

// what one drawn object remembers between ticks
struct GEM_EXPORT DrawInterpolation {
	float prevX = 0.0f;
	float prevY = 0.0f;
	uint32_t serial = 0;

	void Capture(float x, float y)
	{
		prevX = x;
		prevY = y;
		serial = TickInterpolation::Serial();
	}
	// offset from the drawn (integer) position (drawX, drawY) to where the object
	// is shown this frame, given its exact current position (x, y). False if there
	// is nothing to do (not captured this tick, not moving, a jump beyond snapDist)
	bool Offset(float x, float y, int drawX, int drawY, float snapDist, float& ox, float& oy) const;
};

}

#endif
