// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

/**
 * @file TurnManager.h
 * Turn based combat: AD&D 2e initiative order where only the active combatant acts.
 *
 * While a fight runs, every actor but the active combatant is frozen (the same gate
 * Time Stop uses), the world clock stops and only advances by a full round once
 * every combatant had its turn. Initiative is rolled once per combat: d10 plus
 * modifiers, lowest goes first.
 */

#ifndef TURNMANAGER_H
#define TURNMANAGER_H

#include "exports.h"
#include "ie_types.h"

#include "Region.h"

#include <vector>

namespace GemRB {

class Actor;
class Map;

/** What a combatant can spend in a turn, besides movement. */
enum class TBAction : uint8_t {
	Attack, // a full round of attacks (all APR)
	CastSpell,
	UseItem,
	Equip, // anything but the free quick weapon swap
	Run // forfeits the main action for double movement
};

struct GEM_EXPORT Combatant {
	ieDword globalID = 0;
	int roll = 0; // the raw d10
	int initiative = 0; // roll + modifiers, lower goes first
	int dexterity = 0;
	bool isPC = false;
	// the party attacked a neutral, so it counts as hostile while it lives
	bool provoked = false;

	// per turn budget
	bool mainActionUsed = false;
	bool ran = false;
	bool freeWeaponSwapUsed = false;
	int movePx = 0; // remaining movement
	int maxMovePx = 0;
	// the attack round in progress
	bool attacking = false;
	unsigned int lastSwingTick = 0;

	bool done = false; // had its turn this round
	bool dead = false;
};

class GEM_EXPORT TurnManager {
public:
	enum class State : uint8_t {
		Inactive, // real time
		TurnActive, // someone is acting
		Suspended // dialog or cutscene interrupted the fight
	};

	/** Is the feature switched on in the config? */
	static bool IsEnabled();

	/** Runs once per game tick, after the area scripts. */
	void Update();

	bool IsActive() const { return state != State::Inactive; }
	/** Does the world clock stand still (combat running and not suspended)? */
	bool HaltsTime() const { return state == State::TurnActive; }
	/** Is this actor waiting for its turn? */
	bool IsFrozen(const Actor* actor) const;

	void StartCombat(Map* map);
	void EndCombat();
	/** Ends the active combatant's turn. */
	void EndTurn();

	Actor* GetActiveActor() const;
	ieDword GetActiveID() const { return activeID; }
	const std::vector<Combatant>& GetOrder() const { return order; }
	int GetRound() const { return round; }
	Combatant* FindCombatant(ieDword globalID);
	const Combatant* FindCombatant(ieDword globalID) const;
	bool IsCombatant(const Actor* actor) const;

	// action economy
	bool CanAfford(const Actor* actor, TBAction action) const;
	void Spend(const Actor* actor, TBAction action);
	void SpendMovement(const Actor* actor, int px);
	int GetRemainingMovement(const Actor* actor) const;
	/** The first quick weapon swap of a turn is free, later ones take the main action. */
	bool CanSwapWeapon(const Actor* actor) const;
	void SpendWeaponSwap(const Actor* actor);
	/** Runs the attacker's round of attacks: all APR swings, paced, then the action ends. */
	void DriveAttack(Actor* attacker);

	// pure helpers, exposed for tests
	/** true if a acts before b */
	static bool ActsBefore(const Combatant& a, const Combatant& b);
	static void SortByInitiative(std::vector<Combatant>& combatants);
	/** inserts at the initiative position and returns the index used */
	static size_t InsertByInitiative(std::vector<Combatant>& combatants, const Combatant& newcomer);
	static void ResetBudget(Combatant& combatant, int movePx);

private:
	State state = State::Inactive;
	Map* combatMap = nullptr;
	std::vector<Combatant> order;
	size_t activeIdx = 0;
	ieDword activeID = 0;
	// the party group sharing the current turn, a single combatant otherwise
	size_t groupStart = 0;
	size_t groupEnd = 0;
	int round = 0;
	unsigned int turnTicks = 0;
	unsigned int idleTicks = 0;
	unsigned int stuckTicks = 0;
	Point lastActivePos;
	unsigned int savedZoom = 0; // zoom to restore after the fight, 0 if untouched
	unsigned int guiTicks = 0;

	bool ShouldStartCombat(const Map* map) const;
	bool ShouldEndCombat() const;
	bool IsHostileCombatant(const Combatant& combatant) const;
	bool ShouldJoin(const Actor* actor, const std::vector<Actor*>& party) const;
	Combatant MakeCombatant(Actor* actor) const;
	void AddJoiners(bool midRound);
	/** Starts the turn of the combatant at idx, together with its party group */
	void BeginTurn(size_t idx);
	/** Hands control to one combatant of the current group */
	void ActivateMember(size_t idx);
	/** Lets the player pick which party group member acts next, by selecting it */
	void FollowGroupSelection();
	void AdvanceTurn();
	void EndRound();
	bool IsTurnOver(const Actor* actor);
	void RefreshDeaths();
	void NotifyGUI() const;
};

}

#endif
