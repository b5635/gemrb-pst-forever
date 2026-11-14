// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

/**
 * @file CombatDirector.h
 * Turn based combat: AD&D 2e initiative order where only the active combatant acts.
 *
 * When a fight starts the director takes the creatures in it over (IF_COMBAT_OWNED):
 * GemRB stops running their scripts, actions and movement in real time. On a creature's
 * turn the director decides when its actions run, walks it with its own walker inside the
 * movement budget and plays each swing of an attack round as one animation, resolving it
 * through GemRB's rules. Everyone outside the fight keeps running in real time. When the
 * fight ends the creatures are handed back to GemRB.
 *
 * Initiative is rolled once per combat: d10 plus modifiers, lowest goes first.
 */

#ifndef COMBATDIRECTOR_H
#define COMBATDIRECTOR_H

#include "exports.h"
#include "TurnBasedCombat/CombatHud.h"
#include "ie_types.h"

#include "PathFinder.h"
#include "Region.h"

#include <string>
#include <vector>

namespace GemRB {

class Actor;
class Map;
class Scriptable;

/** What a combatant can spend in a turn, besides movement. */
enum class TBAction : uint8_t {
	Attack, // a full round of attacks (all APR)
	CastSpell,
	UseItem,
	Equip, // anything but the free quick weapon swap
	Run, // forfeits the main action; remaining movement += max movement
	Withdraw // forfeits the main action and half remaining movement; immune to attacks of opportunity
};

/** First-swing takedown: trip (fighters, -2) and knockdown (enemies, no penalty). */
enum class TakedownKind : uint8_t {
	None,
	Trip,
	Knockdown
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
	bool withdrawn = false; // immune to attacks of opportunity until next turn; walks
	bool freeWeaponSwapUsed = false;
	int movePx = 0; // remaining movement
	int maxMovePx = 0;
	// attacks this round (shared with Block); allocated at round start
	int remainingAttacks = 0;
	int blockStacks = 0; // incoming melee attacks to attempt to block, until next turn
	TakedownKind takedown = TakedownKind::None; // first swing of the next attack round
	int toHitMod = 0; // applied to the current swing (trip -2)
	bool prone = false; // knocked down until the start of its next turn
	unsigned int standTicks = 0; // standing up at turn start
	// the attack round in progress
	bool attacking = false;

	bool done = false; // had its turn this round
	bool dead = false;
	bool delayed = false; // gave its slot up this round, acts after everyone else
	bool surprised = false; // caught unaware: loses the first round
	bool reactionUsed = false; // one attack of opportunity per round

	// combat clock: the game time this combatant's effects live in while it is taken over;
	// it moves one round per turn of its own (upkeep), the world's clock keeps running
	ieDword clockTime = 0;
	int upkeepRound = 0; // the round its effects last moved on in
};

/** What the event feed reports, for the combat log, dice panel and floaters. */
enum class CombatEventType : uint8_t {
	CombatStart,
	CombatEnd,
	RoundStart,
	TurnStart,
	Swing, // an attack roll: roll, bonus, defense, hit, critical
	Damage,
	Death,
	SwingStart, // a swing begins: value is the d20 it needs, bonus the THAC0, defense the AC
	Intent, // what an AI combatant decided to do this turn
	Reaction // an attack of opportunity: actor swings at target
};

struct GEM_EXPORT CombatEvent {
	CombatEventType type = CombatEventType::TurnStart;
	ieDword actor = 0;
	ieDword target = 0;
	int round = 0;
	int roll = 0;
	int bonus = 0;
	int defense = 0;
	int value = 0; // damage dealt, or the initiative on turn start
	bool hit = false;
	bool critical = false;
	std::string text;
};

/**
 * While it lives, the game clock reads as the combat clock of the actor given (if the director
 * runs it), so its effects' durations, regeneration, poison ticks ... follow its turns.
 */
class GEM_EXPORT CombatClockScope {
public:
	explicit CombatClockScope(const Actor* actor);
	~CombatClockScope();
	CombatClockScope(const CombatClockScope&) = delete;
	CombatClockScope& operator=(const CombatClockScope&) = delete;

private:
	bool swapped = false;
	ieDword saved = 0;
};

class GEM_EXPORT CombatDirector {
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
	/** Is a fight running and not suspended? */
	bool IsRunning() const { return state == State::TurnActive; }
	/** Does the director run this actor (no real time scripts, actions or movement)? */
	static bool Owns(const Actor* actor);
	/** The combat clock of a taken over actor, 0 for everyone else */
	ieDword ClockOf(const Actor* actor) const;

	void StartCombat(Map* map);
	void EndCombat();
	/** Ends the active combatant's turn; the next member of its party group, if any, takes over. */
	void EndTurn();
	/** The active combatant gives up its slot and acts after everyone else this round. */
	bool DelayTurn();
	/** Stops the active combatant's walk where it is; the movement not walked stays. */
	bool CancelMove();

	Actor* GetActiveActor() const;
	ieDword GetActiveID() const { return activeID; }
	const std::vector<Combatant>& GetOrder() const { return order; }
	/** The combatants sharing the current turn (a party group, or just the active one) */
	std::vector<ieDword> GetActiveGroup() const
	{
		std::vector<ieDword> ids;
		for (size_t i = groupStart; i <= groupEnd && i < order.size(); ++i) {
			if (!order[i].dead) ids.push_back(order[i].globalID);
		}
		if (ids.empty() && activeID) ids.push_back(activeID);
		return ids;
	}
	/** Can the player hand the turn to this combatant now (an unfinished member of the active party group)? */
	bool IsSwitchable(ieDword globalID) const
	{
		if (state != State::TurnActive || groupEnd <= groupStart) return false;
		for (size_t i = groupStart; i <= groupEnd && i < order.size(); ++i) {
			if (order[i].globalID == globalID) return !order[i].done && !order[i].dead;
		}
		return false;
	}
	int GetRound() const { return round; }
	Combatant* FindCombatant(ieDword globalID);
	const Combatant* FindCombatant(ieDword globalID) const;
	bool IsCombatant(const Actor* actor) const;
	/** Is the active combatant in the middle of something (walking, swinging, an action)? */
	bool IsBusy(const Actor* actor) const;
	/** Is it still casting, or is a spell (or missile) it fired still on its way to its first hit or explosion? */
	bool SpellInFlight(const Actor* actor) const;
	static bool Casting(const Actor* actor);
	bool ProjectileInFlight(const Actor* actor) const;

	// action economy
	bool CanAfford(const Actor* actor, TBAction action) const;
	void Spend(const Actor* actor, TBAction action);
	int GetRemainingMovement(const Actor* actor) const;
	/** The first quick weapon swap of a turn is free, later ones take the main action. */
	bool CanSwapWeapon(const Actor* actor) const;
	void SpendWeaponSwap(const Actor* actor);

	// combat maneuvers (Run, Withdraw, Block, Trip, Knockdown)
	bool UseRun(Actor* actor);
	/** Player and companions only. The AI never withdraws. */
	bool UseWithdraw(Actor* actor);
	bool UseBlock(Actor* actor); // no action; spends one remaining attack
	bool UseTrip(Actor* actor); // first swing of the next attack round
	bool UseKnockdown(Actor* actor);
	bool CancelPendingTrip(Actor* actor); // trip armed but its target pick was dropped
	bool CanBlock(const Actor* actor) const;
	bool CanTrip(const Actor* actor) const;
	bool CanKnockdown(const Actor* actor) const;
	bool IsProne(const Actor* actor) const;
	bool IsWithdrawn(const Actor* actor) const;
	int GetRemainingAttacks(const Actor* actor) const;
	int GetBlockStacks(const Actor* actor) const;
	TakedownKind GetTakedown(const Actor* actor) const;
	int GetToHitMod(const Actor* actor) const;
	/** An incoming melee hit: consume a block stack and maybe stop the hit. attackRoll is the d20. */
	bool TryBlockHit(Actor* attacker, Actor* target, int attackRoll);

	// pure helpers, exposed for tests
	static void ApplyRun(Combatant& combatant);
	static void ApplyWithdraw(Combatant& combatant);
	static bool ApplyBlock(Combatant& combatant);
	static int TakedownPenalty(TakedownKind kind);

	// hooks from GemRB's actions, for owned actors
	/** AttackCore has the target in reach: run (or refuse) a round of swings. */
	void RequestAttackRound(Actor* attacker, Scriptable* target);
	/** A path was asked for: path it now, clipped to the movement left, for our walker. */
	void RequestPath(Actor* actor, const Point& source, const Point& destination, int minDistance, int flags);
	/** The path a walk from where the actor stands to destination takes. The preview line and the
	 *  walk itself both come from here, so what is drawn is what gets walked. */
	Path PlanPath(const Actor* actor, const Point& destination, unsigned int minDistance) const;
	/** Pin the path a walk to destination will take (the preview's, clipped to where it stops). */
	void KeepPlan(const Actor* actor, const Point& destination, unsigned int minDistance, const Path& path) const;

	/** The event feed; the GUI drains it. */
	std::vector<CombatEvent> TakeEvents();
	void PushEvent(CombatEvent event);
	/** The drawn dice panel */
	const CombatHud& GetHud() const { return hud; }

	// pure helpers, exposed for tests
	/** true if a acts before b */
	static bool ActsBefore(const Combatant& a, const Combatant& b);
	static void SortByInitiative(std::vector<Combatant>& combatants);
	/** inserts at the initiative position and returns the index used */
	static size_t InsertByInitiative(std::vector<Combatant>& combatants, const Combatant& newcomer);
	static void ResetBudget(Combatant& combatant, int movePx);
	/** the part of the path a budget of movement covers, ending exactly where the budget runs out */
	static Path ClipPath(const Point& start, const Path& path, int budget);

private:
	/** Where the active combatant's turn stands. */
	enum class Step : uint8_t {
		Begin, // effects, skip checks, AI decision
		Act, // runs its actions; walking and swinging are their own steps
		Walk, // our walker moves it
		Swing, // an attack animation plays
		Reaction, // someone's attack of opportunity interrupts the walk
		Over // nothing left this turn
	};

	State state = State::Inactive;
	Map* combatMap = nullptr;
	std::vector<Combatant> order;
	size_t activeIdx = 0;
	ieDword activeID = 0;
	// the party group sharing the current turn, a single combatant otherwise
	size_t groupStart = 0;
	size_t groupEnd = 0;
	int round = 0;
	unsigned int savedZoom = 0; // zoom to restore after the fight, 0 if untouched
	unsigned int guiTicks = 0;

	// the active turn
	Step step = Step::Begin;
	unsigned int stallTicks = 0; // ticks its actions ran without walking, swinging or finishing
	unsigned int flightTicks = 0; // ticks it waited for its spell to land
	bool endRequested = false; // the player ended the turn while its spell was still flying
	int decisions = 0; // AI script passes this turn
	bool roundDone = false; // it finished an attack round this turn
	bool wantedMore = false; // it asked for movement or an attack the budget didn't cover
	// the last planned walk; the preview plans, the walk reuses it while nothing has moved
	struct PlannedPath {
		ieDword actorID = 0;
		Point from;
		Point destination;
		unsigned int minDistance = 0;
		Path path;
		bool Matches(const Actor* actor, const Point& dest) const;
	};
	mutable PlannedPath plan;
	// the walk the player committed to: taken whatever range the move action asks for
	mutable PlannedPath committed;
	// where its last walk got stuck without moving, and where that walk was headed
	Point blockedAt { -1, -1 };
	Point blockedDest { -1, -1 };
	// the swing in progress
	ieDword swingTarget = 0;
	bool swingResolved = false;
	bool swingRanged = false;
	int swingLastFrame = -1;
	unsigned int swingTicks = 0;
	unsigned int swingPause = 0; // the beat between two swings of a round
	unsigned int swingWindup = 0; // standing ready, squaring up, before the swing animation
	bool swingPausing = false;
	// the attack of opportunity in progress
	ieDword reactorID = 0;
	std::vector<ieDword> pendingReactors;
	// the defender playing a block animation against the swing in progress
	ieDword blockerID = 0;
	bool blockerFrozen = false;
	bool blockSucceeded = false;

	std::vector<CombatEvent> events;
	CombatHud hud;
	bool reactionSettling = false; // the reaction swing is over, its dice still revealing

	bool ShouldStartCombat(const Map* map) const;
	bool ShouldEndCombat() const;
	bool IsHostileCombatant(const Combatant& combatant) const;
	bool ShouldJoin(const Actor* actor, const std::vector<Actor*>& party) const;
	Combatant MakeCombatant(Actor* actor) const;
	void AddJoiners(bool midRound);
	void ReactToProvocations();
	/** Slots one creature into the order and takes it over */
	void Join(Actor* actor, bool midRound);

	// takeover and handback
	void TakeOver(Actor* actor, Combatant& combatant);
	void HandBack(Actor* actor, Combatant* combatant);
	void TakeOverAll();
	void HandBackAll();

	/** Starts the turn of the combatant at idx, together with its party group */
	void BeginTurn(size_t idx);
	/** Hands control to one combatant of the current group */
	void ActivateMember(size_t idx);
	/** Lets the player pick which party group member acts next, by selecting it */
	void FollowGroupSelection();
	void AdvanceTurn();
	void EndRound();
	void RefreshDeaths();
	void NotifyGUI() const;

	// the turn sequence
	void RunTurn(Actor* actor);
	void BeginStep(Actor* actor, Combatant& combatant);
	void ActStep(Actor* actor, Combatant& combatant);
	void WalkStep(Actor* actor, Combatant& combatant);
	void SwingStep(Actor* actor, Combatant& combatant);
	void StartSwing(Actor* actor, Actor* target);
	void BeginSwingAnimation(Actor* actor);
	void FinishRound(Actor* actor, Combatant& combatant);
	bool Decide(Actor* actor, Combatant& combatant);
	bool TacticsFallback(Actor* actor);
	/** Upkeep: the actor's effects live through one more round of its combat clock */
	void Upkeep(Actor* actor, Combatant& combatant);
	/** Attacks of opportunity: enemies the mover just walked out of reach of get a swing */
	bool CheckOpportunityAttacks(Actor* mover, const std::vector<ieDword>& threatenedBy);
	std::vector<ieDword> ThreatsTo(const Actor* mover) const;
	void ReactionStep(Actor* mover);
	/** Is the player's turn over by itself (auto end turn)? */
	bool PlayerTurnOver(const Actor* actor, const Combatant& combatant) const;

	void AllocateAttacks(Combatant& combatant, Actor* actor);
	void ApplyMovementFlags(Actor* actor, const Combatant& combatant) const;
	void ChooseAIManeuvers(Actor* actor, Combatant& combatant);
	void CloseOnEnemy(Actor* actor, Actor* enemy);
	void StartBlockAnimation(Actor* attacker, Actor* target);
	void FinishBlockAnimation(const Actor* attacker, Actor* target, bool blocked);
	void KnockProne(Actor* target, Combatant& combatant);
	void StandUp(Actor* actor, Combatant& combatant);
	bool ResolveTakedown(Actor* attacker, Actor* target, TakedownKind kind);
	static bool HasFighterClass(const Actor* actor);
	static bool IsMorte(const Actor* actor);
};

}

#endif
