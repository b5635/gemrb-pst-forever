# SPDX-FileCopyrightText: 2007 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# QuitGame.py - display EndGame sequence

###################################################

import GemRB
from GUIDefines import *
import GUICommon
import CommonWindow
import EEUI

def OnLoad ():
	movies = ["", "T1DEATH", "T1ABSORB", "FINALE", "CREDITS"]

	CommonWindow.SetGameGUIHidden(True)
	which = GemRB.GetVar ("QuitGame1")
	if which is not None:
		GemRB.PlayMovie (movies[which], 1)
	which = GemRB.GetVar ("QuitGame2")
	if which is not None:
		GemRB.PlayMovie (movies[which], 1)
	which = GemRB.GetVar ("QuitGame3")
	if which:
		DeathWindowEnd ()
	else:
		GemRB.PlayMovie (movies[4], 1)
		GemRB.QuitGame ()
		GemRB.SetNextScript("Start")

def DonePress ():
		GemRB.QuitGame ()
		GemRB.SetNextScript("Start")

def DeathWindowEnd ():
	GemRB.GamePause (1,3)

	if EEUI.PopupAvailable (1):
		# EE's death box: the reason for death, one button (the picture is POPUPIMG frame 2)
		EEUI.Popup (GemRB.GetVar ("QuitGame3"), [(17237, DonePress, "d")], image=2)
		GUICommon.GameWindow.SetDisabled(True)
		return

	Window = GemRB.LoadWindow (25, GUICommon.GetWindowPack())

	#reason for death
	Label = Window.GetControl (0x0fffffff)
	strref = GemRB.GetVar ("QuitGame3")
	Label.SetText (strref)

	#done
	Button = Window.GetControl (1)
	Button.SetText (17237)
	Button.OnPress (DonePress)
	Button.MakeDefault()

	#making the playing field gray
	GUICommon.GameWindow.SetDisabled(True)
	return
