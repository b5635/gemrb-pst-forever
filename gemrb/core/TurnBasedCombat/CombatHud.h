// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#ifndef TURNBASED_COMBATHUD_H
#define TURNBASED_COMBATHUD_H

#include "exports.h"
#include "globals.h"

#include "Region.h"
#include "Video/Video.h"

#include <string>
#include <vector>

namespace GemRB {

struct CombatEvent;
class Font;

/**
 * Drawn combat presentation: the d20 that spins while a swing winds up and settles on the
 * real roll, then reveals the sum step by step (roll, + modifier, =, result, Hit/Miss).
 * Pure presentation: the director only asks whether it should hold the next swing so the
 * reveal can finish.
 */
class GEM_EXPORT CombatHud {
public:
	/** Fed by the director's event feed (SwingStart, Swing, CombatEnd). */
	void OnEvent(const CombatEvent& event, const String& attacker, const String& target);
	/** A swing result is still being revealed: the director waits before the next swing. */
	bool Holding() const;
	void Reset();
	/** The dice panel, in screen coordinates of the game control. */
	void Draw(const Region& screen) const;

	// drawing kit shared with the hover panel
	struct Theme {
		static const Color panel;
		static const Color border;
		static const Color borderDark;
		static const Color text;
		static const Color textDim;
		static const Color hit;
		static const Color miss;
		static const Color crit;
		static const Color fumble;
	};
	/** a dark panel with a bronze double border */
	static void DrawPanel(const Region& r, float alpha = 1.0f);
	/** stroke drawn digits and + - = %; returns the width used */
	static int DrawStrokeText(const std::string& text, const Point& topLeft, int height, const Color& color);
	static int StrokeTextWidth(const std::string& text, int height);
	/** the game's dialogue font, the text font as a fallback */
	static Holder<Font> HudFont();
	/** one icosahedron, face 'face' (1-20) towards the viewer when spin is 0 */
	static void DrawD20(const Point& center, float radius, float time, float settle, int face, const Color& tint, float alpha);

	/** A saving throw was rolled: a little die spins over the creature, then a sound for the result */
	static void NotifySave(ieDword actor, int roll, bool success);
	/** Combat text over a creature: stays a few seconds, white, slight random drift, stacked so they don't overlap. */
	static void NotifyFloater(ieDword actor, String text);
	/** Save dice and combat text, in map space with overhead text (just above the head). */
	static void DrawWorldOverlays();

private:
	struct Roll {
		bool active = false;
		String attacker;
		String target;
		tick_t start = 0;
		bool hasResult = false;
		tick_t resultAt = 0;
		int roll = 0;
		int modifier = 0;
		int needs = 0; // the total that hits
		int damage = 0;
		bool hit = false;
		bool critical = false;
		bool reaction = false;
		int spinFace = 1; // what shows while it spins
	};
	Roll roll;

	float Scale() const; // combat speed
	tick_t LandStart() const;
	tick_t Landed() const;
	tick_t VerdictAt() const;
};

}

#endif
