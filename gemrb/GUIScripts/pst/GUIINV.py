# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later


# GUIINV.py - scripts to control inventory windows from GUIINV winpack

###################################################

import GemRB
import GUICommon
import CommonTables
import GUICommonWindows
import InventoryCommon
import EEUI
from GUIDefines import *
from ie_stats import *
from ie_slots import *

ItemAmountWindow = None

# Control ID's:
# 0 - 9 eye, rings, earrings, tattoos, etc
# 10-13 Quick Weapon
# 14-18 Quick Item
# 19-23 Quiver
# 24-43 Personal Item
# 47-56 Ground Item

# 44      - portrait
# 45      - ground scrollbar?
# 46      - encumbrance
# 0x10000000 + 57 - name
# 0x10000000 + 58 - AC
# 0x10000000 + 59 - hp
# 0x10000000 + 60 - hp max
# 0x10000000 + 61 - msg
# 0x10000000 + 62 - party gold
# 0x10000000 + 63 - class

# The appearance and usability of inventory slots in PST
# varies from character to character and is defined
# by unhardcoded/avslots.2da
SlotMap = None


def InitInventoryWindow (Window):
	"""Opens the inventory window."""

	global AvSlotsTable

	Window.AddAlias("WIN_INV")

	AvSlotsTable = GemRB.LoadTable ('avslots')
	Window.GetControl(0x1000003d).AddAlias("MsgSys", 1)

	# Reset the ScrollBar index, since it is shared with other windows eg GUILOAD
	GemRB.SetVar("TopIndex", 0)

	# inventory slots
	SlotCount = GemRB.GetSlotType (-1)["Count"]
	for slot in range (SlotCount):
		SlotType = GemRB.GetSlotType (slot)
		if SlotType["ID"] == -1:
			continue
		Button = Window.GetControl (SlotType["ID"])
		if Button:
			Button.OnMouseEnter (InventoryCommon.MouseEnterSlot)
			Button.OnMouseLeave (InventoryCommon.MouseLeaveSlot)
			Button.SetVarAssoc ("ItemButton", slot)

			Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)
			Button.SetFont ("NUMBER")

			color = {'r' : 128, 'g' : 128, 'b' : 255, 'a' : 64}
			Button.SetBorder (0,color,0,1)
			color['r'], color['b'] = color['b'], color['r']
			Button.SetBorder (1,color,0,1)

	# Ground Item
	for i in range (10):
		Button = Window.GetControl (i+47)
		Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)
		Button.SetFont ("NUMBER")

		color = {'r' : 128, 'g' : 128, 'b' : 255, 'a' : 64}
		Button.SetBorder (0,color,0,1)
		color['r'], color['b'] = color['b'], color['r']
		Button.SetBorder (1,color,0,1)

		Button.OnMouseEnter (InventoryCommon.MouseEnterGround)
		Button.OnMouseLeave (InventoryCommon.MouseLeaveGround)

	ScrollBar = Window.GetControl (45)
	if ScrollBar:
		ScrollBar.OnChange (lambda: RefreshInventoryWindow(Window))

	# portrait
	Button = Window.GetControl (44)
	Button.SetState (IE_GUI_BUTTON_LOCKED)
	Button.SetFlags(IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
	Button.SetAction (OnAutoEquip, IE_ACT_DRAG_DROP_DST)

	# encumbrance
	Button = Window.GetControl (46)
	Button.SetState (IE_GUI_BUTTON_LOCKED)
	Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_ALIGN_BOTTOM, OP_SET)
	Button.SetFont ('NUMBER')

	# armor class
	Label = Window.GetControl (0x1000003a)
	Label.SetTooltip (4197)

	# hp current
	Label = Window.GetControl (0x1000003b)
	Label.SetTooltip (4198)

	# hp max
	Label = Window.GetControl (0x1000003c)
	Label.SetTooltip (4199)

	# info label, game paused, etc
	Label = Window.GetControl (0x1000003d)
	Label.SetColor ({'r' : 255, 'g' : 255, 'b' : 255})
	Label.SetText ("")

	return

def UpdateInventoryWindow (Window):
	"""Redraws the inventory window and resets TopIndex."""

	global SlotMap

	Window.OnClose(InventoryCommon.InventoryClosed)
	GUICommonWindows.UpdateAnimation ()

	pc = GemRB.GameGetSelectedPCSingle ()

	Container = GemRB.GetContainer (pc, 1)
	ScrollBar = Window.GetControl (45)
	Count = Container['ItemCount']
	if Count<1:
		Count=1
	if ScrollBar:
		ScrollBar.SetVarAssoc ("TopIndex", max(0, (Count - 10 + 1) // 2))
	RefreshInventoryWindow (Window)

	# PST uses unhardcoded/avslots.2da to decide which slots do what per character
	row = GemRB.GetPlayerStat (pc, IE_SPECIFIC)
	SlotMap = list(map (int, AvSlotsTable.GetValue (row, 1, GTV_STR).split( ',')))
	InventoryCommon.SlotMap = SlotMap

	# populate inventory slot controls
	for i in range (46):
		InventoryCommon.UpdateSlot (pc, i)

# EE slot name -> classic control id (the classic scripts address slots by CHU control id)
EE_SLOT_IDS = {
	"chest0": 6, "wrist0": 8, "earringleft0": 5, "earringright0": 0,
	"tattoo0": 4, "tattoo1": 1, "tattoo2": 9, "ring0": 7, "ring1": 2, "hand0": 3,
}
for _i in range (4):
	EE_SLOT_IDS["weapon%d" % _i] = 10 + _i
for _i in range (5):
	EE_SLOT_IDS["personal%d" % _i] = 14 + _i
	EE_SLOT_IDS["quiver%d" % _i] = 19 + _i
for _i in range (20):
	EE_SLOT_IDS["group%d" % _i] = 24 + _i
for _i in range (10):
	EE_SLOT_IDS["ground%d" % _i] = 47 + _i

# EE label/text index -> classic label id
EE_LABEL_IDS = {4: 0x10000039, 9: 0x1000003a, 11: 0x1000003b, 12: 0x1000003c, 13: 0x1000003d, 6: 0x1000003e, 7: 0x1000003f}

def LoadInventoryWindow (id, pack, pos, loader):
	"""Window loader: the EE inventory layout when it exists, the CHU window otherwise."""
	if not EEUI.Available ("INVENTORY"):
		return loader (id, pack, pos)
	if GemRB.GetView (pack, id):
		return loader (id, pack, pos)   # focus or toggle the open one
	if loader is GUICommonWindows.ToggleWindow and GemRB.GetView ("WIN_STORE"):
		return None
	ids = {0: 44}
	skip = set ()
	for c in EEUI.Controls ("INVENTORY"):
		if c["type"] == "slot":
			key = c.get ("slotinfo", "").replace ("characters[id].equipment.", "")
			if key in EE_SLOT_IDS:
				ids[c["index"]] = EE_SLOT_IDS[key]
			else:
				skip.add (c["index"])   # EE slots PST has no equivalent for
		elif c["index"] in EE_LABEL_IDS:
			ids[c["index"]] = EE_LABEL_IDS[c["index"]]
		elif c["index"] in (2, 3):
			skip.add (c["index"])       # encumbrance numbers, drawn by one button
	arrows = []
	for c in EEUI.Controls ("INVENTORY"):
		if c["type"] == "button" and c.get ("bam") == "ARROBUTT":
			skip.add (c["index"])
			arrows.append (c)

	def MakeArrows (win):
		# made first so they are drawn over the group slots that share their corner
		for c in arrows:
			x, y, w, h = c["frame"]
			b = win.CreateButton (0x4000 + c["index"], x, y, w, h)
			b.SetSprites (c["bam"], c.get ("sequence", 0), 0, 2, 0, 3)
			step = -10 if c.get ("sequence") == 0 else 10
			b.OnPress (lambda step=step: GroundPage (win, step))

	win, ctl = EEUI.Build ("INVENTORY", ids=ids, skip=skip, first=MakeArrows)
	win.AddAlias (pack, id)
	# encumbrance: one two-line button over EE's two labels
	enc = win.CreateButton (46, 534, 548, 50, 92)
	enc.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	enc.SetFont (EEUI.StyleFont ("normal"))
	for c in EEUI.Controls ("INVENTORY"):
		if c["type"] == "button" and c.get ("bam") == "XBUTT":
			ctl[c["index"]].OnPress (win.Close)
			ctl[c["index"]].MakeEscape ()
	return win

def GroundPage (Window, step):
	pc = GemRB.GameGetSelectedPCSingle ()
	count = GemRB.GetContainer (pc, 1)['ItemCount']
	top = GemRB.GetVar ("TopIndex") + step
	GemRB.SetVar ("TopIndex", max (0, min (top, max (0, count - 1) // 10 * 10)))
	RefreshInventoryWindow (Window)

ToggleInventoryWindow = GUICommonWindows.CreateTopWinLoader(3, "GUIINV", lambda i, p, pos: LoadInventoryWindow (i, p, pos, GUICommonWindows.ToggleWindow), InitInventoryWindow, UpdateInventoryWindow)
OpenInventoryWindow = GUICommonWindows.CreateTopWinLoader(3, "GUIINV", lambda i, p, pos: LoadInventoryWindow (i, p, pos, GUICommonWindows.OpenWindowOnce), InitInventoryWindow, UpdateInventoryWindow)

def RefreshInventoryWindow (Window):
	"""Partial redraw without resetting TopIndex."""

	pc = GemRB.GameGetSelectedPCSingle ()

	# name
	Label = Window.GetControl (0x10000039)
	Label.SetText (GemRB.GetPlayerName (pc, 1))

	# portrait
	Button = Window.GetControl (44)
	Button.SetPicture (GUICommonWindows.GetActorPortrait (pc, 'INVENTORY'))

	InventoryCommon.SetEncumbranceLabels (Window, 46, None, pc)

	# armor class
	ac = GemRB.GetPlayerStat (pc, IE_ARMORCLASS)
	Label = Window.GetControl (0x1000003a)
	Label.SetText (str (ac))

	# hp current
	hp = GemRB.GetPlayerStat (pc, IE_HITPOINTS)
	Label = Window.GetControl (0x1000003b)
	Label.SetText (str (hp))

	# hp max
	hpmax = GemRB.GetPlayerStat (pc, IE_MAXHITPOINTS)
	Label = Window.GetControl (0x1000003c)
	Label.SetText (str (hpmax))

	# party gold
	Label = Window.GetControl (0x1000003e)
	Label.SetText (str (GemRB.GameGetPartyGold ()))

	# class
	text = CommonTables.ClassText.GetValue (GUICommon.GetClassRowName (pc), "LOWER")

	Label = Window.GetControl (0x1000003f)
	Label.SetText (text)

	GUICommon.AdjustWindowVisibility (Window, pc, False)

	# update ground inventory slots
	TopIndex = GemRB.GetVar ("TopIndex")
	for i in range (10):
		Button = Window.GetControl (i+47)
		Slot = GemRB.GetContainerItem (pc, i+TopIndex)
		if GemRB.IsDraggingItem ():
			Button.SetState (IE_GUI_BUTTON_FAKEPRESSED)
		elif not Slot:
			Button.SetState (IE_GUI_BUTTON_LOCKED)
		else:
			Button.SetState (IE_GUI_BUTTON_ENABLED)
		Button.SetAction (InventoryCommon.OnDragItemGround, IE_ACT_DRAG_DROP_DST)

		if Slot != None:
			item = GemRB.GetItem (Slot['ItemResRef'])
			identified = Slot["Flags"] & IE_INV_ITEM_IDENTIFIED

			Button.SetItemIcon (Slot['ItemResRef'])
			Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_OR)
			if item['MaxStackAmount'] > 1:
				Button.SetText (str (Slot['Usages0']))
			else:
				Button.SetText ('')
			if not identified or item["ItemNameIdentified"] == -1:
				Button.SetTooltip (item["ItemName"])
				Button.EnableBorder (0, 1)
			else:
				Button.SetTooltip (item["ItemNameIdentified"])
				Button.EnableBorder (0, 0)
			
			Button.SetValue (i + TopIndex)
			Button.SetAction(InventoryCommon.OnDragItemGround, IE_ACT_DRAG_DROP_CRT)
			Button.OnPress (InventoryCommon.OnDragItemGround)
			Button.OnRightPress (InventoryCommon.OpenGroundItemInfoWindow)
			Button.OnShiftPress (InventoryCommon.OpenGroundItemAmountWindow)
			Button.OnDoublePress (InventoryCommon.OpenGroundItemAmountWindow)
		else:
			Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_NAND)
			Button.SetTooltip (4273)
			Button.SetText ('')
			Button.EnableBorder (0, 0)
			Button.OnPress (None)
			Button.OnRightPress (None)
			Button.OnShiftPress (None)
			Button.OnDoublePress (None)
	return

def OnAutoEquip (btn):
	if not GemRB.IsDraggingItem ():
		return

	pc = GemRB.GameGetSelectedPCSingle ()

	item = GemRB.GetSlotItem (0,0)
	ret = GemRB.DropDraggedItem (pc, -1)
	#this is exactly the same hack as the blackisle guys did it
	#quite lame, but we should copy their efforts the best
	if ret == 2 and item and (item['ItemResRef'] == "DUSTROBE"):
		GemRB.SetGlobal("APPEARANCE","GLOBAL",2)

	UpdateInventoryWindow (btn.Window)
	return

###################################################
# End of file GUIINV.py
