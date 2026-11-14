# SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# TurnOrder.py - turn based combat gui: the initiative bar at the top and the
# hotbar above the portraits (that one always). Both only exist while a fight is going on.
# The engine calls UpdateTurnOrder whenever the order or the budget change.

import GemRB
import GUICommon
from GUIDefines import *
from ie_stats import *

ORDER_WINDOW_ID = 950
BAR_WINDOW_ID = 951

CARD_W = 60
CARD_H = 76
ACTIVE_W = 80 # whoever acts gets a bigger card
ACTIVE_H = 101
CARD_GAP = 5
MAX_CARDS = 20
FADE_STEPS = 16
FALL_DISTANCE = 40 # a dead card falls this far as it fades
ORDER_H = ACTIVE_H + 30
SLIDE_SPEED = 6 # pixels per animation step
ANIM_INTERVAL = 40

ColorActive = {'r' : 255, 'g' : 230, 'b' : 60, 'a' : 255}
ColorDone = {'r' : 0, 'g' : 0, 'b' : 0, 'a' : 150}
ColorDamage = {'r' : 170, 'g' : 8, 'b' : 6, 'a' : 165}
ColorTitle = {'r' : 236, 'g' : 222, 'b' : 190, 'a' : 255}
ColorInfo = {'r' : 214, 'g' : 196, 'b' : 158, 'a' : 255}
ColorPC = {'r' : 20, 'g' : 30, 'b' : 60, 'a' : 220}
ColorFoe = {'r' : 60, 'g' : 15, 'b' : 15, 'a' : 220}
ColorNeutral = {'r' : 40, 'g' : 40, 'b' : 40, 'a' : 220}
ColorBarBack = {'r' : 0, 'g' : 0, 'b' : 0, 'a' : 170}
ColorButton = {'r' : 45, 'g' : 35, 'b' : 25, 'a' : 230}
ColorSelected = {'r' : 255, 'g' : 230, 'b' : 60, 'a' : 255}
ColorUnavailable = {'r' : 0, 'g' : 0, 'b' : 0, 'a' : 160}

# card state per combatant: {'ID', 'x', 'fade'}, in display order
Cards = []
CardIDs = [] # combatant per card button, as last drawn
Animating = False
SelectedMode = None

###################################################
# initiative bar

def GetOrderWindow ():
	width = GemRB.GetSystemVariable (SV_WIDTH)
	frame = {'x' : 0, 'y' : 0, 'w' : width, 'h' : ORDER_H}
	Window = GemRB.CreateWindow (ORDER_WINDOW_ID, GUICommon.GetWindowPack (), frame, WINDOW_TOP|WINDOW_HCENTER)
	if Window.GetControl (0):
		return Window

	Window.AddAlias ("TURNORDER")
	Window.SetFlags (WF_DESTROY_ON_CLOSE, OP_NAND)
	# a see-through window: its buffer is cleared before each redraw, so moving cards leave no trails
	Window.SetFlags (WF_ALPHA_CHANNEL | WF_BORDERLESS | IE_GUI_VIEW_IGNORE_EVENTS, OP_OR) # never the key focus
	for i in range (MAX_CARDS):
		Button = Window.CreateButton (i, 0, 0, CARD_W, CARD_H)
		Button.SetFlags (IE_GUI_BUTTON_PICTURE | IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_CENTER_PICTURES, OP_OR)
		Button.SetFont ("NORMAL")
		Button.OnPress (CardPressed)
		Button.SetVisible (False)
	Label = Window.CreateLabel (MAX_CARDS, 0, ACTIVE_H + 6, width, 20, "NORMAL", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_CENTER)
	Label.SetColor (ColorTitle, TA_COLOR_NORMAL)
	return Window

def TopWindowOpen ():
	"""Inventory, journal ... are open: they keep the focus (they only close while focused)."""
	Window = GemRB.GetView ("WIN_TOP")
	return bool (Window and Window.IsVisible ())

def CardPressed (btn):
	"""Clicking a party member's card hands the turn to it, if it is next to the active one in the order."""
	i = btn.ControlID & 0xffff
	if i >= len (CardIDs):
		return
	order = GemRB.GetTurnOrder ()
	if order is None:
		return
	for c in order['Combatants']:
		if c['ID'] == CardIDs[i] and c.get ('PartyID', 0) > 0:
			GemRB.GameSelectPC (c['PartyID'], True, SELECT_REPLACE | SELECT_CLICK)
			return

def CardSize (card):
	w = int (card['w'])
	return w, int (w * CARD_H / CARD_W)

def MergeCards (combatants, activeID):
	"""Keeps the cards in initiative order, with the dying ones fading out and falling in place."""
	global Cards

	known = dict ((card['ID'], card) for card in Cards)
	merged = []
	for c in combatants:
		card = known.get (c['ID'])
		if card is None:
			card = {'ID' : c['ID'], 'x' : None, 'fade' : None, 'w' : float (CARD_W), 'fall' : 0}
		if c['Dead'] and card['fade'] is None:
			card['fade'] = FADE_STEPS
		card['active'] = c['ID'] == activeID and not c['Dead']
		merged.append (card)

	# the engine drops the dead from the order at the end of the round, but let them finish falling
	ids = [c['ID'] for c in combatants]
	for i, card in enumerate (Cards):
		if card['ID'] not in ids and card['fade'] is not None and card['fade'] > 0:
			merged.insert (min (i, len (merged)), card)
	Cards = merged[:MAX_CARDS]

def Shown ():
	return [card for card in Cards if card['fade'] is None or card['fade'] > 0]

def LayoutCards ():
	"""Sets where each card wants to be and how big; the active one is larger, the gone leave a gap that closes."""
	shown = Shown ()
	width = GemRB.GetSystemVariable (SV_WIDTH)
	for card in shown:
		card['targetW'] = ACTIVE_W if card.get ('active') else CARD_W
	total = sum (card['targetW'] for card in shown) + max (0, len (shown) - 1) * CARD_GAP
	x = (width - total) // 2
	for card in shown:
		card['target'] = x
		if card['x'] is None:
			card['x'] = x
		x += card['targetW'] + CARD_GAP

def DrawCards (order):
	Window = GemRB.GetView ("TURNORDER")
	if not Window:
		return

	global CardIDs
	info = dict ((c['ID'], c) for c in order['Combatants'])
	shown = Shown ()
	CardIDs = [card['ID'] for card in shown]
	for i in range (MAX_CARDS):
		Button = Window.GetControl (i)
		if i >= len (shown):
			Button.SetVisible (False)
			continue

		card = shown[i]
		c = info.get (card['ID'])
		w, h = CardSize (card)
		Button.SetVisible (True)
		Button.SetFrame ({'x' : int (card['x']), 'y' : 2 + int (card['fall']), 'w' : w, 'h' : h})

		if c is not None:
			SetCardPicture (Button, c)
			if c['IsPC']:
				Button.SetBackground (ColorPC)
			elif c['Hostile']:
				Button.SetBackground (ColorFoe)
			else:
				Button.SetBackground (ColorNeutral)
			tip = ("{}  Lv. {}\nInitiative {} (d10: {})\nHP {}/{}".format (c['Name'], c.get ('Level', '?'), c['Initiative'], c['Roll'], c['HP'], c['MaxHP']))
			if c.get ('Switchable'):
				tip += "\nClick to act with this character now"
			Button.SetTooltip (tip)

			# lost health fills the portrait red from the bottom up
			if c['MaxHP'] > 0:
				damage = 1.0 - max (0, min (c['HP'], c['MaxHP'])) / float (c['MaxHP'])
			else:
				damage = 1.0
			fill = int (h * damage)
			Button.SetBorder (2, ColorDamage, fill > 0, 1, {'x' : 0, 'y' : h - fill, 'w' : w, 'h' : fill})

		if card['fade'] is not None:
			ShowDeathFade (Button, card)
			continue

		active = c is not None and c['ID'] == order['Active']
		Button.SetBorder (0, ColorActive, active, 0, Button.GetInsetFrame (0))
		Button.SetBorder (1, ColorDone, c is not None and c['Done'] and not active, 1)

	# round, and who acts with their level
	Label = Window.GetControl (MAX_CARDS)
	text = "Round {}".format (order['Round'])
	c = info.get (order['Active'])
	if c is not None:
		text = "{}      {}   Lv. {}".format (text, c['Name'], c.get ('Level', '?'))
	Label.SetText (text)

def SetCardPicture (Button, c):
	# beasts use the bestiary art from the journal, party members animated portraits
	image = None
	if c['Bestiary'] >= 0:
		image = GemRB.GetINIBeastsKey (str (c['Bestiary']), 'imageKnown', '')
	if image:
		Button.SetPicture (image)
		Button.SetText ("")
	elif c['IsPC'] and c['LargePortrait']:
		Button.SetPicture (GemRB.GetSprite (c['LargePortrait'], -1, 0, 0))
		Button.SetText ("")
	else:
		Button.SetPicture (None)
		Button.SetText (c['Name'][:10])

def ShowDeathFade (Button, card):
	# the card darkens as it falls away
	step = FADE_STEPS - card['fade']
	alpha = min (235, 60 + step * 12)
	Button.SetText ("")
	Button.SetBorder (0, ColorActive, 0, 0)
	Button.SetBorder (1, {'r' : 0, 'g' : 0, 'b' : 0, 'a' : alpha}, 1, 1)

def NeedsAnimation ():
	for card in Cards:
		if card['fade'] is not None and card['fade'] > 0:
			return True
		if 'target' in card and card['x'] != card['target']:
			return True
		if 'targetW' in card and card['w'] != card['targetW']:
			return True
	return False

def AnimationStep ():
	global Animating

	Animating = False
	order = GemRB.GetTurnOrder ()
	if order is None:
		return

	for card in Cards:
		if card['fade'] is not None and card['fade'] > 0:
			card['fade'] -= 1
			step = FADE_STEPS - card['fade']
			card['fall'] = int (step * step * FALL_DISTANCE / (FADE_STEPS * FADE_STEPS))
	LayoutCards ()
	for card in Cards:
		if 'target' in card:
			dx = card['target'] - card['x']
			if dx:
				card['x'] += max (-SLIDE_SPEED, min (SLIDE_SPEED, dx))
		if 'targetW' in card:
			dw = card['targetW'] - card['w']
			if abs (dw) < 1:
				card['w'] = float (card['targetW'])
			else:
				card['w'] += dw * 0.35

	DrawCards (order)
	StartAnimation ()

def StartAnimation ():
	global Animating

	if Animating or not NeedsAnimation ():
		return
	Animating = True
	GemRB.SetTimer (AnimationStep, ANIM_INTERVAL, 0)

###################################################
# hotbar
#
# Always up (real time too), just above pst's portrait strip. Everything the selected
# character can do is on it at once, like a modern tactics game: attack, talk, inventory,
# weapon quick slots, quick items, thief skills, every memorized spell and
# ability, then Run, Delay and End Turn (those three only in a turn based fight). Click a
# slot to pick the action, then click a target; Escape, right click or Cancel drops it.
# With nothing picked, clicking the ground moves. Icons are pst's own (radial menu BAMs,
# item and spell icons).

SLOT = 32 # pst's slot art (AMGENS) is 32x32
SLOT_STEP = SLOT + 2
SPELL_COLS = 10
SPELL_PAGE = SPELL_COLS * 2
GROUP_GAP = 10
PAD = 6
INFO_H = 18
ROWS_Y = PAD + INFO_H + 2
ROWS_H = SLOT_STEP + SLOT
SIDE_W = 58 # Run / Delay
END_W = 66
REFRESH_INTERVAL = 250 # selection, gear, spells and the cursor mode change outside of the bar

CID_ATTACK = 0
CID_INVENTORY = 1
CID_TALK = 2
CID_COMMON_EMPTY = 3
CID_WEAPONS = 10 # 4
CID_ITEMS = 20 # 5
CID_SPELLS = 30 # SPELL_PAGE
CID_SPELL_PREV = 60
CID_SPELL_NEXT = 61
CID_RUN = 62
CID_DELAY = 63
CID_END = 64
CID_CANCEL = 65
CID_NAME = 70
CID_MOVE_BACK = 71
CID_MOVE_FILL = 72
CID_MOVE_TEXT = 73
CID_ACTION_PIP = 74
CID_ACTION_TEXT = 75
CID_ATTACKS = 76
CID_PANELS = 80 # group backgrounds
CID_EDGE = 90

MOVE_BAR_W = 110

ColorPanel = {'r' : 28, 'g' : 22, 'b' : 16, 'a' : 235}
ColorGroup = {'r' : 52, 'g' : 41, 'b' : 28, 'a' : 200}
ColorEdge = {'r' : 150, 'g' : 112, 'b' : 62, 'a' : 255}
ColorMoveBack = {'r' : 70, 'g' : 58, 'b' : 40, 'a' : 255}
ColorMoveFill = {'r' : 200, 'g' : 160, 'b' : 60, 'a' : 255}
ColorMoveRan = {'r' : 90, 'g' : 190, 'b' : 90, 'a' : 255}
ColorPipReady = {'r' : 80, 'g' : 200, 'b' : 90, 'a' : 255}
ColorPipUsed = {'r' : 70, 'g' : 60, 'b' : 50, 'a' : 255}
ColorEndTurn = {'r' : 70, 'g' : 46, 'b' : 22, 'a' : 240}

# thief skills lead the spell grid, as in pst's radial menu
ThiefSkills = [
	('SP085', 'Search', 'Search for traps and hidden things.', 'ActionSearchPressed'),
	('SP087', 'Thieving', 'Pick a pocket or a lock, or disarm a trap.', 'ActionThievingPressed'),
	('SP086', 'Stealth', 'Sneak in the shadows.', 'ActionStealthPressed'),
]

# what the bar does outside a fight, and on someone else's turn
RealTimeBudget = {'Busy' : False, 'CanAttack' : True, 'CanUseItem' : True, 'CanCast' : True, 'CanEquip' : True,
	'CanRun' : False, 'MainActionUsed' : False, 'Ran' : False, 'Move' : 0, 'MaxMove' : 0, 'Attacks' : 0}
WaitingBudget = dict (RealTimeBudget, Busy = True, CanAttack = False, CanUseItem = False, CanCast = False, CanEquip = False)

SpellPage = 0
SpellList = [] # what the spell slots show, for the click handlers
SyncTimer = False
BarShown = False

def BarLayout ():
	"""x of each group, left to right, and the window width."""
	x = PAD
	lay = {}
	lay['common'] = x; x += 2 * SLOT_STEP - 2 + GROUP_GAP
	lay['weapons'] = x; x += 2 * SLOT_STEP - 2 + GROUP_GAP
	lay['items'] = x; x += 3 * SLOT_STEP - 2 + GROUP_GAP
	lay['spells'] = x; x += SPELL_COLS * SLOT_STEP - 2 + 2
	lay['pager'] = x; x += 28 + GROUP_GAP
	lay['side'] = x; x += SIDE_W + 4
	lay['end'] = x; x += END_W + PAD
	lay['width'] = x
	lay['height'] = ROWS_Y + ROWS_H + PAD
	return lay

def SlotFrame (gx, col, row):
	return {'x' : gx + col * SLOT_STEP, 'y' : ROWS_Y + row * SLOT_STEP, 'w' : SLOT, 'h' : SLOT}

def MakeSlot (Window, cid, frame, handler):
	Button = Window.CreateButton (cid, frame['x'], frame['y'], frame['w'], frame['h'])
	Button.SetSprites ("AMGENS", 0, 0, 1, 0, 0)
	Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)
	Button.SetFont ("NORMAL")
	Button.OnPress (handler)
	return Button

def MakeIconButton (Window, cid, frame, bam, tip, handler):
	Button = Window.CreateButton (cid, frame['x'], frame['y'], frame['w'], frame['h'])
	Button.SetSprites (bam, 0, 0, 1, 2, 3)
	Button.SetTooltip (tip)
	Button.OnPress (handler)
	return Button

def MakeTextButton (Window, cid, frame, text, tip, handler, back = ColorGroup):
	Button = Window.CreateButton (cid, frame['x'], frame['y'], frame['w'], frame['h'])
	Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
	Button.SetFont ("NORMAL")
	Button.SetText (text)
	Button.SetTooltip (tip)
	Button.SetBackground (back)
	Button.SetBorder (2, ColorEdge, 1, 0)
	Button.OnPress (handler)
	return Button

def MakePanel (Window, cid, frame, color):
	Button = Window.CreateButton (cid, frame['x'], frame['y'], frame['w'], frame['h'])
	Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
	Button.SetBackground (color)
	Button.SetState (IE_GUI_BUTTON_LOCKED)
	return Button

def GetBarWindow ():
	lay = BarLayout ()
	frame = {'x' : 0, 'y' : 0, 'w' : lay['width'], 'h' : lay['height']}
	Window = GemRB.GetView ("COMBATBAR")
	if not Window:
		Window = GemRB.CreateWindow (BAR_WINDOW_ID, GUICommon.GetWindowPack (), frame, WINDOW_BOTTOM|WINDOW_HCENTER)
	if not Window.GetControl (CID_END):
		BuildBar (Window, lay)
	PlaceBar (Window, lay)
	return Window

def PlaceBar (Window, lay):
	"""Just above pst's portrait strip, so the portraits stay visible and clickable."""
	bottom = GemRB.GetSystemVariable (SV_HEIGHT)
	portraits = GemRB.GetView ("PORTWIN")
	if portraits:
		bottom = portraits.GetFrame ()['y']
	Window.SetPos ((GemRB.GetSystemVariable (SV_WIDTH) - lay['width']) // 2, bottom - lay['height'] - 2)

def BuildBar (Window, lay):
	Window.AddAlias ("COMBATBAR")
	Window.SetFlags (WF_DESTROY_ON_CLOSE, OP_NAND)
	# like pst's own hud windows: never the keyboard focus, so keys (Escape, Space, ...) reach the game view
	Window.SetFlags (WF_ALPHA_CHANNEL | WF_BORDERLESS | IE_GUI_VIEW_IGNORE_EVENTS, OP_OR)
	Window.SetBackground (ColorPanel)
	MakePanel (Window, CID_EDGE, {'x' : 0, 'y' : 0, 'w' : lay['width'], 'h' : 2}, ColorEdge)

	# thin bronze rules between the groups (panels under the slots would draw over them)
	for i, key in enumerate (('weapons', 'items', 'spells', 'side')):
		MakePanel (Window, CID_PANELS + i, {'x' : lay[key] - GROUP_GAP // 2 - 1, 'y' : ROWS_Y, 'w' : 1, 'h' : ROWS_H}, ColorEdge)

	# the radial menu's own actions
	common = lay['common']
	MakeIconButton (Window, CID_ATTACK, SlotFrame (common, 0, 0), "AMATTCK", "Attack", BarAttack)
	MakeIconButton (Window, CID_TALK, SlotFrame (common, 1, 0), "AMTLK", "Talk to someone.", BarTalk)
	MakeIconButton (Window, CID_INVENTORY, SlotFrame (common, 0, 1), "AMINVNT", "Inventory", BarInventory)
	ClearSlot (MakeSlot (Window, CID_COMMON_EMPTY, SlotFrame (common, 1, 1), None))

	for i in range (4):
		MakeSlot (Window, CID_WEAPONS + i, SlotFrame (lay['weapons'], i % 2, i // 2), BarWeapon)
	for i in range (5):
		MakeSlot (Window, CID_ITEMS + i, SlotFrame (lay['items'], i % 3, i // 3), BarItem)
	for i in range (SPELL_PAGE):
		MakeSlot (Window, CID_SPELLS + i, SlotFrame (lay['spells'], i % SPELL_COLS, i // SPELL_COLS), BarSpell)

	Button = Window.CreateButton (CID_SPELL_PREV, lay['pager'], ROWS_Y + 4, 28, 24)
	Button.SetSprites ("AMSCRLL", 0, 0, 1, 0, 0)
	Button.SetTooltip ("Previous spells")
	Button.OnPress (lambda: TurnSpellPage (-1))
	Button = Window.CreateButton (CID_SPELL_NEXT, lay['pager'], ROWS_Y + SLOT_STEP + 6, 27, 19)
	Button.SetSprites ("AMSCRLR", 0, 0, 1, 0, 0)
	Button.SetTooltip ("More spells")
	Button.OnPress (lambda: TurnSpellPage (1))

	MakeTextButton (Window, CID_RUN, {'x' : lay['side'], 'y' : ROWS_Y, 'w' : SIDE_W, 'h' : SLOT},
		"Run", "Run: give up your action for twice the movement. Turn based only.", BarRun)
	MakeTextButton (Window, CID_DELAY, {'x' : lay['side'], 'y' : ROWS_Y + SLOT_STEP, 'w' : SIDE_W, 'h' : SLOT},
		"Delay", "Delay: act after everyone else this round. Only before moving or acting.", BarDelay)
	MakeTextButton (Window, CID_END, {'x' : lay['end'], 'y' : ROWS_Y, 'w' : END_W, 'h' : ROWS_H},
		"End\nTurn", "End this character's turn (Space): the next party member in the order goes on.", BarEndTurn, ColorEndTurn)

	# info line: who, movement, action, attacks, cancel
	Label = Window.CreateLabel (CID_NAME, PAD, PAD, 290, INFO_H, "NORMAL", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_MIDDLE)
	Label.SetColor (ColorTitle, TA_COLOR_NORMAL)
	mx = PAD + 296
	# the bar is two panels side by side, filled part and the rest: views overlapping in this
	# window don't redraw in order. Under 10 px tall they don't draw at all.
	MakePanel (Window, CID_MOVE_FILL, {'x' : mx, 'y' : PAD + 3, 'w' : MOVE_BAR_W, 'h' : 12}, ColorMoveFill)
	MakePanel (Window, CID_MOVE_BACK, {'x' : mx, 'y' : PAD + 3, 'w' : MOVE_BAR_W, 'h' : 12}, ColorMoveBack)
	Label = Window.CreateLabel (CID_MOVE_TEXT, mx + MOVE_BAR_W + 6, PAD, 68, INFO_H, "NORMAL", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_MIDDLE)
	Label.SetColor (ColorInfo, TA_COLOR_NORMAL)
	ax = mx + MOVE_BAR_W + 76
	Pip = MakePanel (Window, CID_ACTION_PIP, {'x' : ax, 'y' : PAD + 4, 'w' : 10, 'h' : 10}, ColorPipReady)
	Pip.SetBorder (0, ColorEdge, 1, 0)
	Label = Window.CreateLabel (CID_ACTION_TEXT, ax + 14, PAD, 80, INFO_H, "NORMAL", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_MIDDLE)
	Label.SetColor (ColorInfo, TA_COLOR_NORMAL)
	Label = Window.CreateLabel (CID_ATTACKS, ax + 96, PAD, 70, INFO_H, "NORMAL", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_MIDDLE)
	Label.SetColor (ColorInfo, TA_COLOR_NORMAL)
	Button = MakeTextButton (Window, CID_CANCEL, {'x' : lay['width'] - PAD - 96, 'y' : PAD - 2, 'w' : 96, 'h' : INFO_H + 2},
		"Cancel", "Drop the picked action (also Escape or right click).", BarCancel)

###################################################
# what the character has

def InFight ():
	order = GemRB.GetTurnOrder ()
	return order is not None and not order['Suspended']

def TurnOwnerPC ():
	"""Party slot (1 based) of the party member whose turn it is, or 0."""
	budget = GemRB.GetTurnBudget ()
	order = GemRB.GetTurnOrder ()
	if budget is None or order is None:
		return 0
	for c in order['Combatants']:
		if c['ID'] == budget['ID']:
			return c.get ('PartyID', 0)
	return 0

def ActivePC ():
	"""Party slot the bar is for: whoever's turn it is in a fight, else the selected one."""
	return TurnOwnerPC () or GemRB.GameGetFirstSelectedPC ()

def HotbarSetting ():
	"""The "Hotbar" setting: on, the bar is always up and replaces pst's radial menu; off, only on your turns."""
	value = GemRB.GetVar ("Hotbar")
	return value is None or value != 0

def BarAllowed ():
	"""Hidden in dialogue (pst hides the portraits then) and while a full window is open."""
	portraits = GemRB.GetView ("PORTWIN")
	if not HotbarSetting () and not (InFight () and TurnOwnerPC ()):
		return False
	return bool (portraits and portraits.IsVisible ()) and not TopWindowOpen ()

def ItemName (item):
	if item['ItemNameIdentified'] != -1:
		return item['ItemNameIdentified']
	return item['ItemName']

def WeaponSlotItem (pc, i):
	slot_item = GemRB.GetSlotItem (pc, 10 + i)
	if i == 0 and not slot_item:
		slot_item = GemRB.GetSlotItem (pc, 10, 1) # fists
	return slot_item

def CollectSpells (pc):
	"""Thief skills, the memorized spells of the character's book, then its abilities (innates)."""
	import CommonTables
	import Spellbook
	spells = []
	if GemRB.GetPlayerStat (pc, IE_CLASS) == 9: # thief
		for resref, name, tip, handler in ThiefSkills:
			spells.append ({'Skill' : handler, 'SpellResRef' : resref, 'Name' : name, 'Tip' : tip})
	ClassName = GUICommon.GetClassRowName (pc)
	if CommonTables.ClassSkills.GetValue (ClassName, "CLERICSPELL") == "*":
		books = [IE_SPELL_TYPE_WIZARD, IE_SPELL_TYPE_INNATE]
	else:
		books = [IE_SPELL_TYPE_PRIEST, IE_SPELL_TYPE_INNATE]
	for book in books:
		spells += Spellbook.GetUsableMemorizedSpells (pc, book)
	return spells

###################################################

def SetSlotState (Button, usable, selected):
	Button.SetState (IE_GUI_BUTTON_ENABLED if usable else IE_GUI_BUTTON_DISABLED)
	Button.SetBorder (1, ColorUnavailable, not usable, 1)
	Button.SetBorder (0, ColorSelected, usable and selected, 0, Button.GetInsetFrame (0))

def ClearSlot (Button):
	Button.SetSprites ("AMGENS", 0, 0, 1, 0, 0)
	Button.SetPicture (None)
	Button.SetText ("")
	Button.SetTooltip ("")
	Button.SetState (IE_GUI_BUTTON_LOCKED)
	Button.SetBorder (0, ColorSelected, 0, 0)
	Button.SetBorder (1, ColorUnavailable, 0, 1)
	Button.SetBorder (3, ColorEdge, 0, 0)

def UpdateCombatBar ():
	global SpellList, SpellPage, SelectedMode, BarShown

	StartSync ()
	Window = GemRB.GetView ("COMBATBAR")
	pc = ActivePC ()
	if pc == 0 or not BarAllowed ():
		if Window:
			Window.SetVisible (False)
		BarShown = False
		return

	Window = GetBarWindow ()
	Window.SetVisible (True)
	BarShown = True

	if SelectedMode is not None and GemRB.GameControlGetTargetMode () == TARGET_MODE_NONE:
		SelectedMode = None # dropped by right click, Escape, or the action went off

	fight = InFight ()
	if not fight:
		budget = RealTimeBudget
	elif TurnOwnerPC ():
		budget = GemRB.GetTurnBudget ()
	else:
		budget = WaitingBudget # someone else's turn: the selected character's bar, nothing usable

	busy = budget['Busy']
	canAttack = budget['CanAttack'] and not busy
	canItem = budget['CanUseItem'] and not busy
	canCast = budget['CanCast'] and not busy
	realTime = not fight

	# attack with what's in hand
	Button = Window.GetControl (CID_ATTACK)
	equipped = GemRB.GetEquippedQuickSlot (pc, 1)
	weapon = WeaponSlotItem (pc, equipped) if 0 <= equipped < 4 else None
	tip = "Attack"
	if fight:
		tip = "Attack: a full round of attacks ({} this round). Uses your action.".format (budget['Attacks'])
	if weapon:
		tip = "Attack with {}\n{}".format (GemRB.GetString (ItemName (GemRB.GetItem (weapon['ItemResRef']))), tip)
	Button.SetTooltip (tip)
	SetSlotState (Button, canAttack, SelectedMode == "attack")
	SetSlotState (Window.GetControl (CID_INVENTORY), not busy, False)
	SetSlotState (Window.GetControl (CID_TALK), realTime, SelectedMode == "talk") # no talking in a fight

	# weapon quick slots: click to take it in hand and attack with it
	for i in range (4):
		Button = Window.GetControl (CID_WEAPONS + i)
		slot_item = WeaponSlotItem (pc, i)
		if not slot_item or not slot_item['Flags'] & IE_INV_ITEM_IDENTIFIED:
			ClearSlot (Button)
			continue
		item = GemRB.GetItem (slot_item['ItemResRef'])
		Button.SetItemIcon (slot_item['ItemResRef'], 6)
		Button.SetText ("")
		inHand = i == equipped
		tip = GemRB.GetString (ItemName (item))
		tip += "\nIn hand: click to attack" if inHand else "\nClick to take in hand and attack"
		Button.SetTooltip (tip)
		usable = canAttack or (budget['CanEquip'] and not busy and not inHand)
		SetSlotState (Button, usable, SelectedMode == "weapon{}".format (i) or (inHand and SelectedMode == "attack"))
		Button.SetBorder (3, ColorEdge, inHand, 0, Button.GetInsetFrame (1))

	# quick items
	for i in range (5):
		Button = Window.GetControl (CID_ITEMS + i)
		slot_item = GemRB.GetSlotItem (pc, 21 + i)
		if not slot_item or not slot_item['Flags'] & IE_INV_ITEM_IDENTIFIED:
			ClearSlot (Button)
			continue
		item = GemRB.GetItem (slot_item['ItemResRef'])
		Button.SetItemIcon (slot_item['ItemResRef'], 6)
		Button.SetText (str (slot_item['Usages0']) if item['MaxStackAmount'] > 1 or slot_item['Usages0'] > 1 else "")
		Button.SetTooltip (GemRB.GetString (ItemName (item)) + ("\nUses your action." if fight else ""))
		SetSlotState (Button, canItem, SelectedMode == "item{}".format (i))

	# thief skills, spells and abilities
	SpellList = CollectSpells (pc)
	pages = max (1, (len (SpellList) + SPELL_PAGE - 1) // SPELL_PAGE)
	SpellPage = min (SpellPage, pages - 1)
	for i in range (SPELL_PAGE):
		Button = Window.GetControl (CID_SPELLS + i)
		n = SpellPage * SPELL_PAGE + i
		if n >= len (SpellList):
			ClearSlot (Button)
			continue
		spell = SpellList[n]
		Button.SetSprites ("AMGENS", 0, 0, 1, 0, 0)
		Button.SetBorder (3, ColorEdge, 0, 0)
		if 'Skill' in spell:
			Button.SetPicture (GemRB.GetSprite (spell['SpellResRef'], -1, 0, 0))
			Button.SetText ("")
			Button.SetTooltip ("{}\n{}".format (spell['Name'], spell['Tip']))
			SetSlotState (Button, realTime, SelectedMode == "skill" + spell['Skill'])
			continue
		Button.SetSpellIcon (spell['SpellResRef'])
		Button.SetText (str (spell['MemoCount']) if spell['MemoCount'] > 1 else "")
		kind = "Ability" if spell['BookType'] == IE_SPELL_TYPE_INNATE else "Level {} spell".format (spell.get ('SpellLevel', '?'))
		Button.SetTooltip ("{}\n{}, {} left.{}".format (GemRB.GetString (spell['SpellName']), kind, spell['MemoCount'], " Uses your action." if fight else ""))
		SetSlotState (Button, canCast, SelectedMode == "spell" + spell['SpellResRef'])
	Window.GetControl (CID_SPELL_PREV).SetVisible (SpellPage > 0)
	Window.GetControl (CID_SPELL_NEXT).SetVisible (SpellPage < pages - 1)

	# turn based only: out of a fight they are not there
	for cid in (CID_RUN, CID_DELAY, CID_END):
		Window.GetControl (cid).SetVisible (fight)
	SetSlotState (Window.GetControl (CID_RUN), fight and budget['CanRun'] and not busy, False)
	SetSlotState (Window.GetControl (CID_DELAY), fight and not busy and not budget['MainActionUsed'] and budget['Move'] == budget['MaxMove'], False)
	SetSlotState (Window.GetControl (CID_END), fight and not busy, False)
	Window.GetControl (CID_CANCEL).SetVisible (SelectedMode is not None)

	# info line
	name = GemRB.GetPlayerName (pc, 1)
	hp = GemRB.GetPlayerStat (pc, IE_HITPOINTS)
	maxhp = GemRB.GetPlayerStat (pc, IE_MAXHITPOINTS)
	ac = GemRB.GetPlayerStat (pc, IE_ARMORCLASS)
	thac0 = GemRB.GetPlayerStat (pc, IE_TOHIT)
	Window.GetControl (CID_NAME).SetText ("{}   HP {}/{}   AC {}   THAC0 {}".format (name, hp, maxhp, ac, thac0))

	showTurn = fight and TurnOwnerPC () != 0
	for cid in (CID_MOVE_BACK, CID_MOVE_FILL, CID_MOVE_TEXT, CID_ACTION_PIP, CID_ACTION_TEXT, CID_ATTACKS):
		Window.GetControl (cid).SetVisible (showTurn)
	if not showTurn:
		return

	full = max (1, budget['MaxMove'])
	fillW = int (MOVE_BAR_W * max (0, min (budget['Move'], full)) / float (full))
	Fill = Window.GetControl (CID_MOVE_FILL)
	Back = Window.GetControl (CID_MOVE_BACK)
	Fill.SetVisible (fillW > 0)
	Back.SetVisible (fillW < MOVE_BAR_W)
	frame = Fill.GetFrame ()
	if frame['w'] != max (1, fillW):
		x0 = frame['x']
		frame['w'] = max (1, fillW)
		Fill.SetFrame (frame)
		Back.SetFrame ({'x' : x0 + fillW, 'y' : frame['y'], 'w' : max (1, MOVE_BAR_W - fillW), 'h' : frame['h']})
	Fill.SetBackground (ColorMoveRan if budget['Ran'] else ColorMoveFill)
	Window.GetControl (CID_MOVE_TEXT).SetText ("{} / {} ft".format (budget['Move'], budget['MaxMove']))

	used = budget['MainActionUsed'] or budget['Ran']
	Window.GetControl (CID_ACTION_PIP).SetBackground (ColorPipUsed if used else ColorPipReady)
	Window.GetControl (CID_ACTION_TEXT).SetText ("Running" if budget['Ran'] else ("Action used" if used else "Action"))
	Window.GetControl (CID_ATTACKS).SetText ("Attacks: {}".format (budget['Attacks']))

def StartSync ():
	"""Refreshes the bar a few times a second while in the game."""
	global SyncTimer
	if SyncTimer:
		return
	SyncTimer = True
	GemRB.SetTimer (SyncStep, REFRESH_INTERVAL, 0)

def SyncStep ():
	global SyncTimer
	SyncTimer = False
	if not GemRB.GetView ("PORTWIN"):
		return # left the game; MessageWindow starts it again on load
	UpdateCombatBar ()

def SelectMode (mode):
	global SelectedMode
	SelectedMode = mode
	UpdateCombatBar ()

def TurnSpellPage (step):
	global SpellPage
	SpellPage = max (0, SpellPage + step)
	UpdateCombatBar ()

def BarCancel ():
	global SelectedMode
	SelectedMode = None
	GemRB.GameControlSetTargetMode (TARGET_MODE_NONE)
	UpdateCombatBar ()

def PickMode (mode, handler):
	"""An action from pst's radial menu, picked like a slot."""
	import ActionsWindow
	if SelectedMode == mode:
		BarCancel ()
		return
	getattr (ActionsWindow, handler) ()
	SelectMode (mode)

def BarTalk ():
	PickMode ("talk", "ActionTalkPressed")

def BarAttack ():
	PickMode ("attack", "ActionAttackPressed")

def BarWeapon (btn):
	pc = ActivePC ()
	i = (btn.ControlID & 0xffff) - CID_WEAPONS
	if not pc:
		return
	if GemRB.GetEquippedQuickSlot (pc, 1) != i:
		GemRB.SetEquippedQuickSlot (pc, i)
	budget = GemRB.GetTurnBudget () if InFight () else RealTimeBudget
	if budget and budget['CanAttack']:
		import ActionsWindow
		ActionsWindow.ActionAttackPressed ()
		SelectMode ("weapon{}".format (i))
	else:
		UpdateCombatBar ()

def BarItem (btn):
	pc = ActivePC ()
	i = (btn.ControlID & 0xffff) - CID_ITEMS
	if not pc:
		return
	mode = "item{}".format (i)
	if SelectedMode == mode:
		BarCancel ()
		return
	GemRB.GameControlSetTargetMode (TARGET_MODE_NONE)
	GemRB.UseItem (pc, 21 + i, 0) # picks the target mode, or uses it at once on self
	SelectMode (mode)

def BarSpell (btn):
	import ActionsWindow
	i = (btn.ControlID & 0xffff) - CID_SPELLS
	n = SpellPage * SPELL_PAGE + i
	if n >= len (SpellList):
		return
	spell = SpellList[n]
	if 'Skill' in spell:
		PickMode ("skill" + spell['Skill'], spell['Skill'])
		return
	mode = "spell" + spell['SpellResRef']
	if SelectedMode == mode:
		BarCancel ()
		return
	GemRB.GameControlSetTargetMode (TARGET_MODE_NONE)
	GemRB.SetVar ("Type", 1 << spell['BookType'])
	GemRB.SetVar ("QSpell", None)
	GemRB.SetVar ("Spell", spell['SpellIndex'])
	ActionsWindow.SpellPressed () # picks the target mode, or casts at once on self
	SelectMode (mode)

def BarRun ():
	if GemRB.TurnBasedRun ():
		BarCancel ()

def BarInventory ():
	import GUIINV
	GUIINV.OpenInventoryWindow ()

def BarDelay ():
	SelectMode (None)
	GemRB.DelayTurn ()

def BarEndTurn ():
	SelectMode (None)
	GemRB.EndTurn ()

###################################################

def UpdateTurnOrder ():
	global Cards, SelectedMode

	order = GemRB.GetTurnOrder ()
	if order is None or order['Suspended']:
		Window = GemRB.GetView ("TURNORDER")
		if Window:
			Window.SetVisible (False)
		if order is None:
			Cards = []
		UpdateCombatBar () # the hotbar stays, in its real time form
		return

	Window = GetOrderWindow ()
	Window.SetVisible (True)
	MergeCards (order['Combatants'], order['Active'])
	LayoutCards ()
	DrawCards (order)
	StartAnimation ()

	budget = GemRB.GetTurnBudget ()
	if budget is None or budget['ID'] != order['Active']:
		SelectedMode = None
	UpdateCombatBar ()
