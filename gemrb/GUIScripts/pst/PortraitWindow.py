# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import random

import GemRB
import GUICommonWindows
import MenuWindow
from GUICommon import BindControlCallbackParams
from GUIDefines import *
from GameCheck import MAX_PARTY_SIZE
from ie_stats import *

# the chu has 6 portraits (ids 0-5) over 6 hp bars (ids 6-11) in a 426px wide strip;
# bigger parties (MaxPartySize, up to 8 in pst: the Nameless One and all seven companions)
# get scripted slots on the right, and the strip widens and recenters to fit them
CHU_SLOTS = 6
FRAME_PC_SELECTED = 0 # border index, used by PartyReform

def PortraitID (i):
	return i if i < CHU_SLOTS else 1000 + i

def HPButtonID (i):
	return 6 + i if i < CHU_SLOTS else 1100 + i

def SlotCount ():
	"""Slots the strip shows: the chu's 6, or one per party member up to the limit."""
	return max (CHU_SLOTS, min (GemRB.GetPartySize (), MAX_PARTY_SIZE))

def GetPortraitButtons (Window, *args):
	portraitList = []
	isStrip = not args # PartyReform passes layout args: its own window, no hp bars
	count = SlotCount () if isStrip else GemRB.GetPartySize ()
	for i in range (count):
		btn = Window.GetControl (PortraitID (i))
		if not btn:
			if not isStrip:
				btn = Window.CreateButton (PortraitID (i), 0, 0, 1, 1)
			else:
				btn = CreatePortraitSlot (Window, i)
		btn.SetVarAssoc ("portrait", i + 1)
		portraitList.append (btn)
	if not isStrip:
		FitReformSlots (Window, portraitList)
	return portraitList

def FitReformSlots (Window, portraitList):
	"""The reform window has 7 slots (a full party + 1); a party of 8 overflowing to 9
	squeezes all of them into the same row instead."""
	chuSlots = 0
	while Window.GetControl (chuSlots):
		chuSlots += 1
	if len (portraitList) <= chuSlots:
		return
	first = Window.GetControl (0).GetFrame ()
	last = Window.GetControl (chuSlots - 1).GetFrame ()
	gap = Window.GetControl (1).GetFrame ()['x'] - first['x'] - first['w']
	step = (last['x'] + last['w'] + gap - first['x']) // len (portraitList)
	# the slots tile the whole row on a dark fill: the window art has placeholder text
	# under the chu slot positions that narrower slots would otherwise show
	for i, btn in enumerate (portraitList):
		btn.SetFrame ({'x' : first['x'] + i * step, 'y' : first['y'], 'w' : step, 'h' : first['h']})
		btn.SetBackground ({'r' : 12, 'g' : 9, 'b' : 6, 'a' : 255})

def CreatePortraitSlot (Window, i):
	"""Clones chu slot 0 (portrait + hp bar) for party member i + 1."""
	first = Window.GetControl (0)
	frame = first.GetFrame ()
	w, h = frame['w'], frame['h']
	Button = Window.CreateButton (PortraitID (i), i * w, frame['y'], w, h)
	Button.SetFlags (first.Flags & ~IE_GUI_VIEW_INVISIBLE, OP_SET)
	Button.SetVarAssoc ("portrait", i + 1)
	SetupPortraitButton (Window, Button)

	hpFirst = Window.GetControl (HPButtonID (0))
	hpFrame = hpFirst.GetFrame ()
	ButtonHP = Window.CreateButton (HPButtonID (i), i * w, hpFrame['y'], hpFrame['w'], hpFrame['h'])
	ButtonHP.SetFlags (hpFirst.Flags & ~IE_GUI_VIEW_INVISIBLE, OP_SET)
	SetupHPButton (ButtonHP, i)

	# dark backing where the chu art would frame the slot; created last, as newer
	# subviews stack below the older ones
	Back = Window.CreateButton (1200 + i, i * w, 0, w, Window.GetFrame ()['h'])
	Back.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
	Back.SetBackground ({'r' : 34, 'g' : 28, 'b' : 20, 'a' : 255})
	Back.SetState (IE_GUI_BUTTON_LOCKED)
	return Button

def FitPortraitWindow (Window):
	"""Widens (or shrinks back) the strip to the slot count and keeps it centered."""
	if EEHudActive ():
		import EEHud
		EEHud.LayoutPortraits (Window)
		return
	slotW = Window.GetControl (0).GetFrame ()['w']
	frame = Window.GetFrame ()
	width = slotW * SlotCount ()
	if frame['w'] == width:
		return
	frame['x'] += (frame['w'] - width) // 2
	frame['w'] = width
	Window.SetFrame (frame)

def PortraitButtonHPOnPress (idx):
	hbs = GemRB.GetVar('Health Bar Settings')
	GemRB.SetVar ('Health Bar Settings', hbs ^ (1 << idx))
	Window = GemRB.GetView ("PORTWIN")
	UpdatePortraitButton (Window.GetControl (PortraitID (idx)))
	return

def SetupHPButton (ButtonHP, idx):
	ButtonHP.SetFlags(IE_GUI_BUTTON_PICTURE, OP_SET)
	ButtonHP.SetBAM('FILLBAR', 0, 0, -1)
	ButtonHP.OnPress (BindControlCallbackParams (PortraitButtonHPOnPress, idx))

def SetupPortraitButton (Window, Button):
	pcID = Button.Value
	Button.OnRightPress (GUICommonWindows.OpenInventoryWindowClick)
	Button.OnPress (GUICommonWindows.PortraitButtonOnPress)
	Button.SetAction (GUICommonWindows.PortraitButtonOnShiftPress, IE_ACT_MOUSE_PRESS, GEM_MB_ACTION, GEM_MOD_CTRL, 1)
	Button.SetAction (GUICommonWindows.ButtonDragSourceHandler, IE_ACT_DRAG_DROP_SRC)
	Button.SetAction (GUICommonWindows.ButtonDragDestHandler, IE_ACT_DRAG_DROP_DST)
	Button.SetAction(BindControlCallbackParams(GemRB.GameControlLocateActor, pcID), IE_ACT_MOUSE_ENTER)
	Button.SetAction(lambda: GemRB.GameControlLocateActor(-1), IE_ACT_MOUSE_LEAVE)
	Button.SetBAM ("PPPANN", 0, 0, -1) # NOTE: just a dummy, won't be visible
	Button.SetHotKey(chr(ord('0') + pcID), 0, True)
	Button.OnAnimEnd (UpdateButtonAnimation)
	SetupButtonBorders (Button)

def SetupButtonBorders (Button):
	yellow = {'r' : 255, 'g' : 255, 'b' : 0, 'a' : 255}
	green = {'r' : 0, 'g' : 255, 'b' : 0, 'a' : 255}
	Button.SetBorder (0, green, 0, 0, Button.GetInsetFrame (1, 1, 2, 2))
	Button.SetBorder (1, yellow, 0, 0, Button.GetInsetFrame (3, 3, 4, 4))

def EEHudActive ():
	import EEHud
	return EEHud.Active ()

def OpenPortraitWindow (pos=WINDOW_RIGHT|WINDOW_VCENTER):
	if EEHudActive ():
		import EEHud
		Window = EEHud.OpenPortraitWindow ()
	else:
		Window = GemRB.LoadWindow (1, "GUIWORLD", pos)
	Window.AddAlias("PORTWIN")
	Window.SetFlags(WF_BORDERLESS|IE_GUI_VIEW_IGNORE_EVENTS, OP_OR)

	# Rest
	Button = Window.GetControl (6)
	Button.SetTooltip (11942)
	Button.OnPress (MenuWindow.RestPress)

	# the original ini default (63) only covers 6 hp bars; slots 7+ would start as "hp / max" text
	hbs = GemRB.GetVar ('Health Bar Settings')
	if hbs == 63:
		GemRB.SetVar ('Health Bar Settings', 1023)

	for i, Button in enumerate (GetPortraitButtons (Window)[:CHU_SLOTS]):
		SetupPortraitButton (Window, Button)
		SetupHPButton (Window.GetControl (HPButtonID (i)), i)

	UpdatePortraitWindow()
	return Window
	
def UpdatePortraitWindow ():
	"""Updates all of the portraits."""

	Window = GemRB.GetView("PORTWIN")
	if not Window:
		return

	pc = GemRB.GameGetSelectedPCSingle ()

	PortraitButtons = GetPortraitButtons (Window)
	FitPortraitWindow (Window)
	# slots past the party (left over from a bigger one) stay hidden
	i = len (PortraitButtons)
	while Window.GetControl (PortraitID (i)):
		Window.GetControl (PortraitID (i)).SetVisible (False)
		Window.GetControl (HPButtonID (i)).SetVisible (False)
		Window.GetControl (1200 + i).SetVisible (False)
		i += 1
	for Button in PortraitButtons:
		pcID = Button.Value

		UpdatePortraitButton(Button)
		if GUICommonWindows.SelectionChangeHandler:
			Button.EnableBorder(0, pc == pcID)
		else:
			Button.EnableBorder(0, GemRB.GameIsPCSelected(pcID))

	return

def UpdateButtonAnimation(Button):
	"""Selects the correct portrait cycle depending on character state"""
	# note: there are actually two portraits per chr, eg PPPANN (static), WMPANN (animated)

	pcID = Button.Value

	state = GemRB.GetPlayerStat (pcID, IE_STATE_ID)
	hp = GemRB.GetPlayerStat (pcID, IE_HITPOINTS)
	hp_max = GemRB.GetPlayerStat (pcID, IE_MAXHITPOINTS)

	if state & STATE_DEAD:
		cycle = 9
	elif state & STATE_HELPLESS:
		cycle = 8
	elif state & STATE_PETRIFIED:
		cycle = 7
	elif state & STATE_PANIC: # frozen?
		cycle = 6
	elif state & STATE_POISONED:
		cycle = 2 # and 3
	elif hp < hp_max / 2:
		cycle = 4 # and 5
	else:
		cycle = 0 # and 1

	portrait = GemRB.GetPlayerPortrait (pcID, 0)
	pic = portrait["ResRef"]

	if cycle < 6: # a "random" animation, other cycles are not animated
		def phase2(btn):
			switch = random.randint(0, 29) == 0
			btn.SetAnimation(pic, cycle + int(switch), A_ANI_PLAYONCE)
			btn.OnAnimEnd (UpdateButtonAnimation)
		# note: the granularity of time should be
		# one of twenty values from [500, 10000]
		# but not the full range.
		duration = 500 + 500 * random.randint(0, 19);
		Button.SetAnimation([GemRB.GetSprite(pic, -1, cycle, 0)], duration, A_ANI_PLAYONCE)
		Button.OnAnimEnd (phase2)
	else:
		Button.SetAnimation(pic, cycle, A_ANI_PLAYONCE)
		Button.OnAnimEnd (None)
	return

def UpdatePortraitButton(Button):
	pcID = Button.Value
	idx = pcID - 1
	portrait = GemRB.GetPlayerPortrait (pcID, 0)
	Back = Button.Window.GetControl (1200 + idx) # scripted slots only
	if Back:
		Back.SetVisible (bool (portrait))
	if not portrait:
		Button.SetVisible(False)
		Button.SetAnimation(None)
		ButtonHP = Button.Window.GetControl (HPButtonID (idx))
		ButtonHP.SetVisible (False)
		return

	Button.SetVisible (True)

	hp = GemRB.GetPlayerStat (pcID, IE_HITPOINTS)
	hp_max = GemRB.GetPlayerStat (pcID, IE_MAXHITPOINTS)

	if hp_max < 1 or hp == "?":
		ratio = 0.0
	else:
		ratio = hp / float(hp_max)
		if ratio > 1.0: ratio = 1.0

	r = int (255 * (1.0 - ratio))
	g = int (255 * ratio)

	ButtonHP = Button.Window.GetControl (HPButtonID (idx))
	ButtonHP.SetVisible (True)
	ButtonHP.SetColor ({'r' : r, 'g' : g, 'b' : 0})
	ButtonHP.SetPictureClipping (ratio)

	if GemRB.GetVar('Health Bar Settings') & (1 << idx):
		ButtonHP.SetFlags (IE_GUI_BUTTON_PICTURE, OP_OR)
		ButtonHP.SetText ("")
	else:
		ButtonHP.SetFlags (IE_GUI_BUTTON_PICTURE, OP_NAND)
		ButtonHP.SetText ("{} / {}".format(hp, hp_max))


	UpdateButtonAnimation(Button)
	return
