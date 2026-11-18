# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later


# Start.py - intro and main menu screens

###################################################

import GemRB
import EEUI
from GUIDefines import *

def AutoLoad():
	# dev hook for reproducible screenshots: GEMRB_AUTOLOAD=<save index> loads that save straight away
	import os
	idx = os.environ.get ("GEMRB_AUTOLOAD")
	if idx is None:
		return False
	Games = GemRB.GetSaveGames ()
	if not Games:
		return False
	# a number is the index in GetSaveGames order (slot order, not newest first), anything else a save name
	if idx.lstrip ("-").isdigit ():
		Game = Games[min(int(idx), len(Games) - 1)]
	else:
		Named = [g for g in Games if g.GetName ().lower () == idx.lower ()]
		if not Named:
			print ("AutoLoad: no save named", idx)
			return False
		Game = Named[-1]
	import LoadScreen
	GemRB.SetVar ("PlayMode", 0)
	LoadScreen.StartLoadScreen ()
	GemRB.LoadGame (Game)
	GemRB.EnterGame ()
	return True

def OnLoad():
	import DevConsole
	DevConsole.Start ()
	if AutoLoad():
		return
	skip_videos = GemRB.GetVar ("SkipIntroVideos")

	if not skip_videos:
		GemRB.PlayMovie ("BISLOGO", 1)
		GemRB.PlayMovie ("TSRLOGO", 1)
		GemRB.PlayMovie ("OPENING", 1)

		GemRB.SetVar ("SkipIntroVideos", 1)

	if EEUI.Available ("START_MAIN"):
		handles = BuildEE ()
	else:
		handles = BuildClassic ()
	Wire (handles)

	GemRB.LoadMusicPL("Main.mus")
	return
	
def BuildClassic():
	StartWindow = GemRB.LoadWindow(0, "START")
	Label = StartWindow.CreateLabel(0x0fff0000, 0,415,640,30, "FONTDLG", "", IE_FONT_SINGLE_LINE | IE_FONT_ALIGN_CENTER)
	Label.SetText(GemRB.Version)
	Label.SetColor ({'r' : 255, 'g' : 255, 'b' : 255})
	return {
		"window": StartWindow,
		"new": StartWindow.GetControl(0),
		"load": StartWindow.GetControl(2),
		"quit": StartWindow.GetControl(3),
	}

def BuildEE():
	# EE's Continue (seq 1) and Options (seq 2, 3) have no start-screen function here
	skip = set ()
	for seq in (1, 2, 3):
		idx = EEUI.Find ("START_MAIN", type="button", bam="STARTBUT", sequence=seq)
		if idx is not None:
			skip.add (idx)
	plate = EEUI.Find ("START_MAIN", type="label", mosaic="VERPLATE")
	if plate is not None:
		skip.add (plate)   # the version plate is tiny and the text reads fine on the plate art
	win, ctl = EEUI.Build ("START_MAIN", skip=skip)
	def Pick(seq):
		return ctl[EEUI.Find ("START_MAIN", type="button", bam="STARTBUT", sequence=seq)]
	return {
		"window": win,
		"new": Pick (0),
		"load": Pick (4),
		"quit": Pick (5),
	}

def Wire(handles):
	"""Attach the start screen's logic to whichever window was built."""
	handles["new"].OnPress (NewLifePress)
	handles["load"].OnPress (ResumeLifePress)
	handles["quit"].OnPress (QuitPress)
	handles["quit"].MakeEscape()
	handles["window"].Focus()

def QuitPress():
	if EEUI.PopupAvailable (2):
		EEUI.Popup (20582, [(23789, None, "e"), (23787, GemRB.Quit, "d")])
		return
	QuitWindow = GemRB.LoadWindow(3, "START")
	QuitTextArea = QuitWindow.GetControl(0)
	QuitTextArea.SetText(20582)
	
	ConfirmButton = QuitWindow.GetControl(1)
	ConfirmButton.SetText(23787)
	ConfirmButton.OnPress (lambda: GemRB.Quit())
	ConfirmButton.MakeDefault()

	CancelButton = QuitWindow.GetControl(2)
	CancelButton.SetText(23789)
	CancelButton.OnPress (QuitWindow.Close)
	CancelButton.MakeEscape()
	
	QuitWindow.ShowModal (MODAL_SHADOW_GRAY)
	return
	
def NewLifePress():
	#to make difference between ingame change and new life
	GemRB.SetVar("PlayMode",0)
	GemRB.LoadGame(None) # loading the base game
	GemRB.SetNextScript("NewLife")
	return

def ResumeLifePress():
	#to make difference between ingame load and initial load
	GemRB.SetVar("PlayMode",0)
	GemRB.SetNextScript("GUILOAD")
	return
	
