// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

/**
 * @file CombatAnalyzer.h
 * Turn based combat: reads a creature's compiled script (without running it) and sums up how
 * it fights. PST has no AI engine of its own, every fight is a scripted reaction, so this is
 * what the director's tactics consult (and what the dump tool reports on every script).
 */

#ifndef COMBATANALYZER_H
#define COMBATANALYZER_H

#include "exports.h"

#include "Resource.h"

#include <map>
#include <string>
#include <vector>

namespace GemRB {

class Script;

enum class CombatArchetype : uint8_t {
	None, // no combat blocks
	Brute, // attacks
	Guard, // attacks, calls for help, turns hostile
	Coward, // flees (and calls for help), never attacks
	FightThenFlee, // attacks, flees when hurt
	Caller, // summons reinforcements
	Caster // casts scripted spells (often a step counter)
};

struct GEM_EXPORT CombatProfile {
	ResRef script;
	bool found = false;
	int blocks = 0;
	int combatBlocks = 0;

	bool engages = false;
	bool casts = false;
	bool flees = false;
	bool helps = false;
	bool turnsHostile = false;
	bool summons = false;
	bool talks = false;
	bool swapsScript = false;
	bool stepCounter = false; // casts gated by a Global/Internal counter
	int fleeBelowHP = -1; // HPPercentLT threshold guarding a flee, -1 if none

	std::vector<std::string> spells; // in script order
	// time-taking actions in combat blocks the director has no specific rule for, by count
	std::map<std::string, int> unmapped;
	// how often each action/trigger shows up in combat blocks
	std::map<std::string, int> actions;
	std::map<std::string, int> triggers;

	CombatArchetype archetype = CombatArchetype::None;
};

class GEM_EXPORT CombatAnalyzer {
public:
	/** Analyzes a script resource (cached per resref) */
	static const CombatProfile& Analyze(const ResRef& script);
	/** Analyzes an already parsed script */
	static CombatProfile Analyze(const ResRef& name, const Script* script);
	static const char* ArchetypeName(CombatArchetype archetype);

	// name tables, lower case action/trigger names without parameters
	static bool IsAttack(const std::string& action);
	static bool IsCast(const std::string& action);
	static bool IsFlee(const std::string& action);
	static bool IsWait(const std::string& action);
	/** an action the director runs with a specific turn rule (or that takes no time) */
	static bool IsMapped(const std::string& action, bool instant);
	static bool IsCombatTrigger(const std::string& trigger);
	static CombatArchetype Classify(const CombatProfile& profile);
};

}

#endif
