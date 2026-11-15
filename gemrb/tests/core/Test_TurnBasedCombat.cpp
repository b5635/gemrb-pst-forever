// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

// Turn based combat pieces that don't need a running game: initiative ordering and the
// movement cost helpers the preview and the budget share.

#include "SearchMapBuilder.h"

#include "../../core/PathFinder.h"
#include "../../core/CharAnimations.h"
#include "../../core/TurnBasedCombat/CombatDirector.h"

#include "ie_stats.h"

#include <gtest/gtest.h>

namespace GemRB {

using test::TestSearchMap;

static Combatant MakeCombatant(ieDword id, int initiative, int dex, bool isPC)
{
	Combatant combatant;
	combatant.globalID = id;
	combatant.initiative = initiative;
	combatant.dexterity = dex;
	combatant.isPC = isPC;
	return combatant;
}

static std::vector<ieDword> Ids(const std::vector<Combatant>& combatants)
{
	std::vector<ieDword> ids;
	for (const auto& combatant : combatants) {
		ids.push_back(combatant.globalID);
	}
	return ids;
}

TEST(CombatDirectorTest, LowestInitiativeGoesFirst)
{
	std::vector<Combatant> order = {
		MakeCombatant(1, 7, 10, true),
		MakeCombatant(2, 2, 10, false),
		MakeCombatant(3, 9, 10, false),
		MakeCombatant(4, -1, 10, true)
	};
	CombatDirector::SortByInitiative(order);
	EXPECT_EQ(Ids(order), (std::vector<ieDword> { 4, 2, 1, 3 }));
}

TEST(CombatDirectorTest, TiesGoToHigherDexterityThenParty)
{
	std::vector<Combatant> order = {
		MakeCombatant(1, 5, 12, false),
		MakeCombatant(2, 5, 17, false),
		MakeCombatant(3, 5, 12, true)
	};
	CombatDirector::SortByInitiative(order);
	EXPECT_EQ(Ids(order), (std::vector<ieDword> { 2, 3, 1 }));
}

TEST(CombatDirectorTest, JoinerIsInsertedAtItsInitiative)
{
	std::vector<Combatant> order = {
		MakeCombatant(1, 2, 10, true),
		MakeCombatant(2, 6, 10, false)
	};
	size_t idx = CombatDirector::InsertByInitiative(order, MakeCombatant(3, 4, 10, false));
	EXPECT_EQ(idx, 1u);
	EXPECT_EQ(Ids(order), (std::vector<ieDword> { 1, 3, 2 }));

	idx = CombatDirector::InsertByInitiative(order, MakeCombatant(4, 10, 10, false));
	EXPECT_EQ(idx, 3u);
}

TEST(CombatDirectorTest, CombatVisionIsOnForLivingEnemies)
{
	EXPECT_TRUE(CombatDirector::ShouldGrantCombatVision(true, true));
	EXPECT_FALSE(CombatDirector::ShouldGrantCombatVision(false, true));
	EXPECT_FALSE(CombatDirector::ShouldGrantCombatVision(true, false));
	EXPECT_FALSE(CombatDirector::ShouldGrantCombatVision(false, false));
}

TEST(CombatDirectorTest, OnlyActualHostilesAreEnemies)
{
	EXPECT_TRUE(CombatDirector::IsEnemyEA(EA_ENEMY));
	EXPECT_TRUE(CombatDirector::IsEnemyEA(EA_EVILCUTOFF));
	EXPECT_FALSE(CombatDirector::IsEnemyEA(EA_NEUTRAL));
	EXPECT_FALSE(CombatDirector::IsEnemyEA(EA_PC));
	EXPECT_FALSE(CombatDirector::IsEnemyEA(EA_ALLY));

	EXPECT_TRUE(CombatDirector::IsNeutralEA(EA_NEUTRAL));
	EXPECT_TRUE(CombatDirector::IsNeutralEA(EA_NOTGOOD));
	EXPECT_FALSE(CombatDirector::IsNeutralEA(EA_ENEMY));
	EXPECT_FALSE(CombatDirector::IsNeutralEA(EA_PC));
	EXPECT_FALSE(CombatDirector::IsNeutralEA(EA_GOODCUTOFF));

	EXPECT_TRUE(CombatDirector::AreEnemies(EA_PC, EA_ENEMY));
	EXPECT_TRUE(CombatDirector::AreEnemies(EA_ENEMY, EA_ALLY));
	EXPECT_FALSE(CombatDirector::AreEnemies(EA_PC, EA_NEUTRAL));
	EXPECT_FALSE(CombatDirector::AreEnemies(EA_ENEMY, EA_NEUTRAL));
	EXPECT_FALSE(CombatDirector::AreEnemies(EA_NEUTRAL, EA_NEUTRAL));
	EXPECT_FALSE(CombatDirector::AreEnemies(EA_PC, EA_ALLY));
	EXPECT_FALSE(CombatDirector::AreEnemies(EA_ENEMY, EA_EVILBUTGREEN));
}

TEST(CombatDirectorTest, ResetBudgetRestoresTheTurn)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	combatant.mainActionUsed = true;
	combatant.ran = true;
	combatant.withdrawn = true;
	combatant.freeWeaponSwapUsed = true;
	combatant.attacking = true;
	combatant.blockStacks = 2;
	combatant.takedown = TakedownKind::Trip;
	combatant.movePx = 3;
	CombatDirector::ResetBudget(combatant, 320);
	EXPECT_FALSE(combatant.mainActionUsed);
	EXPECT_FALSE(combatant.ran);
	EXPECT_FALSE(combatant.withdrawn);
	EXPECT_FALSE(combatant.freeWeaponSwapUsed);
	EXPECT_FALSE(combatant.attacking);
	EXPECT_EQ(combatant.blockStacks, 0);
	EXPECT_EQ(combatant.takedown, TakedownKind::None);
	EXPECT_EQ(combatant.movePx, 320);
	EXPECT_EQ(combatant.maxMovePx, 320);
}

TEST(CombatDirectorTest, RunAddsMaxMovementWithoutRaisingTheCap)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	CombatDirector::ResetBudget(combatant, 31);
	combatant.movePx = 15;
	CombatDirector::ApplyRun(combatant);
	EXPECT_TRUE(combatant.ran);
	EXPECT_TRUE(combatant.mainActionUsed);
	EXPECT_EQ(combatant.movePx, 46);
	EXPECT_EQ(combatant.maxMovePx, 31);
}

TEST(CombatDirectorTest, MissingRunAnimStillUsesTypicalRunSpeed)
{
	EXPECT_EQ(CombatDirector::RunSpeedFromWalk(0), 0);
	EXPECT_EQ(CombatDirector::RunSpeedFromWalk(-10), 0);
	// inverted scales: walkscale 5 stores 200, typical runscale 15 stores 66
	EXPECT_EQ(CombatDirector::RunSpeedFromWalk(200), 66);
	EXPECT_EQ(CombatDirector::RunSpeedFromWalk(1), 1);
	// zombie walkscale 2.4 stores 416; 3x is still a run, not a walk
	EXPECT_LT(CombatDirector::RunSpeedFromWalk(416), 416);
}

TEST(CombatDirectorTest, WithdrawHalvesRemainingMovement)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	CombatDirector::ResetBudget(combatant, 31);
	CombatDirector::ApplyWithdraw(combatant);
	EXPECT_TRUE(combatant.withdrawn);
	EXPECT_TRUE(combatant.mainActionUsed);
	EXPECT_EQ(combatant.movePx, 15);
	EXPECT_EQ(combatant.maxMovePx, 31);
}

TEST(CombatDirectorTest, BlockConvertsAllAttacksAndSpendsTheAction)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	combatant.remainingAttacks = 3;
	combatant.takedown = TakedownKind::Trip;
	combatant.toHitMod = -2;
	EXPECT_TRUE(CombatDirector::ApplyBlock(combatant));
	EXPECT_EQ(combatant.remainingAttacks, 0);
	EXPECT_EQ(combatant.blockStacks, 3);
	EXPECT_TRUE(combatant.mainActionUsed);
	EXPECT_EQ(combatant.takedown, TakedownKind::None);
	EXPECT_EQ(combatant.toHitMod, 0);
	EXPECT_FALSE(CombatDirector::ApplyBlock(combatant));
	EXPECT_EQ(combatant.blockStacks, 3);
}

TEST(CombatDirectorTest, BlockWithOneAttackStillSpendsTheAction)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	combatant.remainingAttacks = 1;
	EXPECT_TRUE(CombatDirector::ApplyBlock(combatant));
	EXPECT_EQ(combatant.remainingAttacks, 0);
	EXPECT_EQ(combatant.blockStacks, 1);
	EXPECT_TRUE(combatant.mainActionUsed);
}

TEST(CombatDirectorTest, BlockWithNoAttacksDoesNotSpendTheAction)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	combatant.remainingAttacks = 0;
	EXPECT_FALSE(CombatDirector::ApplyBlock(combatant));
	EXPECT_EQ(combatant.blockStacks, 0);
	EXPECT_FALSE(combatant.mainActionUsed);
}

TEST(CombatDirectorTest, TripAndKnockdownShareTheTakedownPenalty)
{
	EXPECT_EQ(CombatDirector::TakedownPenalty(TakedownKind::Trip), -2);
	EXPECT_EQ(CombatDirector::TakedownPenalty(TakedownKind::Knockdown), 0);
	EXPECT_EQ(CombatDirector::TakedownPenalty(TakedownKind::None), 0);
}

TEST(CombatDirectorTest, TakedownResultTextNamesTheManeuverAndTheOutcome)
{
	EXPECT_EQ(CombatDirector::TakedownResultText(TakedownKind::Trip, true), u"Trip: Success");
	EXPECT_EQ(CombatDirector::TakedownResultText(TakedownKind::Trip, false), u"Trip: Failure");
	EXPECT_EQ(CombatDirector::TakedownResultText(TakedownKind::Knockdown, true), u"Knockdown: Success");
	EXPECT_EQ(CombatDirector::TakedownResultText(TakedownKind::Knockdown, false), u"Knockdown: Failure");
}

TEST(CombatDirectorTest, ProneUsesGetUpWhenPresentOtherwiseDeath)
{
	EXPECT_EQ(CombatDirector::ProneAnimStance(true), IE_ANI_GET_UP);
	EXPECT_TRUE(CombatDirector::ProneFallReversed(true));
	EXPECT_FALSE(CombatDirector::ProneRiseReversed(true));

	EXPECT_EQ(CombatDirector::ProneAnimStance(false), IE_ANI_DIE);
	EXPECT_FALSE(CombatDirector::ProneFallReversed(false));
	EXPECT_TRUE(CombatDirector::ProneRiseReversed(false));
}

TEST(TurnMovementTest, CostIsTheSameAcrossAndDown)
{
	// a foot is 16px across, but only 12px down the squashed navmap
	EXPECT_EQ(PathFinder::MovementCost(Point(0, 0), Point(160, 0)), 160);
	EXPECT_EQ(PathFinder::MovementCost(Point(0, 0), Point(0, 120)), 160);
}

TEST(TurnMovementTest, PathCostAndTruncation)
{
	Path path;
	path.nodes.push_back(PathNode { Point(100, 0), S });
	path.nodes.push_back(PathNode { Point(100, 75), S });
	const Point start(0, 0);

	EXPECT_EQ(PathFinder::PathCost(start, path), 200);
	EXPECT_EQ(PathFinder::PointAlongPath(start, path, 50), Point(50, 0));
	// half way down the second leg: 100 cost units are 75px down
	EXPECT_EQ(PathFinder::PointAlongPath(start, path, 150), Point(100, 37));
	// affording it all ends at the destination
	EXPECT_EQ(PathFinder::PointAlongPath(start, path, 999), Point(100, 75));
}

TEST(CombatDirectorTest, ClipPathStopsWhereTheBudgetEnds)
{
	Path path;
	path.nodes.push_back(PathNode { Point(100, 0), S });
	path.nodes.push_back(PathNode { Point(100, 75), S });
	const Point start(0, 0);

	// the whole path is affordable
	Path all = CombatDirector::ClipPath(start, path, 500);
	ASSERT_EQ(all.Size(), 2u);
	EXPECT_EQ(all.GetLastStep().point, Point(100, 75));

	// the budget runs out half way down the second leg
	Path half = CombatDirector::ClipPath(start, path, 150);
	ASSERT_EQ(half.Size(), 2u);
	EXPECT_EQ(half.GetLastStep().point, Point(100, 37));
	EXPECT_LE(PathFinder::PathCost(start, half), 150);

	// exactly the first leg
	Path first = CombatDirector::ClipPath(start, path, 100);
	ASSERT_EQ(first.Size(), 1u);
	EXPECT_EQ(first.GetLastStep().point, Point(100, 0));

	EXPECT_TRUE(CombatDirector::ClipPath(start, path, 0).Empty());
}

TEST(TurnMovementTest, ReachStopsAtWalls)
{
	const TestSearchMap map {
		"..........",
		"..........",
		"#####.....",
		"..........",
		".........."
	};
	const Point source = SearchmapPoint(1, 0).ToNavmapCenter();
	auto boundary = PathFinder::ReachableBoundary(map.Props(), source, 0, 3 * SEARCHMAP_TILE_WIDTH);
	ASSERT_FALSE(boundary.empty());
	for (const auto& cell : boundary) {
		// nothing behind the wall is in reach with three tiles of movement
		EXPECT_LT(cell.y, 2);
	}
}

TEST(TurnMovementTest, NoMovementNoReach)
{
	const TestSearchMap map {
		"...",
		"..."
	};
	EXPECT_TRUE(PathFinder::ReachableBoundary(map.Props(), Point(8, 6), 0, 0).empty());
}


// The preview draws its stop with PointAlongPath and the walk ends where ClipPath does
TEST(TurnMovementTest, PreviewStopIsTheWalksStop)
{
	Path path;
	path.nodes.push_back(PathNode { Point(37, 11), S });
	path.nodes.push_back(PathNode { Point(90, 70), S });
	path.nodes.push_back(PathNode { Point(20, 133), S });
	const Point start(3, 5);
	for (int budget = 1; budget < PathFinder::PathCost(start, path) + 20; ++budget) {
		const Path clipped = CombatDirector::ClipPath(start, path, budget);
		const Point walkEnd = clipped ? clipped.GetLastStep().point : start;
		EXPECT_EQ(PathFinder::PointAlongPath(start, path, budget), walkEnd) << "budget " << budget;
	}
}

// a goal behind a wall still gets a path, to the nearest spot, and says so
TEST(TurnMovementTest, UnreachableGoalGivesAPartialPath)
{
	const TestSearchMap map {
		"..........",
		"..........",
		"##########",
		".........."
	};
	const test::TestTraversability traversability { map };
	const Point from = TestSearchMap::Nav(1, 0);
	const Path blocked = test::CallFindPath(map, traversability, from, TestSearchMap::Nav(5, 3), nullptr, 1, PF_SIGHT | PF_ACTORS_ARE_BLOCKING | PF_EXACT);
	ASSERT_FALSE(blocked.Empty());
	EXPECT_TRUE(blocked.partial);
	const Path open = test::CallFindPath(map, traversability, from, TestSearchMap::Nav(8, 1), nullptr, 1, PF_SIGHT | PF_ACTORS_ARE_BLOCKING | PF_EXACT);
	ASSERT_FALSE(open.Empty());
	EXPECT_FALSE(open.partial);
}

// the shaded reach doesn't promise a way through creatures that block the walk
TEST(TurnMovementTest, ReachStopsAtCreatures)
{
	const TestSearchMap map {
		"###############",
		"#.......a.....#",
		"###############"
	};
	const test::TestTraversability traversability { map, false };
	const Point source = TestSearchMap::Nav(1, 1);
	const ActorPathContext context { 1, ieVariable(), true };
	const int budget = 12 * SEARCHMAP_TILE_WIDTH;
	const auto withCreatures = PathFinder::ReachableArea(&traversability.Data(), map.Props(), source, context, budget);
	const auto wallsOnly = PathFinder::ReachableArea(map.Props(), source, 1, budget);
	EXPECT_TRUE(wallsOnly.Contains(11, 1));
	EXPECT_FALSE(withCreatures.Contains(11, 1)) << "the corridor is shut by the creature";
	EXPECT_TRUE(withCreatures.Contains(5, 1));
}

// every cell the shade calls reachable the walk reaches within budget, and the other way round
TEST(TurnMovementTest, ReachAgreesWithThePath)
{
	const TestSearchMap map {
		"....................",
		"....................",
		"......####..........",
		"......#.............",
		"......#....a........",
		"..####..............",
		"....................",
		"....................",
		"...........#####....",
		"...................."
	};
	const test::TestTraversability traversability { map, false };
	const Point source = TestSearchMap::Nav(2, 3);
	const ActorPathContext context { 1, ieVariable(), true };
	const int budget = 10 * SEARCHMAP_TILE_WIDTH;
	const auto reach = PathFinder::ReachableArea(&traversability.Data(), map.Props(), source, context, budget);
	// lattice and path differ by a fraction of a tile at most
	constexpr int slack = SEARCHMAP_TILE_WIDTH / 2;
	int checked = 0;
	for (int y = 0; y < 10; ++y) {
		for (int x = 0; x < 20; ++x) {
			if (SearchmapPoint(x, y) == SearchmapPoint(source)) continue;
			const Point to = TestSearchMap::Nav(x, y);
			const Path path = test::CallFindPath(map, traversability, source, to, nullptr, 1, PF_SIGHT | PF_ACTORS_ARE_BLOCKING | PF_EXACT);
			const bool walks = path && !path.partial && SearchmapPoint(path.GetLastStep().point) == SearchmapPoint(x, y);
			const int cost = walks ? PathFinder::PathCost(source, path) : -1;
			if (reach.Contains(x, y)) {
				EXPECT_TRUE(walks) << "shaded but unwalkable: " << x << "," << y;
				if (walks) EXPECT_LE(cost, budget + slack) << "shaded but too far: " << x << "," << y;
				++checked;
			} else if (walks) {
				EXPECT_GT(cost, budget - slack) << "walkable within budget but not shaded: " << x << "," << y;
			}
		}
	}
	EXPECT_GT(checked, 20);
}

}
