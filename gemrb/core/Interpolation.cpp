// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "Interpolation.h"

#include "Interface.h"

#include "Video/Video.h"

#include <algorithm>
#include <cmath>

namespace GemRB {

uint32_t TickInterpolation::serial = 0;
tick_t TickInterpolation::lastTick = 0;
tick_t TickInterpolation::interval = 66;
bool TickInterpolation::enabled = false;

void TickInterpolation::BeginTick(tick_t now, tick_t tickInterval)
{
	++serial;
	if (serial == 0) ++serial; // 0 means "never captured"
	lastTick = now;
	interval = std::max<tick_t>(tickInterval, 1);
	enabled = VideoDriver && VideoDriver->SupportsSceneTransform() && core->GetDictionary().Get("FrameInterpolation", 1) != 0;
}

float TickInterpolation::Alpha()
{
	tick_t now = GetMilliseconds();
	if (now <= lastTick) return 0.0f;
	return std::min(1.0f, float(now - lastTick) / float(interval));
}

bool DrawInterpolation::Offset(float x, float y, int drawX, int drawY, float snapDist, float& ox, float& oy) const
{
	ox = oy = 0.0f;
	if (!TickInterpolation::Enabled() || serial != TickInterpolation::Serial()) return false;
	float dx = x - prevX;
	float dy = y - prevY;
	if (dx == 0.0f && dy == 0.0f && x == float(drawX) && y == float(drawY)) return false;
	if (std::abs(dx) > snapDist || std::abs(dy) > snapDist) return false; // teleport, area change...
	float a = TickInterpolation::Alpha();
	ox = prevX + dx * a - float(drawX);
	oy = prevY + dy * a - float(drawY);
	return ox != 0.0f || oy != 0.0f;
}

}
