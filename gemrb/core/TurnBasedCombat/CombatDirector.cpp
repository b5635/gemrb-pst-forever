// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "TurnBasedCombat/CombatDirector.h"
#include "TurnBasedCombat/CombatAnalyzer.h"

#include "ie_stats.h"
#include "damages.h"

#include "DisplayMessage.h"
#include "Game.h"
#include "GameData.h"
#include "Geometry.h"
#include "Interface.h"
#include "Item.h"
#include "Map.h"
#include "Projectile.h"
#include "RNG.h"
#include "ScenePolish.h"

#include "Audio/Playback.h"
#include "CharAnimations.h"
#include "GUI/GameControl.h"
#include "GameScript/GSUtils.h"
#include "GameScript/GameScript.h"
#include "Logging/Logging.h"
#include "Scriptable/Actor.h"

#include <algorithm>
#include <cctype>
#include <unordered_map>

namespace GemRB {

// camera pan speed on turn change (map pixels per tick); faster than dialog's 75
static constexpr int TURN_CAMERA_SPEED = 120;
// how often the combat gui gets refreshed even without a turn change
static constexpr unsigned int GUI_REFRESH_TICKS = 8;
// safety net: actions that neither walk, swing nor finish for this long end an AI turn
static constexpr unsigned int STALL_TICKS = 4 * 15;
// longest wait for a spell to land before the turn moves on anyway
static constexpr unsigned int FLIGHT_MAX_TICKS = 10 * 15;
// safety net: an attack animation that never reports its end
static constexpr unsigned int SWING_MAX_TICKS = 4 * 15;
// a player character that has nothing left to do ends its turn after this many idle ticks
static constexpr unsigned int PLAYER_IDLE_TICKS = 8;
// script passes an AI gets per turn when a pass only ran instant actions
static constexpr int MAX_DECISIONS = 3;

static unsigned int playerIdleTicks = 0;

static bool Setting(const char* name, int fallback)
{
	return core->GetDictionary().Get(StringView(name), fallback) != 0;
}

static void PlayCombatSound(const Actor* actor, const char* resRef)
{
	if (!actor) return;
	core->GetAudioPlayback().Play(StringView(resRef), AudioPreset::Spatial, SFXChannel::Actions, actor->Pos);
}

static void ShowFloater(Actor* actor, String text)
{
	if (!actor || !Setting("Turn Based Floating Text", 1)) return;
	CombatHud::NotifyFloater(actor->GetGlobalID(), std::move(text));
}

// party members are the player's, unless "Turn Based Party AI" lets the AI play them (autotest)
static bool PlayerControlled(const Actor* actor)
{
	return actor->InParty && !Setting("Turn Based Party AI", 0);
}

// "Turn Based Combat Speed" in percent: 100 is normal, 200 twice as fast.
// ticks are at that normal speed; the game steps at 15 per second.
static unsigned int AtCombatSpeed(unsigned int ticks)
{
	int speed = std::max(10, int(core->GetDictionary().Get(StringView("Turn Based Combat Speed"), 100)));
	return ticks * 100u / unsigned(speed);
}

// the frame of an attack animation the blow lands on: halfway through
static int SwingHitFrame(int frames)
{
	if (frames <= 1) return 0;
	return frames / 2;
}

// standing ready between two swings of a round: 6 ticks is 0.4 s
static unsigned int SwingPauseTicks()
{
	return AtCombatSpeed(6);
}

// A takedown is the attack animation itself: early frames at half speed (the pull-back),
// then the strike at 2.2x. There is no pause before the animation starts.
static constexpr float TAKEDOWN_CHAMBER = 0.5f;
static constexpr float TAKEDOWN_PUNCH = 2.2f;
static Point walkFrom;
static Point walkDest;
// the walk in progress: movement before it, what its whole (clipped) path costs, and the
// unrounded ground covered so far, so the bill matches the preview's to the unit
static int walkBudget = 0;
static int walkCost = 0;
static Point walkEnd;
static float walkSpent = 0;

bool CombatDirector::IsEnabled()
{
	return core->GetDictionary().Get("Turn Based Combat", 1) != 0;
}

bool CombatDirector::CombatVisionEnabled()
{
	return Setting("Turn Based Combat Vision", 1);
}

bool CombatDirector::ShouldGrantCombatVision(bool enabled, bool enemyAndAlive)
{
	return enabled && enemyAndAlive;
}

bool CombatDirector::IsEnemyEA(ieDword ea)
{
	return ea >= EA_EVILCUTOFF;
}

bool CombatDirector::IsNeutralEA(ieDword ea)
{
	return ea > EA_GOODCUTOFF && ea < EA_EVILCUTOFF;
}

bool CombatDirector::AreEnemies(ieDword eaA, ieDword eaB)
{
	if (IsNeutralEA(eaA) || IsNeutralEA(eaB)) return false;
	return (eaA <= EA_GOODCUTOFF) != (eaB <= EA_GOODCUTOFF);
}

bool CombatDirector::GrantsCombatVision(const Actor* actor) const
{
	if (!IsActive() || !actor) return false;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return false;
	return ShouldGrantCombatVision(CombatVisionEnabled(), IsEnemyCombatant(*combatant));
}

bool CombatDirector::RevealCombatVision(Map* map) const
{
	if (!map || map != combatMap || !IsActive() || !CombatVisionEnabled()) return false;
	bool explored = false;
	for (const auto& combatant : order) {
		if (!ShouldGrantCombatVision(true, IsEnemyCombatant(combatant))) continue;
		Actor* actor = map->GetActorByGlobalID(combatant.globalID);
		if (!actor) continue;
		explored |= map->ExploreTile(FogPoint(actor->Pos));
		if (!actor->GetAnims()) continue;
		int vis = std::max(2, int(actor->GetVisualRange()));
		explored |= map->ExploreMapChunk(actor->SMPos, vis + actor->GetAnims()->GetCircleSize(), 1, false);
	}
	return explored;
}

bool CombatDirector::Owns(const Actor* actor)
{
	return actor && (actor->GetInternalFlag() & IF_COMBAT_OWNED);
}

ieDword CombatDirector::ClockOf(const Actor* actor) const
{
	if (!Owns(actor)) return 0;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant ? combatant->clockTime : 0;
}

CombatClockScope::CombatClockScope(const Actor* actor)
{
	Game* game = core->GetGame();
	if (!game || !actor || !CombatDirector::Owns(actor)) return;
	ieDword clock = game->combat.ClockOf(actor);
	if (!clock) return;
	saved = game->GameTime;
	game->GameTime = clock;
	swapped = true;
}

CombatClockScope::~CombatClockScope()
{
	if (swapped) core->GetGame()->GameTime = saved;
}

bool CombatDirector::ActsBefore(const Combatant& a, const Combatant& b)
{
	if (a.initiative != b.initiative) return a.initiative < b.initiative;
	if (a.dexterity != b.dexterity) return a.dexterity > b.dexterity;
	if (a.isPC != b.isPC) return a.isPC;
	return a.globalID < b.globalID;
}

void CombatDirector::SortByInitiative(std::vector<Combatant>& combatants)
{
	std::stable_sort(combatants.begin(), combatants.end(), ActsBefore);
}

size_t CombatDirector::InsertByInitiative(std::vector<Combatant>& combatants, const Combatant& newcomer)
{
	auto pos = std::upper_bound(combatants.begin(), combatants.end(), newcomer, ActsBefore);
	return std::distance(combatants.begin(), combatants.insert(pos, newcomer));
}

void CombatDirector::ResetBudget(Combatant& combatant, int movePx)
{
	combatant.mainActionUsed = false;
	combatant.ran = false;
	combatant.withdrawn = false;
	combatant.freeWeaponSwapUsed = false;
	combatant.attacking = false;
	combatant.takedown = TakedownKind::None;
	combatant.toHitMod = 0;
	combatant.blockStacks = 0;
	combatant.standTicks = 0;
	combatant.movePx = movePx;
	combatant.maxMovePx = movePx;
}

void CombatDirector::ApplyRun(Combatant& combatant)
{
	combatant.ran = true;
	combatant.mainActionUsed = true;
	combatant.movePx += combatant.maxMovePx;
}

void CombatDirector::ApplyWithdraw(Combatant& combatant)
{
	combatant.withdrawn = true;
	combatant.mainActionUsed = true;
	combatant.movePx /= 2;
}

bool CombatDirector::ApplyBlock(Combatant& combatant)
{
	if (combatant.remainingAttacks <= 0) return false;
	--combatant.remainingAttacks;
	++combatant.blockStacks;
	return true;
}

int CombatDirector::TakedownPenalty(TakedownKind kind)
{
	return kind == TakedownKind::Trip ? -2 : 0;
}

String CombatDirector::TakedownResultText(TakedownKind kind, bool success)
{
	return fmt::format(u"{}: {}", kind == TakedownKind::Knockdown ? u"Knockdown" : u"Trip",
			   success ? u"Success" : u"Failure");
}

unsigned char CombatDirector::ProneAnimStance(bool hasGetUp)
{
	return hasGetUp ? IE_ANI_GET_UP : IE_ANI_DIE;
}

bool CombatDirector::ProneFallReversed(bool hasGetUp)
{
	return hasGetUp;
}

bool CombatDirector::ProneRiseReversed(bool hasGetUp)
{
	return !hasGetUp;
}

bool CombatDirector::HasGetUpAnimation(const Actor* actor)
{
	return actor && actor->GetAnims() && actor->GetAnims()->HasGetUpAnimation();
}

void CombatDirector::PlayProneAnimation(Actor* actor, bool rising)
{
	if (!actor) return;
	const bool hasGetUp = HasGetUpAnimation(actor);
	actor->SetStance(ProneAnimStance(hasGetUp));
	actor->SetStancePlayback(rising ? ProneRiseReversed(hasGetUp) : ProneFallReversed(hasGetUp));
}

Path CombatDirector::ClipPath(const Point& start, const Path& path, int budget)
{
	Path clipped;
	if (budget <= 0) return clipped;
	Point prev = start;
	for (size_t i = 0; i < path.Size(); ++i) {
		PathNode node = path.GetStep(i);
		const int leg = PathFinder::MovementCost(prev, node.point);
		if (leg <= budget) {
			prev = node.point;
			budget -= leg;
			clipped.AppendStep(std::move(node));
			continue;
		}
		// the budget runs out on this leg: stop where it does
		const float_t t = float_t(budget) / float_t(leg);
		// truncated toward the start, so the stop never costs more than the budget
		Point stop(prev.x + int((node.point.x - prev.x) * t), prev.y + int((node.point.y - prev.y) * t));
		if (stop != prev) {
			node.point = stop;
			clipped.AppendStep(std::move(node));
		}
		break;
	}
	return clipped;
}

// PST treats a missing runscale as "no run animation" (RUN remaps to WALK).
static bool HasRunAnim(const Actor* actor)
{
	if (!actor) return true;
	ieDword animid = actor->GetBase(IE_ANIMATION_ID);
	if (core->HasFeature(GFFlags::ONE_BYTE_ANIMID)) {
		animid &= 0xff;
	}
	if (animid >= ieDword(CharAnimations::GetAvatarsCount())) return true;
	return CharAnimations::GetAvatarStruct(animid).RunScale != 0;
}

static bool PartyAlwaysRuns(const Actor* actor)
{
	const GameControl* gc = core->GetGameControl();
	return actor && actor->InParty && gc && gc->ShouldRun(actor);
}

// combat walks keep their own speed; Always Run still applies to the party, and
// creatures with no run animation cover ground at a typical run (walk frames).
static void PrepareCombatMoveSpeed(Actor* actor)
{
	if (!actor) return;
	if (!HasRunAnim(actor) || PartyAlwaysRuns(actor)) {
		actor->SetInternalFlag(IF_RUNNING, BitOp::OR);
		actor->SetSpeed(false);
	}
}

// how far the actor would walk in a round of real time
static int MovementAllowance(const Actor* actor)
{
	int scale = actor->CalculateSpeed(false);
	if (!HasRunAnim(actor)) {
		int run = CombatDirector::RunSpeedFromWalk(actor->CalculateSpeed(false, false));
		if (run > 0) scale = run;
	}
	if (scale <= 0) return 0;
	int percent = core->GetDictionary().Get("Turn Based Movement Percent", 100);
	return int(core->Time.round_size * gamedata->GetStepTime() / scale) * percent / 100;
}

int CombatDirector::RunSpeedFromWalk(int walkScale)
{
	if (walkScale <= 0) return 0;
	return std::max(1, walkScale / 3);
}

static bool IsAliveCombatant(const Actor* actor)
{
	return actor && !(actor->GetStat(IE_STATE_ID) & STATE_DEAD) && actor->ValidTarget(GA_NO_DEAD);
}

static String Name(const Actor* actor)
{
	return actor ? actor->GetDisplayedName() : u"?";
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

// the script action's name in lower case, without its parameters: "attack", "wait" ...
static const std::string& ActionName(const Action* action)
{
	static std::unordered_map<unsigned short, std::string> names;
	static const std::string none;
	if (!action || !actionsTable) return none;
	auto it = names.find(action->actionID);
	if (it != names.end()) return it->second;
	std::string name = actionsTable->GetValue(action->actionID);
	size_t paren = name.find('(');
	if (paren != std::string::npos) name.resize(paren);
	// the table has them as the ids file spells them; compare in lower case
	std::transform(name.begin(), name.end(), name.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
	return names.emplace(action->actionID, name).first->second;
}

// how the creature's scripts fight: the first slot (override first) that has combat blocks
static CombatArchetype ArchetypeOf(const Actor* actor)
{
	for (const auto& script : actor->Scripts) {
		if (!script) continue;
		const CombatProfile& profile = CombatAnalyzer::Analyze(script->GetName());
		if (profile.archetype != CombatArchetype::None) return profile.archetype;
	}
	return CombatArchetype::None;
}

// after a Wait the rest of the response used to run once the wait was over: its instant
// actions (step counters, barks) run now, the next time-taking one waits for the next turn
static void RunInstantActions(Actor* actor)
{
	while (!actor->GetCurrentAction()) {
		Holder<Action> next = actor->GetNextAction();
		if (!next || !(actionflags[next->actionID] & AF_INSTANT)) break;
		actor->PopNextAction();
		GameScript::ExecuteAction(actor, std::move(next));
	}
}

// waiting actions: an AI spends its turn (and maybe more) instead of running them in real time
static int WaitSeconds(const Action* action)
{
	const std::string& name = ActionName(action);
	if (name == "wait") return action->int0Parameter;
	if (name == "waitrandom") return RAND(action->int0Parameter, std::max(action->int0Parameter, action->int1Parameter));
	if (name == "smallwait" || name == "noaction") return 0;
	return -1;
}

Combatant CombatDirector::MakeCombatant(Actor* actor) const
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

	PrepareCombatMoveSpeed(actor);
	ResetBudget(combatant, MovementAllowance(actor));
	Log(COMBAT, "CombatDirector", "{} rolls initiative {} (d10: {})", fmt::WideToChar { Name(actor) }, initiative, combatant.roll);
	return combatant;
}

Combatant* CombatDirector::FindCombatant(ieDword globalID)
{
	for (auto& combatant : order) {
		if (combatant.globalID == globalID) return &combatant;
	}
	return nullptr;
}

const Combatant* CombatDirector::FindCombatant(ieDword globalID) const
{
	for (const auto& combatant : order) {
		if (combatant.globalID == globalID) return &combatant;
	}
	return nullptr;
}

bool CombatDirector::IsCombatant(const Actor* actor) const
{
	return actor && FindCombatant(actor->GetGlobalID()) != nullptr;
}

Actor* CombatDirector::GetActiveActor() const
{
	// the combat map may have been unloaded since the last update
	if (!IsActive() || !combatMap || core->GetGame()->GetCurrentArea() != combatMap) return nullptr;
	return combatMap->GetActorByGlobalID(activeID);
}

bool CombatDirector::IsBusy(const Actor* actor) const
{
	if (!actor || !IsRunning() || actor->GetGlobalID() != activeID) return false;
	if (step == Step::Walk || step == Step::Swing || step == Step::Reaction) return true;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (combatant && combatant->standTicks > 0) return true;
	return actor->InMove() || actor->GetCurrentAction() || actor->GetNextAction() || SpellInFlight(actor);
}

bool CombatDirector::SpellInFlight(const Actor* actor) const
{
	return Casting(actor) || (flightTicks <= FLIGHT_MAX_TICKS && ProjectileInFlight(actor));
}

bool CombatDirector::Casting(const Actor* actor)
{
	// SpellCore marks the action uninterruptible until the spell is released
	return actor && actor->GetCurrentAction() && !actor->CurrentActionInterruptible;
}

bool CombatDirector::ProjectileInFlight(const Actor* actor) const
{
	if (!actor || !combatMap) return false;
	proIterator iter;
	size_t count = combatMap->GetProjectileCount(iter);
	for (size_t i = 0; i < count; ++i, ++iter) {
		const Projectile* pro = iter->get();
		if (pro && pro->GetCaster() == actor->GetGlobalID() && pro->Resolving()) return true;
	}
	return false;
}

// ------------------------------------------------------------------------------------------
// who fights

bool CombatDirector::ShouldStartCombat(const Map* map) const
{
	const Game* game = core->GetGame();
	const std::vector<Actor*> party = PartyOnMap(map);
	const bool attacked = game->PartyAttack;
	const bool onSight = core->GetDictionary().Get("Turn Based Start On Sight", 1) != 0;
	if (!attacked && !onSight) return false;

	for (const Actor* actor : map->GetAllActors()) {
		if (!IsEnemyEA(actor->GetStat(IE_EA))) continue;
		if (!IsAliveCombatant(actor) || !actor->Schedule(game->GameTime, true)) continue;
		if (attacked) {
			for (const Actor* pc : party) {
				if (pc->objects.LastTarget == actor->GetGlobalID() || actor->objects.LastTarget == pc->GetGlobalID()) {
					return true;
				}
			}
		}
		if (!onSight || !map->IsVisible(actor->Pos)) continue;
		for (const Actor* pc : party) {
			if (WithinRange(pc, actor->Pos, pc->GetVisualRange()) && map->IsVisibleLOS(pc->Pos, actor->Pos)) {
				return true;
			}
		}
	}
	return false;
}

bool CombatDirector::ShouldJoin(const Actor* actor, const std::vector<Actor*>& party) const
{
	if (actor->InParty || !IsAliveCombatant(actor)) return false;
	if (!actor->Schedule(core->GetGame()->GameTime, true)) return false;

	ieDword ea = actor->GetStat(IE_EA);
	if (IsNeutralEA(ea)) return false;

	bool targeted = false;
	for (const Actor* pc : party) {
		if (pc->objects.LastTarget == actor->GetGlobalID() || actor->objects.LastTarget == pc->GetGlobalID()) {
			targeted = true;
			break;
		}
	}
	if (!targeted && actor->objects.LastTarget && FindCombatant(actor->objects.LastTarget)) {
		targeted = true;
	}

	for (const Actor* pc : party) {
		if (targeted || WithinRange(pc, actor->Pos, pc->GetVisualRange())) {
			return true;
		}
	}
	return false;
}

bool CombatDirector::IsEnemyCombatant(const Combatant& combatant) const
{
	if (combatant.dead) return false;
	const Actor* actor = combatMap ? combatMap->GetActorByGlobalID(combatant.globalID) : nullptr;
	if (!IsAliveCombatant(actor) || actor->InParty) return false;
	return IsEnemyEA(actor->GetStat(IE_EA));
}

bool CombatDirector::ShouldEndCombat() const
{
	if (!combatMap || core->GetGame()->GetCurrentArea() != combatMap) return true;
	return std::none_of(order.begin(), order.end(), [this](const Combatant& c) { return IsEnemyCombatant(c); });
}

// ------------------------------------------------------------------------------------------
// takeover and handback

static Actor* NearestEnemy(const Actor* actor, const Map* map, const std::vector<Combatant>& order)
{
	ieDword ea = actor->GetStat(IE_EA);
	if (CombatDirector::IsNeutralEA(ea)) return nullptr;
	Actor* best = nullptr;
	unsigned int bestDistance = 0;
	for (const Combatant& other : order) {
		if (other.dead || other.globalID == actor->GetGlobalID()) continue;
		Actor* candidate = map->GetActorByGlobalID(other.globalID);
		if (!IsAliveCombatant(candidate)) continue;
		if (!CombatDirector::AreEnemies(ea, candidate->GetStat(IE_EA))) continue;
		unsigned int distance = SquaredDistance(actor->Pos, candidate->Pos);
		if (!best || distance < bestDistance) {
			best = candidate;
			bestDistance = distance;
		}
	}
	return best;
}

void CombatDirector::TakeOver(Actor* actor, Combatant& combatant)
{
	if (Owns(actor)) return;
	actor->SetInternalFlag(IF_COMBAT_OWNED, BitOp::OR);
	// nothing it was doing in real time carries into the fight; its triggers stay for its turn
	actor->ClearPath(true);
	actor->ClearActions();
	actor->ResetBackoff();
	actor->SetWait(0);
	if (!(actor->GetStat(IE_STATE_ID) & (STATE_DEAD | STATE_HELPLESS | STATE_SLEEP))) {
		actor->SetStance(IE_ANI_READY);
	}
	const Actor* enemy = NearestEnemy(actor, combatMap, order);
	if (enemy) actor->FaceTarget(enemy);
	combatant.attacking = false;
	combatant.clockTime = core->GetGame()->GameTime;
	combatant.upkeepRound = round;
}

void CombatDirector::HandBack(Actor* actor, Combatant* combatant)
{
	if (!actor || !Owns(actor)) return;
	// its effects lived on the combat clock; the world's clock went further meanwhile
	if (combatant && combatant->clockTime) {
		ieDword now = core->GetGame()->GameTime;
		if (now > combatant->clockTime) actor->fxqueue.ShiftDurations(int(now - combatant->clockTime));
		combatant->clockTime = 0;
	}
	actor->SetInternalFlag(IF_COMBAT_OWNED, BitOp::NAND);
	actor->SetInternalFlag(IF_RUNNING, BitOp::NAND);
	if (PartyAlwaysRuns(actor)) {
		actor->SetInternalFlag(IF_RUNNING, BitOp::OR);
	}
	actor->SetSpeed(false);
	actor->ClearPath(true);
	actor->ResetBackoff();
	// prone ends with the fight, or SetStance below would keep them lying there
	if (combatant) combatant->prone = false;
	// the dead keep their dying animation and get their last script run from GemRB
	RestoreSwingSpeed(actor);
	if (IsAliveCombatant(actor)) {
		actor->ClearActions();
		actor->SetStance(IE_ANI_READY);
		actor->Timers.roundStart = 0;
	}
	if (combatant) combatant->attacking = false;
	// let its script react right away to whatever happened in the fight
	actor->ImmediateEvent();
}

void CombatDirector::TakeOverAll()
{
	for (auto& combatant : order) {
		Actor* actor = combatMap->GetActorByGlobalID(combatant.globalID);
		if (combatant.dead || !IsAliveCombatant(actor)) continue;
		TakeOver(actor, combatant);
	}
}

void CombatDirector::HandBackAll()
{
	if (!combatMap) return;
	for (auto& combatant : order) {
		HandBack(combatMap->GetActorByGlobalID(combatant.globalID), &combatant);
	}
}

void CombatDirector::Upkeep(Actor* actor, Combatant& combatant)
{
	// a new round for the once-per-round limits
	actor->AuraCooldown = 0;
	// once per round: the round it was taken over in counts as lived
	if (combatant.upkeepRound >= round || !combatant.clockTime) return;
	combatant.upkeepRound = round;

	// between its turns nothing of its effects runs (Map::UpdateEffects skips it); now they live
	// through one round tick by tick: durations, regeneration, poison all follow its turns
	for (ieDword tick = 0; tick < core->Time.round_size; ++tick) {
		++combatant.clockTime;
		actor->RefreshEffects();
		if (!IsAliveCombatant(actor)) break;
	}
	actor->fxqueue.Cleanup();
}

// ------------------------------------------------------------------------------------------
// combat start, end and the order

void CombatDirector::StartCombat(Map* map)
{
	combatMap = map;
	order.clear();
	events.clear();
	hud.Reset();
	reactionSettling = false;
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
		order.push_back(MakeCombatant(actor));
	}
	SortByInitiative(order);

	// surprise: whoever can't see a single enemy as the fight starts loses the first round
	if (Setting("Turn Based Surprise", 0)) {
		for (auto& combatant : order) {
			const Actor* actor = map->GetActorByGlobalID(combatant.globalID);
			if (!actor) continue;
			ieDword ea = actor->GetStat(IE_EA);
			bool sees = false;
			for (const auto& other : order) {
				const Actor* them = map->GetActorByGlobalID(other.globalID);
				if (!them || them == actor) continue;
				if (!AreEnemies(ea, them->GetStat(IE_EA))) continue;
				if (WithinRange(actor, them->Pos, actor->GetVisualRange()) && map->IsVisibleLOS(actor->Pos, them->Pos)) {
					sees = true;
					break;
				}
			}
			combatant.surprised = !sees;
		}
	}
	Log(MESSAGE, "CombatDirector", "Turn based combat starts with {} combatants", order.size());
	state = State::TurnActive;
	TakeOverAll();
	for (auto& combatant : order) {
		Actor* actor = map->GetActorByGlobalID(combatant.globalID);
		if (!actor) continue;
		AllocateAttacks(combatant, actor);
		ShowFloater(actor, fmt::format(u"Initiative: {}", combatant.initiative));
	}

	CombatEvent event;
	event.type = CombatEventType::CombatStart;
	event.round = round;
	PushEvent(event);

	// optional closer camera for the fight, 100 means no change
	GameControl* gc = core->GetGameControl();
	unsigned int zoom = core->GetDictionary().Get("Turn Based Camera Zoom", 100);
	if (gc && zoom != 100) {
		savedZoom = gc->GetScalePercent();
		gc->SetScalePercent(zoom);
	}
	RevealCombatVision(map);
	BeginTurn(0);
}

void CombatDirector::EndCombat()
{
	if (!IsActive()) return;
	Log(MESSAGE, "CombatDirector", "Turn based combat ends after {} rounds", round);
	HandBackAll();

	CombatEvent event;
	event.type = CombatEventType::CombatEnd;
	event.round = round;
	PushEvent(event);

	Map* map = combatMap;
	state = State::Inactive;
	order.clear();
	activeID = 0;
	activeIdx = 0;
	combatMap = nullptr;
	if (map) map->UpdateFog();

	GameControl* gc = core->GetGameControl();
	if (gc && savedZoom) {
		gc->SetScalePercent(savedZoom);
	}
	savedZoom = 0;
	NotifyGUI();
}

void CombatDirector::BeginTurn(size_t idx)
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
		Actor* member = combatMap->GetActorByGlobalID(order[i].globalID);
		PrepareCombatMoveSpeed(member);
		ResetBudget(order[i], member ? MovementAllowance(member) : 0);
	}
	ActivateMember(idx);
}

void CombatDirector::ActivateMember(size_t idx)
{
	activeIdx = idx;
	step = Step::Begin;
	stallTicks = 0;
	decisions = 0;
	roundDone = false;
	wantedMore = false;
	playerIdleTicks = 0;
	blockedAt = Point(-1, -1);
	blockedDest = Point(-1, -1);
	plan = PlannedPath();
	committed = PlannedPath();

	Combatant& combatant = order[idx];
	activeID = combatant.globalID;
	Actor* actor = combatMap->GetActorByGlobalID(activeID);
	if (!actor) {
		combatant.dead = true;
		AdvanceTurn();
		return;
	}
	Log(COMBAT, "CombatDirector", "Round {}: {}'s turn (initiative {})", round, fmt::WideToChar { Name(actor) }, combatant.initiative);

	Game* game = core->GetGame();
	if (actor->InParty && !(game->selected.size() == 1 && actor->IsSelected())) {
		// the turn came to it: a plain acknowledgement, and the click streak (annoyed lines) starts over
		game->SelectActor(actor, true, SELECT_REPLACE | SELECT_QUIET);
		core->SetEventFlag(EF_SELECTION);
		actor->PlaySelectionSound(false, true);
	}
	GameControl* gc = core->GetGameControl();
	if (gc && game->GetCurrentArea() == combatMap) {
		gc->MoveViewportTo(gc->CombatFocus(actor->Pos), true, TURN_CAMERA_SPEED);
	}
	NotifyGUI();
}

void CombatDirector::AdvanceTurn()
{
	endRequested = false;
	flightTicks = 0;
	// a creature never leaves its turn mid-walk or mid-swing
	Actor* previous = combatMap ? combatMap->GetActorByGlobalID(activeID) : nullptr;
	if (previous && Owns(previous)) {
		previous->ClearPath(true);
		previous->ResetBackoff();
		if (IsAliveCombatant(previous) && !(previous->GetStat(IE_STATE_ID) & (STATE_HELPLESS | STATE_SLEEP))) {
			previous->SetStance(IE_ANI_READY);
		}
		Combatant* combatant = FindCombatant(activeID);
		if (combatant) combatant->attacking = false;
	}

	if (activeIdx < order.size() && !order[activeIdx].delayed) {
		order[activeIdx].done = true;
	}
	auto waiting = [](const Combatant& c) { return !c.dead && !c.done && !c.delayed; };
	// first the rest of the party group, in any order the player picked
	for (size_t i = groupStart; i <= groupEnd && i < order.size(); ++i) {
		if (waiting(order[i])) {
			ActivateMember(i);
			return;
		}
	}
	for (size_t i = groupEnd + 1; i < order.size(); ++i) {
		if (waiting(order[i])) {
			BeginTurn(i);
			return;
		}
	}
	// then whoever delayed, in initiative order, with the budget they kept
	for (size_t i = 0; i < order.size(); ++i) {
		if (!order[i].dead && !order[i].done && order[i].delayed) {
			order[i].delayed = false;
			groupStart = groupEnd = i;
			ActivateMember(i);
			return;
		}
	}
	EndRound();
}

void CombatDirector::EndTurn()
{
	if (state != State::TurnActive) return;
	// the whole spell resolves in its caster's turn: the turn ends once it has landed
	if (SpellInFlight(GetActiveActor())) {
		endRequested = true;
		return;
	}
	// the next party member adjacent in the order takes over (with selection and camera);
	// after the last one the turn passes on
	AdvanceTurn();
}

void CombatDirector::EndRound()
{
	++round;

	// the dead stay out, everyone else gets a new round
	order.erase(std::remove_if(order.begin(), order.end(), [](const Combatant& c) { return c.dead; }), order.end());
	for (auto& combatant : order) {
		combatant.done = false;
		combatant.delayed = false;
		combatant.surprised = false;
		combatant.reactionUsed = false;
		Actor* actor = combatMap->GetActorByGlobalID(combatant.globalID);
		if (actor) AllocateAttacks(combatant, actor);
	}
	activeIdx = groupStart = groupEnd = 0;
	AddJoiners(false);

	if (ShouldEndCombat()) {
		EndCombat();
		return;
	}

	CombatEvent event;
	event.type = CombatEventType::RoundStart;
	event.round = round;
	PushEvent(event);

	for (size_t i = 0; i < order.size(); ++i) {
		if (!order[i].dead) {
			BeginTurn(i);
			return;
		}
	}
	EndCombat();
}

void CombatDirector::AddJoiners(bool midRound)
{
	const std::vector<Actor*> party = PartyOnMap(combatMap);
	for (Actor* actor : combatMap->GetAllActors()) {
		if (IsCombatant(actor)) continue;
		bool joins = actor->InParty ? IsAliveCombatant(actor) : ShouldJoin(actor, party);
		if (!joins) continue;
		Join(actor, midRound);
	}
}

// in real time a creature's scripts see an attack or a call for help within a second; here they
// would only see it on its turn, or never if it dies first. So those triggers run its scripts at
// once: the instant part of the response (Enemy, Help, variables) happens now, the rest (attacks,
// movement) stays queued for its turn
void CombatDirector::ReactToProvocations()
{
	if (!Setting("Turn Based Immediate Reactions", 1)) return;
	static const unsigned short provocations[] = { trigger_attackedby, trigger_hitby, trigger_help, trigger_heard };
	for (size_t i = 0; i < order.size(); ++i) {
		if (order[i].dead || order[i].globalID == activeID) continue;
		Actor* actor = combatMap->GetActorByGlobalID(order[i].globalID);
		if (!actor || actor->InParty || !IsAliveCombatant(actor)) continue;
		bool provoked = std::any_of(std::begin(provocations), std::end(provocations), [actor](unsigned short id) {
			return actor->GetMatchingTrigger(id, TEF_TB_REACTED) != nullptr;
		});
		if (!provoked) continue;

		std::string why;
		for (unsigned short id : provocations) {
			const TriggerEntry* trigger = actor->GetMatchingTrigger(id, TEF_TB_REACTED);
			if (!trigger) continue;
			const Actor* from = combatMap->GetActorByGlobalID(trigger->param1);
			why += from ? fmt::format("{:#x} from {} (EA {}) ", id, fmt::WideToChar { Name(from) }, from->GetStat(IE_EA)) : fmt::format("{:#x} ", id);
		}
		// only once per trigger, the ones it keeps still count on its turn
		actor->FlagTriggers(TEF_TB_REACTED);
		ieDword ea = actor->GetStat(IE_EA);
		// instant actions at the head of the response already ran as the script queued them
		actor->ExecuteScript(MAX_SCRIPTS);
		RunInstantActions(actor);
		Log(COMBAT, "CombatDirector", "{} reacts out of turn to {}(EA {} -> {})", fmt::WideToChar { Name(actor) }, why, ea, actor->GetStat(IE_EA));
		NotifyGUI();
	}
}

void CombatDirector::Join(Actor* actor, bool midRound)
{
	{
		Combatant combatant = MakeCombatant(actor);
		size_t idx = InsertByInitiative(order, combatant);
		// their slot already passed this round, so they start next round
		if (midRound && idx <= groupEnd) {
			order[idx].done = true;
			if (idx <= activeIdx) ++activeIdx;
			if (idx <= groupStart) ++groupStart;
			++groupEnd;
		}
		TakeOver(actor, order[idx]);
		AllocateAttacks(order[idx], actor);
		ShowFloater(actor, fmt::format(u"Initiative: {}", order[idx].initiative));
		RevealCombatVision(combatMap);
		Log(COMBAT, "CombatDirector", "{} joins the fight", fmt::WideToChar { Name(actor) });
		NotifyGUI();
	}
}

void CombatDirector::RefreshDeaths()
{
	for (auto& combatant : order) {
		if (combatant.dead) continue;
		Actor* actor = combatMap->GetActorByGlobalID(combatant.globalID);
		if (!IsAliveCombatant(actor)) {
			combatant.dead = true;
			// death handling (scripts, drops, kill variables) is GemRB's
			HandBack(actor, &combatant);
			CombatEvent event;
			event.type = CombatEventType::Death;
			event.actor = combatant.globalID;
			event.round = round;
			PushEvent(event);
			NotifyGUI();
		}
	}
}

void CombatDirector::DropCombatant(size_t idx, bool& droppedActive)
{
	if (idx >= order.size()) return;
	Actor* actor = combatMap ? combatMap->GetActorByGlobalID(order[idx].globalID) : nullptr;
	if (order[idx].globalID == activeID) droppedActive = true;
	Log(COMBAT, "CombatDirector", "{} leaves the fight (not hostile)", fmt::WideToChar { Name(actor) });
	HandBack(actor, &order[idx]);
	order.erase(order.begin() + idx);
	if (idx < activeIdx) --activeIdx;
	if (idx < groupStart) --groupStart;
	if (idx <= groupEnd && groupEnd > 0) --groupEnd;
}

void CombatDirector::ContinueAfterDrop()
{
	endRequested = false;
	flightTicks = 0;
	activeID = 0;
	if (ShouldEndCombat()) return;
	auto waiting = [](const Combatant& c) { return !c.dead && !c.done && !c.delayed; };
	for (size_t i = 0; i < order.size(); ++i) {
		if (waiting(order[i])) {
			BeginTurn(i);
			return;
		}
	}
	for (size_t i = 0; i < order.size(); ++i) {
		if (!order[i].dead && !order[i].done && order[i].delayed) {
			order[i].delayed = false;
			groupStart = groupEnd = i;
			ActivateMember(i);
			return;
		}
	}
	EndRound();
}

void CombatDirector::RefreshBystanders()
{
	bool droppedActive = false;
	bool dropped = false;
	for (size_t i = 0; i < order.size();) {
		if (order[i].dead) {
			++i;
			continue;
		}
		Actor* actor = combatMap->GetActorByGlobalID(order[i].globalID);
		if (actor && actor->InParty) {
			++i;
			continue;
		}
		ieDword ea = actor ? actor->GetStat(IE_EA) : EA_NEUTRAL;
		if (actor && !IsNeutralEA(ea)) {
			++i;
			continue;
		}
		DropCombatant(i, droppedActive);
		dropped = true;
	}
	if (droppedActive) {
		ContinueAfterDrop();
	} else if (dropped) {
		NotifyGUI();
	}
}

// ------------------------------------------------------------------------------------------
// the tick

void CombatDirector::Update()
{
	Game* game = core->GetGame();
	if (!game) return;

	if (!IsEnabled()) {
		EndCombat();
		return;
	}

	Map* area = game->GetCurrentArea();
	if (state == State::Inactive) {
		const GameControl* gc = core->GetGameControl();
		if (area && !core->InCutSceneMode() && !(gc && gc->InDialog()) && ShouldStartCombat(area)) {
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

	// cutscenes and dialogs play out in real time, with everyone handed back
	const GameControl* gc = core->GetGameControl();
	bool interrupted = core->InCutSceneMode() || (gc && gc->InDialog());
	if (interrupted) {
		if (state == State::TurnActive) {
			state = State::Suspended;
			HandBackAll();
			NotifyGUI();
		}
		return;
	}
	if (state == State::Suspended) {
		state = State::TurnActive;
		TakeOverAll();
		// the active creature's queue went with the handback, so it decides again
		step = Step::Begin;
		AddJoiners(true);
		NotifyGUI();
	}

	// hit points, movement and busy state change all the time, keep the gui roughly in sync
	if (++guiTicks % GUI_REFRESH_TICKS == 0) {
		NotifyGUI();
	}

	RefreshDeaths();
	// creatures that act on the fight join it right away, so they never act in real time on it
	AddJoiners(true);
	ReactToProvocations();
	RefreshBystanders();
	if (ShouldEndCombat()) {
		EndCombat();
		return;
	}

	FollowGroupSelection();

	Actor* actor = GetActiveActor();
	if (!actor || !IsAliveCombatant(actor) || !IsCombatant(actor)) {
		AdvanceTurn();
		return;
	}
	RunTurn(actor);
}

void CombatDirector::FollowGroupSelection()
{
	Game* game = core->GetGame();
	if (game->selected.size() != 1 || game->selected[0]->GetGlobalID() == activeID) return;

	// only on the party's turn, and never in the middle of someone's move or attack
	Actor* active = GetActiveActor();
	if (!active || !active->InParty || IsBusy(active)) {
		return;
	}

	ieDword wanted = game->selected[0]->GetGlobalID();
	for (size_t i = groupStart; i <= groupEnd && i < order.size(); ++i) {
		if (order[i].globalID == wanted && !order[i].done && !order[i].dead) {
			ActivateMember(i);
			return;
		}
	}

	// not next to the active one in the order (or done already): the selection goes back
	const Actor* picked = game->selected[0];
	if (picked->InParty && FindCombatant(wanted)) {
		displaymsg->DisplayString(fmt::format(u"{} can't act now: not next in the turn order", Name(picked)), GUIColors::WHITE, nullptr);
	}
	game->SelectActor(active, true, SELECT_REPLACE | SELECT_QUIET);
	core->SetEventFlag(EF_SELECTION);
}

// ------------------------------------------------------------------------------------------
// one turn: Begin -> Act (actions run) <-> Walk / Swing -> Over

void CombatDirector::RunTurn(Actor* actor)
{
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) {
		AdvanceTurn();
		return;
	}
	switch (step) {
		case Step::Begin:
			BeginStep(actor, *combatant);
			break;
		case Step::Act:
			ActStep(actor, *combatant);
			break;
		case Step::Walk:
			WalkStep(actor, *combatant);
			break;
		case Step::Reaction:
			ReactionStep(actor);
			break;
		case Step::Swing:
			SwingStep(actor, *combatant);
			break;
		case Step::Over:
			break;
	}
	if (step == Step::Over) {
		AdvanceTurn();
	}
}

void CombatDirector::BeginStep(Actor* actor, Combatant& combatant)
{
	Upkeep(actor, combatant);
	if (!IsAliveCombatant(actor)) {
		step = Step::Over;
		return;
	}

	CombatEvent event;
	event.type = CombatEventType::TurnStart;
	event.actor = combatant.globalID;
	event.round = round;
	event.value = combatant.initiative;
	PushEvent(event);

	if (round == 1 && combatant.surprised) {
		Log(COMBAT, "CombatDirector", "{} is caught by surprise", fmt::WideToChar { Name(actor) });
		step = Step::Over;
		return;
	}
	if (combatant.prone) {
		StandUp(actor, combatant);
	}
	// held, stunned, asleep: the turn passes
	if (actor->Immobile() || (actor->GetStat(IE_STATE_ID) & (STATE_HELPLESS | STATE_SLEEP))) {
		Log(COMBAT, "CombatDirector", "{} can't act this turn", fmt::WideToChar { Name(actor) });
		step = Step::Over;
		return;
	}

	step = Step::Act;
	if (PlayerControlled(actor)) return;

	Decide(actor, combatant);
	ChooseAIManeuvers(actor, combatant);
}

// the AI's decision: GemRB evaluates its scripts once, the response lands in its action queue
bool CombatDirector::Decide(Actor* actor, Combatant& combatant)
{
	++decisions;
	// a previous turn's unfinished action stays, the script may keep or replace it
	actor->ExecuteScript(MAX_SCRIPTS);

	const Action* intent = actor->GetCurrentAction().get();
	if (!intent) intent = actor->GetNextAction().get();
	// no intent, or only idling (an ambient Wait): tactics may have it fight what it sees
	if (!intent || WaitSeconds(intent) >= 0) {
		Holder<Action> idle = intent ? (actor->GetCurrentAction() ? actor->GetCurrentAction() : actor->GetNextAction()) : nullptr;
		if (TacticsFallback(actor)) {
			if (idle) {
				// drop the idling in favour of the attack the fallback queued
				if (actor->GetCurrentAction() == idle) {
					actor->ReleaseCurrentAction();
				} else if (actor->GetNextAction() == idle) {
					actor->PopNextAction();
				}
				actor->SetWait(0);
			}
			intent = actor->GetCurrentAction() ? actor->GetCurrentAction().get() : actor->GetNextAction().get();
		}
	}

	CombatEvent event;
	event.type = CombatEventType::Intent;
	event.actor = combatant.globalID;
	event.round = round;
	event.text = intent ? ActionName(intent) : "nothing";
	PushEvent(event);
	Log(COMBAT, "CombatDirector", "Round {} / {} ({}): intent {}", round, fmt::WideToChar { Name(actor) },
	    CombatAnalyzer::ArchetypeName(ArchetypeOf(actor)), event.text);
	return intent != nullptr;
}

// a hostile whose scripts have nothing to say attacks the nearest enemy it can see
bool CombatDirector::TacticsFallback(Actor* actor)
{
	// party members only fight on their own when the AI plays them
	bool partyAI = actor->InParty && !PlayerControlled(actor);
	if (!core->GetDictionary().Get("Turn Based Tactical AI", 1) && !partyAI) return false;
	if (!IsEnemyEA(actor->GetStat(IE_EA)) && !partyAI) return false;
	// cowards and callers do what their script says, they aren't made to fight
	CombatArchetype archetype = ArchetypeOf(actor);
	if (!partyAI && (archetype == CombatArchetype::Coward || archetype == CombatArchetype::Caller)) return false;
	Actor* enemy = NearestEnemy(actor, combatMap, order);
	if (!enemy || !CanSee(actor, enemy, true, GA_NO_DEAD)) return false;
	actor->AddAction(GenerateActionDirect("Attack([-1])", enemy));
	return actor->GetNextAction() != nullptr || actor->GetCurrentAction() != nullptr;
}

bool CombatDirector::PlayerTurnOver(const Actor* actor, const Combatant& combatant) const
{
	if (!core->GetDictionary().Get("Turn Based Auto End Turn", 1)) return false;
	if (actor->GetCurrentAction() || actor->GetNextAction()) return false;
	return combatant.mainActionUsed && combatant.movePx <= 0;
}

void CombatDirector::ActStep(Actor* actor, Combatant& combatant)
{
	if (combatant.standTicks > 0) {
		--combatant.standTicks;
		if (combatant.standTicks == 0) {
			combatant.prone = false;
			actor->SetStance(IE_ANI_READY);
		}
		return;
	}

	// the whole spell resolves in its caster's turn: nothing else happens until it has landed
	const bool casting = Casting(actor);
	if (!casting && flightTicks <= FLIGHT_MAX_TICKS && ProjectileInFlight(actor)) {
		if (++flightTicks > FLIGHT_MAX_TICKS) {
			Log(COMBAT, "CombatDirector", "{}: its spell doesn't land, going on", fmt::WideToChar { Name(actor) });
		}
		return;
	}
	if (flightTicks && flightTicks <= FLIGHT_MAX_TICKS) {
		Log(COMBAT, "CombatDirector", "{}: its spell landed after {} ticks", fmt::WideToChar { Name(actor) }, flightTicks);
		flightTicks = 0;
	}
	// the player ended the turn mid-spell: it ends now that the spell has landed
	if (endRequested && !casting) {
		endRequested = false;
		step = Step::Over;
		return;
	}

	Holder<Action> current = actor->GetCurrentAction();
	Holder<Action> next = current ? current : actor->GetNextAction();

	// in a fight a Wait only ends the turn: the script decides afresh next turn, like it
	// re-checks its conditions every few ticks while waiting in real time
	if (!PlayerControlled(actor) && next) {
		int seconds = WaitSeconds(next.get());
		if (seconds >= 0) {
			if (current) {
				actor->ReleaseCurrentAction();
			} else {
				actor->PopNextAction();
			}
			actor->SetWait(0);
			RunInstantActions(actor);
			Log(COMBAT, "CombatDirector", "{} waits ({} s)", fmt::WideToChar { Name(actor) }, seconds);
			step = Step::Over;
			return;
		}
	}

	if (!next && !actor->GetWait()) {
		stallTicks = 0;
		if (PlayerControlled(actor)) {
			playerIdleTicks++;
			if (PlayerTurnOver(actor, combatant) && playerIdleTicks >= PLAYER_IDLE_TICKS) {
				step = Step::Over;
			}
			return;
		}
		// the AI ran out of things to do; look again if its script only ran instant actions
		if (decisions < MAX_DECISIONS && !roundDone && !combatant.mainActionUsed && !wantedMore && Decide(actor, combatant)) {
			return;
		}
		step = Step::Over;
		return;
	}
	playerIdleTicks = 0;

	static const Action* lastTraced = nullptr;
	if (next.get() != lastTraced) {
		lastTraced = next.get();
		Log(COMBAT, "CombatDirector", "{} runs '{}'", fmt::WideToChar { Name(actor) }, ActionName(lastTraced));
	}
	wantedMore = false;
	// GemRB's action code runs: it may ask for a path (-> Walk) or a round of attacks (-> Swing)
	actor->ProcessActions();
	if (step != Step::Act) {
		stallTicks = 0;
		return;
	}
	if (!wantedMore && !actor->GetCurrentAction() && next && actor->GetNextAction() != next && !actor->InMove()) {
		Log(COMBAT, "CombatDirector", "{}: '{}' is done", fmt::WideToChar { Name(actor) }, ActionName(next.get()));
	}

	if (wantedMore) {
		// it wants to walk or attack but the budget is spent
		if (PlayerControlled(actor)) {
			// the player's order can't be carried out this turn
			displaymsg->DisplayString(combatant.mainActionUsed ? u"No action left this turn" : u"Can't get there this turn", GUIColors::WHITE, nullptr);
			actor->ClearActions();
			actor->SetStance(IE_ANI_READY);
		} else if (combatant.ran && combatant.movePx > 0) {
			// spent the action on Run: still use the extra movement to close
			wantedMore = false;
			Actor* enemy = NearestEnemy(actor, combatMap, order);
			CloseOnEnemy(actor, enemy);
			if (step == Step::Walk) return;
			step = Step::Over;
		} else {
			// the AI keeps its action for the next turn
			step = Step::Over;
		}
		return;
	}

	if (actor->GetCurrentAction() || actor->GetNextAction() || actor->GetWait()) {
		// casting and other timed actions play out within the turn
		if (++stallTicks > STALL_TICKS) {
			Log(COMBAT, "CombatDirector", "{}: '{}' doesn't progress, ending the turn", fmt::WideToChar { Name(actor) },
			    ActionName(actor->GetCurrentAction().get()));
			stallTicks = 0;
			if (PlayerControlled(actor)) {
				actor->ClearActions();
				actor->SetWait(0);
			} else {
				step = Step::Over;
			}
		}
		return;
	}
	stallTicks = 0;
}

void CombatDirector::RequestPath(Actor* actor, const Point& source, const Point& destination, int minDistance, int flags)
{
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!IsRunning() || !combatant || actor->GetGlobalID() != activeID || step != Step::Act) {
		// not its turn: it stays put
		Log(COMBAT, "CombatDirector", "{} asked for a path outside its turn", fmt::WideToChar { Name(actor) });
		return;
	}
	if (actor->Pos == blockedAt && destination == blockedDest) {
		// the same walk just went nowhere from here; another destination gets a fresh try
		Log(COMBAT, "CombatDirector", "{}: the way is blocked", fmt::WideToChar { Name(actor) });
		wantedMore = true;
		return;
	}
	if (combatant->movePx <= 0 || actor->GetSpeed() <= 0) {
		Log(COMBAT, "CombatDirector", "{}: no movement left (speed {})", fmt::WideToChar { Name(actor) }, actor->GetSpeed());
		wantedMore = true;
		return;
	}

	const unsigned int minDist = static_cast<unsigned int>(std::max(0, minDistance));
	Path path;
	if (source == actor->Pos) {
		path = PlanPath(actor, destination, minDist);
	} else {
		Map* map = actor->GetCurrentArea();
		const ActorPathContext context { static_cast<unsigned int>(actor->circleSize), actor->GetScriptName(), actor->ValidTarget(GA_ONLY_BUMPABLE) };
		path = PathFinder::FindPath(map->GetFreshTraversabilityCacheData(), map->tileProps, source, destination, context,
					    minDist, PF_SIGHT | PF_ACTORS_ARE_BLOCKING | flags);
	}
	if (!path) {
		Log(COMBAT, "CombatDirector", "{}: no path from {} to {} (min distance {})", fmt::WideToChar { Name(actor) }, source, destination, minDistance);
		actor->FailCombatPath(destination);
		return;
	}
	Path clipped = ClipPath(actor->Pos, path, combatant->movePx);
	if (!clipped) {
		wantedMore = true;
		return;
	}
	ApplyMovementFlags(actor, *combatant);
	Log(COMBAT, "CombatDirector", "{} walks {} of {} units toward {} (speed {})", fmt::WideToChar { Name(actor) },
	    std::min(combatant->movePx, PathFinder::PathCost(actor->Pos, path)), PathFinder::PathCost(actor->Pos, path), destination, actor->GetSpeed());
	walkBudget = combatant->movePx;
	walkCost = PathFinder::PathCost(actor->Pos, clipped);
	walkEnd = clipped.GetLastStep().point;
	walkSpent = 0;
	actor->SetCombatPath(std::move(clipped), minDistance, destination);
	if (combatant->ran) {
		ScenePolish::Get().SpawnSmokePuff(actor->Pos, actor->Pos);
	}
	walkFrom = actor->Pos;
	walkDest = destination;
	step = Step::Walk;
}

bool CombatDirector::PlannedPath::Matches(const Actor* actor, const Point& dest) const
{
	return actorID == actor->GetGlobalID() && from == actor->Pos && destination == dest;
}

Path CombatDirector::PlanPath(const Actor* actor, const Point& destination, unsigned int minDistance) const
{
	if (!actor) return {};
	if (committed.Matches(actor, destination)) return committed.path;
	if (plan.Matches(actor, destination) && plan.minDistance == minDistance) return plan.path;
	Map* map = actor->GetCurrentArea();
	if (!map) return {};
	const ActorPathContext context { static_cast<unsigned int>(actor->circleSize), actor->GetScriptName(), actor->ValidTarget(GA_ONLY_BUMPABLE) };
	Path path = PathFinder::FindPath(map->GetFreshTraversabilityCacheData(), map->tileProps, actor->Pos, destination, context,
					 minDistance, PF_SIGHT | PF_ACTORS_ARE_BLOCKING | PF_EXACT);
	plan = PlannedPath { actor->GetGlobalID(), actor->Pos, destination, minDistance, path };
	return path;
}

void CombatDirector::KeepPlan(const Actor* actor, const Point& destination, unsigned int minDistance, const Path& path) const
{
	committed = PlannedPath { actor->GetGlobalID(), actor->Pos, destination, minDistance, path };
}

void CombatDirector::WalkStep(Actor* actor, Combatant& combatant)
{
	// the path is already clipped to the movement left, so it is walked to its end
	bool arrived = !actor->HasMovementInProgress() || actor->GetRandomBackoff() ||
		actor->GetSpeed() <= 0 || actor->Immobile();
	if (!arrived) {
		Point before = actor->Pos;
		const std::vector<ieDword> threats = ThreatsTo(actor);
		// our walker: GemRB's stepping, driven only from here
		actor->Movable::DoStep(actor->GetSpeed(), core->GetGame()->Ticks);
		int spent = PathFinder::MovementCost(before, actor->Pos);
		const float_t stepX = float_t(actor->Pos.x - before.x);
		const float_t stepY = float_t(actor->Pos.y - before.y) * SEARCHMAP_TILE_WIDTH / SEARCHMAP_TILE_HEIGHT;
		const float_t exactStep = std::sqrt(stepX * stepX + stepY * stepY);
		walkSpent += exactStep;
		combatant.movePx = std::max(0, walkBudget - int(std::lround(walkSpent)));
		if (combatant.ran && spent > 0 && (combatant.movePx % 48) < spent) {
			ScenePolish::Get().SpawnSmokePuff(actor->Pos, before);
		}
		if (CheckOpportunityAttacks(actor, threats)) {
			// caught at the edge of their reach: back to where it stood, the step isn't paid
			actor->MoveTo(before);
			walkSpent -= exactStep;
			combatant.movePx = std::max(0, walkBudget - int(std::lround(walkSpent)));
			return;
		}
		arrived = !actor->HasMovementInProgress() || actor->GetRandomBackoff();
	}
	if (!arrived) return;
	if (actor->Pos == walkEnd) {
		// the whole planned walk: it costs what the preview said
		combatant.movePx = std::max(0, walkBudget - walkCost);
	}

	const char* why = actor->GetRandomBackoff() ? "blocked by someone" : combatant.movePx <= 0 ? "out of movement" :
		actor->PathAbandoned() ? "gave up near the goal" : actor->HasMovementInProgress() ? "can't move" : "arrived";
	Log(COMBAT, "CombatDirector", "{} stops at {} after {} units: {}", fmt::WideToChar { Name(actor) }, actor->Pos,
	    PathFinder::MovementCost(walkFrom, actor->Pos), why);
	if (actor->Pos == walkFrom) {
		blockedAt = actor->Pos;
		blockedDest = walkDest;
	}
	ApplyMovementFlags(actor, combatant);
	// always ends with no path left
	actor->ClearPath(true);
	actor->ResetBackoff();
	step = Step::Act;
	// the action that asked for the walk carries on right away (another leg, the attack ...), so
	// it never stops for a tick between two legs
	ActStep(actor, combatant);
	// a finished path leaves it standing awake (ClearPath); in a fight it stands ready, and one
	// that walks on keeps its walk going instead of flashing a standing frame between the legs
	const unsigned char stance = actor->GetStance();
	if (step == Step::Walk) {
		actor->SetStance((actor->GetInternalFlag() & IF_RUNNING) ? IE_ANI_RUN : IE_ANI_WALK);
	} else if (stance == IE_ANI_WALK || stance == IE_ANI_RUN || stance == IE_ANI_AWAKE) {
		actor->SetStance(IE_ANI_READY);
	}
	NotifyGUI();
}

void CombatDirector::RequestAttackRound(Actor* attacker, Scriptable* target)
{
	Actor* victim = Scriptable::As<Actor>(target);
	if (!Owns(attacker) || !victim) {
		// someone outside the fight goes for a combatant: it joins instead of swinging in real time
		if (victim && IsRunning() && Owns(victim) && attacker->GetCurrentArea() == combatMap && IsAliveCombatant(attacker) && !IsCombatant(attacker)) {
			if (attacker->InParty || ShouldJoin(attacker, PartyOnMap(combatMap))) {
				Join(attacker, true);
			}
			return;
		}
		attacker->PerformAttack(core->GetGame()->GameTime);
		return;
	}
	Combatant* combatant = FindCombatant(attacker->GetGlobalID());
	if (!IsRunning() || !combatant || attacker->GetGlobalID() != activeID || step != Step::Act) {
		Log(COMBAT, "CombatDirector", "{} tried to attack outside its turn", fmt::WideToChar { Name(attacker) });
		return;
	}
	if (!CanAfford(attacker, TBAction::Attack) || combatant->remainingAttacks <= 0) {
		Log(COMBAT, "CombatDirector", "{}: no action left to attack", fmt::WideToChar { Name(attacker) });
		// Run already spent the action: AttackCore thought they were in reach. If they still
		// have movement, ActStep will close instead of stalling in place.
		wantedMore = true;
		return;
	}
	Log(COMBAT, "CombatDirector", "{} attacks {}", fmt::WideToChar { Name(attacker) }, fmt::WideToChar { Name(victim) });

	// one action is one full 2e round of attacks; InitRound also alternates 3/2 APR
	Spend(attacker, TBAction::Attack);
	combatant->attacking = true;
	attacker->InitRound(core->GetGame()->GameTime);
	if (attacker->attackcount > combatant->remainingAttacks) {
		attacker->attackcount = combatant->remainingAttacks;
	}
	if (attacker->attackcount <= 0) {
		FinishRound(attacker, *combatant);
		return;
	}
	StartSwing(attacker, victim);
}

void CombatDirector::StartSwing(Actor* actor, Actor* target)
{
	swingTarget = target->GetGlobalID();
	swingResolved = false;
	swingTicks = 0;
	swingPausing = false;
	blockerID = 0;
	blockerFrozen = false;
	blockSucceeded = false;
	actor->objects.LastTarget = swingTarget;
	actor->objects.LastTargetPersistent = swingTarget;
	actor->FaceTarget(target);

	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (combatant) {
		combatant->toHitMod = TakedownPenalty(combatant->takedown);
	}

	// the dice panel starts rolling now and lands when the swing resolves
	const Actor::HitPrediction hit = actor->PredictHit(target);
	CombatEvent start;
	start.type = CombatEventType::SwingStart;
	start.actor = actor->GetGlobalID();
	start.target = swingTarget;
	start.round = round;
	start.value = hit.valid ? hit.needed : 0;
	start.bonus = hit.thac0;
	start.defense = hit.defense;
	PushEvent(start);

	bool leftOrRight = false;
	const ITMExtHeader* header = actor->GetWeapon(leftOrRight);
	swingRanged = header && (header->AttackType == ITEM_AT_BOW || header->AttackType == ITEM_AT_PROJECTILE);
	actor->SetStance(IE_ANI_READY);
	step = Step::Swing;
	BeginSwingAnimation(actor);
}

void CombatDirector::RestoreSwingSpeed(Actor* actor)
{
	if (swingBaseFps <= 0.0f || !actor || actor->GetGlobalID() != swingSpeedActor) return;
	actor->SetStanceAnimationFPS(swingSpeedStance, static_cast<orient_t>(swingSpeedFace), swingBaseFps);
	swingBaseFps = 0.0f;
	swingSpeedActor = 0;
	takedownPunched = false;
}

void CombatDirector::BeginSwingAnimation(Actor* actor)
{
	if (swingRanged) {
		// GemRB launches the missile on the shooting frame itself
		actor->objects.LastTarget = swingTarget;
		if (!actor->ResolveSwing()) actor->attackcount = 0;
		swingResolved = true;
	} else {
		actor->SetStance(actor->GetAttackStance());
	}
	// the cached animation may still be where an earlier swing was cut off: play it from the top
	actor->RestartStanceAnimation();
	// a previous takedown may still be on this animation if the swing was cut off
	RestoreSwingSpeed(actor);
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!swingRanged && combatant && combatant->takedown != TakedownKind::None) {
		swingBaseFps = actor->GetStanceAnimationFPS();
		swingSpeedActor = actor->GetGlobalID();
		swingSpeedStance = actor->GetStance();
		swingSpeedFace = static_cast<unsigned char>(actor->GetNextFace());
		takedownPunched = false;
		actor->SetStanceAnimationFPS(swingSpeedStance, static_cast<orient_t>(swingSpeedFace), swingBaseFps * TAKEDOWN_CHAMBER);
		PlayCombatSound(actor, "trip");
	}
	if (!swingRanged) {
		Actor* target = combatMap->GetActorByGlobalID(swingTarget);
		StartBlockAnimation(actor, target);
	}
	// the frame shown is still the old stance's until the next draw, so don't trust it yet
	swingLastFrame = -1;
}

void CombatDirector::SwingStep(Actor* actor, Combatant& combatant)
{
	Actor* target = combatMap->GetActorByGlobalID(swingTarget);
	// the beat between two swings, standing ready
	if (swingPausing) {
		if (swingPause > 0) {
			--swingPause;
			return;
		}
		// the dice panel finishes revealing the roll before the next swing
		if (hud.Holding()) return;
		if (actor->attackcount > 0 && IsAliveCombatant(target) && WithinPersonalRange(actor, target, actor->GetWeaponRange(false))) {
			StartSwing(actor, target);
		} else {
			FinishRound(actor, combatant);
		}
		return;
	}
	++swingTicks;
	// until the swing has been drawn once, the frame is still the ready stance's
	if (!actor->StanceAnimationShown() && swingTicks <= SWING_MAX_TICKS) return;
	const int frame = actor->GetStanceFrame();
	const int frames = actor->GetStanceFrameCount();
	const bool attackStance = actor->GetStance() == IE_ANI_ATTACK || actor->GetStance() == IE_ANI_ATTACK_JAB ||
		actor->GetStance() == IE_ANI_ATTACK_SLASH || actor->GetStance() == IE_ANI_ATTACK_BACKSLASH || actor->GetStance() == IE_ANI_SHOOT;

	// the early frames are the pull-back; the strike itself runs fast, and the hit lands in that part
	if (swingBaseFps > 0.0f && !takedownPunched && attackStance && frame >= 0 && frames > 1) {
		const int punchAt = std::max(1, frames * 2 / 5);
		if (frame >= punchAt) {
			actor->SetStanceAnimationFPS(swingSpeedStance, static_cast<orient_t>(swingSpeedFace), swingBaseFps * TAKEDOWN_PUNCH);
			takedownPunched = true;
		}
	}

	if (blockerID && !blockerFrozen) {
		Actor* blocker = combatMap->GetActorByGlobalID(blockerID);
		if (blocker) {
			const int blockHit = SwingHitFrame(blocker->GetStanceFrameCount());
			if (blocker->GetStanceFrame() >= blockHit || swingTicks > SWING_MAX_TICKS / 2) {
				blocker->FreezeStanceAnimation(true);
				blockerFrozen = true;
			}
		}
	}

	TakedownKind resolvedTakedown = TakedownKind::None;
	if (!swingResolved) {
		// melee lands halfway into the swing
		const int hitFrame = SwingHitFrame(frames);
		if (frame < 0 || !attackStance || frame >= hitFrame || swingTicks > SWING_MAX_TICKS) {
			swingResolved = true;
			Log(COMBAT, "CombatDirector", "swing lands on frame {}/{} after {} ticks", frame, frames, swingTicks);
			if (IsAliveCombatant(target) && WithinPersonalRange(actor, target, actor->GetWeaponRange(false))) {
				actor->objects.LastTarget = swingTarget;
				resolvedTakedown = combatant.takedown;
				if (resolvedTakedown != TakedownKind::None) {
					if (!ResolveTakedown(actor, target, resolvedTakedown)) {
						actor->attackcount = 0;
					} else {
						--actor->attackcount;
					}
					combatant.takedown = TakedownKind::None;
					combatant.toHitMod = 0;
				} else if (!actor->ResolveSwing()) {
					actor->attackcount = 0; // it couldn't swing (weapon unusable ...), so the round is lost
				}
				// the damage rides the attack projectile, which GemRB only fires on frame 8 exactly
				if (resolvedTakedown == TakedownKind::None) actor->FireAttackProjectile();
			} else {
				actor->attackcount = 0;
			}
			combatant.remainingAttacks = std::max(0, actor->attackcount);
			FinishBlockAnimation(actor, target, blockSucceeded);
		}
	}

	if (swingResolved && actor->lastSwing.made) {
		const Actor::SwingInfo& info = actor->lastSwing;
		CombatEvent event;
		event.type = CombatEventType::Swing;
		event.actor = actor->GetGlobalID();
		event.target = info.target;
		event.round = round;
		event.roll = info.roll;
		event.bonus = info.bonus;
		event.defense = info.defense;
		event.value = info.damage;
		event.hit = info.hit;
		event.critical = info.critical;
		if (resolvedTakedown != TakedownKind::None) event.text = "takedown";
		else if (blockSucceeded) event.text = "blocked";
		PushEvent(event);
		actor->lastSwing.made = false;
	}

	// the animation ends when it wraps around, stops being an attack, or never reports
	bool ended = frame < 0 || !attackStance || (swingLastFrame >= 0 && frame < swingLastFrame) || swingTicks > SWING_MAX_TICKS;
	swingLastFrame = frame;
	if (!ended || !swingResolved) return;

	// a beat before the next swing, so each one reads as its own blow; after the last one the
	// pause only waits for the dice panel
	RestoreSwingSpeed(actor);
	actor->SetStance(IE_ANI_READY);
	swingPausing = true;
	const bool more = actor->attackcount > 0 && IsAliveCombatant(target) && WithinPersonalRange(actor, target, actor->GetWeaponRange(false));
	swingPause = more ? SwingPauseTicks() : 0;
}

void CombatDirector::FinishRound(Actor* actor, Combatant& combatant)
{
	combatant.attacking = false;
	roundDone = true;
	actor->attackcount = 0;
	actor->SetStance(IE_ANI_READY);
	step = Step::Act;

	Holder<Action> current = actor->GetCurrentAction();
	const std::string& name = ActionName(current.get());
	if (PlayerControlled(actor) || name == "attackoneround") {
		// the player's click was one round; AttackOneRound is too
		if (current) actor->ReleaseCurrentAction();
	} else {
		// the AI keeps its Attack for the next turn: that's how it chases its target
		step = Step::Over;
	}
	NotifyGUI();
}

// ------------------------------------------------------------------------------------------
// reactions, delay, cancel

static bool ActorsAreEnemies(const Actor* a, const Actor* b)
{
	return CombatDirector::AreEnemies(a->GetStat(IE_EA), b->GetStat(IE_EA));
}

static bool HasMeleeWeapon(const Actor* actor)
{
	bool leftOrRight = false;
	const ITMExtHeader* header = actor->GetWeapon(leftOrRight);
	return header && header->AttackType == ITEM_AT_MELEE;
}

std::vector<ieDword> CombatDirector::ThreatsTo(const Actor* mover) const
{
	std::vector<ieDword> threats;
	if (!Setting("Turn Based Opportunity Attacks", 0)) return threats;
	const Combatant* moving = FindCombatant(mover->GetGlobalID());
	if (!moving || moving->withdrawn) return threats;
	for (const Combatant& other : order) {
		if (other.dead || other.reactionUsed || other.globalID == mover->GetGlobalID()) continue;
		const Actor* reactor = combatMap->GetActorByGlobalID(other.globalID);
		if (!IsAliveCombatant(reactor) || !Owns(reactor) || reactor->Immobile()) continue;
		if (reactor->GetStat(IE_STATE_ID) & (STATE_HELPLESS | STATE_SLEEP | STATE_PANIC)) continue;
		const Combatant* otherC = FindCombatant(other.globalID);
		if (otherC && otherC->prone) continue;
		if (!ActorsAreEnemies(reactor, mover) || !HasMeleeWeapon(reactor)) continue;
		if (WithinPersonalRange(reactor, mover, reactor->GetWeaponRange(false))) {
			threats.push_back(other.globalID);
		}
	}
	return threats;
}

bool CombatDirector::CheckOpportunityAttacks(Actor* mover, const std::vector<ieDword>& threatenedBy)
{
	pendingReactors.clear();
	for (ieDword id : threatenedBy) {
		const Actor* reactor = combatMap->GetActorByGlobalID(id);
		if (reactor && !WithinPersonalRange(reactor, mover, reactor->GetWeaponRange(false))) {
			pendingReactors.push_back(id);
			Combatant* combatant = FindCombatant(id);
			if (combatant) combatant->reactionUsed = true;
		}
	}
	if (pendingReactors.empty()) return false;
	mover->SetStance(IE_ANI_READY);
	reactorID = 0;
	reactionSettling = false;
	step = Step::Reaction;
	return true;
}

void CombatDirector::ReactionStep(Actor* mover)
{
	if (reactionSettling) {
		if (hud.Holding()) return;
		reactionSettling = false;
		reactorID = 0;
	}
	Actor* reactor = reactorID ? combatMap->GetActorByGlobalID(reactorID) : nullptr;
	if (!reactor) {
		// the next one in line takes its swing
		reactorID = 0;
		while (!pendingReactors.empty() && !reactor) {
			ieDword id = pendingReactors.front();
			pendingReactors.erase(pendingReactors.begin());
			Actor* candidate = combatMap->GetActorByGlobalID(id);
			if (IsAliveCombatant(candidate) && IsAliveCombatant(mover) && WithinPersonalRange(candidate, mover, candidate->GetWeaponRange(false))) {
				reactor = candidate;
				reactorID = id;
			}
		}
		if (!reactor) {
			// everyone had their go: back to walking, or the turn is over for the dead
			step = IsAliveCombatant(mover) ? Step::Walk : Step::Over;
			if (step == Step::Walk) {
				mover->SetStance((mover->GetInternalFlag() & IF_RUNNING) ? IE_ANI_RUN : IE_ANI_WALK);
			}
			return;
		}
		Log(COMBAT, "CombatDirector", "{} gets an attack of opportunity on {}", fmt::WideToChar { Name(reactor) }, fmt::WideToChar { Name(mover) });
		ShowFloater(reactor, u"Attack of Opportunity!");
		CombatEvent event;
		event.type = CombatEventType::Reaction;
		event.actor = reactorID;
		event.target = mover->GetGlobalID();
		event.round = round;
		PushEvent(event);

		reactor->FaceTarget(mover);
		const Actor::HitPrediction hit = reactor->PredictHit(mover);
		CombatEvent start;
		start.type = CombatEventType::SwingStart;
		start.actor = reactorID;
		start.target = mover->GetGlobalID();
		start.round = round;
		start.value = hit.valid ? hit.needed : 0;
		start.bonus = hit.thac0;
		start.defense = hit.defense;
		PushEvent(start);
		reactor->objects.LastTarget = mover->GetGlobalID();
		reactor->SetStance(reactor->GetAttackStance());
		reactor->RestartStanceAnimation();
		swingTarget = mover->GetGlobalID();
		swingResolved = false;
		swingTicks = 0;
		swingLastFrame = -1;
		return;
	}

	++swingTicks;
	if (!reactor->StanceAnimationShown() && swingTicks <= SWING_MAX_TICKS) return;
	const int frame = reactor->GetStanceFrame();
	const int frames = reactor->GetStanceFrameCount();
	const unsigned char stance = reactor->GetStance();
	const bool attackStance = stance == IE_ANI_ATTACK || stance == IE_ANI_ATTACK_JAB || stance == IE_ANI_ATTACK_SLASH ||
		stance == IE_ANI_ATTACK_BACKSLASH || stance == IE_ANI_SHOOT;
	if (!swingResolved) {
		const int hitFrame = SwingHitFrame(frames);
		if (frame < 0 || !attackStance || frame >= hitFrame || swingTicks > SWING_MAX_TICKS) {
			swingResolved = true;
			// one swing, outside the reactor's own round
			reactor->objects.LastTarget = mover->GetGlobalID();
			reactor->ResolveSingleSwing();
			reactor->FireAttackProjectile();
			const Actor::SwingInfo& info = reactor->lastSwing;
			if (info.made) {
				CombatEvent event;
				event.type = CombatEventType::Swing;
				event.actor = reactorID;
				event.target = info.target;
				event.round = round;
				event.roll = info.roll;
				event.bonus = info.bonus;
				event.defense = info.defense;
				event.value = info.damage;
				event.hit = info.hit;
				event.critical = info.critical;
				event.text = "reaction";
				PushEvent(event);
				reactor->lastSwing.made = false;
			}
		}
	}
	bool ended = frame < 0 || !attackStance || (swingLastFrame >= 0 && frame < swingLastFrame) || swingTicks > SWING_MAX_TICKS;
	swingLastFrame = frame;
	if (!ended || !swingResolved) return;
	reactor->SetStance(IE_ANI_READY);
	reactionSettling = true;
}

bool CombatDirector::DelayTurn()
{
	if (state != State::TurnActive || activeIdx >= order.size()) return false;
	Combatant& combatant = order[activeIdx];
	const Actor* actor = GetActiveActor();
	// only before doing anything, and only if someone is left to go first
	if (!actor || combatant.delayed || combatant.mainActionUsed || combatant.movePx < combatant.maxMovePx || IsBusy(actor)) return false;
	bool othersLeft = std::any_of(order.begin(), order.end(), [&combatant](const Combatant& c) {
		return &c != &combatant && !c.dead && !c.done && !c.delayed;
	});
	if (!othersLeft) return false;
	combatant.delayed = true;
	Log(COMBAT, "CombatDirector", "{} delays its turn", fmt::WideToChar { Name(actor) });
	AdvanceTurn();
	return true;
}

bool CombatDirector::CancelMove()
{
	Actor* actor = GetActiveActor();
	if (!actor || step != Step::Walk) return false;
	actor->ClearPath(true);
	actor->ResetBackoff();
	actor->ClearActions();
	actor->SetStance(IE_ANI_READY);
	step = Step::Act;
	NotifyGUI();
	return true;
}

// ------------------------------------------------------------------------------------------
// action economy

bool CombatDirector::CanAfford(const Actor* actor, TBAction action) const
{
	if (state != State::TurnActive || !actor) return true;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return true;
	if (actor->GetGlobalID() != activeID) return false;

	switch (action) {
		case TBAction::Attack:
			return !combatant->mainActionUsed && !combatant->ran && !combatant->withdrawn && combatant->remainingAttacks > 0;
		case TBAction::Run:
		case TBAction::Withdraw:
		case TBAction::CastSpell:
		case TBAction::UseItem:
		case TBAction::Equip:
			return !combatant->mainActionUsed && !combatant->ran && !combatant->withdrawn;
	}
	return false;
}

void CombatDirector::Spend(const Actor* actor, TBAction action)
{
	if (state != State::TurnActive || !actor) return;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return;

	if (action == TBAction::Run) {
		ApplyRun(*combatant);
	} else if (action == TBAction::Withdraw) {
		ApplyWithdraw(*combatant);
	} else {
		combatant->mainActionUsed = true;
	}
	NotifyGUI();
}

bool CombatDirector::CanSwapWeapon(const Actor* actor) const
{
	if (state != State::TurnActive || !actor) return true;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return true;
	if (actor->GetGlobalID() != activeID) return false;
	return !combatant->freeWeaponSwapUsed || CanAfford(actor, TBAction::Equip);
}

void CombatDirector::SpendWeaponSwap(const Actor* actor)
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

int CombatDirector::GetRemainingMovement(const Actor* actor) const
{
	if (!actor) return 0;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant ? combatant->movePx : 0;
}

// ------------------------------------------------------------------------------------------
// combat maneuvers

void CombatDirector::AllocateAttacks(Combatant& combatant, Actor* actor)
{
	if (!actor) return;
	combatant.remainingAttacks = actor->GetAttacksNextRound();
}

void CombatDirector::ApplyMovementFlags(Actor* actor, const Combatant& combatant) const
{
	if (!actor) return;
	if (combatant.withdrawn) {
		actor->SetInternalFlag(IF_RUNNING, BitOp::NAND);
	} else if (combatant.ran || !HasRunAnim(actor) || PartyAlwaysRuns(actor)) {
		actor->SetInternalFlag(IF_RUNNING, BitOp::OR);
	}
	actor->SetSpeed(false);
}

bool CombatDirector::HasFighterClass(const Actor* actor)
{
	if (!actor) return false;
	// TNO is never a fighter for block/trip: as a fake multiclass he always holds fighter levels
	if (core->HasFeature(GFFlags::PST_STATE_FLAGS) && actor->GetBase(IE_SPECIFIC) == 2) return false;
	if (actor->GetFighterLevel() > 0) return true;
	if (actor->IsWarrior()) return true;
	switch (actor->GetStat(IE_CLASS)) {
		case 2: // FIGHTER
		case 7: // FIGHTER_MAGE
		case 8: // FIGHTER_CLERIC
		case 9: // FIGHTER_THIEF
		case 10: // FIGHTER_MAGE_THIEF
			return true;
		default:
			return false;
	}
}

bool CombatDirector::IsMorte(const Actor* actor)
{
	return actor && actor->GetBase(IE_SPECIFIC) == 9;
}

bool CombatDirector::IsProne(const Actor* actor) const
{
	if (!actor) return false;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant && combatant->prone;
}

bool CombatDirector::IsWithdrawn(const Actor* actor) const
{
	if (!actor) return false;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant && combatant->withdrawn;
}

int CombatDirector::GetRemainingAttacks(const Actor* actor) const
{
	if (!actor) return 0;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant) return 0;
	if (combatant->attacking) {
		Actor* live = combatMap ? combatMap->GetActorByGlobalID(actor->GetGlobalID()) : nullptr;
		return live ? live->attackcount : combatant->remainingAttacks;
	}
	return combatant->remainingAttacks;
}

int CombatDirector::GetBlockStacks(const Actor* actor) const
{
	if (!actor) return 0;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant ? combatant->blockStacks : 0;
}

TakedownKind CombatDirector::GetTakedown(const Actor* actor) const
{
	if (!actor) return TakedownKind::None;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant ? combatant->takedown : TakedownKind::None;
}

int CombatDirector::GetToHitMod(const Actor* actor) const
{
	if (!actor) return 0;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant ? combatant->toHitMod : 0;
}

bool CombatDirector::UseRun(Actor* actor)
{
	if (!actor || !CanAfford(actor, TBAction::Run)) return false;
	Spend(actor, TBAction::Run);
	ApplyMovementFlags(actor, *FindCombatant(actor->GetGlobalID()));
	PlayCombatSound(actor, "sprint");
	ScenePolish::Get().SpawnSmokePuff(actor->Pos, actor->Pos, true);
	ShowFloater(actor, u"Run!");
	Log(COMBAT, "CombatDirector", "{} runs", fmt::WideToChar { Name(actor) });
	return true;
}

bool CombatDirector::UseWithdraw(Actor* actor)
{
	// the player and companions only; hostile and neutral AI never withdraw
	if (!actor || !actor->InParty || !CanAfford(actor, TBAction::Withdraw)) return false;
	Spend(actor, TBAction::Withdraw);
	ApplyMovementFlags(actor, *FindCombatant(actor->GetGlobalID()));
	PlayCombatSound(actor, "withdraw");
	ScenePolish::Get().SpawnDustPuff(actor->Pos);
	ShowFloater(actor, u"Withdraw!");
	Log(COMBAT, "CombatDirector", "{} withdraws", fmt::WideToChar { Name(actor) });
	return true;
}

bool CombatDirector::CanBlock(const Actor* actor) const
{
	if (!IsRunning() || !actor || !HasFighterClass(actor) || IsMorte(actor)) return false;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant && !combatant->dead && !combatant->prone && combatant->remainingAttacks > 0;
}

bool CombatDirector::UseBlock(Actor* actor)
{
	if (!CanBlock(actor)) return false;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant || !ApplyBlock(*combatant)) return false;
	PlayCombatSound(actor, "block");
	ScenePolish::Get().SpawnShieldGlow(actor);
	ShowFloater(actor, u"Block!");
	Log(COMBAT, "CombatDirector", "{} prepares to block ({} stacks, {} attacks left)", fmt::WideToChar { Name(actor) },
	    combatant->blockStacks, combatant->remainingAttacks);
	NotifyGUI();
	return true;
}

bool CombatDirector::CanTrip(const Actor* actor) const
{
	if (!IsRunning() || !actor || actor->GetGlobalID() != activeID || !HasFighterClass(actor)) return false;
	if (!HasMeleeWeapon(actor)) return false;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant || combatant->dead || combatant->prone) return false;
	if (combatant->takedown == TakedownKind::Trip) return true; // click again to cancel
	return CanAfford(actor, TBAction::Attack) && combatant->takedown == TakedownKind::None;
}

bool CombatDirector::CanKnockdown(const Actor* actor) const
{
	if (!IsRunning() || !actor || actor->GetGlobalID() != activeID || actor->InParty) return false;
	if (!HasMeleeWeapon(actor) || actor->GetStat(IE_TOHIT) > 15) return false;
	const Combatant* combatant = FindCombatant(actor->GetGlobalID());
	return combatant && CanAfford(actor, TBAction::Attack) && combatant->takedown == TakedownKind::None;
}

bool CombatDirector::UseTrip(Actor* actor)
{
	if (!CanTrip(actor)) return false;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (combatant->takedown == TakedownKind::Trip) {
		combatant->takedown = TakedownKind::None;
		combatant->toHitMod = 0;
		Log(COMBAT, "CombatDirector", "{} cancels trip", fmt::WideToChar { Name(actor) });
		NotifyGUI();
		return true;
	}
	combatant->takedown = TakedownKind::Trip;
	Log(COMBAT, "CombatDirector", "{} will trip with the first attack", fmt::WideToChar { Name(actor) });
	NotifyGUI();
	return true;
}

bool CombatDirector::CancelPendingTrip(Actor* actor)
{
	if (!actor) return false;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	if (!combatant || combatant->takedown != TakedownKind::Trip || combatant->attacking) return false;
	if (actor->GetCurrentAction() || actor->GetNextAction()) return false; // the attack is on its way
	combatant->takedown = TakedownKind::None;
	combatant->toHitMod = 0;
	Log(COMBAT, "CombatDirector", "{}: trip targeting cancelled", fmt::WideToChar { Name(actor) });
	NotifyGUI();
	return true;
}

bool CombatDirector::UseKnockdown(Actor* actor)
{
	if (!CanKnockdown(actor)) return false;
	Combatant* combatant = FindCombatant(actor->GetGlobalID());
	combatant->takedown = TakedownKind::Knockdown;
	Log(COMBAT, "CombatDirector", "{} will knockdown with the first attack", fmt::WideToChar { Name(actor) });
	NotifyGUI();
	return true;
}

void CombatDirector::StartBlockAnimation(Actor* attacker, Actor* target)
{
	if (!attacker || !target) return;
	Combatant* defender = FindCombatant(target->GetGlobalID());
	if (!defender || defender->blockStacks <= 0 || !HasMeleeWeapon(attacker)) return;
	--defender->blockStacks;
	NotifyGUI();
	blockerID = target->GetGlobalID();
	blockerFrozen = false;
	blockSucceeded = false;
	target->FaceTarget(attacker);
	target->SetStance(target->GetAttackStance());
	target->RestartStanceAnimation();
}

void CombatDirector::FinishBlockAnimation(const Actor* attacker, Actor* target, bool blocked)
{
	if (!target || !blockerID) {
		blockerID = 0;
		blockerFrozen = false;
		return;
	}
	target->FreezeStanceAnimation(false);
	if (blocked) {
		target->ReverseStanceAnimation();
		ScenePolish::Get().SpawnBlockSparks(target, attacker);
		PlayCombatSound(target, "parry");
		ShowFloater(target, u"Blocked!");
	}
	blockerID = 0;
	blockerFrozen = false;
}

bool CombatDirector::TryBlockHit(Actor* attacker, Actor* target, int attackRoll)
{
	blockSucceeded = false;
	if (!attacker || !target || !HasMeleeWeapon(attacker)) return false;
	Combatant* defender = FindCombatant(target->GetGlobalID());
	if (!defender) return false;
	const bool spentThisSwing = blockerID == target->GetGlobalID();
	if (!spentThisSwing) {
		if (defender->blockStacks <= 0) return false;
		--defender->blockStacks;
		NotifyGUI();
	}

	static int sides = gamedata->GetMiscRule("ATTACK_ROLL_DICE_SIDES");
	if (!sides) sides = 20;
	int tohit = 0;
	int damageBonus = 0, speed = 0, criticalBonus = 0, style = 0;
	if (!target->GetCombatDetails(tohit, false, damageBonus, speed, criticalBonus, style, attacker)) {
		return false;
	}
	int blockRoll = target->LuckyRoll(1, sides, 0, LR_CRITICAL);
	constexpr int blockAC = 4;
	bool blockHit = false;
	if (blockRoll == 1) {
		blockHit = false;
	} else if (blockRoll == sides) {
		blockHit = true;
	} else if (Actor::IsReverseToHit()) {
		blockHit = (blockRoll + blockAC) > tohit;
	} else {
		blockHit = (blockRoll + tohit) > blockAC;
	}
	Log(COMBAT, "CombatDirector", "{} blocks with {} vs AC 4 (THAC0 {}); attacker rolled {}",
	    fmt::WideToChar { Name(target) }, blockRoll, tohit, attackRoll);
	if (!blockHit || blockRoll >= attackRoll) return false;
	blockSucceeded = true;
	return true;
}

bool CombatDirector::ResolveTakedown(Actor* attacker, Actor* target, TakedownKind kind)
{
	if (!attacker || !target) return false;

	int tohit = 0;
	int damageBonus = 0, speed = 0, criticalBonus = 0, style = 0;
	if (!attacker->GetCombatDetails(tohit, false, damageBonus, speed, criticalBonus, style, target)) {
		return false;
	}
	static int sides = gamedata->GetMiscRule("ATTACK_ROLL_DICE_SIDES");
	if (!sides) sides = 20;
	int roll = attacker->LuckyRoll(1, sides, 0, LR_CRITICAL);
	int defense = target->GetDefense(0, WEAPON_MELEE, attacker);
	int rollMod = Actor::IsReverseToHit() ? defense : tohit;
	bool hit = roll != 1 && ((roll == sides) || (roll + rollMod) > (Actor::IsReverseToHit() ? tohit : defense));
	if (target->Immobile() || (target->GetStat(IE_STATE_ID) & STATE_SLEEP) || IsProne(target)) {
		hit = roll != 1;
	}

	attacker->lastSwing = Actor::SwingInfo();
	attacker->lastSwing.made = true;
	attacker->lastSwing.target = target->GetGlobalID();
	attacker->lastSwing.roll = roll;
	attacker->lastSwing.bonus = rollMod;
	attacker->lastSwing.defense = Actor::IsReverseToHit() ? tohit : defense;
	attacker->lastSwing.hit = hit;
	attacker->PlaySwingSound(attacker->weaponInfo[0]);

	if (hit && TryBlockHit(attacker, target, roll)) {
		hit = false;
		attacker->lastSwing.hit = false;
	}

	Log(COMBAT, "CombatDirector", "{} takedown roll {} vs {} -> {}", fmt::WideToChar { Name(attacker) },
	    roll, attacker->lastSwing.defense, hit ? "hit" : "miss");
	if (!hit) {
		ShowFloater(target, TakedownResultText(kind, false));
		Log(COMBAT, "CombatDirector", "{}: takedown missed", fmt::WideToChar { Name(attacker) });
		return true;
	}

	// a hit with no damage and no bleeding: the pain of being caught off-balance
	target->PlayHitSound(core->GetResDataINI(), DAMAGE_CRUSHING, false);
	target->GetHit(0);

	target->SetInternalFlag(IF_USEDSAVE, BitOp::OR);
	target->RollSaves();
	const bool saved = target->GetSavingThrow(2, 0); // vs death
	if (saved) {
		ShowFloater(target, TakedownResultText(kind, false));
		Log(COMBAT, "CombatDirector", "{}: takedown hit, {} kept footing", fmt::WideToChar { Name(attacker) }, fmt::WideToChar { Name(target) });
		return true;
	}

	Combatant* victim = FindCombatant(target->GetGlobalID());
	if (victim) KnockProne(target, *victim);
	ShowFloater(target, TakedownResultText(kind, true));
	return true;
}

void CombatDirector::KnockProne(Actor* target, Combatant& combatant)
{
	combatant.prone = true;
	PlayProneAnimation(target, false);
	Log(COMBAT, "CombatDirector", "{} is knocked prone ({})", fmt::WideToChar { Name(target) },
	    HasGetUpAnimation(target) ? "get-up reversed" : "death");
}

void CombatDirector::CloseOnEnemy(Actor* actor, Actor* enemy)
{
	if (!actor || !enemy || step != Step::Act) return;
	unsigned int range = actor->GetWeaponRange(false);
	if (WithinPersonalRange(actor, enemy, range)) return;
	float_t angle = AngleFromPoints(actor->Pos, enemy->Pos);
	RequestPath(actor, actor->Pos, enemy->Pos, int(Feet2Pixels(int(range), angle)), 0);
}

void CombatDirector::StandUp(Actor* actor, Combatant& combatant)
{
	combatant.mainActionUsed = true;
	combatant.remainingAttacks = 0;
	const bool hasGetUp = HasGetUpAnimation(actor);
	PlayProneAnimation(actor, true);
	int ticks = actor->StanceAnimationTicks(ProneAnimStance(hasGetUp));
	combatant.standTicks = unsigned(std::max(6, ticks));
	Log(COMBAT, "CombatDirector", "{} stands up ({}) and loses an action", fmt::WideToChar { Name(actor) },
	    hasGetUp ? "get-up" : "death reversed");
}

void CombatDirector::ChooseAIManeuvers(Actor* actor, Combatant& combatant)
{
	if (!actor || PlayerControlled(actor)) return;
	// Run spends the action, so it only closes a melee gap a walk cannot.
	// Already in reach, or close enough to walk in and attack, they keep the action.
	// Withdraw is only for the player and companions; the AI never takes it.
	const Action* intent = actor->GetCurrentAction().get();
	if (!intent) intent = actor->GetNextAction().get();
	const std::string& intentName = ActionName(intent);
	const bool attacking = intentName.rfind("attack", 0) == 0 || intentName == "groupattack";
	const bool melee = attacking && HasMeleeWeapon(actor);

	Actor* enemy = NearestEnemy(actor, combatMap, order);
	const bool inMelee = enemy && melee && WithinPersonalRange(actor, enemy, actor->GetWeaponRange(false));

	if (melee && enemy && !inMelee && CanAfford(actor, TBAction::Run)) {
		const unsigned int reach = unsigned(Feet2Pixels(int(actor->GetWeaponRange(false)), AngleFromPoints(actor->Pos, enemy->Pos)));
		// personal gap, same measure as the attack range: center distance counts the
		// bodies twice and made them run when they were already close enough to walk in
		const unsigned int gap = PersonalDistance(actor, enemy);
		const unsigned int budget = unsigned(std::max(0, combatant.movePx));
		if (gap > reach + budget) UseRun(actor);
	}

	// Fighters (not Morte) sometimes put an extra attack into Block
	if (melee && CanBlock(actor) && combatant.remainingAttacks > 1 && RAND(1, 100) <= 25) {
		UseBlock(actor);
	}

	// First swing: trip (fighters) or knockdown (THAC0 15-) at random when already in melee
	if (inMelee && combatant.takedown == TakedownKind::None && RAND(1, 100) <= 20) {
		if (CanKnockdown(actor)) UseKnockdown(actor);
		else if (CanTrip(actor)) UseTrip(actor);
	}
}

// ------------------------------------------------------------------------------------------
// events

// miss/fumble over the attacker; damage numbers come from Actor::Damage on the wounded
static void ShowSwingFloater(const CombatEvent& event)
{
	if (event.type != CombatEventType::Swing || !Setting("Turn Based Floating Text", 1)) return;
	if (event.hit || event.text == "blocked" || event.text == "takedown") return;
	const Map* map = core->GetGame()->GetCurrentArea();
	Actor* attacker = map ? map->GetActorByGlobalID(event.actor) : nullptr;
	if (!attacker) return;
	CombatHud::NotifyFloater(attacker->GetGlobalID(), event.roll == 1 ? u"Fumble" : u"Miss");
}

void CombatDirector::PushEvent(CombatEvent event)
{
	ShowSwingFloater(event);
	if (event.type == CombatEventType::SwingStart || event.type == CombatEventType::Swing || event.type == CombatEventType::CombatEnd) {
		const Map* map = combatMap ? combatMap : core->GetGame()->GetCurrentArea();
		const Actor* a = map ? map->GetActorByGlobalID(event.actor) : nullptr;
		const Actor* t = map ? map->GetActorByGlobalID(event.target) : nullptr;
		hud.OnEvent(event, Name(a), Name(t));
	}
	// nobody reads them without the gui; keep the feed bounded
	if (events.size() > 256) {
		events.erase(events.begin(), events.begin() + 128);
	}
	events.push_back(std::move(event));
}

std::vector<CombatEvent> CombatDirector::TakeEvents()
{
	std::vector<CombatEvent> taken;
	taken.swap(events);
	return taken;
}

void CombatDirector::NotifyGUI() const
{
	core->SetEventFlag(EF_TURNORDER);
}

}
