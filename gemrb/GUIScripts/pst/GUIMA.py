# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later


# GUIMA.py - scripts to control map windows from GUIMA and GUIWMAP winpacks

###################################################

import GemRB
import GUICommon
import GUICommonWindows
import GUIMACommon
import EEUI
from GUIDefines import *

WorldMapControl = None

###################################################
def InitMapWindow (Window):
	Window.AddAlias("WIN_MAP")

	# World Map
	Button = Window.GetControl (0)
	Button.SetText (20429)
	Button.OnPress (lambda: OpenTravelWindow(None))

	# Add Note
	Button = Window.GetControl (1)
	Button.SetText (4182)
	Button.SetVarAssoc ("ShowMapNotes", IE_GUI_MAP_SET_NOTE)

	# Note text
	Edit = Window.GetControl (4)
	Edit.OnDone (NoteChanged)
	Edit.SetFlags(IE_GUI_VIEW_IGNORE_EVENTS, OP_OR)

	# Map Control
	# ronote and usernote are the pins for the notes
	Map = Window.ReplaceSubview(3, IE_GUI_MAP, Edit)
	Map.AddAlias("MAP")

	Map.SetVarAssoc ("ShowMapNotes", IE_GUI_MAP_VIEW_NOTES)
	Map.SetStatus (IE_GUI_MAP_VIEW_NOTES)

	Map.OnPress (SetMapNote)
	Map.SetAction(Window.Close, IE_ACT_MOUSE_PRESS, GEM_MB_ACTION, 0, 2)

	MapTable = GemRB.LoadTable( "MAPNAME" )
	MapName = MapTable.GetValue (GemRB.GetCurrentArea (), "STRING")
	
	Label = Window.GetControl (0x10000005)
	Label.SetText (MapName)
	#Label.SetColor (255, 0, 0)
	# 2 - map name?
	# 3 - map bitmap?
	# 4 - ???

	# these overlap the map. lets move them to be children of the map
	Label = Window.ReparentSubview(Label, Map)
	Edit = Window.ReparentSubview(Edit, Map)

	# Done
	Button = Window.GetControl (5)
	Button.SetText (1403)
	Button.OnPress (Window.Close)
	Button.MakeEscape()

	return

def OpenTravelWindow (Travel):
	global WorldMapControl

	color = {'r' : 30, 'g' : 8, 'b' : 0, 'a' : 0xff}
	if EEUI.Available ("WORLD_MAP"):
		# EE's WORLD_MAP popup; its map control is made here, and Travel is by clicking an area
		skip = set ()
		mapFrame = None
		for c in EEUI.Controls ("WORLD_MAP"):
			if c["type"] == "map":
				skip.add (c["index"])
				mapFrame = c["frame"]
			elif c["type"] == "button" and c.get ("text", {}).get ("ee_strref") == 106605:
				skip.add (c["index"])      # the Travel button: the classic screen travels on click
		Window, ctl = EEUI.Build ("WORLD_MAP", skip=skip)
		Window.AddAlias ("WIN_PSTWMAP")
		x, y, w, h = mapFrame
		WorldMapControl = WMap = Window.CreateWorldMapControl (0x10, x - EEUI._origin[0], y - EEUI._origin[1], w, h, "FONTDLG", "WMPTY", color, color, color)
		WMap.SetVarAssoc ("Travel", Travel)
		WMap.Scroll (0,0)
		WMap.Focus()
		if Travel is not None:
			WMap.OnPress (GUIMACommon.MoveToNewArea)
		for c in EEUI.Controls ("WORLD_MAP"):
			if c["type"] == "button" and c.get ("bam") == "XBUTT":
				ctl[c["index"]].OnPress (Window.Close)
				ctl[c["index"]].MakeEscape ()
		Window.ShowModal (MODAL_SHADOW_GRAY)
		return

	Window = GemRB.LoadWindow (0, "GUIWMAP")
	Window.AddAlias ("WIN_PSTWMAP")

	WorldMapControl = WMap = Window.ReplaceSubview (4, IE_GUI_WORLDMAP, "FONTDLG", "WMPTY", color, color, color)
	WMap.SetVarAssoc ("Travel", Travel)
	#center on current area
	WMap.Scroll (0,0)
	WMap.Focus()
	if Travel is not None:
		WMap.OnPress (GUIMACommon.MoveToNewArea)

	# Done
	Button = Window.GetControl (0)
	Button.SetText (1403)
	Button.OnPress (Window.Close)

_eeBuilt = [False]

def LoadAreaMapWindow (id, pack, pos, loader):
	"""Window loader: the EE area map when its layout exists, the CHU window otherwise. Notes (EE's
	Add Note button and its template) are not in the EE window: a text edit can't be made from script."""
	if not EEUI.Available ("AREA_MAP"):
		return loader (id, pack, pos)
	if GemRB.GetView (pack, id):
		return loader (id, pack, pos)   # focus or toggle the open one
	if loader is GUICommonWindows.ToggleWindow and GemRB.GetView ("WIN_STORE"):
		return None

	target = None
	skip = set ()
	for c in EEUI.Controls ("AREA_MAP"):
		if c["index"] in (4, 5, 6, 7) or c["type"] == "template":
			skip.add (c["index"])
		elif c["type"] == "button" and c.get ("text", {}).get ("strref") == 4182:
			skip.add (c["index"])       # Add Note
		elif c.get ("name") == "AREA_MAP_TARGET":
			skip.add (c["index"])
			target = c
	win, ctl = EEUI.Build ("AREA_MAP", skip=skip)
	win.AddAlias (pack, id)
	win.AddAlias ("WIN_MAP")

	for c in EEUI.Controls ("AREA_MAP"):
		if c["type"] == "button" and c.get ("text", {}).get ("strref") == 20429:
			ctl[c["index"]].OnPress (lambda: OpenTravelWindow (None))
		elif c["type"] == "button" and c.get ("bam") == "XBUTT":
			ctl[c["index"]].OnPress (win.Close)
			ctl[c["index"]].MakeEscape ()

	# EE's target box is measured like its slots: from the menu's top, not the centred box
	x, y, w, h = target["frame"]
	y -= EEUI.Load ("AREA_MAP").get ("slot_dy", 0)
	Map = win.CreateMapControl (0x20, x, y, w, h)
	Map.AddAlias ("MAP")
	Map.SetFit (True)      # EE scales the area map to fill its box
	Map.SetVarAssoc ("ShowMapNotes", IE_GUI_MAP_VIEW_NOTES)
	Map.SetStatus (IE_GUI_MAP_VIEW_NOTES)
	Map.SetAction (win.Close, IE_ACT_MOUSE_PRESS, GEM_MB_ACTION, 0, 2)

	MapTable = GemRB.LoadTable ("MAPNAME")
	MapName = MapTable.GetValue (GemRB.GetCurrentArea (), "STRING")
	for c in EEUI.Controls ("AREA_MAP"):
		if c["type"] == "label" and "mapScreen:GetMapName" in c.get ("text_opts", {}).get ("lua", ""):
			lab = ctl[c["index"]]
			fr = lab.GetFrame ()
			fr['y'] -= EEUI.Load ("AREA_MAP").get ("slot_dy", 0)    # same offset as the map box
			lab.SetFrame (fr)
			lab.SetText (MapName)
	_eeBuilt[0] = True
	return win

def InitMapOrEE (Window):
	if _eeBuilt[0]:
		_eeBuilt[0] = False
		return    # wired by LoadAreaMapWindow
	InitMapWindow (Window)

ToggleMapWindow = GUICommonWindows.CreateTopWinLoader(3, "GUIMA", lambda i, p, pos: LoadAreaMapWindow (i, p, pos, GUICommonWindows.ToggleWindow), InitMapOrEE)
OpenMapWindow = GUICommonWindows.CreateTopWinLoader(3, "GUIMA", lambda i, p, pos: LoadAreaMapWindow (i, p, pos, GUICommonWindows.OpenWindowOnce), InitMapOrEE)

def NoteChanged (Edit):
	Edit.SetFlags(IE_GUI_VIEW_IGNORE_EVENTS, OP_OR)
	Text = Edit.QueryText ()
	Edit.SetText ("")
	Edit.SetBackground ("MAMOSED1")
	PosX = GemRB.GetVar("MapControlX")
	PosY = GemRB.GetVar("MapControlY")
	GemRB.SetMapnote (PosX, PosY, 1, Text)

	Map = GemRB.GetView("MAP")
	Map.SetVarAssoc ("ShowMapNotes", IE_GUI_MAP_VIEW_NOTES)
	Map.SetStatus (IE_GUI_MAP_VIEW_NOTES)

	return
	
def SetMapNote (Map):
	if GemRB.GetVar ("ShowMapNotes") != IE_GUI_MAP_SET_NOTE:
		return

	MapWindow = GemRB.GetView("WIN_MAP")

	Edit = MapWindow.GetControl (4)
	Edit.SetFlags (IE_GUI_VIEW_IGNORE_EVENTS, OP_NAND)
	Edit.Focus()

	return

###################################################
# End of file GUIMA.py

