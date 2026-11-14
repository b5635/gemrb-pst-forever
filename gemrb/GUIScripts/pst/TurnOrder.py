# SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# TurnOrder.py - turn based combat gui: the initiative bar at the top and the
# combat action bar at the bottom. Both only exist while a fight is going on.
# The engine calls UpdateTurnOrder whenever the order or the budget change.

import GemRB
import GUICommon
from GUIDefines import *

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

BAR_BTN_W = 72
BAR_BTN_H = 56 # room for the war2 icon on top and the label below it
BAR_INFO_H = 18

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
	Window.SetFlags (WF_ALPHA_CHANNEL | WF_BORDERLESS, OP_OR)
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
# combat action bar

BarButtons = [
	# label, tooltip, handler name, mode
	("Attack", "Attack an enemy: a full round of attacks. Uses your action.", "BarAttack", "attack"),
	("Cast", "Cast a spell. Uses your action.", "BarCast", "cast"),
	("Items", "Use an item or potion. Uses your action.", "BarItems", "items"),
	("Quick", "Quick weapon slots: the first swap each turn is free.", "BarQuick", "quick"),
	("Move", "Move: click to place, click again to go. Right click cancels.", "BarMove", "move"),
	("Run", "Give up your action for twice the movement.", "BarRun", None),
	("Inventory", "Equipment and inventory. Changing gear uses your action.", "BarInventory", None),
	("Delay", "Act after everyone else this round. Only before moving or acting.", "BarDelay", None),
	("End Turn", "End this character's turn (Space): the next party member in the order goes on.", "BarEndTurn", None),
]

def GetBarWindow ():
	width = len (BarButtons) * (BAR_BTN_W + 2) + 8
	height = BAR_BTN_H + BAR_INFO_H + 8
	frame = {'x' : 0, 'y' : 0, 'w' : width, 'h' : height}
	Window = GemRB.CreateWindow (BAR_WINDOW_ID, GUICommon.GetWindowPack (), frame, WINDOW_BOTTOM|WINDOW_HCENTER)
	if Window.GetControl (0):
		return Window

	Window.AddAlias ("COMBATBAR")
	Window.SetFlags (WF_DESTROY_ON_CLOSE, OP_NAND)
	Window.SetFlags (WF_ALPHA_CHANNEL | WF_BORDERLESS, OP_OR)
	Window.SetBackground (ColorBarBack)
	# war2 control panel icons, padded pngs in override/pst
	Icons = ("bar_atk", "bar_cst", "bar_itm", "bar_qck", "bar_mve", "bar_run", "bar_inv", "bar_end", "bar_end")
	for i, (text, tip, handler, mode) in enumerate (BarButtons):
		Button = Window.CreateButton (i, 4 + i * (BAR_BTN_W + 2), 4, BAR_BTN_W, BAR_BTN_H)
		Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)
		Button.SetFont ("NORMAL")
		Button.SetPicture (Icons[i])
		Button.SetText (text)
		Button.SetTooltip (tip)
		Button.SetBackground (ColorButton)
		Button.OnPress (globals ()[handler])
	Info = Window.CreateLabel (len (BarButtons), 4, BAR_BTN_H + 6, width - 8, BAR_INFO_H, "NORMAL", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_CENTER)
	Info.SetColor (ColorInfo, TA_COLOR_NORMAL)

	# sit just above pst's portrait strip
	portraits = GemRB.GetView ("PORTWIN")
	if portraits:
		pframe = portraits.GetFrame ()
		Window.SetPos ((GemRB.GetSystemVariable (SV_WIDTH) - width) // 2, pframe['y'] - height)
	return Window

def UpdateCombatBar ():
	budget = GemRB.GetTurnBudget ()
	Window = GemRB.GetView ("COMBATBAR")
	if budget is None or TopWindowOpen ():
		# not a party member's turn, or the inventory (or another full window) is open
		if Window:
			Window.SetVisible (False)
		return

	Window = GetBarWindow ()
	Window.SetVisible (True)
	Window.Focus ()

	busy = budget['Busy']
	available = {
		"attack" : budget['CanAttack'],
		"cast" : budget['CanCast'],
		"items" : budget['CanUseItem'],
		"quick" : True,
		"move" : budget['Move'] > 0,
	}
	for i, (text, tip, handler, mode) in enumerate (BarButtons):
		Button = Window.GetControl (i)
		if mode is not None:
			usable = available[mode]
		elif handler == "BarRun":
			usable = budget['CanRun']
		elif handler == "BarDelay":
			usable = not budget['MainActionUsed'] and budget['Move'] == budget['MaxMove']
		else:
			usable = True
		usable = usable and not busy
		Button.SetDisabled (not usable)
		Button.SetBorder (1, ColorUnavailable, not usable, 1)
		Button.SetBorder (0, ColorSelected, usable and mode is not None and mode == SelectedMode, 0, Button.GetInsetFrame (0))

	action = "used" if budget['MainActionUsed'] else "ready"
	if budget['Ran']:
		action = "running"
	Label = Window.GetControl (len (BarButtons))
	Label.SetText ("Movement: {} / {} ft    Action: {}    Attacks: {}".format (budget['Move'], budget['MaxMove'], action, budget['Attacks']))

def SelectMode (mode):
	global SelectedMode
	SelectedMode = mode
	UpdateCombatBar ()

def OpenFloatMenu (selector):
	import FloatMenuWindow
	FloatMenuWindow.OpenFloatMenuWindow ()
	getattr (FloatMenuWindow, selector) ()

def BarAttack ():
	SelectMode ("attack")
	GemRB.GameControlSetTargetMode (TARGET_MODE_ATTACK)

def BarCast ():
	SelectMode ("cast")
	OpenFloatMenu ("FloatMenuSelectSpells")

def BarItems ():
	SelectMode ("items")
	OpenFloatMenu ("FloatMenuSelectItems")

def BarQuick ():
	SelectMode ("quick")
	OpenFloatMenu ("FloatMenuSelectWeapons")

def BarMove ():
	SelectMode ("move")
	GemRB.GameControlSetTargetMode (TARGET_MODE_NONE)

def BarRun ():
	if GemRB.TurnBasedRun ():
		SelectMode ("move")
		GemRB.GameControlSetTargetMode (TARGET_MODE_NONE)

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
		for alias in ("TURNORDER", "COMBATBAR"):
			Window = GemRB.GetView (alias)
			if Window:
				Window.SetVisible (False)
		if order is None:
			Cards = []
			SelectedMode = None
		return

	Window = GetOrderWindow ()
	Window.SetVisible (True)
	if not TopWindowOpen ():
		Window.Focus ()
	MergeCards (order['Combatants'], order['Active'])
	LayoutCards ()
	DrawCards (order)
	StartAnimation ()

	budget = GemRB.GetTurnBudget ()
	if budget is None or budget['ID'] != order['Active']:
		SelectedMode = None
	UpdateCombatBar ()
