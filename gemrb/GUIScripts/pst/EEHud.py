# SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# EEHud.py - the world HUD in the EE look (EE_UI_PLAN.md phase 18, section 9.1).
#
# One 80 px strip along the bottom (EEACTBAR, cut from EE's ACTBG by tools/eeui/derived.py):
# clock and Select All / Abort / Formations at the left end (ACTWIN), the hotbar in the
# middle (TurnOrder's COMBATBAR), lock view / AI / message log and the eight menu wedges at the
# right end (OPTWIN). The party portraits are a column at the top left; while a full screen
# (inventory, record, ...) is open they move into the strip as a row, where the hotbar was.
# The dialogue window is EE's DIABG with CONVWING wings and the speaker's bestiary picture.
#
# Same window aliases and control ids as the classic CHU windows, so every caller (Clock,
# MenuWindow, PortraitWindow, Container, GUISTORE, the engine) keeps working unchanged.

import GemRB
import EEUI
from GameCheck import MAX_PARTY_SIZE
from GUIDefines import *

STRIP_Y = 640
STRIP_H = 80
LEFT_W = 104      # left cap of EEACTBAR (clock and three circles)
RIGHT_W = 168     # right cap (three circles, wedge, three circles)
MIDDLE_X = LEFT_W
MIDDLE_W = 1280 - LEFT_W - RIGHT_W

PORTRAIT_SLOT = 80   # PRTRTBG back
PORTRAIT_TOP = 8     # the column's top edge
PORT_SIZE = PORTRAIT_SLOT * MAX_PARTY_SIZE   # PORTWIN: square, a column or a row of every slot

WIN_PLATE = 0x7F00
WIN_ACT = 0x7F01
WIN_OPT = 0x7F02
WIN_PORT = 0x7F03
WIN_DLG = 0x7F04

PORT_BACK = 1200     # PortraitWindow's id for slot backs

def Active ():
	return EEUI.Available ("WORLD_ACTIONBAR_LEFT") and EEUI.Available ("BACKGROUND_DIALOG")

def _HudWindow (wid, frame):
	win = GemRB.CreateWindow (wid, EEUI.WINDOW_PACK, frame)
	win.SetFlags (WF_BORDERLESS | WF_ALPHA_CHANNEL | IE_GUI_VIEW_IGNORE_EVENTS, OP_OR)
	return win

def _Button (win, cid, frame, bam, cycle, tip=None):
	x, y, w, h = frame
	b = win.CreateButton (cid, x, y, w, h)
	# EE button cycles: 0 normal, 1 highlighted, 2 pressed, 3 disabled
	b.SetSprites (bam, cycle, 0, 2, 0, 3)
	if tip is not None:
		b.SetTooltip (tip)
	return b

def _Circle (win, cid, pos, cycle):
	"""EE's round buttons at their real size (EECIRC from tools/eeui/derived.py): normal,
	pressed, selected (a toggle's "on" picture), disabled."""
	b = win.CreateButton (cid, pos[0], pos[1], 23, 23)
	b.SetSprites ("EECIRC", cycle, 0, 1, 2, 3)
	return b

###################################################
# the strip

def OpenPlate ():
	win = _HudWindow (WIN_PLATE, {'x': 0, 'y': STRIP_Y, 'w': 1280, 'h': STRIP_H})
	win.AddAlias ("EEHUDPLATE")
	win.SetBackground ("EEACTBAR")
	return win

def OpenActionsWindow ():
	"""ACTWIN: classic ids 0 clock, 1 select all, 2 pause, 3 abort, 4 formations."""
	win = _HudWindow (WIN_ACT, {'x': 0, 'y': STRIP_Y, 'w': LEFT_W, 'h': STRIP_H})
	# the clock first: first-created controls draw on top, and it sits on the pause button
	clock = win.CreateButton (0, 5, 5, 69, 42)
	_Button (win, 2, (6, 7, 68, 70), "PAUSBUTT", 0)
	_Circle (win, 4, (79, 2), 2)
	_Circle (win, 3, (79, 28), 1)
	_Circle (win, 1, (79, 54), 0)
	return win

# OPTWIN: classic control id -> (frame in the right cap, bam, cycle)
OPTIONS = {
	10: ((4, 2, 23, 23), "EECIRC", 3),       # message log (Expand)
	0: ((4, 28, 23, 23), "EECIRC", 4),       # lock view (Follow), selected = locked
	4: ((4, 54, 23, 23), "EECIRC", 5),       # party AI, selected = on
	1: ((33, 12, 29, 27), "RADWEDGE", 0),    # inventory
	2: ((53, 4, 30, 35), "RADWEDGE", 1),     # map
	3: ((83, 4, 30, 35), "RADWEDGE", 2),     # mage spells
	9: ((104, 12, 30, 27), "RADWEDGE", 3),   # rest
	5: ((33, 41, 29, 27), "RADWEDGE", 4),    # statistics
	6: ((53, 42, 30, 34), "RADWEDGE", 5),    # journal
	7: ((83, 42, 30, 34), "RADWEDGE", 6),    # priest spells
	8: ((104, 41, 30, 27), "RADWEDGE", 7),   # options
}

def OpenOptionsWindow ():
	win = _HudWindow (WIN_OPT, {'x': 1280 - RIGHT_W, 'y': STRIP_Y, 'w': RIGHT_W, 'h': STRIP_H})
	for cid, (frame, bam, cycle) in OPTIONS.items ():
		if bam == "EECIRC":
			_Circle (win, cid, frame[:2], cycle)
		else:
			_Button (win, cid, frame, bam, cycle)
	return win

###################################################
# portraits

def OpenPortraitWindow ():
	"""PORTWIN with every slot up front (no scripted extra slots): PortraitWindow's ids,
	portrait 72x56 and hp bar 73x10 on a PRTRTBG back."""
	n = MAX_PARTY_SIZE
	win = _HudWindow (WIN_PORT, {'x': 0, 'y': PORTRAIT_TOP, 'w': PORT_SIZE, 'h': PORT_SIZE})
	import PortraitWindow
	for i in range (n):
		win.CreateButton (PortraitWindow.PortraitID (i), 0, 0, 69, 54)
		win.CreateButton (PortraitWindow.HPButtonID (i), 0, 0, 73, 15)
	for i in range (n):
		back = win.CreateButton (PORT_BACK + i, 0, 0, PORTRAIT_SLOT - 1, PORTRAIT_SLOT - 1)
		back.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
		back.SetPicture ("PRTRTBG")
		back.SetState (IE_GUI_BUTTON_LOCKED)
	LayoutPortraits (win)
	return win

_row = [False]   # portraits sit in the strip as a row while a full screen is open, else in the column

def PortraitRow ():
	return _row[0]

def LayoutPortraits (win=None, count=None):
	win = win or GemRB.GetView ("PORTWIN")
	if not win:
		return
	import PortraitWindow
	if count is None:
		count = max (1, min (GemRB.GetPartySize (), MAX_PARTY_SIZE))
	row = PortraitRow ()
	S = PORTRAIT_SLOT
	# the window keeps one size and only moves: a window resized after it first drew stops
	# drawing (its new back buffer stays blank). Its empty parts let clicks through.
	if row:
		x0 = MIDDLE_X + (MIDDLE_W - S * count) // 2
		win.SetPos (x0, STRIP_Y + STRIP_H - PORT_SIZE)
		oy = PORT_SIZE - STRIP_H
	else:
		win.SetPos (0, PORTRAIT_TOP)
		oy = 0
	for i in range (MAX_PARTY_SIZE):
		x, y = (i * S, oy) if row else (0, i * S)
		pb = win.GetControl (PortraitWindow.PortraitID (i))
		# PRTRTBG (3x art): portrait recess 72x56 at 4,2, bar hole 72x10 at 4,64
		pb.SetFrame ({'x': x + 4, 'y': y + 2, 'w': 72, 'h': 56})
		hp = win.GetControl (PortraitWindow.HPButtonID (i))
		hp.SetFrame ({'x': x + 3, 'y': y + 64, 'w': 73, 'h': 10})
		back = win.GetControl (PORT_BACK + i)
		back.SetFrame ({'x': x, 'y': y, 'w': S - 1, 'h': S - 1})

def SnapPortraits (snap):
	"""GUICommonWindows calls this when a full screen opens (snap) or closes."""
	_row[0] = bool (snap)
	top = GemRB.GetView ("WIN_TOP")
	if snap and top:
		# the strip (and the portrait row in it) goes in front of the full screen, so it stays
		# visible and clickable over the screen's plate. Never shrink the screen to end at the strip
		# instead: a window resized after it first drew shows its content shifted up.
		# The HUD windows ignore events, so the keyboard focus stays with the screen. Each call puts
		# the window right in front of the screen, below the ones raised before it: top first.
		for name in ("COMBATBAR", "PORTWIN", "ACTWIN", "OPTWIN", "EEHUDPLATE"):
			win = GemRB.GetView (name)
			if win:
				win.OrderAbove (top)
	LayoutPortraits ()
	import TurnOrder
	TurnOrder.UpdateCombatBar ()

###################################################
# dialogue

DLG_Y = 441
DLG_H = 279
PIC_FRAME = (193, 18, 160, 241)     # EEDLGPF, left of the reply panel
PIC_BUTTON = (202, 27, 142, 222)    # a 281x441 bestiary picture drawn at half size
CID_PICTURE = 0x7F10
CID_PIC_FRAME = 0x7F11

def OpenDialogWindow ():
	"""MSGWIN: classic ids 0 close (log view only), 1 the text, 0x10000003 gold."""
	win = GemRB.CreateWindow (WIN_DLG, EEUI.WINDOW_PACK, {'x': 0, 'y': DLG_Y, 'w': 1280, 'h': DLG_H})
	win.SetFlags (WF_BORDERLESS | WF_ALPHA_CHANNEL, OP_OR)

	# first created = on top: picture over its frame, everything over DIABG, DIABG over the wings
	pic = win.CreateButton (CID_PICTURE, *PIC_BUTTON)
	pic.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
	pic.SetState (IE_GUI_BUTTON_LOCKED)

	ta = win.CreateTextArea (1, 368, 31, 544, 191, EEUI.StyleFont ("normal"))

	close = _Button (win, 0, (570, 239, 128, 40), "WIDEBUTT", 0)
	close.SetFont (EEUI.StyleFont ("button"))
	close.SetColor (EEUI.StyleColor ("button"))

	gold = win.CreateLabel (0x10000003, 820, 228, 39, 41, EEUI.StyleFont ("gold"), "", IE_FONT_ALIGN_RIGHT | IE_FONT_ALIGN_MIDDLE)
	gold.SetColor (EEUI.StyleColor ("gold"))
	icon = win.CreateLabel (0x7F12, 862, 228, 51, 41, EEUI.StyleFont ("gold"), "", IE_FONT_ALIGN_CENTER)
	icon.SetBackground ("ICGOLDF")

	frame = win.CreateLabel (CID_PIC_FRAME, *PIC_FRAME, EEUI.StyleFont ("normal"), "", 0)
	frame.SetBackground ("EEDLGPF")
	plate = win.CreateLabel (0x7F13, 0, 0, 1280, DLG_H, EEUI.StyleFont ("normal"), "", 0)
	plate.SetBackground ("DIABG")
	for i, x in enumerate ((926, -984)):
		wing = win.CreateLabel (0x7F14 + i, x, 24, 1403, 255, EEUI.StyleFont ("normal"), "", 0)
		wing.SetBackground ("CONVWING")
	return win

def _BeastImages ():
	"""Bestiary picture per creature name (classic beast.ini), built once."""
	global _beastImages
	try:
		return _beastImages
	except NameError:
		pass
	_beastImages = {}
	count = int (GemRB.GetINIBeastsKey ('init', 'beastcount', '0'))
	for i in range (count):
		name = GemRB.GetINIBeastsKey (str (i), 'name', '0')
		image = GemRB.GetINIBeastsKey (str (i), 'imageKnown', '')
		if image and name and name != '0':
			_beastImages[GemRB.GetString (int (name)).strip ().lower ()] = image
	return _beastImages

_shownTarget = [None]
_dialogTimer = [False]

def DialogPicture (win):
	"""The bestiary picture of whoever talks; no picture (frame and all) when there is none."""
	target = GemRB.GetDialogTarget ()
	if target == _shownTarget[0]:
		return
	_shownTarget[0] = target
	image = None
	if target:
		for which in (0, 1, -1):
			try:
				name = GemRB.GetPlayerName (target, which)
			except RuntimeError:
				break
			image = _BeastImages ().get (name.strip ().lower ())
			if image:
				break
	pic = win.GetControl (CID_PICTURE)
	frame = win.GetControl (CID_PIC_FRAME)
	pic.SetPicture (image if image else None)
	pic.SetVisible (bool (image))
	frame.SetVisible (bool (image))

def _DialogStep ():
	_dialogTimer[0] = False
	win = GemRB.GetView ("MSGWIN")
	if not win or not (GemRB.GetGUIFlags () & (GS_DIALOGMASK | GS_DIALOG)):
		_shownTarget[0] = None
		return
	DialogPicture (win)
	StartDialogUpdates ()

def StartDialogUpdates ():
	"""The speaker can change line by line (companions interject): follow it while the dialogue runs."""
	if _dialogTimer[0]:
		return
	_dialogTimer[0] = True
	GemRB.SetTimer (_DialogStep, 200, 0)

def UpdateDialogMode (inDialog):
	"""MessageWindow.UpdateControlStatus: dialogue hides the close button and the portraits,
	the log view shows them."""
	win = GemRB.GetView ("MSGWIN")
	if win:
		win.GetControl (0).SetVisible (not inDialog)
		if inDialog:
			DialogPicture (win)
			StartDialogUpdates ()
		else:
			_shownTarget[0] = None
			win.GetControl (CID_PICTURE).SetVisible (False)
			win.GetControl (CID_PIC_FRAME).SetVisible (False)
	port = GemRB.GetView ("PORTWIN")
	if port:
		port.SetVisible (not inDialog)
