# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later


# GUISAVE.py - Save game screen from GUISAVE winpack

###################################################

import GemRB
import EEUI
import GUIClasses
import LoadScreen
import GUIOPT
from GUIDefines import *

SaveWindow = None
SaveDetailWindow = None
OptionsWindow = None
Games = ()
ScrollBar = 0
CurrentPreview = None
Rows = []
Handles = {}


def OpenSaveWindow ():
	global SaveWindow, OptionsWindow, Games, ScrollBar, CurrentPreview, Rows, Handles, Selected

	# temporarily reenable the game window, so the screenshot does not get tinted darker
	GameWin = GemRB.GetView("GAMEWIN")
	GameWin.SetDisabled (False)
	CurrentPreview = GemRB.GetGamePreview ()
	GameWin.SetDisabled (True)

	if SaveWindow:
		if SaveDetailWindow: OpenSaveDetailWindow ()

		if SaveWindow:
			SaveWindow.Close ()
		SaveWindow = None
		# FIXME: LOAD GUIOPT?

		return

	if EEUI.Available ("SAVE"):
		Handles = BuildEE ()
	else:
		Handles = BuildClassic ()
	SaveWindow = Window = Handles["window"]
	Rows = Handles["rows"]
	OptionsWindow = GemRB.GetView("OPTWIN")

	# Cancel button
	CancelButton = Handles["cancel"]
	CancelButton.SetText (4196)
	CancelButton.OnPress (CancelPress)
	CancelButton.MakeEscape()
	GemRB.SetVar ("SaveIdx", 0)
	Selected = None

	if Handles.get ("save"):
		# EE: Save, Delete and New Save act on the selected row
		for key, text, handler in (("save", 28645, SaveGamePress), ("delete", 28640, DeleteGamePress),
		                           ("new", None, NewSavePress)):
			if text:
				Handles[key].SetText (text)
			Handles[key].OnPress (handler)
		for key in ("save", "delete"):
			Handles[key].SetState (IE_GUI_BUTTON_DISABLED)

	for i, row in enumerate (Rows):
		for key, text, handler in (("save", 28645, SaveGamePress), ("delete", 28640, DeleteGamePress)):
			if row.get (key):
				row[key].SetText (text)
				row[key].OnPress (handler)
				row[key].SetState (IE_GUI_BUTTON_DISABLED)
				row[key].SetVarAssoc ("SaveIdx", i)
		if row.get ("select"):
			row["select"].OnPress (lambda *args, i=i: SelectRow (i))
			row["select"].OnDoublePress (lambda *args, i=i: (SelectRow (i), SaveGamePress ()))

	ScrollBar = Handles["scrollbar"]
	ScrollBar.OnChange (ScrollBarPress)
	Window.SetEventProxy (ScrollBar)
	Games = GemRB.GetSaveGames()
	TopIndex = max (0, len(Games) - len (Rows) + 1) #one more for the 'new game'

	GemRB.SetVar ("TopIndex",TopIndex)
	ScrollBar.SetVarAssoc ("TopIndex", TopIndex)
	ScrollBarPress ()
	if Handles.get ("save"):
		# the EE screen covers the whole display, over the HUD windows
		Window.ShowModal (MODAL_SHADOW_NONE)

def BuildClassic ():
	win = GemRB.LoadWindow (0, "GUISAVE")
	h = {"window": win, "cancel": win.GetControl (46), "rows": []}
	for i in range (4):
		row = {"save": win.GetControl (14 + i), "delete": win.GetControl (18 + i),
		       "preview": win.GetControl (1 + i), "name": win.GetControl (0x10000004+i),
		       "time": win.GetControl (0x10000008 + i), "portraits": []}
		row["preview"].SetFlags (IE_GUI_BUTTON_NO_IMAGE|IE_GUI_BUTTON_PICTURE, OP_SET)
		for j in range (6):
			Button = win.GetControl (22 + i*6 + j)
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE|IE_GUI_BUTTON_PICTURE, OP_SET)
			row["portraits"].append (Button)
		h["rows"].append (row)
	h["scrollbar"] = win.GetControl (13)
	return h

ROW_PICTURES = ("LOADROWB", "LOADROWC")
Selected = None

def BuildEE ():
	win, ctl = EEUI.Build ("SAVE", skip={0, 2})
	rows, frame = EEUI.BuildRows (win, "SAVE", 2, 5, sel_pictures=ROW_PICTURES)
	x, y, w, hgt = frame
	bar = win.CreateScrollBar (0x5000, {'x': x + w - 24, 'y': y, 'w': 24, 'h': hgt}, EEUI.Alias ("CGSCRL1"))
	return {"window": win, "cancel": ctl[3], "save": ctl[4], "delete": ctl[5], "new": ctl[6],
	        "rows": rows, "scrollbar": bar}

def SelectRow (i):
	"""EE list: pick row i (highlight it, enable Save and Delete)."""
	global Selected
	Selected = i
	GemRB.SetVar ("SaveIdx", i)
	ScrollBarPress ()

def NewSavePress ():
	"""EE 'New Save': aim at the empty slot after the last save and open the name box."""
	global Selected
	Pos = len (Games)
	n = len (Rows)
	TopIndex = max (0, Pos - n + 1)
	GemRB.SetVar ("TopIndex", TopIndex)
	ScrollBar.SetVarAssoc ("TopIndex", TopIndex)
	Selected = Pos - TopIndex
	GemRB.SetVar ("SaveIdx", Selected)
	ScrollBarPress ()
	OpenSaveDetailWindow ()

def ScrollBarPress():
	# draw the saved games
	Pos = GemRB.GetVar ("TopIndex") or 0
	have = False
	deletable = False
	for i, row in enumerate (Rows):
		ActPos = Pos + i
		if ActPos < len(Games):
			Slotname = Games[ActPos].GetName ()
			Slottime = Games[ActPos].GetDate ()
			Preview = Games[ActPos].GetPreview()
			states = (True, True)
		elif ActPos == len(Games):
			Slotname = 28647 # "Empty"
			Slottime = ""
			Preview = None
			states = (True, False)
		else:
			Slotname = ""
			Slottime = ""
			Preview = None
			states = (False, False)

		for key, on in zip (("save", "delete"), states):
			if row.get (key):
				row[key].SetState (IE_GUI_BUTTON_ENABLED if on else IE_GUI_BUTTON_DISABLED)
		if row.get ("select"):
			row["select"].SetVisible (states[0])
			row["bg"].SetVisible (states[0])
			if states[0]:
				chosen = Selected == i
				row["bg"].SetBackground (ROW_PICTURES[1 if chosen else 0])
				if chosen:
					have = True
					deletable = states[1]
		for key in ("name", "time", "area", "preview"):
			if row.get (key):
				row[key].SetVisible (states[0] or not row.get ("select"))

		row["name"].SetText (Slotname)
		row["time"].SetText (Slottime)
		if row.get ("area"):
			row["area"].SetText ("")
		row["preview"].SetPicture (Preview)

		for j, Button in enumerate (row["portraits"]):
			if Button:
				Button.SetPicture (Games[ActPos].GetPortrait(j) if ActPos < len(Games) else None)
	if Handles.get ("save"):
		Handles["save"].SetState (IE_GUI_BUTTON_ENABLED if have else IE_GUI_BUTTON_DISABLED)
		Handles["delete"].SetState (IE_GUI_BUTTON_ENABLED if deletable else IE_GUI_BUTTON_DISABLED)


def SaveGamePress ():
	OpenSaveDetailWindow ()
	return

def DeleteGameConfirm():
	global Games, Selected

	Selected = None
	TopIndex = GemRB.GetVar("TopIndex")
	Pos = TopIndex +GemRB.GetVar("SaveIdx")
	GemRB.DeleteSaveGame (Games[Pos])
	del Games[Pos]
	if TopIndex>0:
		TopIndex -= 1
		GemRB.SetVar ("TopIndex", TopIndex)
	ScrollBar.SetVarAssoc("TopIndex", TopIndex, 0, max (0, len(Games) - len (Rows) + 1))
	ScrollBarPress()
	if ConfirmWindow:
		ConfirmWindow.Close ()
	SaveWindow.Focus()
	return

def DeleteGameCancel():
	global ConfirmWindow

	if ConfirmWindow:
		ConfirmWindow.Close ()
		ConfirmWindow = None
	SaveWindow.Focus()
	return

def DeleteGamePress():
	global ConfirmWindow

	if EEUI.PopupAvailable (2):
		ConfirmWindow = None
		EEUI.Popup (28639, [(4196, DeleteGameCancel, "e"), (28640, DeleteGameConfirm, "d")])
		return

	SaveWindow.SetVisible(False)
	ConfirmWindow=GemRB.LoadWindow (3, "GUISAVE")

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

	ConfirmWindow.Focus()
	return

def CancelPress():
	OpenSaveWindow ()
	return

def OpenSaveDetailWindow ():
	global SaveDetailWindow

	if SaveDetailWindow != None:
		if SaveDetailWindow:
			SaveDetailWindow.Close ()
		SaveDetailWindow = None

		return

	SaveDetailWindow = Window = GemRB.LoadWindow (1, "GUISAVE")

	Pos = GemRB.GetVar ("TopIndex") + GemRB.GetVar ("SaveIdx")


	# Save/Overwrite
	Button = Window.GetControl (4)
	if Pos < len(Games):
		Button.SetText (28644) # Overwrite
	else:
		Button.SetText (28645) # Save
	Button.OnPress (ConfirmedSaveGame)
	Button.MakeDefault()

	# Cancel
	Button = Window.GetControl (5)
	Button.SetText (4196)
	Button.OnPress (OpenSaveDetailWindow)
	Button.MakeEscape()

	# Slot name and time
	if Pos < len(Games):
		Slotname = Games[Pos].GetName ()
		Slottime = Games[Pos].GetGameDate ()
	else:
		Slotname = ""
		Slottime = ""

	Edit = Window.GetControl (1)
	Edit.SetText (Slotname)
	Edit.OnChange (CheckSaveName)
	Edit.OnDone (ConfirmedSaveGame)

	Label = Window.GetControl (0x10000002)
	Label.SetText (Slottime)


	# Areapreview
	Button = Window.GetControl (0)
	Button.SetPicture (CurrentPreview)

	# PC portraits
	from GameCheck import MAX_PARTY_SIZE
	for j in range (min (6, MAX_PARTY_SIZE)): # the chu has 6 portrait slots (controls 6-11)
		Button = Window.GetControl (6 + j)
		if Button:
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)

	CheckSaveName ()
	Window.ShowModal (MODAL_SHADOW_GRAY)
	Edit.Focus() # ShowModal will happily reset this..


# Disable Save/Overwrite button if the save slotname is empty,
# else enable it
def CheckSaveName ():
	Window = SaveDetailWindow
	Button = Window.GetControl (4)
	Edit = Window.GetControl (1)
	Name = Edit.QueryText ()

	if Name == "":
		Button.SetState (IE_GUI_BUTTON_DISABLED)
	else:
		Button.SetState (IE_GUI_BUTTON_ENABLED)



# User entered save name and pressed save/overwrite.
# Display progress bar screen and save the game, close the save windows
def ConfirmedSaveGame ():
	Window = SaveDetailWindow

	Pos = GemRB.GetVar ("TopIndex") + GemRB.GetVar ("SaveIdx")
	Label = Window.GetControl (1)
	Slotname = Label.QueryText ()

	# Empty save name. We can get here if user presses Enter key
	if Slotname == "":
		return

	# We have to close floating window first
	OpenSaveDetailWindow ()
	#FIXME: make this work
	#LoadScreen.StartLoadScreen (LoadScreen.LS_TYPE_SAVING)
	CloseSaveWindow ()
	game = None
	if Pos < len(Games):
		game = Games[Pos]
	GemRB.SaveGame (game, Slotname, -1, CurrentPreview)

def QuickSavePressed():
	GemRB.SaveGame (1, -1, GemRB.GetGamePreview ())

# Exit either back to game or to the Start window
def CloseSaveWindow ():
	OpenSaveWindow ()
	if GemRB.GetVar ("QuitAfterSave"):
		GemRB.QuitGame ()
		GemRB.SetNextScript ("Start")
		return

	GUIOPT.OpenOptionsWindow ()
