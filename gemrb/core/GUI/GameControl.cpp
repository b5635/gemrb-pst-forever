// SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

#include "GUI/GameControl.h"

#include "damages.h"
#include "ie_cursors.h"
#include "ie_stats.h"

#include "CharAnimations.h"
#include "DialogHandler.h"
#include "DisplayMessage.h"
#include "GUIScriptInterface.h"
#include "Game.h"
#include "GameData.h"
#include "GlobalTimer.h"
#include "Interface.h"
#include "KeyMap.h"
#include "Map.h"
#include "PathFinder.h"
#include "RNG.h"
#include "ScenePolish.h"
#include "ScriptEngine.h"
#include "TileMap.h"

#include "GUI/Button.h"
#include "GUI/EventMgr.h"
#include "GUI/TextArea.h"
#include "GUI/WindowManager.h"
#include "GameScript/GSUtils.h"
#include "Scriptable/Container.h"
#include "Spell.h"
#include "Effect.h"
#include <map>
#include "TurnBasedCombat/CombatHud.h"
#include "GUI/TextSystem/Font.h"
#include "Scriptable/Door.h"
#include "Scriptable/InfoPoint.h"
#include "Video/Video.h"
#include "fmt/ranges.h"

#include <array>
#include <cmath>

namespace GemRB {

constexpr uint8_t FORMATIONSIZE = 10;
using formation_t = std::array<Point, FORMATIONSIZE>;

class Formations {
	std::vector<formation_t> formations;

	Formations() noexcept
	{
		//TODO:
		//There could be a custom formation which is saved in the save game
		//alternatively, all formations could be saved in some compatible way
		//so it doesn't cause problems with the original engine
		AutoTable tab = gamedata->LoadTable("formatio");
		if (!tab) {
			// fallback
			formations.emplace_back();
			return;
		}
		auto formationcount = tab->GetRowCount();
		formations.resize(formationcount);
		for (unsigned int i = 0; i < formationcount; i++) {
			for (uint8_t j = 0; j < FORMATIONSIZE; j++) {
				Point p(tab->QueryFieldSigned<int>(i, j * 2), tab->QueryFieldSigned<int>(i, j * 2 + 1));
				formations[i][j] = p;
			}
		}
	}

public:
	static const formation_t& GetFormation(size_t formation) noexcept
	{
		static const Formations formations;
		formation = std::min(formation, formations.formations.size() - 1);
		return formations.formations[formation];
	}
};

static const ResRef TestSpell = "SPWI207";

uint32_t GameControl::DebugFlags = 0;
uint8_t GameControl::DebugPropVal = 0;

static Actor* GetMainSelectedActor()
{
	auto actor = core->GetFirstSelectedPC(false);
	if (actor) return actor;
	return core->GetFirstSelectedActor();
}

//If one of the actors has tracking on, the gamecontrol needs to display
//arrow markers on the edges to point at detected monsters
//tracterID is the tracker actor's global ID
//distance is the detection distance
void GameControl::SetTracker(const Actor* actor, ieDword dist)
{
	trackerID = actor->GetGlobalID();
	distance = dist;
}

GameControl::GameControl(const Region& frame)
	: View(frame), viewport(Point { 0, 0 }, frame.size)
{
	this->AlwaysRun = core->GetDictionary().Get("Always Run", 0);

	ResetTargetMode();
	SetCursor(nullptr);

	int lookup = core->GetDictionary().Get("Center", 0);
	if (lookup) {
		screenFlags.Set(ScreenFlags::AlwaysCenter);
	}
	// the game always starts paused so nothing happens till we are ready
	dialoghandler = std::make_unique<DialogHandler>();

	EventMgr::EventCallback cb = METHOD_CALLBACK(&GameControl::OnGlobalMouseMove, this);
	eventMonitors[0] = EventMgr::RegisterEventMonitor(cb, Event::MouseMoveMask);
	EventMgr::EventCallback cb2 = METHOD_CALLBACK(&GameControl::DispatchEvent, this);
	eventMonitors[1] = EventMgr::RegisterEventMonitor(cb2, Event::KeyDownMask);
}

GameControl::~GameControl()
{
	for (unsigned long eventMonitor : eventMonitors) {
		EventMgr::UnRegisterEventMonitor(eventMonitor);
	}
}

//returns a single point offset for a formation
//formation: the formation type
//pos: the actor's slot ID
Point GameControl::GetFormationOffset(size_t formation, uint8_t pos) const
{
	pos = std::min<uint8_t>(pos, FORMATIONSIZE - 1);
	return Formations::GetFormation(formation)[pos];
}

Point GameControl::GetFormationPoint(const Point& origin, size_t pos, float_t angle, const std::vector<Point>& exclude) const
{
	Point vec;

	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();
	assert(area);

	static constexpr int radius = 36 / 2; // 36 diameter is copied from make_formation.py
	const auto& formationid = game->GetFormation();
	const auto& formation = Formations::GetFormation(formationid);

	Point stepVec;
	int direction = (pos % 2 == 0) ? 1 : -1;

	/* Correct for the innate orientation of the points.  */
	angle += M_PI_2;

	if (pos < FORMATIONSIZE) {
		// calculate new coordinates by rotating formation around (0,0)
		vec = RotatePoint(formation[pos], angle);
		stepVec.y = radius;
	} else {
		// create a line formation perpendicular to the formation start point and beginning at the last point
		// of the formation table. Alternate between +90 degrees and -90 degrees to keep it balanced
		// the formation table is created along the x axis starting at (0,0)
		Point p = formation[FORMATIONSIZE - 1];
		vec = RotatePoint(p, angle);
		stepVec.x = radius * direction;
	}

	vec.y *= 0.75f; // isometric projection
	Point dest = vec + origin;
	int step = 0;
	constexpr int maxStep = 4;
	float_t stepAngle = 0.0;
	const Point& start = vec;

	auto NextDest = [&]() {
		// adjust the point if the actor cant get to `dest`
		// we do this by sweeping an M_PI arc a `radius` (stepVec) away from the point
		// and oriented according to `direction`
		// if nothing is found, reset to `start` and increase the `stepVec` and sweep again
		// each incremental sweep step the `stepAngle` increment shrinks because we have more area to fit
		// if nothing is found after `maxStep` sweeps we just give up and leave it to the path finder to work out

		// FIXME: we should precalculate these into a table and use step as an index
		// there is a precission/rounding problem here with comparing against M_PI
		// and we may not use one of the arc end points
		stepAngle += (M_PI_4 / (step + 1)) * direction;
		if (stepAngle > M_PI || stepAngle < -M_PI) {
			++step;
			stepAngle = 0.0;
			if (stepVec.y != 0) {
				stepVec.y += radius;
			} else {
				stepVec.x += radius * direction;
			}
		}

		Point rotated = RotatePoint(stepVec, angle + stepAngle);
		rotated.y *= 0.75f; // isometric projection
		return origin + start + rotated;
	};

	while (step < maxStep) {
		auto it = std::find_if(exclude.begin(), exclude.end(), [&](const Point& p) {
			// look for points within some radius
			return p.IsWithinRadius(radius, dest);
		});

		if (it != exclude.end()) {
			dest = NextDest();
			continue;
		}

		if (area->IsExplored(dest) && !(area->GetBlocked(dest) & (PathMapFlags::PASSABLE | PathMapFlags::ACTOR))) {
			dest = NextDest();
			continue;
		}

		break;
	}

	if (step == maxStep) {
		// we never found a suitable point
		// to garauntee a point that is reachable just fall back to origin
		// let the pathfinder sort it out
		return origin;
	}

	return dest;
}

GameControl::FormationPoints GameControl::GetFormationPoints(const Point& origin, const std::vector<Actor*>& actors,
							     float_t angle) const
{
	FormationPoints formation;
	for (size_t i = 0; i < actors.size(); ++i) {
		formation.emplace_back(GetFormationPoint(origin, i, angle, formation));
	}
	return formation;
}

void GameControl::DrawFormation(const std::vector<Actor*>& actors, const Point& formationPoint, float_t angle) const
{
	std::vector<Point> formationPoints = GetFormationPoints(formationPoint, actors, angle);
	for (size_t i = 0; i < actors.size(); ++i) {
		DrawTargetReticle(actors[i], formationPoints[i] - viewport.origin);
	}
}

void GameControl::ClearMouseState()
{
	isSelectionRect = false;
	isFormationRotation = false;

	SetCursor(nullptr);
}

// generate an action to do the actual movement
// only PST supports RunToPoint
void GameControl::CreateMovement(Actor* actor, const Point& p, bool append, bool tryToRun) const
{
	if (TurnBasedForbids(actor)) return;
	Holder<Action> action;
	tryToRun = tryToRun || AlwaysRun;

	if (append) {
		action = GenerateAction(fmt::format("AddWayPoint([{}.{}])", p.x, p.y));
		assert(action);
	} else {
		//try running (in PST) only if not encumbered
		if (tryToRun && CanRun(actor)) {
			action = GenerateAction(fmt::format("RunToPoint([{}.{}])", p.x, p.y));
		}

		// check again because GenerateAction can fail (non PST)
		if (!action) {
			action = GenerateAction(fmt::format("MoveToPoint([{}.{}])", p.x, p.y));
			if (overMe && overMe->Type == ST_TRAVEL) {
				// gemrb extension to make travel through nearly blocked regions less painful
				action->int0Parameter = MAX_TRAVELING_DISTANCE / 10; // empirical
			}
		}
	}

	actor->CommandActor(std::move(action), !append);
	actor->Destination = p; // just to force target reticle drawing if paused
}

// can we handle it (no movement impairments)?
bool GameControl::CanRun(const Actor* actor) const
{
	if (!actor) return false;
	static bool hasRun = GenerateActionDirect("RunToPoint([0.0])", actor) != nullptr;
	if (!hasRun) return false;
	return actor->GetEncumbranceFactor(true) == 1;
}

bool GameControl::ShouldRun(const Actor* actor) const
{
	return CanRun(actor) && AlwaysRun;
}

// Draws arrow markers along the edge of the game window
void GameControl::DrawArrowMarker(const Point& p, const Color& color) const
{
	const WindowManager* wm = core->GetWindowManager();
	auto lock = wm->DrawHUD();

	const Region& bounds = Viewport();
	if (bounds.PointInside(p)) return;

	orient_t dir = GetOrient(bounds.Center(), p);
	Holder<Sprite2D> arrow = core->GetScrollCursorSprite(dir, 0);

	const Point& dp = bounds.Intercept(p) - bounds.origin;
	VideoDriver->BlitGameSprite(arrow, dp, BlitFlags::COLOR_MOD | BlitFlags::BLENDED, color);
}

void GameControl::DrawTargetReticle(uint16_t size, const Color& color, const Point& p, int radialOffset) const
{
	uint8_t offset = GlobalColorCycle.Step() >> 1;
	BasePoint offsetH = BasePoint(offset, 0);
	BasePoint offsetV = BasePoint(0, offset);

	/* segments should not go outside selection radius */
	uint16_t xradius = (size * 4) - 5 + radialOffset;
	uint16_t yradius = (size * 3) - 5 + radialOffset;
	const Size s(xradius * 2, yradius * 2);
	const Region r(p - s.Center(), s);

	std::vector<BasePoint> points = PlotEllipse(r);
	assert(points.size() % 4 == 0);

	// a line bisecting the ellipse diagonally
	const Point adj(size + 1, 0);
	BasePoint b1 = r.origin - adj;
	BasePoint b2 = r.Maximum() + adj;

	size_t i = 0;
	// points are ordered per quadrant, so we can process 4 each iteration
	// at first, 2 points will be the left segment and 2 will be the right segment
	for (; i < points.size(); i += 4) {
		// each point is in a different quadrant
		const BasePoint& q1 = points[i];
		const BasePoint& q2 = points[i + 1];
		const BasePoint& q3 = points[i + 2];
		const BasePoint& q4 = points[i + 3];

		if (left(b1, b2, q1)) {
			// remaining points are top and bottom segments
			break;
		}

		VideoDriver->DrawPoint(q1 + offsetH, color);
		VideoDriver->DrawPoint(q2 - offsetH, color);
		VideoDriver->DrawPoint(q3 - offsetH, color);
		VideoDriver->DrawPoint(q4 + offsetH, color);
	}

	assert(i < points.size() - 4);

	// the current points are the ends of the side segments
	BasePoint p2(p);
	VideoDriver->DrawLine(points[i++] + offsetH, p2 + offsetH, color); // begin right segment
	VideoDriver->DrawLine(points[i++] - offsetH, p2 - offsetH, color); // begin left segment
	VideoDriver->DrawLine(points[i++] - offsetH, p2 - offsetH, color); // end left segment
	VideoDriver->DrawLine(points[i++] + offsetH, p2 + offsetH, color); // end right segment

	b1 = r.origin + adj;
	b2 = r.Maximum() - adj;

	// skip the void between segments
	for (; i < points.size(); i += 4) {
		if (left(b1, b2, points[i])) {
			break;
		}
	}

	// the current points are the ends of the top/bottom segments
	VideoDriver->DrawLine(points[i++] + offsetV, p2 + offsetV, color); // begin top segment
	VideoDriver->DrawLine(points[i++] + offsetV, p2 + offsetV, color); // end top segment
	VideoDriver->DrawLine(points[i++] - offsetV, p2 - offsetV, color); // begin bottom segment
	VideoDriver->DrawLine(points[i++] - offsetV, p2 - offsetV, color); // end bottom segment

	// remaining points are top/bottom segments
	for (; i < points.size(); i += 4) {
		const BasePoint& q1 = points[i];
		const BasePoint& q2 = points[i + 1];
		const BasePoint& q3 = points[i + 2];
		const BasePoint& q4 = points[i + 3];

		VideoDriver->DrawPoint(q1 + offsetV, color);
		VideoDriver->DrawPoint(q2 + offsetV, color);
		VideoDriver->DrawPoint(q3 - offsetV, color);
		VideoDriver->DrawPoint(q4 - offsetV, color);
	}
}

void GameControl::DrawTargetReticle(const Movable* target, const Point& p, int offset) const
{
	int size = target->CircleSize2Radius();
	const Color& green = target->selectedColor;
	const Color& color = (target->Over) ? GlobalColorCycle.Blend(target->overColor, green) : green;

	DrawTargetReticle(size, color, p, offset);
}

void GameControl::WillDraw(const Region& /*drawFrame*/, const Region& /*clip*/)
{
	auto scale = GetScalePercent();
	if (scale != 100 && !SceneCamera()) {
		auto screenSize = VideoDriver->GetScreenSize();
		screenSize.w = (screenSize.w * scale) / 100;
		screenSize.h = (screenSize.h * scale) / 100;
		Region r(Point {}, screenSize);
		VideoDriver->SetScreenClip(&r, false);
	}

	UpdateCursor();

	bool update_scripts = !(DialogueFlags & DF_FREEZE_SCRIPTS);

	// handle keeping the actor in the spotlight, but only when unpaused
	if (screenFlags.Test(ScreenFlags::AlwaysCenter) && update_scripts) {
		const Actor* star = core->GetFirstSelectedActor();
		if (star) {
			vpVector = star->Pos - viewport.origin - Point(frame.w / 2, frame.h / 2);
		}
	}

	// in turn based combat the camera follows whoever is walking on their turn
	const Game* game = core->GetGame();
	if (game && game->combat.IsRunning() && update_scripts && !core->timer.ViewportIsMoving()) {
		const Actor* active = game->combat.GetActiveActor();
		if (active && active->InMove() && active->GetCurrentArea() == CurrentArea() && CurrentArea()->IsVisible(active->Pos)) {
			Point center = viewport.origin + Point(viewport.w / 2, viewport.h / 2);
			// only once it strays from the middle, so short steps don't make it swim
			if (Distance(center, active->Pos) > viewport.h / 4) {
				Point step = active->Pos - center;
				step.x /= 8;
				step.y /= 8;
				MoveViewportTo(viewport.origin + step, false);
			}
		}
	}

	// Prevent key scrolling from continuing when another window opens
	if (scrollKeysActive && !IsReceivingEvents()) {
		scrollKeysDown = scrollKeysActive = 0;
		vpVector.reset();
	}

	if (!vpVector.IsZero() && MoveViewportTo(viewport.origin + vpVector, false)) {
		if ((Flags() & IgnoreEvents) == 0 && !scrollKeysActive && core->GetMouseScrollSpeed() && !screenFlags.Test(ScreenFlags::AlwaysCenter)) {
			orient_t orient = GetOrient(Point(), vpVector);
			// set these cursors on game window so they are universal
			window->SetCursor(core->GetScrollCursorSprite(orient, numScrollCursor));

			numScrollCursor = (numScrollCursor + 1) % 15;
		}
	} else if (!window->IsDisabled()) {
		window->SetCursor(nullptr);
	}

	UpdateCamera();

	const Map* area = CurrentArea();
	if (!area) return;

	int flags = GA_NO_DEAD | GA_NO_UNSCHEDULED | GA_SELECT | GA_NO_ENEMY | GA_NO_NEUTRAL;
	auto ab = area->GetActorsInRect(SelectionRect(), flags);

	std::vector<Actor*>::iterator it = highlighted.begin();
	for (; it != highlighted.end(); ++it) {
		Actor* act = *it;
		act->SetOver(false);
	}

	highlighted.clear();
	for (Actor* actor : ab) {
		if (actor->GetStat(IE_EA) > EA_CONTROLLABLE) continue;
		actor->SetOver(true);
		highlighted.push_back(actor);
	}
}

// FIXME: some of this should happen during mouse events
void GameControl::OutlineInfoPoints() const
{
	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();

	for (const auto& infoPoint : area->TMap->GetInfoPoints()) {
		infoPoint->Highlight = false;

		if (infoPoint->VisibleTrap(0)) {
			if (overMe == infoPoint.get() && targetMode != TargetMode::None) {
				infoPoint->outlineColor = displaymsg->GetColor(GUIColors::HOVERTARGETABLE);
			} else {
				infoPoint->outlineColor = displaymsg->GetColor(GUIColors::TRAPCOLOR);
			}
			infoPoint->Highlight = true;
			continue;
		}
	}
}

// FIXME: some of this should happen during mouse events
void GameControl::OutlineDoors() const
{
	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();

	for (const auto& door : area->TMap->GetDoors()) {
		door->Highlight = false;
		if (door->Flags & DOOR_HIDDEN) {
			continue;
		}

		if (door->Flags & DOOR_SECRET) {
			if (door->Flags & DOOR_FOUND) {
				door->Highlight = true;
				door->outlineColor = displaymsg->GetColor(GUIColors::HIDDENDOOR);
			} else {
				continue;
			}
		}

		// traps always take precedence
		if (door->VisibleTrap(0)) {
			door->Highlight = true;
			door->outlineColor = displaymsg->GetColor(GUIColors::TRAPCOLOR);
			continue;
		}

		if (overMe != door.get()) continue;

		door->Highlight = true;
		if (targetMode != TargetMode::None) {
			if (door->Visible() && door->IsLocked()) {
				// only highlight targetable doors
				door->outlineColor = displaymsg->GetColor(GUIColors::HOVERTARGETABLE);
			}
		} else if (!(door->Flags & DOOR_SECRET)) {
			// mouse over, not in target mode, no secret door
			door->outlineColor = displaymsg->GetColor(GUIColors::HOVERDOOR);
		}
	}
}

// FIXME: some of this should happen during mouse events
void GameControl::OutlineContainers() const
{
	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();

	for (const auto& container : area->TMap->GetContainers()) {
		if (container->Flags & CONT_DISABLED) {
			continue;
		}

		if (overMe == container.get()) {
			container->Highlight = true;
			if (targetMode == TargetMode::None) {
				container->outlineColor = displaymsg->GetColor(GUIColors::HOVERCONTAINER);
			} else if (container->IsLocked()) {
				container->outlineColor = displaymsg->GetColor(GUIColors::HOVERTARGETABLE);
			}
		}

		// traps always take precedence
		if (container->VisibleTrap(0)) {
			container->Highlight = true;
			container->outlineColor = displaymsg->GetColor(GUIColors::TRAPCOLOR);
		}
	}
}

void GameControl::DrawTrackingArrows()
{
	if (!trackerID) return;

	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();
	const Actor* actor = area->GetActorByGlobalID(trackerID);
	if (actor) {
		std::vector<Actor*> monsters = area->GetAllActorsInRadius(actor->Pos, GA_NO_DEAD | GA_NO_LOS | GA_NO_UNSCHEDULED, distance);
		for (const auto& monster : monsters) {
			if (monster->IsInExtendedParty()) continue;
			if (monster->GetStat(IE_NOTRACKING)) continue;
			DrawArrowMarker(monster->Pos, ColorBlack);
		}
	} else {
		trackerID = 0;
	}
}

/** Draws the Control on the Output Display */
void GameControl::DrawSelf(const Region& screen, const Region& /*clip*/)
{
	const Game* game = core->GetGame();
	Map* area = game->GetCurrentArea();
	if (!area) return;

	OutlineInfoPoints();
	OutlineDoors();
	OutlineContainers();

	uint32_t tmpflags = DebugFlags;
	if (EventMgr::ModState(GEM_MOD_ALT)) {
		tmpflags |= DEBUG_SHOW_CONTAINERS | DEBUG_SHOW_DOORS;
	}
	UpdateTurnPreview();

	// with a scene transform the map is drawn in map units at 1:1 from an integer
	// origin; the driver applies zoom and the sub-pixel rest of the camera.
	// Everything in here sees the drawn viewport, not the logical one
	const Region logicalViewport = viewport;
	const bool scene = SceneCamera() && camera.scale > 0.0f;
	if (scene) {
		float s = camera.scale;
		// phase 5: smooth script / impact shake, drawn only (picking keeps the steady camera)
		float shx = 0.0f, shy = 0.0f;
		ScenePolish::Get().ShakeOffset(shx, shy);
		float cx = camera.x + shx, cy = camera.y + shy;
		int ox = int(std::floor(cx));
		int oy = int(std::floor(cy));
		float fx = cx - float(ox);
		float fy = cy - float(oy);
		viewport = Region(ox, oy, int(std::ceil(frame.w * s + fx)) + 1, int(std::ceil(frame.h * s + fy)) + 1);
		float zoom = 1.0f / s;
		VideoDriver->BeginScene(zoom, -fx * zoom, -fy * zoom, Region(Point(), frame.size));
	}

	//drawmap should be here so it updates fog of war
	area->DrawMap(viewport, core->GetFogRenderer(), tmpflags);

	DrawTrackingArrows();

	if (lastActorID && !(DialogueFlags & DF_FREEZE_SCRIPTS)) {
		const Actor* actor = GetLastActor();
		if (actor) {
			DrawArrowMarker(actor->Pos, ColorGreen);
		}
	}

	// Draw selection rect
	if (isSelectionRect) {
		Region r = SelectionRect();
		r.x -= viewport.origin.x;
		r.y -= viewport.origin.y;
		VideoDriver->DrawRect(r, ColorGreen, false);
	}

	if (scene) {
		VideoDriver->EndScene();
		viewport = logicalViewport;
	}

	DrawCombatOverlays(screen);

	if (core->HasFeature(GFFlags::ONSCREEN_TEXT) && !DisplayText.empty()) {
		Font::PrintColors colors = { displaymsg->GetColor(GUIColors::FLOAT_TXT_INFO), ColorBlack };
		core->GetTextFont()->Print(screen, DisplayText, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_MIDDLE, colors);
		if (!(DialogueFlags & DF_FREEZE_SCRIPTS)) {
			// just replicating original engine behaviour
			if (DisplayTextTime == 0) {
				SetDisplayText(u"", 0);
			} else {
				DisplayTextTime--;
			}
		}
	}
}

void GameControl::DrawTargetReticles() const
{
	const Point& gameMousePos = GameMousePos();
	const Game* game = core->GetGame();
	if (isFormationRotation) {
		float_t angle = AngleFromPoints(gameMousePos, gameClickPoint);
		DrawFormation(game->selected, gameClickPoint, angle);
		return;
	}

	DrawTurnPreview();

	for (const auto& selectee : game->selected) {
		assert(selectee);
		if (!selectee->ShouldDrawReticle()) continue;

		// any waypoints to draw?
		const Path& path = selectee->GetPath();
		for (size_t i = 0; i < path.Size(); i++) {
			const PathNode& step = path.GetStep(i);
			if (!step.waypoint) continue;
			Point wp = step.point - viewport.origin;
			DrawTargetReticle(selectee, wp);
		}
		DrawTargetReticle(selectee, selectee->Destination - viewport.origin); // always draw last step
	}
}

Actor* GameControl::GetTurnBasedActor() const
{
	const Game* game = core->GetGame();
	if (!game || !game->combat.IsRunning()) return nullptr;
	Actor* actor = game->combat.GetActiveActor();
	if (!actor || !actor->InParty || actor->GetCurrentArea() != CurrentArea()) return nullptr;
	return actor;
}

bool GameControl::TurnBasedForbids(const Actor* source) const
{
	const Game* game = core->GetGame();
	if (!game || !source || !game->combat.IsRunning()) return false;
	return source != game->combat.GetActiveActor();
}

static bool IsTurnBasedBusy(const Actor* actor)
{
	return core->GetGame()->combat.IsBusy(actor);
}

// how many cells the dimming outside the reach takes to fade in
static constexpr int SHADE_STEPS = 4;

// distance (in cells, capped) of every cell around the reach to the nearest reachable one
static PathFinder::ReachArea BuildReachShade(const PathFinder::ReachArea& reach)
{
	PathFinder::ReachArea shade;
	if (reach.Empty()) return shade;
	shade.corner = SearchmapPoint(reach.corner.x - SHADE_STEPS, reach.corner.y - SHADE_STEPS);
	shade.w = reach.w + 2 * SHADE_STEPS;
	shade.h = reach.h + 2 * SHADE_STEPS;
	shade.cells.assign(size_t(shade.w * shade.h), uint8_t(SHADE_STEPS));
	std::vector<int> frontier;
	for (int ly = 0; ly < shade.h; ++ly) {
		for (int lx = 0; lx < shade.w; ++lx) {
			if (reach.Contains(shade.corner.x + lx, shade.corner.y + ly)) {
				shade.cells[size_t(ly * shade.w + lx)] = 0;
				frontier.push_back(ly * shade.w + lx);
			}
		}
	}
	for (uint8_t level = 1; level < SHADE_STEPS && !frontier.empty(); ++level) {
		std::vector<int> next;
		for (int idx : frontier) {
			const int fx = idx % shade.w;
			const int fy = idx / shade.w;
			for (int dy = -1; dy <= 1; ++dy) {
				for (int dx = -1; dx <= 1; ++dx) {
					const int nx = fx + dx;
					const int ny = fy + dy;
					if (nx < 0 || ny < 0 || nx >= shade.w || ny >= shade.h) continue;
					uint8_t& cell = shade.cells[size_t(ny * shade.w + nx)];
					if (cell > level) {
						cell = level;
						next.push_back(ny * shade.w + nx);
					}
				}
			}
		}
		frontier.swap(next);
	}
	return shade;
}

// the reach's edge as closed curves: the cell edges between reachable and unreachable cells,
// chained into loops, cut down to their corners and rounded off (Chaikin)
static std::vector<std::vector<Point>> BuildReachOutline(const PathFinder::ReachArea& reach)
{
	std::vector<std::vector<Point>> loops;
	if (reach.Empty()) return loops;
	// directed lattice edges, inside on the same side everywhere, so they chain head to tail
	std::multimap<std::pair<int, int>, std::pair<int, int>> edges;
	for (int ly = 0; ly < reach.h; ++ly) {
		for (int lx = 0; lx < reach.w; ++lx) {
			const int x = reach.corner.x + lx;
			const int y = reach.corner.y + ly;
			if (!reach.Contains(x, y)) continue;
			if (!reach.Contains(x, y - 1)) edges.emplace(std::make_pair(x, y), std::make_pair(x + 1, y));
			if (!reach.Contains(x + 1, y)) edges.emplace(std::make_pair(x + 1, y), std::make_pair(x + 1, y + 1));
			if (!reach.Contains(x, y + 1)) edges.emplace(std::make_pair(x + 1, y + 1), std::make_pair(x, y + 1));
			if (!reach.Contains(x - 1, y)) edges.emplace(std::make_pair(x, y + 1), std::make_pair(x, y));
		}
	}
	while (!edges.empty()) {
		std::vector<std::pair<int, int>> corners;
		auto it = edges.begin();
		const std::pair<int, int> start = it->first;
		std::pair<int, int> at = start;
		while (it != edges.end()) {
			corners.push_back(at);
			at = it->second;
			edges.erase(it);
			if (at == start) break;
			it = edges.find(at);
		}
		if (corners.size() < 3) continue;
		// keep only the turns: straight runs would otherwise stay straight after rounding
		std::vector<std::pair<float, float>> pts;
		const size_t n = corners.size();
		for (size_t i = 0; i < n; ++i) {
			const auto& prev = corners[(i + n - 1) % n];
			const auto& cur = corners[i];
			const auto& next = corners[(i + 1) % n];
			const bool straight = (cur.first - prev.first) * (next.second - cur.second) == (cur.second - prev.second) * (next.first - cur.first);
			if (!straight) pts.emplace_back(float(cur.first * SEARCHMAP_TILE_WIDTH), float(cur.second * SEARCHMAP_TILE_HEIGHT));
		}
		if (pts.size() < 3) continue;
		// staircases along diagonals: drop corners that sit close to the line through their
		// neighbours, so the rounding gives a smooth slope instead of a wiggle
		constexpr float TOLERANCE = 7.0f;
		for (bool changed = true; changed && pts.size() > 4;) {
			changed = false;
			for (size_t i = 0; i < pts.size() && pts.size() > 4; ++i) {
				const auto& a = pts[(i + pts.size() - 1) % pts.size()];
				const auto& p = pts[i];
				const auto& b = pts[(i + 1) % pts.size()];
				const float dx = b.first - a.first;
				const float dy = b.second - a.second;
				const float len = std::sqrt(dx * dx + dy * dy);
				if (len <= 0.0f) continue;
				const float dist = std::abs(dx * (a.second - p.second) - dy * (a.first - p.first)) / len;
				if (dist < TOLERANCE) {
					pts.erase(pts.begin() + std::ptrdiff_t(i));
					changed = true;
				}
			}
		}
		for (int pass = 0; pass < 3; ++pass) {
			std::vector<std::pair<float, float>> smooth;
			smooth.reserve(pts.size() * 2);
			for (size_t i = 0; i < pts.size(); ++i) {
				const auto& a = pts[i];
				const auto& b = pts[(i + 1) % pts.size()];
				smooth.emplace_back(a.first * 0.75f + b.first * 0.25f, a.second * 0.75f + b.second * 0.25f);
				smooth.emplace_back(a.first * 0.25f + b.first * 0.75f, a.second * 0.25f + b.second * 0.75f);
			}
			pts.swap(smooth);
		}
		std::vector<Point> loop;
		loop.reserve(pts.size() + 1);
		for (const auto& p : pts) loop.emplace_back(int(std::lround(p.first)), int(std::lround(p.second)));
		loop.push_back(loop.front());
		loops.push_back(std::move(loop));
	}
	return loops;
}

void GameControl::UpdateTurnPreview()
{
	TurnPreview& preview = turnPreview;
	Actor* actor = GetTurnBasedActor();
	if (!actor) {
		preview = TurnPreview();
		return;
	}
	if (preview.actorID != actor->GetGlobalID()) {
		preview = TurnPreview();
		preview.actorID = actor->GetGlobalID();
	}
	if (IsTurnBasedBusy(actor)) {
		// the move or attack is playing out, recompute once it's done
		preview.budget = -1;
		return;
	}

	const Game* game = core->GetGame();
	Map* area = actor->GetCurrentArea();
	int budget = game->combat.GetRemainingMovement(actor);
	if (preview.actorPos != actor->Pos || preview.budget != budget) {
		preview.reach = PathFinder::ReachableArea(area->tileProps, actor->Pos, actor->circleSize, budget);
		preview.shade = BuildReachShade(preview.reach);
		preview.outline = BuildReachOutline(preview.reach);
		preview.actorPos = actor->Pos;
		preview.budget = budget;
		preview.targetCell = SearchmapPoint(-1, -1);
	}

	Point target = preview.pending ? preview.pendingDest : GameMousePos();
	const Actor* hovered = preview.pending ? nullptr : GetLastActor();
	bool attack = hovered && hovered != actor && hovered->ValidTarget(GA_NO_DEAD) &&
		(hovered->GetStat(IE_EA) >= EA_EVILCUTOFF || targetMode == TargetMode::Attack);
	ieDword targetID = attack ? hovered->GetGlobalID() : 0;
	SearchmapPoint cell(target);
	if (cell == preview.targetCell && targetID == preview.targetActorID) return;

	preview.targetCell = cell;
	preview.targetActorID = targetID;
	preview.attackPreview = attack;
	preview.attackReachable = false;
	preview.hitChance = -1;
	preview.moveNeededFt = 0;
	if (attack) {
		// the numbers PerformAttack will roll against
		const Actor::HitPrediction hit = actor->PredictHit(hovered);
		if (hit.valid) {
			preview.hitChance = hit.chance;
			preview.hitNeeded = hit.needed;
			preview.damageMin = hit.damageMin;
			preview.damageMax = hit.damageMax;
			preview.baseThac0 = hit.baseThac0;
			preview.thac0 = hit.thac0;
			preview.abilityBonus = hit.abilityBonus;
			preview.weaponBonus = hit.weaponBonus;
			preview.proficiencyBonus = hit.proficiencyBonus;
			preview.armorBonus = hit.armorBonus;
			preview.otherBonus = hit.otherBonus;
			preview.modifier = hit.modifier;
			preview.totalNeeded = hit.totalNeeded;
			preview.ranged = hit.ranged;
			preview.autoHit = hit.autoHit;
		}
		preview.targetAC = static_cast<int>(hovered->GetStat(IE_ARMORCLASS));
		preview.distanceFt = PathFinder::MovementCost(actor->Pos, hovered->Pos) / SEARCHMAP_TILE_WIDTH;
	}
	preview.path = Path();
	preview.pathCost = 0;

	unsigned int minDistance = 0;
	if (attack) {
		target = hovered->Pos;
		bool leftOrRight = false;
		actor->GetWeapon(leftOrRight);
		unsigned int range = actor->GetWeaponRange(leftOrRight);
		bool canAttack = game->combat.CanAfford(actor, TBAction::Attack);
		if (WithinPersonalRange(actor, hovered, range)) {
			preview.attackReachable = canAttack;
			return;
		}
		// the same distance AttackCore approaches to
		minDistance = static_cast<unsigned int>(Feet2Pixels(range, AngleFromPoints(actor->Pos, target)));
	}

	const ActorPathContext context { static_cast<unsigned int>(actor->circleSize), actor->GetScriptName(), actor->ValidTarget(GA_ONLY_BUMPABLE) };
	preview.path = PathFinder::FindPath(area->GetTraversabilityCacheData(), area->tileProps, actor->Pos, target, context, minDistance, PF_SIGHT | PF_ACTORS_ARE_BLOCKING);
	if (!preview.path) {
		// boxed in by other creatures: the director's walker then takes the open floor path too
		preview.path = PathFinder::FindPath(area->GetTraversabilityCacheData(), area->tileProps, actor->Pos, target, context, minDistance, PF_SIGHT);
	}
	preview.pathCost = PathFinder::PathCost(actor->Pos, preview.path);
	preview.moveNeededFt = attack && preview.path ? preview.pathCost / SEARCHMAP_TILE_WIDTH : 0;
	if (attack) {
		preview.attackReachable = preview.path && preview.pathCost <= budget && game->combat.CanAfford(actor, TBAction::Attack);
	}
}

void GameControl::DrawTurnPreview() const
{
	const TurnPreview& preview = turnPreview;
	const Actor* actor = GetTurnBasedActor();
	if (!actor || IsTurnBasedBusy(actor) || preview.budget < 0) return;

	static const Color reachColor(255, 255, 255, 120);
	static const Color shadeColor(0, 0, 0, 64);
	static const Color inReach(90, 230, 90, 230);
	static const Color outOfReach(230, 60, 60, 230);
	static const Color pendingColor(250, 220, 80, 255);
	const Point& origin = viewport.origin;
	constexpr int TW = SEARCHMAP_TILE_WIDTH;
	constexpr int TH = SEARCHMAP_TILE_HEIGHT;

	// how far this turn's movement goes: what lies beyond fades darker over a few cells, and a
	// soft rounded line runs along the edge
	const PathFinder::ReachArea& shade = preview.shade;
	const auto shadeLevel = [&shade](int x, int y) {
		const int lx = x - shade.corner.x;
		const int ly = y - shade.corner.y;
		if (lx < 0 || ly < 0 || lx >= shade.w || ly >= shade.h) return SHADE_STEPS;
		return int(shade.cells[size_t(ly * shade.w + lx)]);
	};
	const int firstCol = origin.x / TW - 1;
	const int lastCol = (origin.x + viewport.w) / TW + 1;
	const int firstRow = origin.y / TH - 1;
	const int lastRow = (origin.y + viewport.h) / TH + 1;
	for (int y = firstRow; y <= lastRow; ++y) {
		int runStart = firstCol;
		int runLevel = shadeLevel(firstCol, y);
		for (int x = firstCol + 1; x <= lastCol + 1; ++x) {
			const int level = x <= lastCol ? shadeLevel(x, y) : -1;
			if (level == runLevel) continue;
			if (runLevel > 0) {
				Color c = shadeColor;
				c.a = uint8_t(shadeColor.a * runLevel / SHADE_STEPS);
				const Region r(Point(runStart * TW, y * TH) - origin, Size((x - runStart) * TW, TH));
				VideoDriver->DrawRect(r, c, true, BlitFlags::BLENDED);
			}
			runStart = x;
			runLevel = level;
		}
	}
	static const Color glowColor(255, 255, 255, 28);
	const bool outline = core->GetDictionary().Get("Turn Based Reach Outline", 0) != 0;
	for (const auto& loop : outline ? preview.outline : std::vector<std::vector<Point>>()) {
		std::vector<Point> shifted(loop.size());
		// a faint halo around a thin line
		for (const Point& offset : { Point(-1, 0), Point(1, 0), Point(0, -1), Point(0, 1), Point(-1, -1), Point(1, 1) }) {
			for (size_t i = 0; i < loop.size(); ++i) shifted[i] = loop[i] - origin + offset;
			VideoDriver->DrawLines(shifted, glowColor, BlitFlags::BLENDED);
		}
		for (size_t i = 0; i < loop.size(); ++i) shifted[i] = loop[i] - origin;
		VideoDriver->DrawLines(shifted, reachColor, BlitFlags::BLENDED);
	}

	// aiming a spell, item, talk ...: the click goes to that, not to a walk, so no path
	if (!preview.pending && targetMode != TargetMode::None && targetMode != TargetMode::Attack) return;

	const int budget = preview.budget;
	if (preview.path) {
		// the path as a line: green as far as we can afford it, red beyond
		const Point stop = PathFinder::PointAlongPath(actor->Pos, preview.path, budget);
		std::vector<Point> affordable { actor->Pos - origin };
		std::vector<Point> beyond;
		int walked = 0;
		Point prev = actor->Pos;
		for (size_t i = 0; i < preview.path.Size(); ++i) {
			const Point& next = preview.path.GetStep(i).point;
			walked += PathFinder::MovementCost(prev, next);
			if (beyond.empty() && walked <= budget) {
				affordable.push_back(next - origin);
			} else {
				if (beyond.empty()) {
					affordable.push_back(stop - origin);
					beyond.push_back(stop - origin);
				}
				beyond.push_back(next - origin);
			}
			prev = next;
		}
		// a couple of pixels wide
		const auto thickLine = [](const std::vector<Point>& points, const Color& color) {
			if (points.size() < 2) return;
			for (const Point& offset : { Point(0, 0), Point(1, 0), Point(0, 1), Point(1, 1) }) {
				std::vector<Point> shifted;
				shifted.reserve(points.size());
				for (const Point& p : points) shifted.push_back(p + offset);
				VideoDriver->DrawLines(shifted, color, BlitFlags::BLENDED);
			}
		};
		thickLine(affordable, inReach);
		thickLine(beyond, outOfReach);

		// exactly where the actor would stop
		const Color& stopColor = preview.pending ? pendingColor : (preview.pathCost <= budget ? inReach : outOfReach);
		DrawTargetReticle(actor->CircleSize2Radius(), stopColor, stop - origin);
	}

	String label;
	Point labelPos = (preview.pending ? preview.pendingDest : GameMousePos()) - origin + Point(12, -24);
	constexpr int UNITS_PER_FOOT = SEARCHMAP_TILE_WIDTH;
	if (preview.attackPreview) {
		const Actor* target = GetLastActor();
		if (target) {
			DrawTargetReticle(target->CircleSize2Radius(), preview.attackReachable ? inReach : outOfReach, target->Pos - origin);
		}
		// the numbers are in the hit panel beside the target
		label = preview.attackReachable ? String() : String(u"Out of reach");
	} else if (preview.path) {
		int cost = std::min(preview.pathCost, budget) / UNITS_PER_FOOT;
		label = fmt::format(u"{} ft / {} ft left", preview.pathCost / UNITS_PER_FOOT, budget / UNITS_PER_FOOT);
		if (preview.pathCost > budget) {
			label = fmt::format(u"Too far: stops after {} ft", cost);
		}
	} else {
		label = fmt::format(u"{} ft left", budget / UNITS_PER_FOOT);
	}
	if (preview.pending) {
		label += u" - click again to move";
	}
	Font::PrintColors colors = { preview.attackReachable || (preview.path && preview.pathCost <= budget) ? inReach : ColorWhite, ColorBlack };
	CombatHud::HudFont()->Print(Region(labelPos, Size(560, 20)), label, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP, colors);
}

void GameControl::HandleTurnBasedMove(const Point& p, bool commit)
{
	Actor* actor = GetTurnBasedActor();
	if (!actor || IsTurnBasedBusy(actor)) return;

	TurnPreview& preview = turnPreview;
	bool confirm = core->GetDictionary().Get("Turn Based Move Confirm", 1);
	// clicking near the placed destination again confirms it
	bool samePlace = preview.pending && SearchmapPoint(p) == SearchmapPoint(preview.pendingDest);
	if (confirm && !commit && !samePlace) {
		preview.pending = true;
		preview.pendingDest = p;
		preview.targetCell = SearchmapPoint(-1, -1);
		UpdateTurnPreview();
		return;
	}

	if (!preview.pending || !samePlace) {
		// the path under the cursor, if we commit without placing first
		preview.pending = true;
		preview.pendingDest = p;
		preview.targetCell = SearchmapPoint(-1, -1);
		UpdateTurnPreview();
	}
	preview.pending = false;
	if (!preview.path || preview.budget <= 0) return;

	// incremental: go as far as the budget allows, the rest of the turn can move again
	Point stop = PathFinder::PointAlongPath(actor->Pos, preview.path, preview.budget);
	if (stop == actor->Pos) return;
	actor->ClearPath(true);
	CreateMovement(actor, stop, false, false);
	preview.targetCell = SearchmapPoint(-1, -1);
}

void GameControl::ConfirmTurnBasedMove()
{
	if (turnPreview.pending) {
		HandleTurnBasedMove(turnPreview.pendingDest, true);
	}
}

// ------------------------------------------------------------------------------------------
// screen-space combat overlays

Point GameControl::MapToScreen(const Point& p, const Region& screen) const
{
	Point local;
	if (SceneCamera() && camera.scale > 0.0f) {
		local = Point(int((float(p.x) - camera.x) / camera.scale), int((float(p.y) - camera.y) / camera.scale));
	} else {
		local = p - viewport.origin;
	}
	return screen.origin + local;
}

void GameControl::DrawCombatOverlays(const Region& screen)
{
	const Game* game = core->GetGame();
	if (!game) return;
	const float mapScale = SceneCamera() && camera.scale > 0.0f ? camera.scale : 1.0f;
	CombatHud::DrawSaves([&](const Point& p) { return MapToScreen(p, screen); }, mapScale);
	DrawHoverHP(screen);
	if (game->combat.IsActive()) {
		DrawHitPanel(screen);
		game->combat.GetHud().Draw(screen);
	}
	DrawTurnBanner(screen);
}

static String Signed(int v)
{
	return fmt::format(u"{:+d}", v);
}

void GameControl::DrawHitPanel(const Region& screen) const
{
	const TurnPreview& preview = turnPreview;
	const Actor* actor = GetTurnBasedActor();
	if (!actor || IsTurnBasedBusy(actor) || preview.budget < 0 || !preview.attackPreview || preview.hitChance < 0) return;
	const Actor* target = GetLastActor();
	Holder<Font> font = CombatHud::HudFont();
	if (!target || !font) return;
	using Theme = CombatHud::Theme;

	struct Row {
		String label;
		String value;
		Color color;
	};
	std::vector<Row> rows;
	rows.push_back({ u"Base THAC0", fmt::format(u"{}", preview.baseThac0), Theme::text });
	if (preview.abilityBonus) rows.push_back({ preview.ranged ? u"Dexterity" : u"Strength", Signed(preview.abilityBonus), Theme::text });
	if (preview.weaponBonus) rows.push_back({ u"Weapon", Signed(preview.weaponBonus), Theme::text });
	if (preview.proficiencyBonus) rows.push_back({ u"Proficiency", Signed(preview.proficiencyBonus), Theme::text });
	if (preview.armorBonus) rows.push_back({ u"Armor", Signed(preview.armorBonus), Theme::text });
	if (preview.otherBonus) rows.push_back({ u"Situational", Signed(preview.otherBonus), Theme::text });
	rows.push_back({ u"THAC0", fmt::format(u"{}", preview.thac0), Theme::crit });
	rows.push_back({ u"Target AC", fmt::format(u"{}", preview.targetAC), Theme::text });
	rows.push_back({ u"Damage", fmt::format(u"{} - {}", preview.damageMin, preview.damageMax), Theme::text });

	String reach;
	Color reachColor = Theme::hit;
	if (!preview.attackReachable) {
		reach = u"Out of reach";
		reachColor = Theme::miss;
	} else if (preview.moveNeededFt > 0) {
		reach = fmt::format(u"Walks {} ft, then attacks", preview.moveNeededFt);
		reachColor = Theme::text;
	} else {
		reach = u"In reach";
	}

	const int line = font->LineHeight + 2;
	const int bigH = 30;
	const int w = 236;
	const int h = 14 + line + bigH + 6 + line + 8 + int(rows.size()) * line + 8 + line + line + 12;

	// beside the target: right of it, or left near the screen edge
	const Point at = MapToScreen(target->Pos, screen);
	const float scale = SceneCamera() && camera.scale > 0.0f ? camera.scale : 1.0f;
	const int r = int(float(target->CircleSize2Radius()) * 2.0f / scale) + 24;
	int x = at.x + r;
	if (x + w > screen.x + screen.w - 8) x = at.x - r - w;
	int y = at.y - h / 2 - int(40 / scale);
	x = Clamp(x, screen.x + 8, screen.x + screen.w - w - 8);
	// never over the hover HP bar at the top
	const int minY = std::max(screen.y + 8, hoverBarBottom + 8);
	y = std::max(minY, std::min(y, screen.y + screen.h - h - 8));
	const Region panel(x, y, w, h);
	CombatHud::DrawPanel(panel);

	const Font::PrintColors title { target->GetStat(IE_EA) >= EA_EVILCUTOFF ? Color(236, 120, 96, 255) : Theme::text, ColorBlack };
	int cy = y + 8;
	font->Print(Region(x + 10, cy, w - 20, line), target->GetShortName(), IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, title);
	cy += line + 4;

	// the chance, big
	const int chance = preview.hitChance;
	const Color chanceColor = chance >= 60 ? Theme::hit : (chance >= 35 ? Theme::crit : Theme::miss);
	const std::string number = std::to_string(chance);
	const String suffix = u"% to hit";
	const int numW = CombatHud::StrokeTextWidth(number, bigH);
	const int sufW = font->StringSize(suffix).w;
	const int bx = x + (w - numW - 8 - sufW) / 2;
	CombatHud::DrawStrokeText(number, Point(bx, cy), bigH, chanceColor);
	const Font::PrintColors chanceColors { chanceColor, ColorBlack };
	font->Print(Region(bx + numW + 8, cy + bigH - line, sufW + 4, line), suffix, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, chanceColors);
	cy += bigH + 6;

	const Font::PrintColors dim { Theme::textDim, ColorBlack };
	String howTo = preview.autoHit ? String(u"Helpless: always hits") :
		fmt::format(u"d20 {:+d}, needs {}  (a {}+ on the die)", preview.modifier, preview.totalNeeded, preview.hitNeeded);
	font->Print(Region(x + 8, cy, w - 16, line), howTo, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, dim);
	cy += line + 4;
	VideoDriver->DrawLine(Point(x + 12, cy), Point(x + w - 12, cy), Theme::borderDark, BlitFlags::BLENDED);
	cy += 4;

	for (const Row& row : rows) {
		const Font::PrintColors labelColors { Theme::textDim, ColorBlack };
		const Font::PrintColors valueColors { row.color, ColorBlack };
		font->Print(Region(x + 14, cy, w - 28, line), row.label, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, labelColors);
		font->Print(Region(x + 14, cy, w - 28, line), row.value, IE_FONT_ALIGN_RIGHT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, valueColors);
		cy += line;
	}
	cy += 4;
	VideoDriver->DrawLine(Point(x + 12, cy), Point(x + w - 12, cy), Theme::borderDark, BlitFlags::BLENDED);
	cy += 4;
	font->Print(Region(x + 8, cy, w - 16, line), fmt::format(u"Distance {} ft", preview.distanceFt), IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, dim);
	cy += line;
	const Font::PrintColors reachColors { reachColor, ColorBlack };
	font->Print(Region(x + 8, cy, w - 16, line), reach, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, reachColors);
}

namespace {
struct EffectInfo {
	String name;
	ResRef icon;
	bool hostile = false;
	bool valid = false;
};
const EffectInfo& SpellEffectInfo(const ResRef& ref)
{
	static std::map<std::string, EffectInfo> cache;
	auto it = cache.find(ref.c_str());
	if (it != cache.end()) return it->second;
	EffectInfo info;
	const Spell* spl = gamedata->GetSpell(ref, true);
	if (spl) {
		ieStrRef name = spl->SpellNameIdentified != ieStrRef::INVALID ? spl->SpellNameIdentified : spl->SpellName;
		if (name != ieStrRef::INVALID) info.name = core->GetString(name);
		info.icon = spl->SpellbookIcon;
		info.hostile = (spl->Flags & SF_HOSTILE) != 0;
		info.valid = !info.name.empty();
		gamedata->FreeSpell(spl, ref, false);
	}
	return cache.emplace(ref.c_str(), info).first->second;
}

String TitleCase(const std::string& s)
{
	String out;
	bool start = true;
	for (char c : s) {
		if (c == '_') {
			out += u' ';
			start = true;
			continue;
		}
		out += char16_t(start ? std::toupper(static_cast<unsigned char>(c)) : std::tolower(static_cast<unsigned char>(c)));
		start = false;
	}
	return out;
}
}

void GameControl::DrawHoverHP(const Region& screen) const
{
	hoverBarBottom = 0;
	if (!core->GetDictionary().Get("Hover HP Bar", 1)) return;
	const Actor* actor = GetLastActor();
	Holder<Font> font = CombatHud::HudFont();
	if (!actor || !font || (actor->GetStat(IE_STATE_ID) & STATE_DEAD)) return;
	using Theme = CombatHud::Theme;

	const int hp = std::max(0, int(actor->GetStat(IE_HITPOINTS)));
	const int maxHP = std::max(1, int(actor->GetStat(IE_MAXHITPOINTS)));
	const int line = font->LineHeight + 2;

	// buffs and debuffs: the spells with timed effects on it, once each
	std::vector<const EffectInfo*> effects;
	for (auto it = actor->fxqueue.GetFirstEffect(); const Effect* fx = actor->fxqueue.GetNextEffect(it);) {
		if (fx->SourceType != 2 || fx->SourceRef.IsEmpty() || fx->TimingMode != FX_DURATION_INSTANT_LIMITED) continue;
		const EffectInfo& info = SpellEffectInfo(fx->SourceRef);
		if (!info.valid || std::find(effects.begin(), effects.end(), &info) != effects.end()) continue;
		effects.push_back(&info);
		if (effects.size() >= 4) break;
	}

	const String className = TitleCase(actor->GetClassName(actor->GetActiveClass()));
	const bool hasClass = !className.empty();
	const int w = 380;
	const int h = 10 + line + (hasClass ? line : 0) + 18 + 8 + (effects.empty() ? 0 : 26) + 6;
	const Game* game = core->GetGame();
	// under the turn order bar in a fight
	const int top = game && game->combat.IsRunning() ? 138 : 12;
	const Region panel(screen.x + (screen.w - w) / 2, screen.y + top, w, h);
	CombatHud::DrawPanel(panel);
	hoverBarBottom = panel.y + panel.h;

	Color nameColor = Theme::text;
	if (!actor->InParty) nameColor = actor->GetStat(IE_EA) >= EA_EVILCUTOFF ? Color(236, 120, 96, 255) : Theme::textDim;
	const String name = actor->GetShortName();
	const String level = fmt::format(u"  Lv. {}", actor->GetXPLevel(true));
	const int nameW = font->StringSize(name).w;
	const int levelW = font->StringSize(level).w;
	int cy = panel.y + 6;
	const int nx = panel.x + (w - nameW - levelW) / 2;
	const Font::PrintColors nameColors { nameColor, ColorBlack };
	const Font::PrintColors dim { Theme::textDim, ColorBlack };
	font->Print(Region(nx, cy, nameW + 4, line), name, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, nameColors);
	font->Print(Region(nx + nameW, cy, levelW + 4, line), level, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, dim);
	cy += line;
	if (hasClass) {
		font->Print(Region(panel.x + 10, cy, w - 20, line), className, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, dim);
		cy += line;
	}
	cy += 2;

	const Region bar(panel.x + 18, cy, w - 36, 18);
	VideoDriver->DrawRect(bar, Color(34, 10, 8, 255), true);
	const float ratio = Clamp(float(hp) / float(maxHP), 0.0f, 1.0f);
	const Region fill(bar.x, bar.y, int(bar.w * ratio), bar.h);
	const Color barColor = ratio > 0.5f ? Color(168, 34, 26, 255) : (ratio > 0.25f ? Color(190, 74, 22, 255) : Color(210, 28, 20, 255));
	if (fill.w > 0) {
		VideoDriver->DrawRect(fill, barColor, true);
		VideoDriver->DrawRect(Region(fill.x, fill.y, fill.w, 4), Color(255, 255, 255, 46), true, BlitFlags::BLENDED);
		VideoDriver->DrawRect(Region(fill.x, fill.y + fill.h - 4, fill.w, 4), Color(0, 0, 0, 60), true, BlitFlags::BLENDED);
	}
	VideoDriver->DrawRect(bar, Theme::borderDark, false);
	const Font::PrintColors hpColors { Theme::text, ColorBlack };
	font->Print(Region(bar.x, bar.y + (bar.h - line) / 2 + 1, bar.w, line), fmt::format(u"{} / {}", hp, maxHP),
		    IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, hpColors);
	cy += bar.h + 8;

	if (effects.empty()) return;
	// icon + name for each, centred as a row
	constexpr int ICON = 20;
	int total = 0;
	for (const EffectInfo* e : effects) total += ICON + 4 + font->StringSize(e->name).w + 14;
	int ex = panel.x + std::max(8, (w - total) / 2);
	for (const EffectInfo* e : effects) {
		Holder<Sprite2D> icon = e->icon.IsEmpty() ? nullptr : gamedata->GetBAMSprite(e->icon, 0, 0, true);
		if (icon) {
			VideoDriver->BlitSprite(icon, Region(Point(), icon->Frame.size), Region(ex, cy, ICON, ICON), BlitFlags::BLENDED);
		} else {
			VideoDriver->DrawRect(Region(ex + 4, cy + 4, ICON - 8, ICON - 8), e->hostile ? Theme::miss : Theme::hit, true);
		}
		ex += ICON + 4;
		const Font::PrintColors ec { e->hostile ? Color(232, 120, 100, 255) : Color(170, 220, 150, 255), ColorBlack };
		const int tw = font->StringSize(e->name).w;
		font->Print(Region(ex, cy + (ICON - line) / 2 + 1, tw + 4, line), e->name, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, ec);
		ex += tw + 14;
		if (ex > panel.x + w - 20) break;
	}
}

void GameControl::DrawTurnBanner(const Region& screen)
{
	const Game* game = core->GetGame();
	const tick_t now = GetMilliseconds();
	const Actor* active = game && game->combat.IsRunning() ? game->combat.GetActiveActor() : nullptr;
	const bool party = active && active->InParty && !core->GetDictionary().Get("Turn Based Party AI", 0);
	if (party && !lastActiveWasParty && core->GetDictionary().Get("Turn Based Turn Banner", 1)) {
		bannerStart = now;
		bannerActorID = active->GetGlobalID();
	}
	lastActiveWasParty = party;
	if (!bannerStart || !game) return;

	constexpr tick_t DURATION = 1800;
	const tick_t t = now - bannerStart;
	if (t > DURATION) {
		bannerStart = 0;
		return;
	}
	Holder<Font> font = CombatHud::HudFont();
	if (!font) return;
	float alpha = 1.0f;
	if (t < 180) alpha = float(t) / 180.0f;
	if (t > DURATION - 450) alpha = float(DURATION - t) / 450.0f;
	const float slide = 1.0f - std::min(1.0f, float(t) / 220.0f);

	// a panel under the turn order: "Your Turn" and who shares it
	String names;
	const Map* area = CurrentArea();
	for (ieDword id : game->combat.GetActiveGroup()) {
		const Actor* who = area ? area->GetActorByGlobalID(id) : nullptr;
		if (!who || !who->InParty) continue;
		if (!names.empty()) names += u"     ";
		names += who->GetShortName();
	}
	const int w = std::max(420, font->StringSize(names).w + 80);
	const int h = 76;
	const Region panel(screen.x + (screen.w - w) / 2, screen.y + 138 - int(slide * 16), w, h);
	CombatHud::DrawPanel(panel, alpha);

	const String text = u"Your Turn";
	const float zoom = 2.0f;
	const Size size = font->StringSize(text);
	const Font::PrintColors colors { Color(255, 222, 150, uint8_t(255 * alpha)), Color(0, 0, 0, uint8_t(255 * alpha)) };
	if (VideoDriver->SupportsSceneTransform()) {
		const Point at(panel.x + w / 2 - int(size.w * zoom / 2), panel.y + 8);
		VideoDriver->BeginScaledUI(zoom, at, screen);
		font->Print(Region(0, 0, size.w + 8, font->LineHeight + 4), text, IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, colors);
		VideoDriver->EndScaledUI();
	} else {
		font->Print(Region(panel.x, panel.y + 12, w, font->LineHeight + 4), text, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, colors);
	}
	const int ruleY = panel.y + 8 + int(font->LineHeight * zoom) + 4;
	VideoDriver->DrawRect(Region(panel.x + w / 4, ruleY, w / 2, 1), Color(158, 118, 66, uint8_t(200 * alpha)), true, BlitFlags::BLENDED);
	const Font::PrintColors sub { Color(232, 222, 196, uint8_t(230 * alpha)), Color(0, 0, 0, uint8_t(255 * alpha)) };
	font->Print(Region(panel.x, ruleY + 5, w, font->LineHeight + 4), names, IE_FONT_ALIGN_CENTER | IE_FONT_ALIGN_TOP | IE_FONT_SINGLE_LINE, sub);
}

// show partymember hp/maxhp as overhead text
// the ees do that plus show the names of every visible actor
static void DisplayHeadHPNames(bool enable, const Region& vp)
{
	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();
	if (!area) return;

	if (!enable) {
		auto actors = area->GetActorsInRect(vp, GA_NO_DEAD | GA_NO_UNSCHEDULED);
		for (Actor* actor : actors) {
			actor->overHead.Display(false, 0);
		}
		return;
	}

	if (core->HasFeature(GFFlags::NAME_EVERYONE_ON_TAB)) {
		auto actors = area->GetActorsInRect(vp, GA_NO_DEAD | GA_NO_UNSCHEDULED);
		for (Actor* actor : actors) {
			if (actor->InParty) {
				actor->DisplayHeadHPRatio(true);
			} else {
				actor->overHead.SetText(fmt::format(u"{}", actor->GetName()), true, false);
			}
		}
	} else {
		for (int pm = 0; pm < game->GetPartySize(false); pm++) {
			Actor* pc = game->GetPC(pm, true);
			if (!pc) continue;
			pc->DisplayHeadHPRatio();
		}
	}
}

// this existly only so tab can be handled
// it's used both for tooltips everywhere and hp display on game control
bool GameControl::DispatchEvent(const Event& event) const
{
	if (!window || window->IsDisabled() || (Flags() & IgnoreEvents)) {
		return false;
	}

	if (event.keyboard.keycode == GEM_TAB) {
		DisplayHeadHPNames(true, viewport);
		return true;
	} else if (event.keyboard.keycode == GEM_ESCAPE) {
		core->ResetActionBar();
		core->SetEventFlag(EF_RESETTARGET);
	}
	return false;
}

/** Key Press Event */
bool GameControl::OnKeyPress(const KeyboardEvent& Key, unsigned short mod)
{
	int i;
	int pc;
	Game* game = core->GetGame();

	KeyboardKey keycode = Key.keycode;
	if (mod) {
		// the random bitshift is to skip checking hotkeys with mods
		// eg. ctrl-j should be ignored for keymap.ini handling and
		// passed straight on
		if (!core->GetKeyMap()->ResolveKey(Key.keycode, mod << 20)) {
			game->SendHotKey(towupper(Key.character));
			return View::OnKeyPress(Key, mod);
		}
		return true;
	}

	switch (keycode) {
		case GEM_UP:
		case GEM_DOWN:
		case GEM_LEFT:
		case GEM_RIGHT:
			{
				if (InDialog()) {
					// work around the fact that the MessageWindow is ignoring events
					TextArea* ta = core->GetMessageTextArea();
					int delta = ta->LineHeight() * (keycode == GEM_UP ? 1 : -1);
					ta->ScrollDelta(Point(0, delta));
					break;
				}
				if (Flags() & IgnoreEvents) {
					break;
				}
				unsigned int arrowKey = 1 << (keycode - GEM_LEFT);

				// You only get repeating OnKeyPress events for the last key pressed.
				// More than one direction can be held down for diagonal scrolling, so we have
				// to track which keys are pressed/released instead of relying on continuous events.
				// don't reprocess repeating keystrokes
				if (scrollKeysDown & arrowKey) {
					break;
				}

				scrollKeysDown |= arrowKey;
				scrollKeysActive |= arrowKey;

				// If the opposite arrow key is held down, the new key press overrides it:
				// Each pair shares adjacent bits: LEFT|RIGHT = bits 0,1 and UP|DOWN = bits 2,3
				unsigned int oppositeKey = (arrowKey & (SCROLL_LEFT | SCROLL_UP)) ? arrowKey << 1 : arrowKey >> 1;
				scrollKeysActive &= ~oppositeKey;

				// Update the vector to start scrolling in the direction that was pressed:
				ApplyKeyScrolling();
			}
			break;
		case GEM_TAB: // show partymember hp/maxhp as overhead text
		// fallthrough
		case GEM_ESCAPE: // redraw actionbar
			// do nothing; these are handled in DispatchEvent due to tab having two functions
			break;
		case '0':
			game->SelectActor(nullptr, false, SELECT_NORMAL);
			i = game->GetPartySize(false) / 2 + 1;
			while (i--) {
				SelectActor(i, true);
			}
			break;
		case '-':
			game->SelectActor(nullptr, true, SELECT_NORMAL);
			i = game->GetPartySize(false) / 2 + 1;
			while (i--) {
				SelectActor(i, false);
			}
			break;
		case GEM_RETURN: // confirm a placed turn based move
			if (turnPreview.pending) {
				ConfirmTurnBasedMove();
			} else {
				return View::OnKeyPress(Key, mod);
			}
			break;
		case ' ': //soft pause, or end turn in turn based combat
			if (game->combat.IsRunning()) {
				const Actor* active = game->combat.GetActiveActor();
				if (active && active->InParty) {
					game->combat.EndTurn();
				}
			} else {
				core->TogglePause();
			}
			break;
		case '=':
			SelectActor(-1);
			break;
		case '7': // 1 & 2
		case '8': // 3 & 4
		case '9': // 5 & 6
			// We do not handle the range 1..6, these are handled as hotkeys
			// for the portrait buttons, so that they remain working when the
			// inventory screen is open.
			game->SelectActor(nullptr, false, SELECT_NORMAL);
			i = game->GetPartySize(false);
			pc = 2 * (keycode - '6') - 1;
			if (pc >= i) {
				SelectActor(i, true);
				break;
			}
			SelectActor(pc, true);
			SelectActor(pc + 1, true);
			break;
		default:
			if (!core->GetKeyMap()->ResolveKey(Key.keycode, 0)) {
				game->SendHotKey(towupper(Key.character));
				return View::OnKeyPress(Key, 0);
			}
			break;
	}
	return true;
}

//Select (or deselect) a new actor (or actors)
void GameControl::SelectActor(int whom, int type)
{
	Game* game = core->GetGame();
	if (whom == -1) {
		game->SelectActor(nullptr, true, SELECT_NORMAL);
		return;
	}

	/* doesn't fall through here */
	Actor* actor = game->FindPC(whom);
	if (!actor)
		return;

	if (type == 0) {
		game->SelectActor(actor, false, SELECT_NORMAL);
		return;
	}
	if (type == 1) {
		game->SelectActor(actor, true, SELECT_NORMAL);
		return;
	}

	bool was_selected = actor->IsSelected();
	if (game->SelectActor(actor, true, SELECT_REPLACE | SELECT_CLICK)) {
		if (was_selected || screenFlags.Test(ScreenFlags::AlwaysCenter)) {
			screenFlags.Set(ScreenFlags::CenterOnActor);
		}
	}
}

void GameControl::DumpActorInfo(ActorDump dump, const Map* area) const noexcept
{
	const Point gameMousePos = GameMousePos();
	const Actor* act = area->GetActorByGlobalID(lastActorID);
	if (!act) {
		act = area->GetActor(gameMousePos, GA_DEFAULT);
	}
	if (!act) {
		// ValidTarget never returns immobile targets, making debugging a nightmare
		// so if we don't have an actor, we make really really sure by checking manually
		unsigned int count = area->GetActorCount(true);
		while (count--) {
			const Actor* actor = area->GetActor(count, true);
			if (actor->IsOver(gameMousePos)) {
				act = actor;
				break;
			}
		}
	}

	if (act) {
		if (dump == ActorDump::Stats) {
			fmt::println("{}", act->dump());
		} else if (dump == ActorDump::Anims) {
			constexpr int width = 10;
			const CharAnimations* anims = act->GetAnims();
			fmt::println("{1:<{0}}: {2:#x}", width, "Anim ID", anims->GetAnimationID());
			fmt::println("{1:<{0}}: {2}", width, "BloodColor", anims->GetBloodColor());
			fmt::println("{1:<{0}}: {2:#x}", width, "Flags", anims->GetFlags());
		}
	}
}

template<typename CONTAIN>
static void PrintCollection(const char* name, const CONTAIN& container)
{
	fmt::println("{} ({}):\n{}", name, container.size(), fmt::join(container, "\n"));
}

//Effect for the ctrl-r cheatkey (resurrect)
static EffectRef heal_ref = { "CurrentHPModifier", -1 };
static EffectRef damage_ref = { "Damage", -1 };
static EffectRef puppet_ref = { "PuppetMarker", -1 };

bool GameControl::OnCheatKeyRelease(const KeyboardEvent& key, unsigned short /*mod*/)
{
	if (!core->CheatEnabled()) return false;

	Game* game = core->GetGame();
	Map* area = game->GetCurrentArea();
	if (!area) return false;

	static std::array<uint32_t, 4> fogFlags {
		0,
		DEBUG_SHOW_FOG_ALL,
		DEBUG_SHOW_FOG_INVISIBLE,
		DEBUG_SHOW_FOG_UNEXPLORED
	};
	static uint32_t fogFlagIdx = 0;
	static std::array<uint32_t, 6> wallFlags {
		0,
		DEBUG_SHOW_WALLS_ALL,
		DEBUG_SHOW_DOORS_SECRET,
		DEBUG_SHOW_DOORS_DISABLED,
		DEBUG_SHOW_WALLS,
		DEBUG_SHOW_WALLS_ANIM_COVER
	};
	static uint32_t wallFlagIdx = 0;
	static std::array<uint32_t, 5> flags {
		0,
		DEBUG_SHOW_SEARCHMAP,
		DEBUG_SHOW_MATERIALMAP,
		DEBUG_SHOW_HEIGHTMAP,
		DEBUG_SHOW_LIGHTMAP,
	};
	static uint32_t flagIdx = 0;

	Point gameMousePos = GameMousePos();
	Highlightable* over = Scriptable::As<Highlightable>(overMe);
	Actor* lastActor = area->GetActorByGlobalID(lastActorID);

	switch (key.character) {
		case 'a': // switches through the avatar animations
			if (lastActor) {
				lastActor->GetNextAnimation();
			}
			break;
		// b
		case 'c': // force cast a hardcoded spell
			// caster is the last selected actor
			// target is the door/actor currently under the pointer
			if (game->selected.empty()) break;

			if (GetHoverObject()) {
				Actor* src = game->selected[0];
				src->SetSpellResRef(TestSpell);
				src->CastSpell(GetHoverObject(), false);
				if (src->objects.LastSpellTarget) {
					src->CastSpellEnd(0, false);
				} else {
					src->CastSpellPointEnd(0, false);
				}
			}
			break;
		case 'd': // detect a trap or door
			if (over) {
				if (overMe->Type == ST_DOOR) {
					Scriptable::As<Door>(overMe)->TryDetectSecret(256, lastActorID);
				}
				over->DetectTrap(256, lastActorID);
			}
			break;
		case 'e': // reverses pc order (useful for parties bigger than 6)
			game->ReversePCs();
			break;
		// f
		case 'g': // shows loaded areas and other game information
			Log(DEBUG, "Game", "{}", game->dump());
			break;
		// h
		case 'i': // interact trigger (from the original game)
			if (!lastActor) {
				lastActor = area->GetActor(gameMousePos, GA_DEFAULT);
				if (!lastActor) break;
			}
			if (lastActor->GetStat(IE_MC_FLAGS) & MC_EXPORTABLE || lastActor->GetCurrentArea() != area) {
				break;
			}
			int size;
			size = game->GetPartySize(true);
			if (size < 2) break;
			for (int i = core->Roll(1, size, 0); i < 2 * size; i++) {
				const Actor* target = game->GetPC(i % size, true);
				if (target == lastActor) continue;
				if (target->GetStat(IE_MC_FLAGS) & MC_EXPORTABLE) continue; // user generated pc
				lastActor->HandleInteractV1(target);
				break;
			}
			break;
		case 'j': // teleports the selected actors
			for (Actor* selectee : game->selected) {
				selectee->ClearActions();
				MoveBetweenAreasCore(selectee, core->GetGame()->CurrentArea, gameMousePos, -1, true);
			}
			break;
		case 'k': // kicks out actor
			if (lastActor && lastActor->InParty) {
				lastActor->Stop();
				lastActor->AddAction("LeaveParty()");
			}
			break;
		case 'l': // play an animation (vvc/bam) over an actor
			// the original engine was able to swap through all animations
			if (lastActor) {
				lastActor->AddAnimation(ResRef("S056ICBL"), 0, 0, 0);
			}
			break;
		case 'M':
			DumpActorInfo(ActorDump::Anims, area);
			FlushLogs();
			break;
		case 'm': // prints a debug dump (ctrl-m in the original game too)
			if (overMe && overMe->Type != ST_ACTOR) {
				fmt::println("{}", overMe->dump());
			} else if (lastActor) {
				DumpActorInfo(ActorDump::Stats, area);
			} else {
				area->dump(false);
			}
			FlushLogs();
			break;
		case 'n': // prints a list of all the live actors in the area
			area->dump(true);
			FlushLogs();
			break;
		case 'o': // dump Scriptable's local vars (for Game see below)
			if (lastActor) {
				PrintCollection("locals", lastActor->locals);
			} else if (overMe) {
				PrintCollection("locals", overMe->locals);
			} else {
				PrintCollection("locals", area->locals);
			}
			break;
		case 'p': // center on actor
			screenFlags.Flip(ScreenFlags::CenterOnActor);
			screenFlags.Flip(ScreenFlags::AlwaysCenter);
			break;
		case 'q': // joins actor to the party
			if (lastActor && !lastActor->InParty) {
				lastActor->Stop();
				lastActor->AddAction("JoinParty()");
			}
			break;
		case 'r': // resurrects actor
			if (!lastActor) {
				lastActor = area->GetActor(gameMousePos, GA_DEFAULT);
			}
			if (lastActor) {
				auto fx = EffectQueue::CreateEffect(heal_ref, lastActor->GetStat(IE_MAXHITPOINTS), 0x30001, FX_DURATION_INSTANT_PERMANENT);
				if (fx) {
					core->ApplyEffect(std::move(fx), lastActor, lastActor);
				}
			}
			break;
		case 's': // switches through the stance animations
			if (lastActor) {
				lastActor->GetNextStance();
			}
			break;
		case 't': // advances time by 1 hour
			game->AdvanceTime(core->Time.hour_size);
			break;
		case 'u': // dump GameScript GLOBAL vars
			PrintCollection("locals", core->GetGame()->locals);
			break;
		case 'U': // dump death vars
			PrintCollection("kaputz", core->GetGame()->kaputz);
			break;
		case 'V': // dump GemRB vars like the game ini settings
			PrintCollection("variables", core->GetDictionary());
			break;
		case 'v': // marks some of the map visited (random vision distance)
			area->ExploreMapChunk(SearchmapPoint(gameMousePos), RAND(0, 29), 1);
			break;
		case 'w': // consolidates found ground piles under the pointed pc
			area->MoveVisibleGroundPiles(gameMousePos);
			break;
		case 'x': // shows coordinates on the map
			fmt::println("{}: {}", area->GetScriptName(), gameMousePos);
			break;
		case 'Y': // damages all enemies by 300 (resistances apply)
			// mwahaha!
			int i;
			i = area->GetActorCount(false);
			while (i--) {
				Actor* victim = area->GetActor(i, false);
				if (victim->Modified[IE_EA] == EA_ENEMY) {
					auto newfx = EffectQueue::CreateEffect(damage_ref, 300, DAMAGE_MAGIC << 16, FX_DURATION_INSTANT_PERMANENT);
					core->ApplyEffect(std::move(newfx), victim, victim);
				}
			}
			// fallthrough
		case 'y': // kills actor
			if (lastActor) {
				// using action so the actor is killed
				// correctly (synchronisation)
				lastActor->Stop();

				auto newfx = EffectQueue::CreateEffect(damage_ref, 300, DAMAGE_MAGIC << 16, FX_DURATION_INSTANT_PERMANENT);
				core->ApplyEffect(std::move(newfx), lastActor, lastActor);
				if (!(lastActor->GetInternalFlag() & IF_REALLYDIED)) {
					newfx = EffectQueue::CreateEffect(damage_ref, 300, DAMAGE_ACID << 16, FX_DURATION_INSTANT_PERMANENT);
					core->ApplyEffect(std::move(newfx), lastActor, lastActor);
					newfx = EffectQueue::CreateEffect(damage_ref, 300, DAMAGE_CRUSHING << 16, FX_DURATION_INSTANT_PERMANENT);
					core->ApplyEffect(std::move(newfx), lastActor, lastActor);
				}
			} else if (!overMe) {
				break;
			} else if (overMe->Type == ST_CONTAINER) {
				Scriptable::As<Container>(overMe)->SetContainerLocked(false);
			} else if (overMe->Type == ST_DOOR) {
				Scriptable::As<Door>(overMe)->SetDoorLocked(0, 0);
			}
			break;
		case 'z': // shift through the avatar animations backward
			if (lastActor) {
				lastActor->GetPrevAnimation();
			}
			break;
		case '1': // change paperdoll armour level
			if (!lastActor) break;
			lastActor->NewStat(IE_ARMOR_TYPE, 1, MOD_ADDITIVE);
			break;
		case '4': // show all traps and infopoints
			DebugFlags ^= DEBUG_SHOW_INFOPOINTS;
			Log(MESSAGE, "GameControl", "Show traps and infopoints {}", DebugFlags & DEBUG_SHOW_INFOPOINTS ? "ON" : "OFF");
			break;
		case '5':
			DebugFlags &= ~DEBUG_SHOW_WALLS_ALL;
			DebugFlags |= wallFlags[wallFlagIdx];
			wallFlagIdx = (wallFlagIdx + 1) % wallFlags.size();
			break;
		case '6': // toggle between lightmap/heightmap/material/search
			DebugFlags &= ~DEBUG_SHOW_MAPS_ALL;
			DebugFlags |= flags[flagIdx];
			flagIdx = (flagIdx + 1) % flags.size();

			if (DebugFlags & DEBUG_SHOW_MAPS_ALL) {
				// fog interferese with debugging the map
				// you can manually reenable with ctrl+7
				DebugFlags |= DEBUG_SHOW_FOG_ALL;
			} else {
				DebugFlags &= ~DEBUG_SHOW_FOG_ALL;
				DebugPropVal = 0;
			}
			break;
		case '7': // toggles fog of war
			DebugFlags &= ~DEBUG_SHOW_FOG_ALL;
			DebugFlags |= fogFlags[fogFlagIdx];
			fogFlagIdx = (fogFlagIdx + 1) % fogFlags.size();
			break;
		default:
			break;
	}

	// always consume the event regardless if a key matched or not
	return true;
}

/** Key Release Event */
bool GameControl::OnKeyRelease(const KeyboardEvent& key, unsigned short mod)
{
	if (mod & GEM_MOD_CTRL) {
		return OnCheatKeyRelease(key, mod);
	}

	switch (key.keycode) {
			//FIXME: move these to guiscript
		case GEM_TAB: // remove overhead partymember hp/maxhp / names
			DisplayHeadHPNames(false, viewport);
			break;
		case GEM_UP:
		case GEM_DOWN:
		case GEM_LEFT:
		case GEM_RIGHT:
			unsigned int releasedKey;
			releasedKey = 1 << (key.keycode - GEM_LEFT);
			scrollKeysDown &= ~releasedKey;
			scrollKeysActive &= ~releasedKey;

			// If the opposite arrow key is still held down, switch to that direction:
			unsigned int oppositeKey;
			oppositeKey = (releasedKey & (SCROLL_LEFT | SCROLL_UP)) ? releasedKey << 1 : releasedKey >> 1;
			if (scrollKeysDown & oppositeKey) {
				scrollKeysActive |= oppositeKey;
			}

			// Update the vector to stop scrolling in the direction that was released:
			ApplyKeyScrolling();
			break;
		default:
			return false;
	}
	return true;
}

String GameControl::TooltipText() const
{
	const Map* area = CurrentArea();
	if (!area) {
		return View::TooltipText();
	}

	const Point& gameMousePos = GameMousePos();
	if (!area->IsVisible(gameMousePos)) {
		return View::TooltipText();
	}

	const Actor* actor = area->GetActor(gameMousePos, GA_NO_DEAD | GA_NO_UNSCHEDULED);
	if (!actor || actor->GetStat(IE_MC_FLAGS) & MC_NO_TOOLTIPS || (!actor->InParty && actor->IsInvisibleTo(nullptr))) {
		return View::TooltipText();
	}

	static String tip; // only one game control and we return a const& so cant be temporary.
	// pst ignores TalkCount
	if (core->HasFeature(GFFlags::PST_STATE_FLAGS)) {
		tip = actor->GetName();
	} else {
		tip = actor->GetDefaultName();
	}

	int hp = actor->GetStat(IE_HITPOINTS);
	int maxhp = actor->GetStat(IE_MAXHITPOINTS);

	if (actor->InParty) {
		if (core->HasFeature(GFFlags::ONSCREEN_TEXT)) {
			tip += u": ";
		} else {
			tip += u"\n";
		}

		if (actor->HasVisibleHP()) {
			tip += fmt::format(u"{}/{}", hp, maxhp);
		} else {
			tip += u"?";
		}
	} else {
		// a guess at a neutral check
		bool enemy = actor->GetStat(IE_EA) != EA_NEUTRAL;
		// test for an injured string being present for this game
		ieStrRef strref = DisplayMessage::GetStringReference(HCStrings::Uninjured);
		if (enemy && strref != ieStrRef::INVALID) {
			// non-neutral, not in party: display injured string
			// these boundaries are just a guess
			HCStrings strIdx = HCStrings::Injured4;
			if (hp == maxhp) {
				strIdx = HCStrings::Uninjured;
			} else if (hp > (maxhp * 3) / 4) {
				strIdx = HCStrings::Injured1;
			} else if (hp > maxhp / 2) {
				strIdx = HCStrings::Injured2;
			} else if (hp > maxhp / 3) {
				strIdx = HCStrings::Injured3;
			}
			strref = DisplayMessage::GetStringReference(strIdx);
			String injuredstring = core->GetString(strref, STRING_FLAGS::NONE);
			tip += u"\n" + injuredstring;
		}
	}

	return tip;
}

Holder<Sprite2D> GameControl::GetTargetActionCursor(TargetMode mode)
{
	int curIdx = -1;
	switch (mode) {
		case TargetMode::Talk:
			curIdx = IE_CURSOR_TALK;
			break;
		case TargetMode::Attack:
			curIdx = IE_CURSOR_ATTACK;
			break;
		case TargetMode::Cast:
			curIdx = IE_CURSOR_CAST;
			break;
		case TargetMode::Defend:
			curIdx = IE_CURSOR_DEFEND;
			break;
		case TargetMode::Pick:
			curIdx = IE_CURSOR_PICK;
			break;
		default:
			break;
	}
	if (curIdx != -1) {
		return core->Cursors[curIdx];
	}
	return nullptr;
}

Holder<Sprite2D> GameControl::Cursor() const
{
	Holder<Sprite2D> cursor = View::Cursor();
	if (!cursor && lastCursor != IE_CURSOR_INVALID) {
		int idx = lastCursor & ~IE_CURSOR_GRAY;
		if (EventMgr::MouseDown()) {
			++idx;
		}
		cursor = core->Cursors[idx];
	}
	return cursor;
}

/** Mouse Over Event */
bool GameControl::OnMouseOver(const MouseEvent& /*me*/)
{
	const Map* area = CurrentArea();
	if (!area) {
		return false;
	}

	Actor* lastActor = area->GetActorByGlobalID(lastActorID);

	// (un)highlight portrait border for pcs
	auto PulsateBorder = [&lastActor](bool enable) {
		if (!lastActor || !lastActor->InParty) return;

		const Window* win = GemRB::GetWindow(0, "PORTWIN");
		if (!win) return;

		Button* btn = GetControl<Button>(lastActor->InParty - 1, win);
		if (!btn) return;
		bool selected = lastActor->IsSelected();
		if (!selected) btn->EnableBorder(0, enable);
		btn->EnablePulsating(enable);
	};

	if (lastActor) {
		lastActor->SetOver(false);
		PulsateBorder(false);
	}

	Point gameMousePos = GameMousePos();
	// let us target party members even if they are invisible
	lastActor = area->GetActor(gameMousePos, GA_NO_DEAD | GA_NO_UNSCHEDULED);
	if (lastActor && lastActor->Modified[IE_EA] >= EA_CONTROLLED) {
		if (!lastActor->ValidTarget(targetTypes) || !area->IsVisible(gameMousePos)) {
			lastActor = nullptr;
		}
	}

	if ((targetTypes & GA_NO_SELF) && lastActor == core->GetFirstSelectedActor()) {
		lastActor = nullptr;
	}

	if (lastActor && lastActor->GetStat(IE_NOCIRCLE)) {
		lastActor = nullptr;
	}

	SetLastActor(lastActor);
	PulsateBorder(true);

	return true;
}

void GameControl::UpdateCursor()
{
	const Map* area = CurrentArea();
	if (!area) {
		lastCursor = IE_CURSOR_BLOCKED;
		return;
	}

	Point gameMousePos = GameMousePos();
	int nextCursor = area->GetCursor(gameMousePos);
	//make the invisible area really invisible
	if (nextCursor == IE_CURSOR_INVALID) {
		lastCursor = IE_CURSOR_BLOCKED;
		return;
	} else if (nextCursor == IE_CURSOR_BLOCKED) {
		// don't leak that an enemy is invisible and treat its space as passable
		// it's not necessarily lastActor, so we have to search again
		const Actor* actor = area->GetActor(gameMousePos, GA_NO_DEAD | GA_NO_UNSCHEDULED | GA_NO_ALLY);
		if (actor && actor->IsInvisibleTo(nullptr)) {
			lastCursor = IE_CURSOR_WALK;
			return;
		}
	}

	Door* overDoor = Scriptable::As<Door>(overMe);
	if (overDoor) {
		overDoor->Highlight = false;
	}
	Container* overContainer = Scriptable::As<Container>(overMe);
	if (overContainer) {
		overContainer->Highlight = false;
	}

	overMe = overDoor = area->TMap->GetDoor(gameMousePos);
	// ignore infopoints and containers beneath doors
	// pst mortuary door right above the starting position is a good test
	if (overDoor) {
		if (overDoor->Visible()) {
			nextCursor = overDoor->GetCursor(targetMode, lastCursor);
		} else {
			overMe = nullptr;
		}
	} else {
		InfoPoint* overInfoPoint = area->TMap->GetInfoPoint(gameMousePos, false);
		overMe = overInfoPoint;
		if (overInfoPoint) {
			nextCursor = overInfoPoint->GetCursor(targetMode);
		}
		// recheck in case the position was different, resulting in a new isVisible check
		if (nextCursor == IE_CURSOR_INVALID) {
			lastCursor = IE_CURSOR_BLOCKED;
			return;
		}

		// don't allow summons to try travelling (alone), since it causes tons of loading
		if (nextCursor == IE_CURSOR_TRAVEL && core->GetGame()->OnlyNPCsSelected()) {
			lastCursor = IE_CURSOR_BLOCKED;
			return;
		}

		// let containers override infopoints if at the same location
		// needed in bg2 ar0809 or you can't get the loot on the altar
		// how ar3201 and a bunch in the pst mortuary (eg. near Ei-vene) show it as a usability win as well
		overContainer = area->TMap->GetContainer(gameMousePos);
		if (overContainer) {
			overMe = overContainer;
		}
	}

	if (overContainer) {
		nextCursor = overContainer->GetCursor(targetMode, lastCursor);
	}
	// recheck in case the position was different, resulting in a new isVisible check
	// fixes bg2 long block door in ar0801 above vamp beds, crashing on mouseover (too big)
	if (nextCursor == IE_CURSOR_INVALID) {
		lastCursor = IE_CURSOR_BLOCKED;
		return;
	}

	const Actor* lastActor = area->GetActorByGlobalID(lastActorID);
	if (lastActor) {
		// don't change the cursor for birds
		if (lastActor->GetStat(IE_DONOTJUMP) == DNJ_BIRD) return;

		ieDword type = lastActor->GetStat(IE_EA);
		if (type >= EA_EVILCUTOFF || type == EA_GOODBUTRED) {
			nextCursor = IE_CURSOR_ATTACK;
		} else if (type > EA_CHARMED) {
			if (lastActor->GetStat(IE_NOCIRCLE)) return;
			nextCursor = IE_CURSOR_TALK;
			//don't let the pc to talk to frozen/stoned creatures
			ieDword state = lastActor->GetStat(IE_STATE_ID);
			if (state & (STATE_CANTMOVE ^ STATE_SLEEP)) {
				nextCursor |= IE_CURSOR_GRAY;
			}
		} else {
			nextCursor = IE_CURSOR_NORMAL;
		}
	}

	if (targetMode == TargetMode::Talk) {
		nextCursor = IE_CURSOR_TALK;
		if (!lastActor) {
			nextCursor |= IE_CURSOR_GRAY;
		} else {
			//don't let the pc to talk to frozen/stoned creatures
			ieDword state = lastActor->GetStat(IE_STATE_ID);
			if (state & (STATE_CANTMOVE ^ STATE_SLEEP)) {
				nextCursor |= IE_CURSOR_GRAY;
			}
		}
	} else if (targetMode == TargetMode::Attack) {
		nextCursor = IE_CURSOR_ATTACK;
		if (!lastActor && (!overMe || overMe->Type <= ST_TRIGGER)) {
			nextCursor |= IE_CURSOR_GRAY;
		}
	} else if (targetMode == TargetMode::Cast) {
		nextCursor = IE_CURSOR_CAST;
		// point is always valid if accessible
		// knock ignores that
		bool blocked = bool(area->GetBlocked(gameMousePos) & (PathMapFlags::PASSABLE | PathMapFlags::TRAVEL | PathMapFlags::ACTOR));
		bool ignoreSM = gamedata->GetSpecialSpell(spellName) & SpecialSpell::AreaTarget;
		if (!ignoreSM && (!blocked || (!(targetTypes & GA_POINT) && !lastActor))) {
			nextCursor |= IE_CURSOR_GRAY;
		}
	} else if (targetMode == TargetMode::Defend) {
		nextCursor = IE_CURSOR_DEFEND;
		if (!lastActor) {
			nextCursor |= IE_CURSOR_GRAY;
		}
	} else if (targetMode == TargetMode::Pick) {
		if (lastActor) {
			nextCursor = IE_CURSOR_PICK;
		} else if (!overMe) {
			nextCursor = IE_CURSOR_STEALTH | IE_CURSOR_GRAY;
		}
	}

	if (nextCursor >= 0) {
		lastCursor = nextCursor;
	}
}

bool GameControl::IsDisabledCursor() const
{
	bool isDisabled = View::IsDisabledCursor();
	if (lastCursor != IE_CURSOR_INVALID)
		isDisabled |= bool(lastCursor & IE_CURSOR_GRAY);

	return isDisabled;
}

void GameControl::DebugPaint(const Point& p, bool sample) const noexcept
{
	if (DebugFlags & (DEBUG_SHOW_SEARCHMAP | DEBUG_SHOW_MATERIALMAP | DEBUG_SHOW_HEIGHTMAP | DEBUG_SHOW_LIGHTMAP)) {
		Map* map = CurrentArea();
		SearchmapPoint tile { p };
		TileProps::Property prop = TileProps::Property::SEARCH_MAP;
		if (DebugFlags & DEBUG_SHOW_MATERIALMAP) {
			prop = TileProps::Property::MATERIAL;
		} else if (DebugFlags & DEBUG_SHOW_HEIGHTMAP) {
			prop = TileProps::Property::ELEVATION;
		} else if (DebugFlags & DEBUG_SHOW_LIGHTMAP) {
			prop = TileProps::Property::LIGHTING;
		}

		if (sample) {
			DebugPropVal = map->tileProps.QueryTileProp(tile, prop);
		} else {
			map->tileProps.SetTileProp(tile, prop, DebugPropVal);
		}
	}
}

bool GameControl::OnMouseDrag(const MouseEvent& me)
{
	if (EventMgr::ModState(GEM_MOD_CTRL)) {
		Point p = ConvertPointFromScreen(me.Pos());
		DebugPaint(p + viewport.origin, false);
		return true;
	}

	auto furtherAwayFromZero = [this](int a) {
		// at closer zoom, mouse and move speed may not be colinear due to hitting almost 0 here
		int b = a * static_cast<int>(GetScalePercent()) / 100;
		return std::abs(a) > std::abs(b) ? a : b;
	};

	if (me.ButtonState(GEM_MB_MIDDLE)) {
		auto delta = me.Delta();
		delta.x = furtherAwayFromZero(delta.x);
		delta.y = furtherAwayFromZero(delta.y);
		Scroll(delta);
		return true;
	}

	if (me.ButtonState(GEM_MB_MENU)) {
		InitFormation(gameClickPoint, true);
		return true;
	}

	if (targetMode != TargetMode::None) {
		// we are in a target mode; nothing here applies
		return true;
	}

	if (overMe) {
		return true;
	}

	if (me.ButtonState(GEM_MB_ACTION) && !isFormationRotation) {
		isSelectionRect = true;
		SetCursor(core->Cursors[IE_CURSOR_PRESSED]);
	}

	return true;
}

bool GameControl::OnTouchDown(const TouchEvent& te, unsigned short mod)
{
	if (EventMgr::NumFingersDown() == 2) {
		// container highlights
		DebugFlags |= DEBUG_SHOW_CONTAINERS | DEBUG_SHOW_DOORS;
	}

	// TODO: check pressure to distinguish between tooltip and HP modes
	if (View::OnTouchDown(te, mod)) {
		if (te.numFingers == 1) {
			screenMousePos = te.Pos();

			// if an actor is being touched show HP
			Actor* actor = GetLastActor();
			if (actor) {
				actor->DisplayHeadHPRatio();
			}
		}
		return true;
	}
	return false;
}

bool GameControl::OnTouchUp(const TouchEvent& te, unsigned short mod)
{
	if (EventMgr::ModState(GEM_MOD_ALT) == false) {
		DebugFlags &= ~(DEBUG_SHOW_CONTAINERS | DEBUG_SHOW_DOORS);
	}

	return View::OnTouchUp(te, mod);
}

bool GameControl::OnTouchGesture(const GestureEvent& gesture)
{
	if (gesture.numFingers == 1) {
		if (targetMode != TargetMode::None) {
			// we are in a target mode; nothing here applies
			return true;
		}

		screenMousePos = gesture.Pos();
		isSelectionRect = true;
	} else if (gesture.numFingers == 2) {
		if (gesture.dTheta < -0.2 || gesture.dTheta > 0.2) { // TODO: actually figure out a good number
			if (EventMgr::ModState(GEM_MOD_ALT) == false) {
				DebugFlags &= ~(DEBUG_SHOW_CONTAINERS | DEBUG_SHOW_DOORS);
			}

			isSelectionRect = false;

			if (core->GetGame()->selected.size() <= 1) {
				isFormationRotation = false;
			} else {
				screenMousePos = gesture.fingers[1].Pos();
				InitFormation(screenMousePos, true);
			}
		} else { // scroll viewport
			MoveViewportTo(viewport.origin - gesture.Delta(), false);
		}
	} else if (gesture.numFingers == 3) { // keyboard/console
		enum class SWIPE { DOWN = -1,
				   NONE = 0,
				   UP = 1 };
		SWIPE swipe = SWIPE::NONE;
		if (gesture.deltaY < -EventMgr::mouseDragRadius) {
			swipe = SWIPE::UP;
		} else if (gesture.deltaY > EventMgr::mouseDragRadius) {
			swipe = SWIPE::DOWN;
		}

		Window* consoleWin = GemRB::GetWindow(0, "WIN_CON");
		assert(consoleWin);

		// swipe up to show the keyboard
		// if the kwyboard is showing swipe up to access console
		// swipe down to hide both keyboard and console
		switch (swipe) {
			case SWIPE::DOWN:
				consoleWin->Close();
				VideoDriver->StopTextInput();
				consoleWin->Close();
				break;
			case SWIPE::UP:
				if (VideoDriver->InTextInput()) {
					consoleWin->Focus();
				}
				VideoDriver->StartTextInput();
				break;
			case SWIPE::NONE:
				break;
		}
	}
	return true;
}

Point GameControl::GameMousePos() const
{
	if (SceneCamera() && camera.scale > 0.0f) {
		return ScreenToMap(screenMousePos);
	}
	return viewport.origin + ConvertPointFromScreen(screenMousePos);
}

bool GameControl::SceneCamera() const
{
	return VideoDriver && VideoDriver->SupportsSceneTransform();
}

Point GameControl::ScreenToMap(const Point& screenPos) const
{
	Point local = View::ConvertPointFromScreen(screenPos);
	return Point(int(std::floor(camera.x + local.x * camera.scale)), int(std::floor(camera.y + local.y * camera.scale)));
}

void GameControl::UpdateCamera()
{
	if (!SceneCamera()) {
		camera.scale = 0.0f;
		return;
	}

	tick_t now = GetMilliseconds();
	float dt = camera.lastTick ? float(std::min<tick_t>(now - camera.lastTick, 100)) : 0.0f;
	camera.lastTick = now;

	float tx = float(viewport.x);
	float ty = float(viewport.y);
	float ts = float(GetScalePercent()) / 100.0f;
	const Map* area = CurrentArea();
	bool smooth = core->GetDictionary().Get("SmoothCamera", 1) != 0;
	// jumps (new area, centring on someone far away) and screen shakes are not eased
	bool snap = !smooth || camera.scale <= 0.0f || area != camera.area || (core->timer.IsShaking() && !ScenePolish::SmoothShake()) ||
		std::abs(tx - camera.x) > frame.w * ts * 1.5f || std::abs(ty - camera.y) > frame.h * ts * 1.5f;
	camera.area = area;
	if (snap) {
		camera.x = tx;
		camera.y = ty;
		camera.scale = ts;
		camera.pivot = false;
		return;
	}

	float kPan = 1.0f - std::exp(-dt / 60.0f);
	float kZoom = 1.0f - std::exp(-dt / 80.0f);
	// zoom eases in log space, so in and out feel the same
	float ls = std::log(camera.scale);
	camera.scale = std::exp(ls + (std::log(ts) - ls) * kZoom);
	if (std::abs(camera.scale - ts) < 0.0005f) camera.scale = ts;

	if (camera.pivot && viewport.origin == camera.pivotTarget) {
		// keep the map point under the cursor in place while the zoom animates
		camera.x = camera.pivotMapX - camera.pivotScreen.x * camera.scale;
		camera.y = camera.pivotMapY - camera.pivotScreen.y * camera.scale;
		if (camera.scale == ts) camera.pivot = false;
		return;
	}
	camera.pivot = false;
	camera.x += (tx - camera.x) * kPan;
	camera.y += (ty - camera.y) * kPan;
	if (std::abs(tx - camera.x) < 0.05f) camera.x = tx;
	if (std::abs(ty - camera.y) < 0.05f) camera.y = ty;
}

bool GameControl::OnGlobalMouseMove(const Event& e)
{
	// we are using the window->IsDisabled on purpose
	// to avoid bugs, we are disabling the window when we open one of the "top window"s
	// GC->IsDisabled is for other uses
	if (!window || window->IsDisabled() || (Flags() & IgnoreEvents) || scrollKeysActive) {
		return false;
	}

	if (e.mouse.ButtonState(GEM_MB_MIDDLE)) {
		// if we are panning the map don't scroll from being at the edge
		vpVector.reset();
		return false;
	}

	Region mask = frame;
	mask.ExpandAllSides(-1 * core->config.EdgeScrollOffset);

	screenMousePos = e.mouse.Pos();
	Point mp = View::ConvertPointFromScreen(e.mouse.Pos());
	int mousescrollspd = core->GetMouseScrollSpeed();
	mousescrollspd = (mousescrollspd * GetScalePercent()) / 100;

	if (mp.x < mask.x) {
		vpVector.x = -mousescrollspd;
	} else if (mp.x > mask.x + mask.w) {
		vpVector.x = mousescrollspd;
	} else {
		vpVector.x = 0;
	}

	if (mp.y < mask.y) {
		vpVector.y = -mousescrollspd;
	} else if (mp.y > mask.y + mask.h) {
		vpVector.y = mousescrollspd;
	} else {
		vpVector.y = 0;
	}

	if (!vpVector.IsZero()) {
		// cancel any scripted moves
		// we are not in dialog or cutscene mode anymore
		// and the user is attempting to move the viewport
		core->timer.SetMoveViewPort(viewport.origin, 0, false);
	}

	return true;
}

void GameControl::MoveViewportUnlockedTo(Point p, bool center)
{
	Point half(viewport.w / 2, viewport.h / 2);
	if (center) {
		p -= half;
	}

	core->GetAudioDrv()->SetListenerPosition(p + half);
	viewport.origin = p;
}

bool GameControl::MoveViewportTo(Point p, bool center, int speed)
{
	const Map* area = CurrentArea();
	bool canMove = area != nullptr;
	int mwinh = 0;

	if (center || (!(updateVPTimer && speed) && canMove && p != viewport.origin)) {
		const TextArea* mta = core->GetMessageTextArea();
		if (mta) {
			mwinh = (mta->GetWindow()->Frame().h * GetScalePercent()) / 100;
		}
	}

	if (updateVPTimer && speed) {
		updateVPTimer = false;
		if (center) {
			// also account for message window height, since it can cover the center of the
			// window at lowest resolutions and we want to center in the visible map space
			// GlobalTimer does its own centering, so we only offset
			p.y += mwinh / 2;
		}
		core->timer.SetMoveViewPort(p, speed, center);
	} else if (canMove && p != viewport.origin) {
		updateVPTimer = true;

		Size mapsize = area->GetSize();

		if (center) {
			// should we account for the message window height here too?
			p.x -= viewport.w / 2;
			p.y -= viewport.h / 2;
		}

		// TODO: make the overflow more dynamic
		if (viewport.w >= mapsize.w + 64) {
			p.x = (mapsize.w - viewport.w) / 2;
			canMove = false;
		} else if (p.x + viewport.w >= mapsize.w + 64) {
			p.x = mapsize.w - viewport.w + 64;
			canMove = false;
		} else if (p.x < -64) {
			p.x = -64;
			canMove = false;
		}

		constexpr int padding = 50;
		if (viewport.h >= mapsize.h + mwinh + padding) {
			p.y = (mapsize.h - viewport.h) / 2 + padding;
			canMove = false;
		} else if (p.y + viewport.h >= mapsize.h + mwinh + padding) {
			p.y = mapsize.h - viewport.h + mwinh + padding;
			canMove = false;
		} else if (p.y < 0) {
			p.y = 0;
			canMove = false;
		}

		MoveViewportUnlockedTo(p, false); // we already handled centering
	} else {
		updateVPTimer = true;
		canMove = (p != viewport.origin);
	}

	if (canMove) {
		core->GetAudioSpatialMonitor().UpdateSoundEffects();
	}

	return canMove;
}

Region GameControl::Viewport() const
{
	return viewport;
}

//generate action code for source actor to try to attack a target
void GameControl::TryToAttack(Actor* source, const Actor* tgt) const
{
	if (TurnBasedForbids(source)) return;
	if (source->GetStat(IE_SEX) == SEX_ILLUSION) return;
	source->CommandActor(GenerateActionDirect("NIDSpecial3()", tgt));
}

//generate action code for source actor to try to defend a target
void GameControl::TryToDefend(Actor* source, const Actor* tgt) const
{
	if (TurnBasedForbids(source)) return;
	source->SetModal(Modal::None);
	source->CommandActor(GenerateActionDirect("NIDSpecial4()", tgt));
}

// generate action code for source actor to try to pick pockets of a target (if an actor)
// else if door/container try to pick a lock/disable trap
// The -1 flag is a placeholder for dynamic target IDs
void GameControl::TryToPick(Actor* source, const Scriptable* tgt) const
{
	if (TurnBasedForbids(source)) return;
	source->SetModal(Modal::None);
	std::string cmdString;
	cmdString.reserve(20);
	switch (tgt->Type) {
		case ST_ACTOR:
			cmdString = "PickPockets([-1])";
			break;
		case ST_DOOR:
		case ST_CONTAINER:
			if (((const Highlightable*) tgt)->Trapped && ((const Highlightable*) tgt)->TrapDetected) {
				cmdString = "RemoveTraps([-1])";
			} else {
				cmdString = "PickLock([-1])";
			}
			break;
		default:
			Log(ERROR, "GameControl", "Invalid pick target of type {}", tgt->Type);
			return;
	}
	source->CommandActor(GenerateActionDirect(std::move(cmdString), tgt));
}

//generate action code for source actor to try to disable trap (only trap type active regions)
void GameControl::TryToDisarm(Actor* source, const InfoPoint* tgt) const
{
	if (TurnBasedForbids(source)) return;
	if (tgt->Type != ST_PROXIMITY) return;

	source->SetModal(Modal::None);
	source->CommandActor(GenerateActionDirect("RemoveTraps([-1])", tgt));
}

//generate action code for source actor to use item/cast spell on a point
void GameControl::TryToCast(Actor* source, const Point& tgt)
{
	if (TurnBasedForbids(source)) return;
	if ((targetTypes & GA_POINT) == false) {
		return; // not allowed to target point
	}

	if (!spellCount) {
		ResetTargetMode();
		return; // not casting or using an own item
	}
	source->Stop();

	spellCount--;
	std::string tmp;
	tmp.reserve(30);
	if (spellOrItem >= 0) {
		if (spellIndex < 0) {
			tmp = "SpellPointNoDec(\"\",[0.0])";
		} else {
			tmp = "SpellPoint(\"\",[0.0])";
		}
	} else {
		//using item on target
		tmp = "UseItemPoint(\"\",[0,0],0)";
	}
	Holder<Action> action = GenerateAction(std::move(tmp));
	action->pointParameter = tgt;
	if (spellOrItem >= 0) {
		if (spellIndex < 0) {
			action->resref0Parameter = spellName;
		} else {
			const CREMemorizedSpell* si;
			//spell casting at target
			si = source->spellbook.GetMemorizedSpell(spellOrItem, spellSlot, spellIndex);
			if (!si) {
				ResetTargetMode();
				return;
			}
			action->resref0Parameter = si->SpellResRef;
		}
	} else {
		action->int0Parameter = spellSlot;
		action->int1Parameter = spellIndex;
		action->int2Parameter = UI_SILENT;
		//for multi-shot items like BG wand of lightning
		if (spellCount) {
			action->int2Parameter |= UI_NOAURA | UI_NOCHARGE;
		}
	}
	source->AddAction(std::move(action));
	if (!spellCount) {
		ResetTargetMode();
	}
}

//generate action code for source actor to use item/cast spell on another actor
void GameControl::TryToCast(Actor* source, const Actor* tgt)
{
	if (TurnBasedForbids(source)) return;
	// pst has no aura pollution
	bool aural = true;
	if (spellCount >= 1000) {
		spellCount -= 1000;
		aural = false;
	}

	if (!spellCount) {
		ResetTargetMode();
		return; //not casting or using an own item
	}
	source->Stop();

	// cannot target spells on invisible or sanctuaried creatures
	// invisible actors are invisible, so this is usually impossible by itself, but improved invisibility changes that
	if (source != tgt && tgt->Untargetable(spellName, source)) {
		displaymsg->DisplayConstantStringName(HCStrings::NoSeeNoCast, GUIColors::RED, source);
		ResetTargetMode();
		return;
	}

	spellCount--;
	std::string tmp;
	tmp.reserve(20);
	if (spellOrItem >= 0) {
		if (spellIndex < 0) {
			tmp = "NIDSpecial7()";
		} else {
			tmp = "NIDSpecial6()";
		}
	} else {
		//using item on target
		tmp = "NIDSpecial5()";
	}
	Holder<Action> action = GenerateActionDirect(std::move(tmp), tgt);
	if (spellOrItem >= 0) {
		if (spellIndex < 0) {
			action->resref0Parameter = spellName;
		} else {
			const CREMemorizedSpell* si;
			//spell casting at target
			si = source->spellbook.GetMemorizedSpell(spellOrItem, spellSlot, spellIndex);
			if (!si) {
				ResetTargetMode();
				return;
			}
			action->resref0Parameter = si->SpellResRef;
		}
	} else {
		action->int0Parameter = spellSlot;
		action->int1Parameter = spellIndex;
		action->int2Parameter = UI_SILENT;
		if (!aural) {
			action->int2Parameter |= UI_NOAURA;
		}
		//for multi-shot items like BG wand of lightning
		if (spellCount) {
			action->int2Parameter |= UI_NOAURA | UI_NOCHARGE;
		}
	}
	source->AddAction(std::move(action));
	if (!spellCount) {
		ResetTargetMode();
	}
}

//generate action code for source actor to use talk to target actor
void GameControl::TryToTalk(Actor* source, const Actor* tgt) const
{
	if (TurnBasedForbids(source)) return;
	if (source->GetStat(IE_SEX) == SEX_ILLUSION || source->fxqueue.HasEffectWithParam(puppet_ref, 3)) {
		return;
	}
	//Nidspecial1 is just an unused action existing in all games
	//(non interactive demo)
	//i found no fitting action which would emulate this kind of
	// dialog initiation
	source->SetModal(Modal::None);
	dialoghandler->SetTarget(tgt); //this is a hack, but not so deadly
	source->CommandActor(GenerateActionDirect("NIDSpecial1()", tgt));
}

//generate action code for actor appropriate for the target mode when the target is a container
void GameControl::HandleContainer(Container* container, Actor* actor)
{
	if (actor->GetStat(IE_SEX) == SEX_ILLUSION || actor->fxqueue.HasEffectWithParam(puppet_ref, 3)) {
		return;
	}
	//container is disabled, it should not react
	if (container->Flags & CONT_DISABLED) {
		return;
	}

	if ((targetMode == TargetMode::Cast) && spellCount) {
		//we'll get the container back from the coordinates
		targetTypes |= GA_POINT;
		TryToCast(actor, container->Pos);
		//Do not reset target_mode, TryToCast does it for us!!
		return;
	}

	core->SetEventFlag(EF_RESETTARGET);

	if (targetMode == TargetMode::Attack) {
		std::string Tmp = fmt::format("BashDoor(\"{}\")", container->GetScriptName());
		actor->CommandActor(GenerateAction(std::move(Tmp)));
		return;
	}

	if (targetMode == TargetMode::Pick) {
		TryToPick(actor, container);
		return;
	}

	// familiars can not pick up items
	if (actor->GetBase(IE_EA) == EA_FAMILIAR) {
		displaymsg->DisplayConstantString(HCStrings::FamiliarNoHands, GUIColors::WHITE, actor);
		return;
	}

	container->AddTrigger(TriggerEntry(trigger_clicked, actor->GetGlobalID()));
	core->SetCurrentContainer(actor, container);
	actor->CommandActor(GenerateAction("UseContainer()"));
}

//generate action code for actor appropriate for the target mode when the target is a door
void GameControl::HandleDoor(Door* door, Actor* actor)
{
	if (actor->GetStat(IE_SEX) == SEX_ILLUSION) return;
	if ((targetMode == TargetMode::Cast) && spellCount) {
		//we'll get the door back from the coordinates
		unsigned int dist;
		const Point* p = door->GetClosestApproach(actor, dist);
		TryToCast(actor, *p);
		return;
	}

	core->SetEventFlag(EF_RESETTARGET);

	if (targetMode == TargetMode::Attack) {
		std::string Tmp = fmt::format("BashDoor(\"{}\")", door->GetScriptName());
		actor->CommandActor(GenerateAction(std::move(Tmp)));
		return;
	}

	if (targetMode == TargetMode::Pick) {
		TryToPick(actor, door);
		return;
	}

	door->AddTrigger(TriggerEntry(trigger_clicked, actor->GetGlobalID()));
	// internal gemrb toggle door action hack - should we use UseDoor instead?
	auto toggle = GenerateAction("NIDSpecial9()");
	toggle->int0Parameter = door->GetGlobalID();
	actor->CommandActor(std::move(toggle));
}

//generate action code for actor appropriate for the target mode when the target is an active region (infopoint, trap or travel)
bool GameControl::HandleActiveRegion(InfoPoint* trap, Actor* actor, const Point& p)
{
	if (actor->GetStat(IE_SEX) == SEX_ILLUSION) return false;
	if ((targetMode == TargetMode::Cast) && spellCount) {
		//we'll get the active region from the coordinates (if needed)
		TryToCast(actor, p);
		//don't bother with this region further
		return true;
	}
	if (targetMode == TargetMode::Pick) {
		TryToDisarm(actor, trap);
		return true;
	}
	if (actor->fxqueue.HasEffectWithParam(puppet_ref, 3)) return false;

	switch (trap->Type) {
		case ST_TRAVEL:
			trap->AddTrigger(TriggerEntry(trigger_clicked, actor->GetGlobalID()));
			actor->objects.LastMarked = trap->GetGlobalID();
			//clear the go closer flag
			trap->GetCurrentArea()->LastGoCloser = 0;
			return false;
		case ST_TRIGGER:
			// pst, eg. ar1500
			if (!trap->GetDialog().IsEmpty()) {
				trap->AddAction("Dialogue([PC])");
				return true;
			}

			// always display overhead text; totsc's ar0511 library relies on it
			DisplayString(trap);

			//the importer shouldn't load the script
			//if it is unallowed anyway (though
			//deactivated scripts could be reactivated)
			//only the 'trapped' flag should be honoured
			//there. Here we have to check on the
			//reset trap and deactivated flags
			if (trap->Scripts[0]) {
				if (!(trap->Flags & TRAP_DEACTIVATED) && !(GetDialogueFlags() & DF_FREEZE_SCRIPTS)) {
					trap->AddTrigger(TriggerEntry(trigger_clicked, actor->GetGlobalID()));
					actor->objects.LastMarked = trap->GetGlobalID();
					//directly feeding the event, even if there are actions in the queue
					//trap->Scripts[0]->Update();
					// FIXME
					trap->ExecuteScript(1);
					trap->ProcessActions();
				}
			}

			// bleh, pst has this infopoint that needs to trigger, but covers two others that also do
			if (trap->Flags & TRAP_SILENT) {
				// recheck if there are other infopoints at this position
				const Map* map = trap->GetCurrentArea();
				InfoPoint* ip2 = map->TMap->GetInfoPoint(p, true);
				DisplayString(ip2);
			}

			if (trap->GetUsePoint()) {
				std::string Tmp = fmt::format("TriggerWalkTo(\"{}\")", trap->GetScriptName());
				actor->CommandActor(GenerateAction(std::move(Tmp)));
				return true;
			}
			return true;
		default:;
	}
	return false;
}

// Calculate the angle between a clicked point and the first selected character,
// so that we can set a sensible orientation for the formation.
void GameControl::InitFormation(const Point& clickPoint, bool rotating)
{
	// Of course single actors don't get rotated, but we need to ensure
	// isFormationRotation is set in all cases where we initiate movement,
	// since OnMouseUp tests for it.
	if (isFormationRotation || core->GetGame()->selected.empty()) {
		return;
	}

	const Actor* selectedActor = GetMainSelectedActor();

	isFormationRotation = rotating;
	formationBaseAngle = AngleFromPoints(clickPoint, selectedActor->Pos);
	SetCursor(core->Cursors[IE_CURSOR_USE]);
}

void GameControl::TryDefaultTalk() const
{
	Actor* targetActor = GetLastActor();
	if (targetActor) {
		targetActor->PlaySelectionSound(true);
	}
}

/** Mouse Button Down */
bool GameControl::OnMouseDown(const MouseEvent& me, unsigned short Mod)
{
	if (Mod & GEM_MOD_CTRL) { // debug paint mode
		return true;
	}

	Point p = ConvertPointFromScreen(me.Pos());
	gameClickPoint = p + viewport.origin;

	switch (me.button) {
		case GEM_MB_MENU: //right click.
			// pst's radial menu; the hotbar ("Hotbar" setting) replaces it, right click then only cancels
			if (core->HasFeature(GFFlags::HAS_FLOAT_MENU) && !Mod && !core->GetDictionary().Get("Hotbar", 1)) {
				core->GetGUIScriptEngine()->RunFunction("GUICommon", "OpenFloatMenuWindow", p, false);
			} else {
				TryDefaultTalk();
			}
			break;
		case GEM_MB_ACTION:
			// PST uses alt + left click for formation rotation
			// is there any harm in this being true in all games?
			if (me.repeats != 2 && EventMgr::ModState(GEM_MOD_ALT)) {
				InitFormation(gameClickPoint, true);
			}

			break;
	}
	return true;
}

// list of allowed area and exit combinations in pst that trigger worldmap travel
static const ResRefMap<std::vector<ResRef>> pstWMapExits {
	{ "ar0100", { "to0300", "to0200", "to0101" } },
	{ "ar0101", { "to0100" } },
	{ "ar0200", { "to0100", "to0301", "to0400" } },
	{ "ar0300", { "to0100", "to0301", "to0400" } },
	{ "ar0301", { "to0200", "to0300" } },
	{ "ar0400", { "to0200", "to0300" } },
	{ "ar0500", { "to0405", "to0600" } },
	{ "ar0600", { "to0500" } }
};

// pst: determine if we need to trigger worldmap travel, since it had it's own system
// eg. it doesn't use the searchmap for this in ar0500 when travelling globally
// has to be a plain travel region and on the whitelist
bool GameControl::ShouldTriggerWorldMap(const Actor* pc) const
{
	if (!core->HasFeature(GFFlags::TEAM_MOVEMENT)) return false;

	bool keyAreaVisited = CheckVariable(pc, "AR0500_Visited", "GLOBAL") == 1;
	if (!keyAreaVisited) return false;

	bool teamMoved = (pc->GetInternalFlag() & IF_USEEXIT) && overMe && overMe->Type == ST_TRAVEL;
	if (!teamMoved) return false;

	teamMoved = false;
	auto wmapExits = pstWMapExits.find(pc->GetCurrentArea()->GetScriptRef());
	if (wmapExits != pstWMapExits.end()) {
		for (const auto& exit : wmapExits->second) {
			if (exit == overMe->GetScriptName()) {
				teamMoved = true;
				break;
			}
		}
	}

	return teamMoved;
}

/** Mouse Button Up */
bool GameControl::OnMouseUp(const MouseEvent& me, unsigned short Mod)
{
	if (Mod & GEM_MOD_CTRL) {
		Point p = ConvertPointFromScreen(me.Pos());
		DebugPaint(p + viewport.origin, me.button == GEM_MB_MENU);
		return true;
	}

	//heh, i found no better place
	core->CloseCurrentContainer();

	Point p = ConvertPointFromScreen(me.Pos()) + viewport.origin;
	bool isDoubleClick = me.repeats == 2;
	bool tryToRun = isDoubleClick;
	if (core->HasFeature(GFFlags::HAS_FLOAT_MENU)) {
		tryToRun = tryToRun || (Mod & GEM_MOD_SHIFT);
	}

	// right click
	if (me.button == GEM_MB_MENU) {
		// turn based combat: right click stops a party member's walk, the rest of its movement stays
		if (GetTurnBasedActor() && core->GetGame()->combat.CancelMove()) {
			ClearMouseState();
			return true;
		}
		if (turnPreview.pending) {
			CancelTurnBasedMove();
			ClearMouseState();
			return true;
		}
		ieDword actionLevel = core->GetDictionary().Get("ActionLevel", 0);

		if (targetMode != TargetMode::None || actionLevel) {
			if (!core->HasFeature(GFFlags::HAS_FLOAT_MENU) || core->GetDictionary().Get("Hotbar", 1)) {
				SetTargetMode(TargetMode::None);
			}
			// update the action bar
			core->ResetActionBar();
			ClearMouseState();
			return true;
		} else {
			p = gameClickPoint;
		}
	} else if (me.button == GEM_MB_MIDDLE) {
		// do nothing, so middle button panning doesn't trigger a move
		// except reset zoom if there's no panning
		if (me.Pos() == screenMousePos) {
			SetScalePercent(100, true);
		}
		return true;
	} else {
		// any other button behaves as left click (scrollwhell buttons are mouse wheel events now)
		if (isDoubleClick)
			MoveViewportTo(p, true);

		// handle actions
		if (targetMode == TargetMode::None && lastActorID) {
			switch (lastCursor & ~IE_CURSOR_GRAY) {
				case IE_CURSOR_TALK:
					SetTargetMode(TargetMode::Talk);
					break;
				case IE_CURSOR_ATTACK:
					SetTargetMode(TargetMode::Attack);
					break;
				case IE_CURSOR_CAST:
					SetTargetMode(TargetMode::Cast);
					break;
				case IE_CURSOR_DEFEND:
					SetTargetMode(TargetMode::Defend);
					break;
				case IE_CURSOR_PICK:
					SetTargetMode(TargetMode::Pick);
					break;
				default:
					break;
			}
		}

		if (targetMode == TargetMode::None && (isSelectionRect || lastActorID)) {
			MakeSelection(Mod & GEM_MOD_SHIFT);
			ClearMouseState();
			return true;
		}

		if (lastCursor == IE_CURSOR_BLOCKED) {
			// don't allow travel if the destination is actually blocked
			return false;
		}

		bool alreadyActed = false;
		if (overMe && (overMe->Type == ST_DOOR || overMe->Type == ST_CONTAINER || (overMe->Type == ST_TRAVEL && targetMode == TargetMode::None))) {
			// move to the object before trying to interact with it
			// except for pst worldmapping purposes, where we need Actor::UsedExit to be called sooner
			Actor* mainActor = GetMainSelectedActor();
			if (mainActor && overMe->Type != ST_TRAVEL) {
				CreateMovement(mainActor, p, false, tryToRun); // let one actor handle doors, loot and containers
			} else if (core->HasFeature(GFFlags::TEAM_MOVEMENT) && overMe->Type == ST_TRAVEL) {
				PerformSelectedAction(p);
				alreadyActed = true;
				CommandSelectedMovement(p, overMe->Type != ST_TRAVEL, false, tryToRun);
			} else {
				CommandSelectedMovement(p, overMe->Type != ST_TRAVEL, false, tryToRun);
			}
		}

		if (targetMode != TargetMode::None || (overMe && overMe->Type != ST_ACTOR)) {
			if (!alreadyActed) PerformSelectedAction(p);
			ClearMouseState();
			return true;
		}

		// Ensure that left-click movement also orients the formation
		// in the direction of movement.
		InitFormation(p, false);
	}

	// handle movement/travel, but not if we just opened the float window
	// or if it doesn't make sense due to the location
	bool saneCursor = lastCursor != IE_CURSOR_BLOCKED && lastCursor != IE_CURSOR_NORMAL && lastCursor != IE_CURSOR_TALK;
	if ((!core->HasFeature(GFFlags::HAS_FLOAT_MENU) || me.button != GEM_MB_MENU) && saneCursor) {
		if (core->GetGame()->combat.IsRunning()) {
			// only the active party member moves, and only as far as its turn allows
			if (me.button != GEM_MB_MENU) {
				HandleTurnBasedMove(p, false);
			}
		} else {
			// pst has different mod keys
			int modKey = GEM_MOD_SHIFT;
			if (core->HasFeature(GFFlags::HAS_FLOAT_MENU)) modKey = GEM_MOD_CTRL;
			CommandSelectedMovement(p, lastCursor != IE_CURSOR_TRAVEL, Mod & modKey, tryToRun);
		}
	}
	ClearMouseState();
	return true;
}

void GameControl::PerformSelectedAction(const Point& p)
{
	const Game* game = core->GetGame();
	const Map* area = game->GetCurrentArea();
	Actor* targetActor = area->GetActor(p, targetTypes & ~GA_NO_HIDDEN);
	if (targetActor && targetActor->GetStat(IE_NOCIRCLE) == 0) {
		PerformActionOn(targetActor);
		return;
	}

	Actor* selectedActor = GetMainSelectedActor();
	if (!selectedActor) {
		return;
	}

	//add a check if you don't want some random monster handle doors and such
	if (targetMode == TargetMode::Cast && !(gamedata->GetSpecialSpell(spellName) & SpecialSpell::AreaTarget)) {
		//the player is using an item or spell on the ground
		targetTypes |= GA_POINT;
		TryToCast(selectedActor, p);
	} else if (!overMe) {
		return;
	} else if (overMe->Type == ST_DOOR) {
		HandleDoor(Scriptable::As<Door>(overMe), selectedActor);
	} else if (overMe->Type == ST_CONTAINER) {
		HandleContainer(Scriptable::As<Container>(overMe), selectedActor);
	} else if (overMe->Type == ST_TRAVEL && targetMode == TargetMode::None) {
		ieDword exitID = overMe->GetGlobalID();
		if (core->HasFeature(GFFlags::TEAM_MOVEMENT)) {
			// pst forces everyone to travel (eg. ar0201 outside_portal)
			int i = game->GetPartySize(false);
			while (i--) {
				game->GetPC(i, false)->UseExit(exitID);
			}
		} else {
			size_t i = game->selected.size();
			while (i--) {
				game->selected[i]->UseExit(exitID);
			}
		}
		if (HandleActiveRegion(Scriptable::As<InfoPoint>(overMe), selectedActor, p)) {
			core->SetEventFlag(EF_RESETTARGET);
		}
	} else if (overMe->Type == ST_TRAVEL || overMe->Type == ST_PROXIMITY || overMe->Type == ST_TRIGGER) {
		if (HandleActiveRegion(Scriptable::As<InfoPoint>(overMe), selectedActor, p)) {
			core->SetEventFlag(EF_RESETTARGET);
		}
	}
}

void GameControl::CommandSelectedMovement(const Point& p, bool formation, bool append, bool tryToRun) const
{
	const Game* game = core->GetGame();

	// construct a sorted party
	std::vector<Actor*> party;
	// first, from the actual party
	int max = game->GetPartySize(false);
	for (int idx = 1; idx <= max; idx++) {
		Actor* act = game->FindPC(idx);
		assert(act);
		if (act->IsSelected()) {
			party.push_back(act);
		}
	}
	// then summons etc.
	for (Actor* selected : game->selected) {
		if (!selected->InParty) {
			party.push_back(selected);
		}
	}

	if (party.empty())
		return;

	float_t angle = isFormationRotation ? AngleFromPoints(GameMousePos(), p) : formationBaseAngle;
	bool doWorldMap = ShouldTriggerWorldMap(party[0]);

	std::vector<Point> formationPoints = GetFormationPoints(p, party, angle);
	for (size_t i = 0; i < party.size(); i++) {
		Actor* actor = party[i];
		// don't stop the party if we're just trying to add a waypoint
		if (!append) {
			actor->Stop();
		}

		if (formation && party.size() > 1) {
			CreateMovement(actor, formationPoints[i], append, tryToRun);
		} else {
			CreateMovement(actor, p, append, tryToRun);
		}

		// don't trigger the travel region, so everyone can bunch up there and NIDSpecial2 can take over
		if (doWorldMap) actor->SetInternalFlag(IF_PST_WMAPPING, BitOp::OR);
	}

	// p is a searchmap travel region or a plain travel region in pst (matching several other criteria)
	if (party[0]->GetCurrentArea()->GetCursor(p) == IE_CURSOR_TRAVEL || doWorldMap) {
		party[0]->AddAction("NIDSpecial2()");
	}
}

bool GameControl::OnMouseWheelScroll(const Point& delta)
{
	if (core->GetDictionary().Get("Zoom Lock", 0) == 1) {
		// touchpad two finger scrolling ends up here as well
		// redirect to panning like on middle-click, but make more intuitive
		Scroll({ delta.x, -delta.y });
		return true;
	}

	auto lastScale = GetScalePercent();
	// EEs have 27 zoom steps
	if (delta.y > 0 && zoomLevel > 1) {
		zoomLevel--;
	} else if (delta.y < 0 && zoomLevel < 27) {
		zoomLevel++;
	}

	ScaleViewport(lastScale);

	if (SceneCamera() && camera.scale > 0.0f && lastScale != GetScalePercent()) {
		// zoom toward the cursor instead of the screen centre
		Point local = View::ConvertPointFromScreen(screenMousePos);
		float mx = camera.x + local.x * camera.scale;
		float my = camera.y + local.y * camera.scale;
		float ns = float(GetScalePercent()) / 100.0f;
		Point goal(int(std::lround(mx - local.x * ns)), int(std::lround(my - local.y * ns)));
		MoveViewportTo(goal, false);
		// only pin the cursor point if the map edges didn't clamp the goal
		camera.pivot = std::abs(viewport.x - goal.x) <= 1 && std::abs(viewport.y - goal.y) <= 1;
		camera.pivotScreen = local;
		camera.pivotMapX = mx;
		camera.pivotMapY = my;
		camera.pivotTarget = viewport.origin;
	}

	return true;
}

void GameControl::ScaleViewport(unsigned int lastScale)
{
	// reset to 100% first
	if (lastScale != 100) {
		viewport.Unscale(lastScale);
	}

	auto scale = GetScalePercent();
	if (scale == 100) {
		return;
	}

	viewport.Scale(scale);
}

bool GameControl::OnControllerButtonDown(const ControllerEvent& ce)
{
	switch (ce.button) {
		case CONTROLLER_BUTTON_Y:
			return !core->GetGUIScriptEngine()->RunFunction("GUIINV", "ToggleInventoryWindow", false).IsNull();
		case CONTROLLER_BUTTON_X:
			return !core->GetGUIScriptEngine()->RunFunction("GUIMA", "ToggleMapWindow", false).IsNull();
		case CONTROLLER_BUTTON_BACK:
			core->SetEventFlag(EF_ACTION | EF_RESETTARGET);
			return true;
		default:
			return View::OnControllerButtonDown(ce);
	}
}

void GameControl::ApplyKeyScrolling()
{
	// Use the scrollKeysActive flags to set the vector values.
	// This vector is then used in WillDraw to perform scrolling.
	vpVector.reset();
	auto keyScrollSpd = core->GetDictionary().Get("Keyboard Scroll Speed", 64);

	if (scrollKeysActive & SK_LEFT) {
		vpVector.x = -1 * keyScrollSpd;
	} else if (scrollKeysActive & SK_RIGHT) {
		vpVector.x = keyScrollSpd;
	}
	if (scrollKeysActive & SK_UP) {
		vpVector.y = -1 * keyScrollSpd;
	} else if (scrollKeysActive & SK_DOWN) {
		vpVector.y = keyScrollSpd;
	}
}

void GameControl::Scroll(const Point& amt)
{
	MoveViewportTo(viewport.origin + amt, false);
}

// only party members and familiars can start conversations from the GUI
static Actor* GetTalkInitiator()
{
	const Game* game = core->GetGame();
	Actor* source;
	if (core->HasFeature(GFFlags::PROTAGONIST_TALKS)) {
		source = game->GetPC(0, false); // protagonist
	} else {
		source = core->GetFirstSelectedPC(false);
		if (!source) {
			// check also for familiars
			for (auto& npc : game->selected) {
				if (npc->GetBase(IE_EA) == EA_FAMILIAR) {
					source = npc;
					break;
				}
			}
		}
	}
	return source;
}

void GameControl::PerformActionOn(Actor* actor)
{
	const Game* game = core->GetGame();

	//determining the type of the clicked actor
	ieDword type = actor->GetStat(IE_EA);
	if (type >= EA_EVILCUTOFF || type == EA_GOODBUTRED) {
		type = ACT_ATTACK; //hostile
	} else if (type > EA_CHARMED) {
		type = ACT_TALK; //neutral
	} else {
		type = ACT_NONE; //party
	}

	if (targetMode == TargetMode::Attack) {
		type = ACT_ATTACK;
	} else if (targetMode == TargetMode::Talk) {
		type = ACT_TALK;
	} else if (targetMode == TargetMode::Cast) {
		type = ACT_CAST;
	} else if (targetMode == TargetMode::Defend) {
		type = ACT_DEFEND;
	} else if (targetMode == TargetMode::Pick) {
		type = ACT_THIEVING;
	}

	if (type != ACT_NONE && !actor->ValidTarget(targetTypes)) {
		return;
	}

	//we shouldn't zero this for two reasons in case of spell or item
	//1. there could be multiple targets
	//2. the target mode is important
	if (targetMode != TargetMode::Cast || !spellCount) {
		ResetTargetMode();
	}

	Actor* source = nullptr;
	switch (type) {
		case ACT_NONE: //none
			if (!actor->ValidTarget(GA_SELECT)) {
				return;
			}

			if (actor->InParty)
				SelectActor(actor->InParty);
			else if (actor->GetStat(IE_EA) <= EA_CHARMED) {
				/*let's select charmed/summoned creatures
				EA_CHARMED is the maximum value known atm*/
				core->GetGame()->SelectActor(actor, true, SELECT_REPLACE);
			}
			break;
		case ACT_TALK:
			if (!actor->ValidTarget(GA_TALK)) {
				return;
			}

			// talk (first selected talks)
			if (!game->selected.empty()) {
				source = GetTalkInitiator();
				if (source) {
					TryToTalk(source, actor);
				}
			}
			break;
		case ACT_ATTACK:
			//all of them attacks the red circled actor
			for (Actor* selectee : game->selected) {
				TryToAttack(selectee, actor);
			}
			break;
		case ACT_CAST: //cast on target or use item on target
			if (game->selected.size() == 1) {
				source = core->GetFirstSelectedActor();
			} else {
				source = game->GetSelectedPCSingle(true);
			}
			if (source) {
				TryToCast(source, actor);
			}
			break;
		case ACT_DEFEND:
			for (Actor* selectee : game->selected) {
				TryToDefend(selectee, actor);
			}
			break;
		case ACT_THIEVING:
			if (game->selected.size() == 1) {
				source = core->GetFirstSelectedActor();
			} else {
				source = game->GetSelectedPCSingle(true);
			}
			if (source) {
				TryToPick(source, actor);
			}
			break;
	}
}

//sets target mode, and resets the cursor
void GameControl::SetTargetMode(TargetMode mode)
{
	targetMode = mode;
	Window* win = GemRB::GetWindow(0, "PORTWIN");
	if (win) {
		win->SetCursor(GetTargetActionCursor(mode));
	}
}

void GameControl::ResetTargetMode()
{
	targetTypes = GA_NO_DEAD | GA_NO_HIDDEN | GA_NO_UNSCHEDULED;
	SetTargetMode(TargetMode::None);
}

void GameControl::UpdateTargetMode()
{
	SetTargetMode(targetMode);
}

Region GameControl::SelectionRect() const
{
	Point pos = GameMousePos();
	if (isSelectionRect) {
		return Region::RegionFromPoints(pos, gameClickPoint);
	}
	return Region(pos.x, pos.y, 1, 1);
}

void GameControl::MakeSelection(bool extend)
{
	Game* game = core->GetGame();

	if (!extend && !highlighted.empty()) {
		game->SelectActor(nullptr, false, SELECT_NORMAL);
	}

	std::vector<Actor*>::iterator it = highlighted.begin();
	for (; it != highlighted.end(); ++it) {
		Actor* act = *it;
		act->SetOver(false);
		game->SelectActor(act, true, SELECT_NORMAL);
	}
}

void GameControl::SetCutSceneMode(bool active)
{
	WindowManager* wm = core->GetWindowManager();
	if (active) {
		screenFlags.Set(ScreenFlags::Cutscene);
		vpVector.reset();
		wm->SetCursorFeedback(WindowManager::MOUSE_NONE);
	} else {
		screenFlags.Clear(ScreenFlags::Cutscene);
		wm->SetCursorFeedback(WindowManager::CursorFeedback(core->config.MouseFeedback));
	}
	SetFlags(IgnoreEvents, (active || InDialog()) ? BitOp::OR : BitOp::NAND);
}

//Create an overhead text over a scriptable target
//Multiple texts are possible, as this code copies the text to a new object
void GameControl::DisplayString(Scriptable* target) const
{
	if (!target || target->overHead.Empty() || target->overHead.IsDisplaying()) {
		return;
	}

	// add as a "subtitle" to the main message window
	auto lookup = core->GetDictionary().Get("Duplicate Floating Text", 0);
	if (lookup) {
		displaymsg->DisplayString(target->overHead.GetText());
	}
	target->overHead.Display(true, 0);
}

/** changes displayed map to the currently selected PC */
void GameControl::ChangeMap(const Actor* pc, bool forced)
{
	//swap in the area of the actor
	Game* game = core->GetGame();
	if (forced || (pc && pc->AreaName != game->CurrentArea)) {
		// disable so that drawing and events dispatched doesn't happen while there is not an area
		// we are single threaded, but game loading runs its own event loop which will cause events/drawing to come in
		SetDisabled(true);
		ClearMouseState();

		dialoghandler->EndDialog();
		overMe = nullptr;
		/*this is loadmap, because we need the index, not the pointer*/
		if (pc) {
			game->GetMap(pc->AreaName, true);
		} else {
			ResRef oldMaster = game->LastMasterArea; // only update it for party travel
			game->GetMap(game->CurrentArea, true);
			game->LastMasterArea = oldMaster;
		}

		if (!core->InCutSceneMode()) {
			// don't interfere with any scripted moves of the viewport
			// checking core->timer->ViewportIsMoving() is not enough
			screenFlags.Set(ScreenFlags::CenterOnActor);
		}

		SetDisabled(false);

		if (window) {
			window->Focus();
		}
	}
	//center on first selected actor
	if (pc && screenFlags.Test(ScreenFlags::CenterOnActor)) {
		MoveViewportTo(pc->Pos, true);
		screenFlags.Clear(ScreenFlags::CenterOnActor);
	}
}

void GameControl::FlagsChanged(unsigned int /*oldflags*/)
{
	if (Flags() & IgnoreEvents) {
		ClearMouseState();
		vpVector.reset();
		scrollKeysDown = scrollKeysActive = 0;
	}
}

bool GameControl::SetScreenFlags(ScreenFlags value, BitOp mode)
{
	auto bits = screenFlags.to_ulong();
	bool toggled = SetBits(bits, (unsigned long) (1 << UnderType(value)), mode);
	screenFlags = EnumBitset<ScreenFlags>(bits);
	return toggled;
}

void GameControl::SetDialogueFlags(unsigned int value, BitOp mode)
{
	SetBits(DialogueFlags, value, mode);
	SetFlags(IgnoreEvents, (DialogueFlags & DF_IN_DIALOG || screenFlags.Test(ScreenFlags::Cutscene)) ? BitOp::OR : BitOp::NAND);
}

Map* GameControl::CurrentArea() const
{
	const Game* game = core->GetGame();
	if (game) {
		return game->GetCurrentArea();
	}
	return nullptr;
}

Actor* GameControl::GetLastActor() const
{
	Actor* actor = nullptr;
	const Map* area = CurrentArea();
	if (area) {
		actor = area->GetActorByGlobalID(lastActorID);
	}
	return actor;
}

void GameControl::SetLastActor(Actor* lastActor)
{
	if (lastActorID) {
		const Map* area = CurrentArea();
		if (!area) {
			return;
		}

		Actor* current = area->GetActorByGlobalID(lastActorID);
		if (current)
			current->SetOver(false);
		lastActorID = 0;
	}

	if (lastActor) {
		lastActorID = lastActor->GetGlobalID();
		lastActor->SetOver(true);
	}
}

bool GameControl::IsOverLastActor(const Point& pos) const
{
	const Actor* lastActor = lastActorID != 0 ? GetLastActor() : nullptr;
	return lastActor && lastActor->IsOver(pos + viewport.origin);
}

Scriptable* GameControl::GetHoverObject() const
{
	Scriptable* const lastActor = lastActorID != 0 ? GetLastActor() : nullptr;
	return lastActor != nullptr ? lastActor : overMe;
}

//Set up an item use which needs targeting
//Slot is an inventory slot
//header is the used item extended header
//u is the user
//target type is a bunch of GetActor flags that alter valid targets
//cnt is the number of different targets (usually 1)
void GameControl::SetupItemUse(int slot, size_t header, int targettype, int cnt)
{
	spellName.Reset();
	spellOrItem = -1;
	spellSlot = slot;
	spellIndex = static_cast<int>(header);
	//item use also uses the casting icon, this might be changed in some custom game?
	SetTargetMode(TargetMode::Cast);
	targetTypes = targettype;
	spellCount = cnt;
}

//Set up spell casting which needs targeting
//type is the spell's type
//level is the caster level
//idx is the spell's number
//u is the caster
//target type is a bunch of GetActor flags that alter valid targets
//cnt is the number of different targets (usually 1)
void GameControl::SetupCasting(const ResRef& spellname, int type, int level, int idx, int targettype, int cnt)
{
	spellName = spellname;
	spellOrItem = type;
	spellSlot = level;
	spellIndex = idx;
	SetTargetMode(TargetMode::Cast);
	targetTypes = targettype;
	spellCount = cnt;
}

void GameControl::SetDisplayText(const String& text, unsigned int time)
{
	DisplayTextTime = time;
	DisplayText = text;
}

void GameControl::SetDisplayText(HCStrings text, unsigned int time)
{
	SetDisplayText(core->GetString(text, STRING_FLAGS::NONE), time);
}

void GameControl::ToggleAlwaysRun()
{
	AlwaysRun = !AlwaysRun;
	core->GetDictionary().Set("Always Run", AlwaysRun);
}

int GameControl::GetOverheadOffset() const
{
	const Actor* actor = GetLastActor();
	if (actor) {
		return actor->overHead.GetHeightOffset();
	}
	return 0;
}

void GameControl::SetScalePercent(unsigned int level, bool force)
{
	unsigned int oldScale = GetScalePercent();
	auto value = Clamp(level, 25u, 160u);
	zoomLevel = (value - 20) / 5;

	ScaleViewport(force ? oldScale : 100);
}

unsigned int GameControl::GetScalePercent() const
{
	return 20 + zoomLevel * 5;
}

Point GameControl::ConvertPointFromScreen(const Point& p) const
{
	if (SceneCamera() && camera.scale > 0.0f) {
		// relative to the logical viewport, through what is actually shown
		return ScreenToMap(p) - viewport.origin;
	}

	auto scale = GetScalePercent();
	if (scale == 100) {
		return View::ConvertPointFromScreen(p);
	}

	auto offset = p;
	offset.x = (offset.x * scale) / 100;
	offset.y = (offset.y * scale) / 100;

	return offset;
}

}
