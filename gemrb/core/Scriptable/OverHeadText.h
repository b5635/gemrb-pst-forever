// SPDX-FileCopyrightText: 2023 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef OVERHEADTEXT_H
#define OVERHEADTEXT_H

#include "exports.h"
#include "globals.h"

#include <vector>

namespace GemRB {

struct OverHeadMsg {
	Point pos { -1, -1 };
	Point scrollOffset { -1, -1 };
	Color color = ColorBlack;
	tick_t timeStartDisplaying = 0;
	tick_t minDuration = 0;
	String text;

	bool Draw(int heightOffset, const Point& fallbackPos, int ownerType);
};

class GEM_EXPORT OverHeadText {
	bool isDisplaying = false;
	const Scriptable* owner = nullptr;
	// the first message is reserved for regular overhead text
	// all the rest are used only in pst by either:
	// - actors (full queue at same position) or
	// - areas (disparate messages at different positions)
	std::vector<OverHeadMsg> messages { 1 };

public:
	static constexpr tick_t DefaultDurationMs = 6000;

	explicit OverHeadText(const Scriptable* head)
		: owner(head) {};
	const String& GetText(size_t idx = 0) const;
	void SetText(String newText, bool display = true, bool append = true, const Color& newColor = ColorBlack);
	bool Empty(size_t idx = 0) const { return messages[idx].text.empty(); }
	bool IsDisplaying() const { return isDisplaying; }
	bool Display(bool show, size_t idx = 0);
	// Keep this showing at least `ms` (the default 6s floor still applies).
	void SetMinDuration(tick_t ms, size_t idx = 0);
	static tick_t DurationAtLeast(tick_t voiceMs);
	void FixPos(const Point& pos, size_t idx = 0);
	int GetHeightOffset() const;
	void Draw();
};

}

#endif
