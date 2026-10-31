// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "TurnBasedCombat/TurnManager.h"

#include "ie_stats.h"

#include "Game.h"
#include "GameData.h"
#include "Interface.h"
#include "Item.h"
#include "Map.h"
#include "RNG.h"

#include "GUI/GameControl.h"
#include "Logging/Logging.h"
#include "Scriptable/Actor.h"

#include <algorithm>

namespace GemRB {

// an AI turn can't take longer than this many ticks, in case a script never settles
static constexpr unsigned int AI_TURN_TIMEOUT = 8 * 15;
// how long an AI combatant has to stay idle before we consider its turn over
static constexpr unsigned int AI_IDLE_TICKS = 10;
// grace period, so the AI gets a script evaluation in before we check for idleness
static constexpr unsigned int AI_MIN_TURN_TICKS = 16;
// camera pan speed on turn change, same as dialog uses
static constexpr int TURN_CAMERA_SPEED = 30;
// pause between the swings of an attack round, so each attack animation plays out
static constexpr unsigned int SWING_TICKS = 20;
// an AI combatant that neither moved nor acted for this long is done
static constexpr unsigned int AI_STUCK_TICKS = 30;
// how often the combat gui gets refreshed even without a turn change
static constexpr unsigned int GUI_REFRESH_TICKS = 8;

bool TurnManager::IsEnabled()
{
	return core->GetDictionary().Get("Turn Based Combat", 1) != 0;
}

bool TurnManager::ActsBefore(const Combatant& a, const Combatant& b)
{
	if (a.initiative != b.initiative) return a.initiative < b.initiative;
	if (a.dexterity != b.dexterity) return a.dexterity > b.dexterity;
	if (a.isPC != b.isPC) return a.isPC;
	return a.globalID < b.globalID;
}

void TurnManager::SortByInitiative(std::vector<Combatant>& combatants)
{
	std::stable_sort(combatants.begin(), combatants.end(), ActsBefore);
}

size_t TurnManager::InsertByInitiative(std::vector<Combatant>& combatants, const Combatant& newcomer)
{
	auto pos = std::upper_bound(combatants.begin(), combatants.end(), newcomer, ActsBefore);
	return std::distance(combatants.begin(), combatants.insert(pos, newcomer));
}

void TurnManager::ResetBudget(Combatant& combatant, int movePx)
{
	combatant.mainActionUsed = false;
	combatant.ran = false;
	combatant.freeWeaponSwapUsed = false;
	combatant.attacking = false;
	combatant.lastSwingTick = 0;
	combatant.movePx = movePx;
	combatant.maxMovePx = movePx;
}

// how far the actor would walk in a round of real time
static int MovementAllowance(const Actor* actor)
{
	int walkScale = actor->CalculateSpeed(false);
	if (walkScale <= 0) return 0;
	int percent = core->GetDictionary().Get("Turn Based Movement Percent", 100);
	return int(core->Time.round_size * gamedata->GetStepTime() / walkScale) * percent / 100;
}

static bool IsAliveCombatant(const Actor* actor)
{
	return actor && !(actor->GetStat(IE_STATE_ID) & STATE_DEAD) && actor->ValidTarget(GA_NO_DEAD);
}

// the living party members standing in this area
static std::vector<Actor*> PartyOnMap(const Map* map)
{
	std::vector<Actor*> party;
	const Game* game = core->GetGame();
	for (int i = 0; i < game->GetPartySize(false); ++i) {
		Actor* pc = game->GetPC(i, false);
		if (pc && pc->GetCurrentArea() == map && IsAliveCombatant(pc)) {
			party.push_back(pc);
		}
	}
	return party;
}

Combatant TurnManager::MakeCombatant(Actor* actor) const
{
	Combatant combatant;
	combatant.globalID = actor->GetGlobalID();
	combatant.isPC = actor->InParty != 0;
	combatant.dexterity = int(actor->GetStat(IE_DEX));
	combatant.roll = RAND(1, 10);

	int initiative = combatant.roll;
	// a better reaction adjustment lowers the roll
	initiative -= core->GetDexterityBonus(STAT_DEX_REACTION, combatant.dexterity);
	if (core->GetDictionary().Get("Turn Based Weapon Speed", 1)) {
		bool leftOrRight = false;
		const ITMExtHeader* header = actor->GetWeapon(leftOrRight);
		if (header) initiative += header->Speed;
	}
	ieDword state = actor->GetStat(IE_STATE_ID);
	if (state & STATE_HASTED) initiative -= 2;
	if (state & STATE_SLOWED) initiative += 2;
	combatant.initiative = initiative;

	ResetBudget(combatant, MovementAllowance(actor));
	Log(COMBAT, "TurnManager", "{} rolls initiative {} (d10: {})", fmt::WideToChar { actor->GetShortName() }, initiative, combatant.roll);
	return combatant;
}

Combatant* TurnManager::FindCombatant(ieDword globalID)
{
	for (auto& combatant : order) {
		if (combatant.globalID == globalID) return &combatant;
	}
	return nullptr;
}

const Combatant* TurnManager::FindCombatant(ieDword globalID) const
{
	for (const auto& combatant : order) {
		if (combatant.globalID == globalID) return &combatant;
	}
	return nullptr;
}

bool TurnManager::IsCombatant(const Actor* actor) const
{
	return actor && FindCombatant(actor->GetGlobalID()) != nullptr;
}

Actor* TurnManager::GetActiveActor() const
{
	// the combat map may have been unloaded since the last update
	if (!IsActive() || !combatMap || core->GetGame()->GetCurrentArea() != combatMap) return nullptr;
	return combatMap->GetActorByGlobalID(activeID);
}

bool TurnManager::IsFrozen(const Actor* actor) const
{
	if (state != State::TurnActive || !actor) return false;
	// only the fight is turn based
	if (actor->GetCurrentArea() != combatMap) return false;
	return actor->GetGlobalID() != activeID;
}

bool TurnManager::ShouldStartCombat(const Map* map) const
{
	const Game* game = core->GetGame();
	if (game->PartyAttack) return true;
	if (!core->GetDictionary().Get("Turn Based Start On Sight", 1)) return false;

	const std::vector<Actor*> party = PartyOnMap(map);
	for (const Actor* actor : map->GetAllActors()) {
		if (actor->GetStat(IE_EA) < EA_EVILCUTOFF) continue;
		if (!IsAliveCombatant(actor) || !actor->Schedule(game->GameTime, true)) continue;
		if (!map->IsVisible(actor->Pos)) continue;
		for (const Actor* pc : party) {
			if (WithinRange(pc, actor->Pos, pc->GetVisualRange()) && map->IsVisibleLOS(pc->Pos, actor->Pos)) {
				return true;
			}
		}
	}
	return false;
}

bool TurnManager::ShouldJoin(const Actor* actor, const std::vector<Actor*>& party) const
{
	if (actor->InParty || !IsAliveCombatant(actor)) return false;
	if (!actor->Schedule(core->GetGame()->GameTime, true)) return false;

	ieDword ea = actor->GetStat(IE_EA);
	bool hostile = ea >= EA_EVILCUTOFF;
	bool ally = ea <= EA_GOODCUTOFF;
	bool targeted = false;
	for (const Actor* pc : party) {
		if (pc->objects.LastTarget == actor->GetGlobalID() || actor->objects.LastTarget == pc->GetGlobalID()) {
			targeted = true;
			break;
		}
	}
	if (!hostile && !ally && !targeted) return false;

	for (const Actor* pc : party) {
		if (targeted || WithinRange(pc, actor->Pos, pc->GetVisualRange())) {
			return true;
		}
	}
	return false;
}

void TurnManager::StartCombat(Map* map)
{
	combatMap = map;
	order.clear();
	round = 1;

	const std::vector<Actor*> party = PartyOnMap(map);
	if (party.empty()) {
		combatMap = nullptr;
		return;
	}

	for (Actor* pc : party) {
		order.push_back(MakeCombatant(pc));
	}
	for (Actor* actor : map->GetAllActors()) {
		if (!ShouldJoin(actor, party)) continue;
		Combatant combatant = MakeCombatant(actor);
		combatant.provoked = actor->GetStat(IE_EA) < EA_EVILCUTOFF && actor->GetStat(IE_EA) > EA_GOODCUTOFF;
		order.push_back(combatant);
	}
	SortByInitiative(order);

	Log(MESSAGE, "TurnManager", "Turn based combat starts with {} combatants", order.size());
	state = State::TurnActive;

	// optional closer camera for the fight, 100 means no change
	GameControl* gc = core->GetGameControl();
	unsigned int zoom = core->GetDictionary().Get("Turn Based Camera Zoom", 100);
	if (gc && zoom != 100) {
		savedZoom = gc->GetScalePercent();
		gc->SetScalePercent(zoom);
	}
	BeginTurn(0);
}

void TurnManager::EndCombat()
{
	if (!IsActive()) return;
	Log(MESSAGE, "TurnManager", "Turn based combat ends after {} rounds", round);
	state = State::Inactive;
	order.clear();
	activeID = 0;
	activeIdx = 0;
	combatMap = nullptr;

	GameControl* gc = core->GetGameControl();
	if (gc && savedZoom) {
		gc->SetScalePercent(savedZoom);
	}
	savedZoom = 0;
	NotifyGUI();
}

void TurnManager::BeginTurn(size_t idx)
{
	groupStart = groupEnd = idx;
	if (idx >= order.size()) {
		activeIdx = idx;
		activeID = 0;
		return;
	}

	// party members next to each other in the order share their turn and act in any order
	if (order[idx].isPC && core->GetDictionary().Get("Turn Based Party Groups", 1)) {
		while (groupEnd + 1 < order.size() && order[groupEnd + 1].isPC && !order[groupEnd + 1].dead && !order[groupEnd + 1].done) {
			++groupEnd;
		}
	}
	for (size_t i = groupStart; i <= groupEnd; ++i) {
		const Actor* member = combatMap->GetActorByGlobalID(order[i].globalID);
		ResetBudget(order[i], member ? MovementAllowance(member) : 0);
	}
	ActivateMember(idx);
}

void TurnManager::ActivateMember(size_t idx)
{
	activeIdx = idx;
	turnTicks = 0;
	idleTicks = 0;

	Combatant& combatant = order[idx];
	activeID = combatant.globalID;
	Actor* actor = combatMap->GetActorByGlobalID(activeID);
	if (!actor) {
		combatant.dead = true;
		AdvanceTurn();
		return;
	}
	stuckTicks = 0;
	lastActivePos = actor->Pos;
	Log(COMBAT, "TurnManager", "Round {}: {}'s turn (initiative {})", round, fmt::WideToChar { actor->GetShortName() }, combatant.initiative);

	// get the AI to think right away instead of waiting for its staggered update
	actor->ImmediateEvent();

	Game* game = core->GetGame();
	if (actor->InParty) {
		game->SelectActor(actor, true, SELECT_REPLACE);
	}
	GameControl* gc = core->GetGameControl();
	if (gc && game->GetCurrentArea() == combatMap) {
		gc->MoveViewportTo(actor->Pos, true, TURN_CAMERA_SPEED);
	}
	NotifyGUI();
}

void TurnManager::AdvanceTurn()
{
	if (activeIdx < order.size()) {
		order[activeIdx].done = true;
	}
	// first the rest of the party group, in any order the player picked
	for (size_t i = groupStart; i <= groupEnd && i < order.size(); ++i) {
		if (!order[i].dead && !order[i].done) {
			ActivateMember(i);
			return;
		}
	}
	for (size_t i = groupEnd + 1; i < order.size(); ++i) {
		if (!order[i].dead && !order[i].done) {
			BeginTurn(i);
			return;
		}
	}
	EndRound();
}

void TurnManager::EndTurn()
{
	if (state != State::TurnActive) return;
	AdvanceTurn();
}

void TurnManager::EndRound()
{
	Game* game = core->GetGame();
	// the world catches up by exactly one round, so effect durations and timers count in rounds
	game->AdvanceTime(core->Time.round_size);
	++round;

	// the dead stay out, everyone else gets a new round
	order.erase(std::remove_if(order.begin(), order.end(), [](const Combatant& c) { return c.dead; }), order.end());
	for (auto& combatant : order) {
		combatant.done = false;
	}
	activeIdx = groupStart = groupEnd = 0;
	AddJoiners(false);

	if (ShouldEndCombat()) {
		EndCombat();
		return;
	}
	for (size_t i = 0; i < order.size(); ++i) {
		if (!order[i].dead) {
			BeginTurn(i);
			return;
		}
	}
	EndCombat();
}

void TurnManager::AddJoiners(bool midRound)
{
	const std::vector<Actor*> party = PartyOnMap(combatMap);
	for (Actor* actor : combatMap->GetAllActors()) {
		if (IsCombatant(actor)) continue;
		bool joins = actor->InParty ? IsAliveCombatant(actor) : ShouldJoin(actor, party);
		if (!joins) continue;
		Combatant combatant = MakeCombatant(actor);
		size_t idx = InsertByInitiative(order, combatant);
		// their slot already passed this round, so they start next round
		if (midRound && idx <= groupEnd) {
			order[idx].done = true;
			if (idx <= activeIdx) ++activeIdx;
			if (idx <= groupStart) ++groupStart;
			++groupEnd;
		}
		Log(COMBAT, "TurnManager", "{} joins the fight", fmt::WideToChar { actor->GetShortName() });
	}
}

bool TurnManager::IsHostileCombatant(const Combatant& combatant) const
{
	if (combatant.dead) return false;
	const Actor* actor = combatMap->GetActorByGlobalID(combatant.globalID);
	if (!IsAliveCombatant(actor)) return false;
	if (actor->GetStat(IE_EA) >= EA_EVILCUTOFF) return true;
	if (!combatant.provoked) return false;

	// a provoked neutral only keeps the fight going while the party is around
	const std::vector<Actor*> party = PartyOnMap(combatMap);
	return std::any_of(party.begin(), party.end(), [actor](const Actor* pc) {
		return WithinRange(pc, actor->Pos, pc->GetVisualRange());
	});
}

bool TurnManager::ShouldEndCombat() const
{
	if (!combatMap || core->GetGame()->GetCurrentArea() != combatMap) return true;
	return std::none_of(order.begin(), order.end(), [this](const Combatant& c) { return IsHostileCombatant(c); });
}

void TurnManager::RefreshDeaths()
{
	for (auto& combatant : order) {
		if (combatant.dead) continue;
		const Actor* actor = combatMap->GetActorByGlobalID(combatant.globalID);
		if (!IsAliveCombatant(actor)) {
			combatant.dead = true;
			NotifyGUI();
		}
	}
}

bool TurnManager::IsTurnOver(const Actor* actor)
{
	++turnTicks;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return true;

	bool busy = actor->GetCurrentAction() || actor->GetNextAction() || actor->InMove() || combatant->attacking;
	idleTicks = busy ? 0 : idleTicks + 1;
	bool spent = combatant->mainActionUsed && combatant->movePx <= 0;

	// player characters end their turn themselves, unless there is nothing left to do
	if (actor->InParty) {
		bool autoEnd = core->GetDictionary().Get("Turn Based Auto End Turn", 1);
		return autoEnd && spent && idleTicks >= AI_IDLE_TICKS;
	}

	if (turnTicks >= AI_TURN_TIMEOUT) {
		Log(COMBAT, "TurnManager", "{} took too long, ending its turn", fmt::WideToChar { actor->GetShortName() });
		return true;
	}
	if (turnTicks < AI_MIN_TURN_TICKS) return false;
	if (spent && !combatant->attacking) return true;

	// scripts that keep asking for what the budget won't allow never go idle
	if (actor->Pos == lastActivePos && !combatant->attacking) {
		++stuckTicks;
	} else {
		stuckTicks = 0;
		lastActivePos = actor->Pos;
	}
	if (stuckTicks >= AI_STUCK_TICKS) return true;

	return idleTicks >= AI_IDLE_TICKS;
}

void TurnManager::Update()
{
	Game* game = core->GetGame();
	if (!game) return;

	if (!IsEnabled()) {
		EndCombat();
		return;
	}

	Map* area = game->GetCurrentArea();
	if (state == State::Inactive) {
		if (area && !core->InCutSceneMode() && ShouldStartCombat(area)) {
			StartCombat(area);
		}
		return;
	}

	// the party left (or the map went away), so did the fight
	if (area != combatMap) {
		EndCombat();
		return;
	}

	// keep the combat music and the rest checks going
	game->CombatCounter = 150;

	// cutscenes and dialogs play out in real time
	const GameControl* gc = core->GetGameControl();
	bool interrupted = core->InCutSceneMode() || (gc && gc->InDialog());
	if (interrupted) {
		state = State::Suspended;
		return;
	}
	if (state == State::Suspended) {
		state = State::TurnActive;
		AddJoiners(true);
		NotifyGUI();
	}

	// hit points, movement and busy state change all the time, keep the gui roughly in sync
	if (++guiTicks % GUI_REFRESH_TICKS == 0) {
		NotifyGUI();
	}

	RefreshDeaths();
	if (ShouldEndCombat()) {
		EndCombat();
		return;
	}

	FollowGroupSelection();

	const Actor* actor = GetActiveActor();
	if (!actor || !IsAliveCombatant(actor)) {
		AdvanceTurn();
		return;
	}
	if (IsTurnOver(actor)) {
		AdvanceTurn();
	}
}

void TurnManager::FollowGroupSelection()
{
	if (groupEnd <= groupStart) return;
	const Game* game = core->GetGame();
	if (game->selected.size() != 1 || game->selected[0]->GetGlobalID() == activeID) return;

	// don't switch in the middle of someone's move or attack
	const Actor* active = GetActiveActor();
	const Combatant* current = FindCombatant(activeID);
	if (active && (active->InMove() || active->GetCurrentAction() || active->GetNextAction() || (current && current->attacking))) {
		return;
	}

	ieDword wanted = game->selected[0]->GetGlobalID();
	for (size_t i = groupStart; i <= groupEnd && i < order.size(); ++i) {
		if (order[i].globalID == wanted && !order[i].done && !order[i].dead) {
			ActivateMember(i);
			return;
		}
	}
}

bool TurnManager::CanAfford(const Actor* actor, TBAction action) const
{
	if (state != State::TurnActive || !actor) return true;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return true;
	if (actor->GetGlobalID() != activeID) return false;

	switch (action) {
		case TBAction::Run:
		case TBAction::Attack:
		case TBAction::CastSpell:
		case TBAction::UseItem:
		case TBAction::Equip:
			return !combatant->mainActionUsed && !combatant->ran;
	}
	return false;
}

void TurnManager::Spend(const Actor* actor, TBAction action)
{
	if (state != State::TurnActive || !actor) return;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return;

	if (action == TBAction::Run) {
		combatant->ran = true;
		combatant->movePx += combatant->maxMovePx;
		combatant->maxMovePx *= 2;
	}
	combatant->mainActionUsed = true;
	NotifyGUI();
}

bool TurnManager::CanSwapWeapon(const Actor* actor) const
{
	if (state != State::TurnActive || !actor) return true;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return true;
	if (actor->GetGlobalID() != activeID) return false;
	return !combatant->freeWeaponSwapUsed || CanAfford(actor, TBAction::Equip);
}

void TurnManager::SpendWeaponSwap(const Actor* actor)
{
	if (state != State::TurnActive || !actor) return;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return;
	if (!combatant->freeWeaponSwapUsed) {
		combatant->freeWeaponSwapUsed = true;
		NotifyGUI();
	} else {
		Spend(actor, TBAction::Equip);
	}
}

void TurnManager::SpendMovement(const Actor* actor, int px)
{
	if (state != State::TurnActive || !actor) return;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return;
	combatant->movePx = std::max(0, combatant->movePx - px);
}

void TurnManager::DriveAttack(Actor* attacker)
{
	Combatant* combatant = FindCombatant(attacker->GetGlobalID());
	ieDword gameTime = core->GetGame()->GameTime;
	if (!HaltsTime() || !combatant) {
		attacker->PerformAttack(gameTime);
		return;
	}

	auto finishRound = [attacker, combatant]() {
		combatant->attacking = false;
		attacker->SetStance(IE_ANI_READY);
		attacker->ReleaseCurrentAction();
	};

	if (!combatant->attacking) {
		if (!CanAfford(attacker, TBAction::Attack)) {
			attacker->SetStance(IE_ANI_READY);
			attacker->ReleaseCurrentAction();
			return;
		}
		Spend(attacker, TBAction::Attack);
		combatant->attacking = true;
		// one action is one full 2e round of attacks; this also alternates 3/2 APR
		attacker->InitRound(gameTime);
	} else if (turnTicks - combatant->lastSwingTick < SWING_TICKS) {
		return;
	}

	if (attacker->attackcount <= 0) {
		finishRound();
		return;
	}

	int attacksLeft = attacker->attackcount;
	attacker->PerformAttack(gameTime, true);
	combatant->lastSwingTick = turnTicks;
	if (attacker->attackcount == attacksLeft) {
		// it couldn't swing (target gone, weapon unusable ...), so the round is lost
		finishRound();
	}
}

int TurnManager::GetRemainingMovement(const Actor* actor) const
{
	if (!actor) return 0;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant ? combatant->movePx : 0;
}

void TurnManager::NotifyGUI() const
{
	core->SetEventFlag(EF_TURNORDER);
}

}
