// SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
//
// SPDX-License-Identifier: GPL-2.0-or-later

// Turn based combat pieces that don't need a running game: initiative ordering and the
// movement cost helpers the preview and the budget share.

#include "SearchMapBuilder.h"

#include "../../core/PathFinder.h"
#include "../../core/TurnBasedCombat/CombatDirector.h"

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

TEST(CombatDirectorTest, ResetBudgetRestoresTheTurn)
{
	Combatant combatant = MakeCombatant(1, 1, 10, true);
	combatant.mainActionUsed = true;
	combatant.ran = true;
	combatant.freeWeaponSwapUsed = true;
	combatant.attacking = true;
	combatant.movePx = 3;
	CombatDirector::ResetBudget(combatant, 320);
	EXPECT_FALSE(combatant.mainActionUsed);
	EXPECT_FALSE(combatant.ran);
	EXPECT_FALSE(combatant.freeWeaponSwapUsed);
	EXPECT_FALSE(combatant.attacking);
	EXPECT_EQ(combatant.movePx, 320);
	EXPECT_EQ(combatant.maxMovePx, 320);
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
	EXPECT_EQ(PathFinder::PointAlongPath(start, path, 150), Point(100, 38));
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

}
