# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# GUILOAD.py - Load game window from GUILOAD winpack

###################################################

import GemRB
import EEUI
import GUICommon
import LoadScreen
from GameCheck import MAX_PARTY_SIZE
from GUIDefines import *

LoadWindow = 0
TextAreaControl = 0
Games = ()
ScrollBar = 0

def BuildClassic ():
	win = GemRB.LoadWindow (0, "GUILOAD")
	h = {"window": win, "cancel": win.GetControl (46), "load": None, "delete": None, "rows": []}
	for i in range (4):
		row = {"load": win.GetControl (14+i), "delete": win.GetControl (18+i), "select": None,
		       "preview": win.GetControl (1+i), "name": win.GetControl (0x10000004+i),
		       "time": win.GetControl (0x10000008+i), "area": None, "portraits": []}
		row["preview"].SetState (IE_GUI_BUTTON_LOCKED)
		row["preview"].SetFlags (IE_GUI_BUTTON_NO_IMAGE|IE_GUI_BUTTON_PICTURE,OP_SET)
		for j in range (min(6, MAX_PARTY_SIZE)):
			Button = win.GetControl (22+i*min(6, MAX_PARTY_SIZE)+j)
			if Button:
				Button.SetState (IE_GUI_BUTTON_LOCKED)
				Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE|IE_GUI_BUTTON_PICTURE,OP_SET)
			row["portraits"].append (Button)
		h["rows"].append (row)
	h["scrollbar"] = win.GetControl (13)
	return h

ROW_PICTURES = ("LOADROWB", "LOADROWC")

def BuildEE ():
	skip = {0, 2}   # EE's "click outside the list to deselect" backdrop button, and the list itself
	win, ctl = EEUI.Build ("LOAD", skip=skip)
	rows, frame = EEUI.BuildRows (win, "LOAD", 2, 5, sel_pictures=ROW_PICTURES)
	x, y, w, hgt = frame
	bar = win.CreateScrollBar (0x5000, {'x': x + w - 24, 'y': y, 'w': 24, 'h': hgt}, EEUI.Alias ("CGSCRL1"))
	return {"window": win, "cancel": ctl[3], "delete": ctl[4], "load": ctl[5], "rows": rows,
	        "scrollbar": bar}

def OnLoad ():
	global LoadWindow, TextAreaControl, Games, ScrollBar, Rows, Handles

	if EEUI.Available ("LOAD"):
		Handles = BuildEE ()
	else:
		Handles = BuildClassic ()
	LoadWindow = Handles["window"]
	Rows = Handles["rows"]
	CancelButton = Handles["cancel"]
	CancelButton.SetText (4196)
	CancelButton.OnPress (LoadWindow.Close)
	CancelButton.MakeEscape()

	GemRB.SetVar ("LoadIdx",0)
	if Handles["load"]:
		# EE: one Load and one Delete button act on the selected row
		for key, text, handler in (("load", 28648, LoadGamePress), ("delete", 28640, DeleteGamePress)):
			Handles[key].SetText (text)
			Handles[key].OnPress (handler)
			Handles[key].SetState (IE_GUI_BUTTON_DISABLED)

	for i, row in enumerate (Rows):
		for key, text, handler in (("load", 28648, LoadGamePress), ("delete", 28640, DeleteGamePress)):
			if row.get (key):
				row[key].SetText (text)
				row[key].OnPress (handler)
				row[key].SetState (IE_GUI_BUTTON_DISABLED)
				row[key].SetVarAssoc ("LoadIdx",i)
		if row.get ("select"):
			row["select"].OnPress (lambda *args, i=i: SelectRow (i))
			row["select"].OnDoublePress (lambda *args, i=i: (SelectRow (i), LoadGamePress ()))

	ScrollBar = Handles["scrollbar"]
	ScrollBar.OnChange (ScrollBarPress)
	GUICommon.SetSaveDir ()
	Games=GemRB.GetSaveGames () #count of games in save folder?
	n = len (Rows)
	if len(Games)>n-1:
		TopIndex = len(Games)-n
	else:
		TopIndex = 0
	GemRB.SetVar ("TopIndex",TopIndex)
	ScrollBar.SetVarAssoc ("TopIndex", TopIndex, 0, TopIndex)
	ScrollBarPress ()

	LoadWindow.SetEventProxy(ScrollBar)
	LoadWindow.Focus()
	return

Selected = None

def SelectRow (i):
	"""EE list: pick row i (highlight it, enable the Load and Delete buttons)."""
	global Selected
	Selected = i
	GemRB.SetVar ("LoadIdx", i)
	ScrollBarPress ()

def ScrollBarPress ():
	#draw load game portraits
	Pos = GemRB.GetVar ("TopIndex") or 0
	have = False
	for i, row in enumerate (Rows):
		ActPos = Pos + i
		valid = ActPos<len(Games)

		for key in ("load", "delete"):
			if row.get (key):
				row[key].SetState (IE_GUI_BUTTON_ENABLED if valid else IE_GUI_BUTTON_DISABLED)
		if row.get ("select"):
			row["select"].SetVisible (valid)
			row["bg"].SetVisible (valid)
			if valid:
				chosen = Selected == i
				row["bg"].SetBackground (ROW_PICTURES[1 if chosen else 0])
				have = have or chosen
		for key in ("name", "time", "area", "preview"):
			if row.get (key):
				row[key].SetVisible (valid or not row.get ("select"))

		row["name"].SetText (Games[ActPos].GetName() if valid else "")
		row["time"].SetText (Games[ActPos].GetDate() if valid else "")
		if row.get ("area"):
			row["area"].SetText ("")
		row["preview"].SetPicture (Games[ActPos].GetPreview() if valid else None)
		for j, Button in enumerate (row["portraits"]):
			if Button:
				Button.SetPicture (Games[ActPos].GetPortrait(j) if valid else None)
	if Handles["load"]:
		for key in ("load", "delete"):
			Handles[key].SetState (IE_GUI_BUTTON_ENABLED if have else IE_GUI_BUTTON_DISABLED)
	return

def LoadGamePress ():
	if LoadWindow:
		LoadWindow.Close ()
	Pos = GemRB.GetVar ("TopIndex")+GemRB.GetVar ("LoadIdx")
	LoadScreen.StartLoadScreen ()
	GemRB.LoadGame(Games[Pos]) # load & start game
	GemRB.EnterGame ()
	return

def DeleteGameConfirm ():
	global Games

	global Selected
	TopIndex = GemRB.GetVar ("TopIndex")
	Pos = TopIndex +GemRB.GetVar ("LoadIdx")
	GemRB.DeleteSaveGame(Games[Pos])
	del Games[Pos]
	Selected = None
	if TopIndex>0:
		TopIndex = TopIndex - 1
	ScrollBar.SetVarAssoc ("TopIndex", TopIndex, 0, max(0, len(Games) - len(Rows)))
	ScrollBarPress ()
	if ConfirmWindow:
		ConfirmWindow.Close ()
	LoadWindow.Focus()
	return

def DeleteGameCancel ():
	if ConfirmWindow:
		ConfirmWindow.Close ()
	LoadWindow.Focus()
	return

def DeleteGamePress ():
	global ConfirmWindow

	if EEUI.PopupAvailable (2):
		ConfirmWindow = None
		EEUI.Popup (28639, [(4196, DeleteGameCancel, "e"), (28640, DeleteGameConfirm, "d")])
		return

	ConfirmWindow=GemRB.LoadWindow (1, "GUILOAD")
	ConfirmWindow.SetFlags (WF_ALPHA_CHANNEL, OP_OR)

	Text=ConfirmWindow.GetControl (0)
	Text.SetText (28639)

	DeleteButton=ConfirmWindow.GetControl (1)
	DeleteButton.SetText (28640)
	DeleteButton.OnPress (DeleteGameConfirm)
	DeleteButton.MakeDefault()

	CancelButton=ConfirmWindow.GetControl (2)
	CancelButton.SetText (4196)
	CancelButton.OnPress (DeleteGameCancel)
	CancelButton.MakeEscape()
	ConfirmWindow.ShowModal (MODAL_SHADOW_GRAY)
	return
