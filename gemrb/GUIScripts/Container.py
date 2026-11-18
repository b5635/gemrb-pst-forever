# SPDX-FileCopyrightText: 2021 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

import GemRB
import GameCheck
import GUICommon
import InventoryCommon
from CommonWindow import SetGameGUIHidden, IsGameGUIHidden
from ie_stats import *
from GUIDefines import *
if GameCheck.IsPST ():
	import EEUI
else:
	EEUI = None

HideOnClose = False
ContainerWindow = None
Container = None
if GameCheck.IsIWD2():
	leftdiv = 5
	ground_size = 10
else:
	leftdiv = 3
	ground_size = 6
personal_size = 4   # inventory buttons shown
rightdiv = 2        # inventory buttons per row (the strip scrolls by rows)
EEContainer = False

def UpdateContainerWindow ():
	global Container

	Window = ContainerWindow

	pc = GemRB.GameGetFirstSelectedPC ()
	if GameCheck.IsPST():
		InventoryCommon.SetEncumbranceLabels (Window, 54, None, pc)
	else:
		InventoryCommon.SetEncumbranceLabels (Window, 0x10000045, 0x10000046, pc)

	party_gold = GemRB.GameGetPartyGold ()
	Text = Window.GetControl (0x10000036)
	Text.SetText (str (party_gold))

	Container = GemRB.GetContainer (0) #will use first selected pc anyway
	LeftCount = Container['ItemCount']
	ScrollBar = Window.GetControl (52)
	Count = max (0, (LeftCount - ground_size + leftdiv - 1) // leftdiv)
	ScrollBar.SetVarAssoc ("LeftTopIndex", GemRB.GetVar ("LeftTopIndex"), 0, Count)

	inventory_slots = GemRB.GetSlots (pc, 0x8000)
	RightCount = len(inventory_slots)
	ScrollBar = Window.GetControl (53)
	Count = max (0, (RightCount - personal_size + rightdiv - 1) // rightdiv)
	ScrollBar.SetVarAssoc ("RightTopIndex", GemRB.GetVar ("RightTopIndex"), 0, Count)

	RedrawContainerWindow ()

def RedrawContainerWindow ():
	Window = ContainerWindow

	# scroll in multiples of the number of columns
	LeftTopIndex = GemRB.GetVar ("LeftTopIndex") * leftdiv
	RightTopIndex = GemRB.GetVar ("RightTopIndex") * rightdiv
	pc = GemRB.GameGetFirstSelectedPC ()
	inventory_slots = GemRB.GetSlots (pc, 0x8000)
	RightCount = len(inventory_slots)

	for i in range (ground_size):
		#this is an autoselected container, but we could use PC too
		Slot = GemRB.GetContainerItem (0, i+LeftTopIndex)
		Button = Window.GetControl (i)
		if Slot:
			Button.SetVarAssoc ("LeftIndex", LeftTopIndex+i)
			callback = TakeItemContainer
		else:
			Button.SetVarAssoc ("LeftIndex", None)
			callback = None
		if GameCheck.IsPST():
			SetItemButton (Window, Button, Slot, callback, None)
		else:
			InventoryCommon.UpdateInventorySlot (pc, Button, Slot, "container")

	for i in range (personal_size):
		if i+RightTopIndex < RightCount:
			Slot = GemRB.GetSlotItem (pc, inventory_slots[i+RightTopIndex])
		else:
			Slot = None
		Button = Window.GetControl (i+10)

		#pst had a redundant call here, reenable if it turns out it isn't redundant:
		#SetItemButton (Window, Button, Slot, None, None)

		if Slot:
			Button.SetVarAssoc ("RightIndex", RightTopIndex+i)
			callback = DropItemContainer
		else:
			Button.SetVarAssoc ("RightIndex", None)
			callback = None
		if GameCheck.IsPST():
			SetItemButton (Window, Button, Slot, callback, None)
		else:
			InventoryCommon.UpdateInventorySlot (pc, Button, Slot, "inventory")

	# shade the inventory icon if it is full
	Button = Window.GetControl (54)
	if Button:
		free_slots = GemRB.GetSlots (pc, 0x8000, -1)
		if free_slots == ():
			Button.SetState (IE_GUI_BUTTON_PRESSED)
		else:
			Button.SetState (IE_GUI_BUTTON_LOCKED)

def BuildEEContainer ():
	"""EE's WORLD_CONTAINER strip with the classic ids: ground slots 0-9, inventory slots 10-29,
	scroll bars 52 / 53 (hidden: EE scrolls the ground list with its two arrows), container icon 50,
	Done 51, encumbrance 54, gold label 0x10000036."""
	ids = {41: 51, 38: 0x10000036}
	skip = {13, 14, 15, 16, 17}
	for i in range (10):
		ids[3 + i] = i
	for i in range (20):
		ids[18 + i] = 10 + i
	win, ctl = EEUI.Build ("WORLD_CONTAINER", ids = ids, skip = skip, bar = (642, 78), reverse = True)
	oy = 642
	for c in EEUI.Controls ("WORLD_CONTAINER"):
		if c["index"] in (13, 14):
			x, y, w, h = c["frame"]
			b = win.CreateButton (0x4000 + c["index"], x, y - oy, w, h)
			b.SetSprites (c["bam"], c.get ("sequence", 0), 0, 2, 0, 3)
			step = -1 if c["index"] == 13 else 1
			b.OnPress (lambda step = step: ScrollGround (step))
	# the classic code writes to these
	for cid in (52, 53):
		win.CreateScrollBar (cid, {'x': 0, 'y': 0, 'w': 1, 'h': 1}, EEUI.Alias ("CGSCRL1")).SetVisible (False)
	win.CreateButton (50, 0, 0, 1, 1).SetVisible (False)
	enc = win.CreateButton (54, 498, 657 - oy, 52, 56)
	enc.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	enc.SetFont ("NUMBER")
	return win

def ScrollGround (step):
	"""EE's arrows: move the ground list by one row."""
	top = GemRB.GetVar ("LeftTopIndex") or 0
	count = max (0, (Container['ItemCount'] - ground_size + leftdiv - 1) // leftdiv)
	GemRB.SetVar ("LeftTopIndex", max (0, min (top + step, count)))
	RedrawContainerWindow ()

def OpenContainerWindow ():
	global ContainerWindow, Container

	if ContainerWindow:
		return

	global HideOnClose
	HideOnClose = IsGameGUIHidden()

	if HideOnClose:
		SetGameGUIHidden(False)
		# must use a timed event because SetGameGUIHidden(False) sets a flag to unhide the gui next frame
		# AFIK not needed, commented out in case it turns out there are conditions we will need it
		# GemRB.SetTimedEvent (lambda: GemRB.GetView ("MSGWIN").SetVisible(False), 1)
	elif not GameCheck.IsPST ():
		GemRB.GetView ("MSGWIN").SetVisible (False)
		ActWin = GemRB.GetView ("ACTWIN")
		if ActWin:
			ActWin.SetVisible (False)

	global ground_size, leftdiv, personal_size, rightdiv, EEContainer
	EEContainer = EEUI is not None and EEUI.Available ("WORLD_CONTAINER")
	if EEContainer:
		ContainerWindow = Window = BuildEEContainer ()
		ground_size, leftdiv, personal_size, rightdiv = 10, 5, 20, 10
		# the EE strip takes the party bar's place; the portraits come back when it closes
		PortraitWindow = GemRB.GetView ("PORTWIN")
		if PortraitWindow:
			PortraitWindow.SetVisible (False)
	else:
		ground_size, leftdiv = (10, 5) if GameCheck.IsIWD2 () else (6, 3)
		personal_size, rightdiv = 4, 2
		ContainerWindow = Window = GemRB.LoadWindow (8, GUICommon.GetWindowPack(), WINDOW_BOTTOM|WINDOW_HCENTER)
	ContainerWindow.SetEventProxy(GUICommon.GameControl)

	# fix wrong height in the guiw10.chu and reposition
	# that chu is also used as a base for some arbitrary resolutions
	if GameCheck.IsBG2 () and GemRB.GetSystemVariable (SV_HEIGHT) >= 768:
		Size = Window.GetSize ()
		Pos = Window.GetPos ()
		Window.SetSize (Size[0], 90)
		Window.SetPos (Pos[0], GemRB.GetSystemVariable (SV_HEIGHT) - 90)

	if not GameCheck.IsIWD2 () and not GameCheck.IsGemRBDemo () and not GameCheck.IsPST ():
		# container window shouldnt be in front
		GemRB.GetView("OPTWIN").Focus()
		GemRB.GetView("PORTWIN").Focus()

	Container = GemRB.GetContainer(0)

	# Gears (time) when options pane is down
	if GameCheck.IsBG2OrEE ():
		import Clock
		Clock.CreateClockButton(Window.GetControl (62))

	# 0-5 - Ground Item
	for i in range (ground_size):
		Button = Window.GetControl (i)
		Button.SetVarAssoc ("LeftIndex", i)
		Button.OnPress (TakeItemContainer)
		if GameCheck.IsPST():
			Button.SetFont ("NUMBER")
			Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)

	# 10-13 - Personal Item
	for i in range (personal_size):
		Button = Window.GetControl (i+10)
		Button.SetVarAssoc ("RightIndex", i)
		Button.OnPress (DropItemContainer)
		if GameCheck.IsPST():
			Button.SetFont ("NUMBER")
			Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)

	# left scrollbar (container)
	ScrollBar = Window.GetControl (52)
	ScrollBar.SetVisible(True) # unhide because in PST it is linked to a TextArea
	ScrollBar.OnChange (RedrawContainerWindow)

	# right scrollbar (inventory)
	ScrollBar = Window.GetControl (53)
	ScrollBar.SetVisible(True) # unhide because in PST it is linked to a TextArea
	ScrollBar.OnChange (RedrawContainerWindow)

	# encumbrance and inventory icon
	# iwd has a handy button
	Button = Window.GetControl (54)
	if Button:
		if GameCheck.IsPST():
			Button.SetFont ("NUMBER")
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
		Button.CreateLabel (0x10000045, "NUMBER", "", IE_FONT_ALIGN_LEFT|IE_FONT_ALIGN_TOP|IE_FONT_SINGLE_LINE)
		Button.CreateLabel (0x10000046, "NUMBER", "", IE_FONT_ALIGN_RIGHT|IE_FONT_ALIGN_BOTTOM|IE_FONT_SINGLE_LINE)
	else:
		Window.CreateLabel (0x10000045, 323, 14, 60, 15, "NUMBER", "0:", IE_FONT_ALIGN_LEFT|IE_FONT_ALIGN_TOP|IE_FONT_SINGLE_LINE)
		Window.CreateLabel (0x10000046, 323, 20, 80, 15, "NUMBER", "0:", IE_FONT_ALIGN_RIGHT|IE_FONT_ALIGN_TOP|IE_FONT_SINGLE_LINE)

	# container icon
	Button = Window.GetControl (50)
	if GameCheck.IsPST():
		Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	Button.SetState (IE_GUI_BUTTON_LOCKED)

	if not GameCheck.IsPST():
		Table = GemRB.LoadTable ("containr", False, True)
		row = Container['Type']
		rowName = Table.GetRowName (row)
		tmp = Table.GetValue (rowName, "SOUND")
		if tmp!='*':
			GemRB.PlaySound (tmp)
		tmp = Table.GetValue (rowName, "BAM")
		if tmp!='*':
			Button.SetSprites (tmp, 0, 0, 0, 0, 0 )

	# Done
	Button = Window.GetControl (51)
	if GameCheck.IsPST():
		Button.SetText (1403)
	else:
		Button.SetText ("")

	Button.MakeEscape()
	Button.OnPress (LeaveContainer)

	GemRB.SetVar ("LeftTopIndex", 0)
	GemRB.SetVar ("RightTopIndex", 0)
	UpdateContainerWindow ()

def CloseContainerWindow ():
	global ContainerWindow

	if not ContainerWindow:
		return

	ContainerWindow.Close ()
	ContainerWindow = None
	if EEContainer:
		PortraitWindow = GemRB.GetView ("PORTWIN")
		if PortraitWindow:
			PortraitWindow.SetVisible (True)
	if not GameCheck.IsPST ():
		GemRB.GetView ("MSGWIN").SetVisible (True)
		if GemRB.GetView ("ACTWIN"):
			GemRB.GetView ("ACTWIN").SetVisible (True)
	SetGameGUIHidden(HideOnClose)

	Table = GemRB.LoadTable ("containr")
	row = Container['Type']
	rowName = Table.GetRowName (row)
	tmp = Table.GetValue (rowName, "CLOSE")
	#play closing sound if applicable
	if tmp!='*':
		GemRB.PlaySound (tmp)

#doing this way it will inform the core system too, which in turn will call
#CloseContainerWindow ()
def LeaveContainer ():
	GemRB.LeaveContainer()

def DropItemContainer ():
	RightIndex = GemRB.GetVar ("RightIndex")
	if RightIndex is None:
		return

	#we need to get the right slot number
	pc = GemRB.GameGetFirstSelectedPC ()
	inventory_slots = GemRB.GetSlots (pc, 0x8000)
	if RightIndex >= len(inventory_slots):
		return

	GemRB.ChangeContainerItem (0, inventory_slots[RightIndex], 0)
	UpdateContainerWindow ()

def TakeItemContainer ():
	LeftIndex = GemRB.GetVar ("LeftIndex")
	if LeftIndex is None:
		return

	if LeftIndex >= Container['ItemCount']:
		return

	GemRB.ChangeContainerItem (0, LeftIndex, 1)
	UpdateContainerWindow ()

# pst container override (maybe recheck if UpdateInventorySlot could handle it)
def SetItemButton (Window, Button, Slot, PressHandler, RightPressHandler):
	if Slot != None:
		Item = GemRB.GetItem (Slot['ItemResRef'])
		identified = Slot['Flags'] & IE_INV_ITEM_IDENTIFIED
		Button.SetItemIcon (Slot['ItemResRef'],0)

		if Item['MaxStackAmount'] > 1:
			Button.SetText (str (Slot['Usages0']))
		else:
			Button.SetText ('')

		if not identified or Item['ItemNameIdentified'] == -1:
			Button.SetTooltip (Item['ItemName'])
		else:
			Button.SetTooltip (Item['ItemNameIdentified'])

		Button.OnPress (PressHandler)
		Button.OnRightPress (RightPressHandler)
	else:
		Button.SetItemIcon ('')
		Button.SetTooltip (4273) # Ground Item
		Button.SetText ('')
		Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_NAND)

		Button.OnPress (None)
		Button.OnRightPress (None)
