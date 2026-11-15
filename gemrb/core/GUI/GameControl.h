// SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

/**
 * @file GameControl.h
 * Declares GameControl widget which is responsible for displaying areas,
 * interacting with PCs, NPCs and the rest of the game world.
 * @author The GemRB Project
 */

#ifndef GAMECONTROL_H
#define GAMECONTROL_H

#include "exports.h"
#include "strrefs.h"

#include "EnumIndex.h"
#include "PathFinder.h"
#include "Sprite2D.h"
#include "View.h"

#include "GUI/EventMgr.h"
#include "GUI/GameControlDefs.h"

#include <vector>

namespace GemRB {

class Container;
class DialogHandler;
class Door;
class InfoPoint;
class Map;
class Movable;

/**
 * @class GameControl
 * Widget displaying areas, where most of the game 'happens'.
 * It allows for interacting with PCs, NPCs and the rest of the world.
 * It's also a very core part of GemRB, as some processes are driven from it.
 * It's always assigned Control index 0.
 */

class GEM_EXPORT GameControl : public View {
private:
	ieDword lastActorID = 0;
	ieDword trackerID = 0;
	ieDword distance = 0; //tracking distance
	std::vector<Actor*> highlighted;

	bool isSelectionRect = false;
	bool isFormationRotation = false;

	// mouse coordinates represented in game coordinates
	Point gameClickPoint;
	Point screenMousePos;
	Region viewport;
	bool updateVPTimer = true;

	// What is shown, with video drivers that support scene transforms: eases toward
	// viewport/zoom (the logical camera that the game and scripts use) with sub-pixel
	// position and continuous zoom. scale = map units per screen pixel, 0 = unused.
	struct Camera {
		float x = 0.0f;
		float y = 0.0f;
		float scale = 0.0f;
		bool pivot = false; // zooming around a fixed screen point (the cursor)
		Point pivotScreen;
		float pivotMapX = 0.0f;
		float pivotMapY = 0.0f;
		Point pivotTarget; // viewport origin the pivot zoom ends at
		const Map* area = nullptr;
		tick_t lastTick = 0;
	} camera;
	bool SceneCamera() const;
	void UpdateCamera();
	Point ScreenToMap(const Point& screenPos) const;
	float_t formationBaseAngle = 0.0;

	// currently selected targeting type, such as talk, attack, cast, ...
	// private to enforce proper cursor changes
	TargetMode targetMode = TargetMode::None;
	int lastCursor = 0;
	Point vpVector;
	int numScrollCursor = 0;
	EnumBitset<ScreenFlags> screenFlags { ScreenFlags::CenterOnActor };
	// Scroll direction bits: LEFT=1, RIGHT=2, UP=4, DOWN=8
	// Pairs: LEFT<->RIGHT (bits 0,1) and UP<->DOWN (bits 2,3)
	static constexpr unsigned int SCROLL_LEFT  = 1 << 0;
	static constexpr unsigned int SCROLL_RIGHT = 1 << 1;
	static constexpr unsigned int SCROLL_UP    = 1 << 2;
	static constexpr unsigned int SCROLL_DOWN  = 1 << 3;
	unsigned int scrollKeysActive = 0;
	unsigned int scrollKeysDown = 0;
	unsigned int DialogueFlags = DF_FREEZE_SCRIPTS;
	String DisplayText;
	unsigned int DisplayTextTime = 0;
	bool AlwaysRun = false;
	Actor* user = nullptr; //the user of item or spell
	unsigned int zoomLevel = 16; // 100%

	Scriptable* overMe = nullptr;

	EventMgr::TapMonitorId eventMonitors[2];

	// turn based movement preview, recomputed only when its inputs change
	struct TurnPreview {
		ieDword actorID = 0;
		Point actorPos;
		int budget = -1;
		PathFinder::ReachArea reach;
		// the reach's edge as smoothed closed curves (map coordinates)
		std::vector<std::vector<Point>> outline;
		// how dimmed each cell around the reach is: 0 inside, up to SHADE_STEPS far outside
		PathFinder::ReachArea shade;

		SearchmapPoint targetCell { -1, -1 };
		ieDword targetActorID = 0;
		Path path;
		int pathCost = 0;
		bool attackPreview = false;
		bool attackReachable = false;
		// what the attack would need and do, for the hover text
		int hitChance = -1;
		int hitNeeded = 0;
		int targetAC = 0;
		int damageMin = 0;
		int damageMax = 0;
		int distanceFt = 0;
		// where the THAC0 comes from, for the hover panel (see Actor::HitPrediction)
		int baseThac0 = 0;
		int thac0 = 0;
		int abilityBonus = 0;
		int weaponBonus = 0;
		int proficiencyBonus = 0;
		int armorBonus = 0;
		int otherBonus = 0;
		int modifier = 0;
		int totalNeeded = 0;
		bool ranged = false;
		bool autoHit = false;
		int moveNeededFt = 0; // the walk before the attack, 0 if in reach

		bool pending = false; // a destination waiting for confirmation
		Point pendingDest;
	} turnPreview;

public:
	static uint32_t DebugFlags;
	static uint8_t DebugPropVal;

	std::unique_ptr<DialogHandler> dialoghandler;
	//the name of the spell to cast
	ResRef spellName;
	//using spell or item
	int spellOrItem = 0; // -1 = item, otherwise the spell type
	int spellSlot = 0; // or inventorySlot/itemHeader
	int spellIndex = 0;
	int spellCount = 0; //multiple targeting
	// allow targeting allies, enemies and/or neutrals (bitmask)
	int targetTypes = 0;

private:
	using FormationPoints = std::vector<Point>;
	Map* CurrentArea() const;

	Region SelectionRect() const;
	/** Draws an arrow on the edge of the screen based on the point (points at offscreen actors) */
	void DrawArrowMarker(const Point& p, const Color& color) const;
	void DrawFormation(const std::vector<Actor*>& actors, const Point& formationPoint, float_t angle) const;

	Point GetFormationPoint(const Point& origin, size_t pos, float_t angle, const FormationPoints& exclude = FormationPoints()) const;
	FormationPoints GetFormationPoints(const Point& origin, const std::vector<Actor*>& actors, float_t angle) const;

	void ApplyKeyScrolling();
	void Scroll(const Point& amt);

	void HandleContainer(Container* container, Actor* actor);
	void HandleDoor(Door* door, Actor* actor);

	void UpdateCursor();
	bool IsDisabledCursor() const override;

	void PerformSelectedAction(const Point& p);
	void CommandSelectedMovement(const Point& p, bool formation = true, bool append = false, bool tryToRun = false) const;

	bool OnGlobalMouseMove(const Event&);
	bool OnCheatKeyRelease(const KeyboardEvent& key, unsigned short mod);

	/** Draws the Control on the Output Display */
	void DrawSelf(const Region& drawFrame, const Region& clip) override;
	void WillDraw(const Region& /*drawFrame*/, const Region& /*clip*/) override;
	void OutlineInfoPoints() const;
	void OutlineDoors() const;
	void OutlineContainers() const;
	void DrawTrackingArrows();
	void ScaleViewport(unsigned int);

	bool CanLockFocus() const override { return true; };
	void FlagsChanged(unsigned int /*oldflags*/) override;

	void DebugPaint(const Point& p, bool sample) const noexcept;

	/** The party member whose combat turn it is, if the player is to act now. */
	Actor* GetTurnBasedActor() const;
	/** In turn based combat only the active combatant takes orders. */
	bool TurnBasedForbids(const Actor* source) const;
	void UpdateTurnPreview();
	void DrawTurnPreview() const;
	/** Screen-space combat overlays: dice panel, hit panel, hover HP bar, turn banner. */
	void DrawCombatOverlays(const Region& screen);
	void DrawHitPanel(const Region& screen) const;
	void DrawHoverHP(const Region& screen) const;
	void DrawTurnBanner(const Region& screen);
	/** a map point in the control's screen coordinates */
	Point MapToScreen(const Point& p, const Region& screen) const;
	ieDword bannerActorID = 0;
	tick_t bannerStart = 0;
	bool lastActiveWasParty = false;
	mutable int hoverBarBottom = 0; // where the hover HP bar ended this frame, 0 if none
	/** Left click on the ground during a party member's turn: place or commit a move. */
	void HandleTurnBasedMove(const Point& p, bool commit);

	enum class ActorDump { Anims,
			       Stats };
	void DumpActorInfo(ActorDump, const Map*) const noexcept;

public:
	explicit GameControl(const Region& frame);
	~GameControl(void) override;

	// GameControl always needs to redraw unless we arent in a game (disabled)
	bool IsAnimated() const override { return !IsDisabled(); }
	void DrawTargetReticles() const;
	void DrawTargetReticle(uint16_t size, const Color& color, const Point& p, int offset = 0) const;
	/** Draws the target reticle for Actor movement. */
	void DrawTargetReticle(const Movable* target, const Point& point, int offset = 0) const;
	/** Sets multiple quicksaves flag*/
	//static void MultipleQuickSaves(int arg);
	void SetTracker(const Actor* actor, ieDword dist);

	String TooltipText() const override;

	void SetTargetMode(TargetMode mode);
	TargetMode GetTargetMode() const { return targetMode; }
	bool SetScreenFlags(ScreenFlags value, BitOp mode);
	void SetDialogueFlags(unsigned int value, BitOp mode);
	EnumBitset<ScreenFlags> GetScreenFlags() const { return screenFlags; }
	int GetDialogueFlags() const { return DialogueFlags; }
	bool InDialog() const { return DialogueFlags & DF_IN_DIALOG; }
	void SetDisplayText(const String& text, unsigned int time);
	void SetDisplayText(HCStrings text, unsigned int time);
	void ClearMouseState();
	Point GameMousePos() const;

	Point ConvertPointFromScreen(const Point&) const override;
	void MoveViewportUnlockedTo(Point, bool center);
	bool MoveViewportTo(Point, bool center, int speed = 0);
	Region Viewport() const;
	/** Map pixels to shift combat centering: +X right, +Y toward the bottom of the screen. */
	Point CombatCameraOffset() const;
	/** Map point to center on so the actor sits at the combat camera offset. */
	Point CombatFocus(const Point& actorPos) const;

	/** Selects one or all PC */
	void SelectActor(int whom, int type = -1);
	void SetCutSceneMode(bool active);
	void TryToAttack(Actor* source, const Actor* target) const;
	void TryToCast(Actor* source, const Point& p);
	void TryToCast(Actor* source, const Actor* target);
	void TryToDefend(Actor* source, const Actor* target) const;
	void TryToTalk(Actor* source, const Actor* target) const;
	void TryToPick(Actor* source, const Scriptable* tgt) const;
	void TryToDisarm(Actor* source, const InfoPoint* tgt) const;
	void PerformActionOn(Actor* actor);
	void ResetTargetMode();
	void UpdateTargetMode();

	Holder<Sprite2D> Cursor() const override;

	bool HandleActiveRegion(InfoPoint* trap, Actor* actor, const Point& p);

	void MakeSelection(bool extend = false);
	void InitFormation(const Point&, bool rotating);
	Point GetFormationOffset(size_t formation, uint8_t pos) const;
	/** calls MoveToPoint or RunToPoint */
	void CreateMovement(Actor* actor, const Point& p, bool append = true, bool tryToRun = false) const;
	bool ShouldTriggerWorldMap(const Actor* pc) const;
	/** checks if the actor should be running instead of walking */
	bool CanRun(const Actor* actor) const;
	bool ShouldRun(const Actor* actor) const;
	/** Displays a string over an object */
	void DisplayString(Scriptable* target) const;
	/** Displays a string on screen */
	void DisplayString(const Point& p, const char* Text);
	Actor* GetLastActor() const;
	void SetLastActor(Actor* lastActor);
	bool IsOverLastActor(const Point& pos) const;
	/** Gets the Scriptable currently under the cursor */
	Scriptable* GetHoverObject() const;
	/** changes map to the current PC */
	void ChangeMap(const Actor* pc, bool forced);
	/** Sets up targeting with spells or items */
	void SetupItemUse(int slot, size_t header, int targettype, int cnt);
	/** Page is the spell type + spell level info */
	void SetupCasting(const ResRef& spellname, int type, int level, int slot, int targettype, int cnt);
	void ToggleAlwaysRun();
	int GetOverheadOffset() const;
	void TryDefaultTalk() const;
	void SetScalePercent(unsigned int zoomLevel, bool force = false);
	unsigned int GetScalePercent() const;
	/** Drops a turn based move waiting for confirmation */
	void CancelTurnBasedMove() { turnPreview.pending = false; }
	/** Confirms the turn based move waiting for confirmation, if any */
	void ConfirmTurnBasedMove();
	/** A click-and-confirm move to p, as the player makes it; reports what the preview promised */
	struct TurnMovePromise {
		bool hasPath = false;
		bool partial = false;
		Point stop;
		int cost = 0;
	};
	TurnMovePromise TurnBasedMoveTo(const Point& p);

protected:
	//Events
	/** Key Press Event */
	bool OnKeyPress(const KeyboardEvent& Key, unsigned short Mod) override;
	/** Key Release Event */
	bool OnKeyRelease(const KeyboardEvent& Key, unsigned short Mod) override;
	/** Mouse Over Event */
	bool OnMouseOver(const MouseEvent&) override;
	bool OnMouseDrag(const MouseEvent& /*me*/) override;

	bool OnTouchDown(const TouchEvent& /*te*/, unsigned short /*Mod*/) override;
	bool OnTouchUp(const TouchEvent& /*te*/, unsigned short /*Mod*/) override;
	bool OnTouchGesture(const GestureEvent& gesture) override;

	/** Currently only deals with the GEM_TAB exception */
	bool DispatchEvent(const Event& event) const;

	/** Mouse Button Down */
	bool OnMouseDown(const MouseEvent& /*me*/, unsigned short Mod) override;
	/** Mouse Button Up */
	bool OnMouseUp(const MouseEvent& /*me*/, unsigned short Mod) override;
	bool OnMouseWheelScroll(const Point& delta) override;

	bool OnControllerButtonDown(const ControllerEvent& ce) override;

	// returns the default cursor fitting the targeting mode
	static Holder<Sprite2D> GetTargetActionCursor(TargetMode mode);
};

}

#endif
