// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "TurnBasedCombat/CombatAnalyzer.h"

#include "ie_types.h"

#include "GameScript/GSUtils.h"
#include "GameScript/GameScript.h"
#include "Logging/Logging.h"

#include <algorithm>
#include <cctype>
#include <unordered_map>
#include <unordered_set>

namespace GemRB {

static std::string Bare(std::string name)
{
	size_t paren = name.find('(');
	if (paren != std::string::npos) name.resize(paren);
	std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
	return name;
}

static std::string ActionNameOf(unsigned short id)
{
	if (!actionsTable) return {};
	return Bare(actionsTable->GetValue(id));
}

static std::string TriggerNameOf(unsigned short id)
{
	if (!triggersTable) return {};
	std::string name = triggersTable->GetValue(id);
	if (name.empty()) name = triggersTable->GetValue(id | 0x4000);
	return Bare(name);
}

static bool StartsWith(const std::string& s, const char* prefix)
{
	return s.rfind(prefix, 0) == 0;
}

bool CombatAnalyzer::IsAttack(const std::string& a)
{
	// all of these go through AttackCore, so the director plays them as attack rounds
	return StartsWith(a, "attack") || StartsWith(a, "runningattack") || a == "groupattack" || a == "forceattack";
}

bool CombatAnalyzer::IsCast(const std::string& a)
{
	return StartsWith(a, "spell") || StartsWith(a, "forcespell") || StartsWith(a, "reallyforcespell") || StartsWith(a, "useitem");
}

bool CombatAnalyzer::IsFlee(const std::string& a)
{
	return StartsWith(a, "runawayfrom") || a == "panic";
}

bool CombatAnalyzer::IsWait(const std::string& a)
{
	return a == "wait" || a == "smallwait" || a == "waitrandom" || a == "noaction";
}

bool CombatAnalyzer::IsMapped(const std::string& a, bool instant)
{
	if (instant) return true;
	if (IsAttack(a) || IsCast(a) || IsFlee(a) || IsWait(a)) return true;
	static const std::unordered_set<std::string> walking = {
		"movetopoint", "movetoobject", "movetoobjectnointerrupt", "movetopointnointerrupt", "movetopointnorecticle",
		"movetooffset", "movetosavedlocation", "movetoobjectfollow", "runtopoint", "runtoobject", "runtopointnorecticle",
		"escapearea", "escapeareadestroy", "escapeareanosee", "escapeareaobject", "escapeareamove", "randomwalk",
		"randomwalkcontinuous", "randomfly", "fly", "escapearearunning", "timedmovetopoint"
	};
	static const std::unordered_set<std::string> others = {
		"dialogue", "dialog", "startdialogue", "startdialog", "startdialoguenoset", "startdialognoset", "startdialogoverride",
		"startdialogueoverride", "startdialogueinterrupt", "polymorph", "polymorphcopy", "changeaiscript", "continue",
		"destroyself", "playdead", "playdeadinterruptable", "hide", "protectobject", "protectpoint", "follow", "followobjectformation",
		// short animations and facing: they play out inside the turn
		"faceobject", "face", "playsequence", "setanimstate", "enablefogdither", "enablespritedither"
	};
	return walking.count(a) || others.count(a);
}

bool CombatAnalyzer::IsCombatTrigger(const std::string& t)
{
	static const std::unordered_set<std::string> combat = {
		"see", "attackedby", "help", "die", "died", "hppercentlt", "hplt", "hitby", "heard", "attacked", "targetunreachable",
		"combatcounter", "combatcountergt", "combatcounterlt", "nearestenemyof", "allegiance", "hpgt", "hppercentgt",
		"spellcast", "spellcastonme", "morale", "moralelt", "moralegt", "delay", "seeing"
	};
	return combat.count(t) != 0;
}

CombatArchetype CombatAnalyzer::Classify(const CombatProfile& p)
{
	if (!p.combatBlocks) return CombatArchetype::None;
	if (p.casts && (p.stepCounter || !p.engages)) return CombatArchetype::Caster;
	if (p.engages && p.flees && p.fleeBelowHP >= 0) return CombatArchetype::FightThenFlee;
	if (p.flees && !p.engages) return CombatArchetype::Coward;
	if (p.summons && !p.engages) return CombatArchetype::Caller;
	if (p.engages && p.helps && p.turnsHostile) return CombatArchetype::Guard;
	if (p.engages) return CombatArchetype::Brute;
	if (p.summons) return CombatArchetype::Caller;
	if (p.casts) return CombatArchetype::Caster;
	return CombatArchetype::None;
}

const char* CombatAnalyzer::ArchetypeName(CombatArchetype archetype)
{
	switch (archetype) {
		case CombatArchetype::None:
			return "none";
		case CombatArchetype::Brute:
			return "brute";
		case CombatArchetype::Guard:
			return "guard";
		case CombatArchetype::Coward:
			return "coward";
		case CombatArchetype::FightThenFlee:
			return "fight-then-flee";
		case CombatArchetype::Caller:
			return "caller";
		case CombatArchetype::Caster:
			return "caster";
	}
	return "?";
}

CombatProfile CombatAnalyzer::Analyze(const ResRef& name, const Script* script)
{
	CombatProfile p;
	p.script = name;
	if (!script) return p;
	p.found = true;

	for (const auto& block : script->responseBlocks) {
		if (!block) continue;
		++p.blocks;

		std::vector<std::string> triggers;
		bool combatTrigger = false;
		bool counterGate = false;
		int hpGate = -1;
		if (block->condition) {
			for (const auto& trigger : block->condition->triggers) {
				if (!trigger) continue;
				std::string t = TriggerNameOf(trigger->triggerID);
				triggers.push_back(t);
				combatTrigger |= IsCombatTrigger(t);
				if (StartsWith(t, "global") || StartsWith(t, "internal") || StartsWith(t, "local")) counterGate = true;
				if (t == "hppercentlt" || t == "hplt") hpGate = trigger->int0Parameter;
			}
		}

		struct Seen {
			std::string name;
			bool instant;
			const Action* action;
		};
		std::vector<Seen> actions;
		bool fights = false;
		bool reacts = false;
		if (block->responseSet) {
			for (const auto& response : block->responseSet->responses) {
				if (!response) continue;
				for (const auto& action : response->actions) {
					if (!action) continue;
					std::string a = ActionNameOf(action->actionID);
					bool instant = (actionflags[action->actionID] & AF_INSTANT) != 0 || (actionflags[action->actionID] & AF_MASK) == AF_IMMEDIATE;
					actions.push_back({ a, instant, action.get() });
					fights |= IsAttack(a) || IsCast(a);
					reacts |= IsFlee(a) || a == "help" || a == "shout" || a == "enemy" || a == "changeenemyally" || StartsWith(a, "createcreature");
				}
			}
		}

		if (!fights && !(reacts && combatTrigger)) continue;
		++p.combatBlocks;
		for (const auto& t : triggers) {
			++p.triggers[t];
		}
		for (const Seen& seen : actions) {
			const std::string& a = seen.name;
			++p.actions[a];
			if (IsAttack(a)) p.engages = true;
			if (IsCast(a)) {
				p.casts = true;
				if (counterGate) p.stepCounter = true;
				std::string spell = seen.action->resref0Parameter.IsEmpty() ? std::to_string(seen.action->int0Parameter) : std::string(seen.action->resref0Parameter.c_str());
				if (std::find(p.spells.begin(), p.spells.end(), spell) == p.spells.end()) p.spells.push_back(spell);
			}
			if (IsFlee(a)) {
				p.flees = true;
				if (hpGate >= 0) p.fleeBelowHP = std::max(p.fleeBelowHP, hpGate);
			}
			if (a == "help" || a == "shout" || a == "globalshout") p.helps = true;
			if (a == "enemy" || a == "changeenemyally") p.turnsHostile = true;
			if (StartsWith(a, "createcreature")) p.summons = true;
			if (StartsWith(a, "dialog") || StartsWith(a, "startdialog")) p.talks = true;
			if (a == "changeaiscript") p.swapsScript = true;
			if (!IsMapped(a, seen.instant)) ++p.unmapped[a];
		}
	}
	p.archetype = Classify(p);
	return p;
}

const CombatProfile& CombatAnalyzer::Analyze(const ResRef& script)
{
	static std::unordered_map<std::string, CombatProfile> cache;
	std::string key = script.c_str();
	auto it = cache.find(key);
	if (it != cache.end()) return it->second;

	CombatProfile profile;
	if (!script.IsEmpty() && !IsStar(script)) {
		GameScript loaded(script, nullptr);
		profile = Analyze(script, loaded.GetScript());
	}
	return cache.emplace(key, std::move(profile)).first->second;
}

}
