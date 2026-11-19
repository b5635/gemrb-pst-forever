# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# NewLife.py - Character generation screen

###################################################

import GemRB
import EEUI
from GUIDefines import *
from ie_stats import *
import CommonTables

CommonTables.Load()

NewLifeWindow = 0
TextArea = 0

TotLabel = 0
AcLabel = 0
HpLabel = 0

StatTable = 0
# maintain this order in all lists!
StatIDs = [ IE_STR, IE_INT, IE_WIS, IE_DEX, IE_CON, IE_CHR ]
StatLimit = [ 18, 18, 18, 18, 18, 18 ]
StatLabels = [ None ] * 6
StatLowerLimit = [ 9 ] * 6

LevelUp = 0
TotPoints = 0
AcPoints = 0
HpPoints = 0

def OnLoad():
	OpenLUStatsWindow (0)
	return

def OpenLUStatsWindow(Type = 1, LevelDiff = 0):
	global NewLifeWindow, StatTable
	global TotPoints, AcPoints, HpPoints
	global TotLabel, AcLabel, HpLabel
	global TextArea, StatLabels, StatLowerLimit, StatLimit, LevelUp

	LevelUp = Type
	if LevelUp:
		# only TNO gets the main stat boosts
		pc = GemRB.GameGetSelectedPCSingle ()
		Specific = GemRB.GetPlayerStat (pc, IE_SPECIFIC)
		if Specific != 2 or LevelDiff == 0:
			return
	else:
		GemRB.CreatePlayer ("charbase", 1)

	StatTable = GemRB.LoadTable("abcomm")

	#setting up CG window
	if EEUI.Available ("CHARGEN"):
		handles = BuildEE ()
	else:
		handles = BuildClassic ()
	NewLifeWindow = handles["window"]

	if LevelUp:
		StatLowerLimit = []
		for stat in StatIDs:
			StatLowerLimit.append (GemRB.GetPlayerStat (1, stat, 1))
		TotPoints = LevelDiff
		StatLimit = [ 25 ] * 6
	else:
		for stat in StatIDs:
			GemRB.SetPlayerStat (1, stat, 9)
		TotPoints = 21

	Wire (handles)

	UpdateLabels()

	NewLifeWindow.Focus()
	return

def BuildClassic():
	win = GemRB.LoadWindow(0, "GUICG")
	h = {"window": win}
	if nameLabel is not None:
		ctl[nameLabel].SetText (GemRB.GetPlayerName (1, 0))
	h["statlabels"] = [win.GetControl(0x10000018 + i) for i in range(6)]
	h["statbtn"] = [win.GetControl(i + 2) for i in range(6)]
	for b in h["statbtn"]:
		b.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	for key, ctl, text in (("ac", 8, 5025), ("hp", 9, 5026), ("pts", 10, 5027)):
		Button = win.GetControl(ctl)
		Button.SetFlags(IE_GUI_BUTTON_RADIOBUTTON, OP_SET)
		Button.SetState(IE_GUI_BUTTON_LOCKED)
		Button.SetSprites("", 0, 0, 0, 0, 0)
		Button.SetText(text)
		h[key] = Button
	h["plus"] = [win.GetControl(11 + 2*i) for i in range(6)]
	h["minus"] = [win.GetControl(12 + 2*i) for i in range(6)]
	h["title"] = win.GetControl(0x10000023)
	h["text"] = win.GetControl(23)
	h["tot"] = win.GetControl(0x10000020)
	h["aclabel"] = win.GetControl(0x1000001E)
	h["hplabel"] = win.GetControl(0x1000001F)
	win.GetControl(0x10000021).SetText(254)
	Photo = win.GetControl(35)
	Photo.SetState(IE_GUI_BUTTON_LOCKED)
	Photo.SetFlags(IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
	h["photo"] = Photo
	h["accept"] = win.GetControl(0)
	h["cancel"] = win.GetControl(1)
	return h

def BuildEE():
	import re
	ctrls = EEUI.Controls ("CHARGEN")
	# EE numbers the abilities 1 STR, 2 DEX, 3 CON, 4 INT, 5 WIS, 6 CHA; ours go STR INT WIS DEX CON CHA
	ee_of = [1, 4, 5, 2, 3, 6]
	by_var = {}
	plus, minus, hover = {}, {}, {}
	extras = {}
	for c in ctrls:
		lua = c.get ("text_opts", {}).get ("lua")
		if lua:
			by_var[lua] = c["index"]
		act = c.get ("raw", {}).get ("action", "")
		m = re.search (r"OnAbilityPlusMinusButtonClick\((\d), (true|false)\)", act)
		if m:
			(plus if m.group (2) == "true" else minus)[int (m.group (1))] = c["index"]
		m = re.match (r"showAbilityHelpText\((\d)\)", act)
		if m and c["type"] == "text" and c.get ("bam") == "CGATTR":
			hover[int (m.group (1))] = c["index"]
		for key, strref in (("ac", 5025), ("hp", 5026), ("pts", 5027)):
			if c["type"] == "text" and (c.get ("text") or {}).get ("strref") == strref:
				extras[key] = c["index"]
		if c["type"] == "label" and (c.get ("text") or {}).get ("strref") == 1899:
			extras["title"] = c["index"]
		if c["type"] == "label" and c.get ("style") == "normal":
			extras["text"] = c["index"]
		if c["type"] == "label" and c.get ("frame") and c["frame"][2] > 200 and c["frame"][3] > 200 and not c.get ("style") and not c.get ("mosaic"):
			extras["photo"] = c["index"]
		if c.get ("bam") == "CGACCEPT":
			extras["accept"] = c["index"]
		if c["type"] == "button" and (c.get ("text") or {}).get ("strref") == 4196:
			extras["cancel"] = c["index"]
	skip = set ()
	nameLabel = None
	for c in ctrls:   # the second title has no classic function; the name plaque shows the PC's name
		if c["index"] == 1:
			skip.add (c["index"])
		elif c.get ("text_opts", {}).get ("lua") == "chargen.name":
			nameLabel = c["index"]
	override = {extras["text"]: "textarea", extras["photo"]: "button"}
	dx, dy = EEUI.MenuBoxOffset ("CHARGEN")   # placed by EE's menu box, as EE does
	win, ctl = EEUI.Build ("CHARGEN", skip=skip, override=override, dx=dx, dy=dy)
	h = {"window": win}
	h["statlabels"] = [ctl[by_var["chargen.ability[%d].roll" % e]] for e in ee_of]
	h["statbtn"] = [ctl[hover[e]] for e in ee_of]
	h["ac"], h["hp"], h["pts"] = ctl[extras["ac"]], ctl[extras["hp"]], ctl[extras["pts"]]
	h["plus"] = [ctl[plus[e]] for e in ee_of]
	h["minus"] = [ctl[minus[e]] for e in ee_of]
	h["title"] = ctl[extras["title"]]
	h["text"] = ctl[extras["text"]]
	h["tot"] = ctl[by_var["chargen.extraAbilityPoints"]]
	h["aclabel"] = ctl[by_var["chargen.AC"]]
	h["hplabel"] = ctl[by_var["chargen.hitpoints"]]
	h["photo"] = ctl[extras["photo"]]
	h["accept"] = ctl[extras["accept"]]
	h["cancel"] = ctl[extras["cancel"]]
	for lab in h["statlabels"] + [h["tot"], h["aclabel"], h["hplabel"]]:
		lab.SetFont ("EXOFONT")
	return h

def Wire(h):
	"""Attach chargen's logic to the controls of whichever window was built."""
	global TextArea, StatLabels, TotLabel, AcLabel, HpLabel
	for i in range(6):
		StatLabels[i] = h["statlabels"][i]
		h["statbtn"][i].OnMouseEnter (StatPress[i])
	h["ac"].OnMouseEnter (AcPress)
	h["hp"].OnMouseEnter (HpPress)
	h["pts"].OnMouseEnter (PointPress)
	for i in range(len(StatPress)):
		Button = h["plus"][i]
		Button.OnPress (IncreasePress)
		Button.OnMouseEnter (StatPress[i])
		Button.SetVarAssoc ("Pressed", i)
		Button.SetActionInterval (200)

		Button = h["minus"][i]
		Button.OnPress (DecreasePress)
		Button.OnMouseEnter (StatPress[i])
		Button.SetVarAssoc ("Pressed", i)
		Button.SetActionInterval (200)

	h["title"].SetText(19356 if LevelUp else 1899)

	TextArea = h["text"]
	TextArea.SetText(18495)

	TotLabel = h["tot"]
	AcLabel = h["aclabel"]
	HpLabel = h["hplabel"]

	PhotoButton = h["photo"]
	PhotoButton.OnMouseEnter (OverPhoto)
	PhotoButton.SetPicture("STPNOC")

	AcceptButton = h["accept"]
	AcceptButton.SetText(4192)
	AcceptButton.OnPress (AcceptPress)
	AcceptButton.MakeDefault()

	CancelButton = h["cancel"]
	CancelButton.SetText(4196)
	CancelButton.OnPress (CancelPress)
	if LevelUp:
		CancelButton.SetState(IE_GUI_BUTTON_DISABLED)

def UpdateLabels():
	global AcPoints, HpPoints

	Str = GemRB.GetPlayerStat(1, IE_STR, 1)
	strEx = GemRB.GetPlayerStat(1, IE_STREXTRA, 1)
	if Str != 18 or strEx == 0:
		StatLabels[0].SetText(str(Str))
	else:
		StatLabels[0].SetText("18/" + ("00" if strEx == 100 else str(strEx)))
	for i in range(1, 6):
		StatLabels[i].SetText (str(GemRB.GetPlayerStat (1, StatIDs[i], 1)))

	TotLabel.SetText(str(TotPoints))
	if LevelUp:
		AcPoints = GemRB.GetPlayerStat(1, IE_ARMORCLASS, 1)
	else:
		AcPoints = 10
		Dex = GemRB.GetPlayerStat(1, IE_DEX, 1)
		if Dex > 14:
			AcPoints = AcPoints - (Dex-14)

	if LevelUp:
		HpPoints = GemRB.GetPlayerStat(1, IE_HITPOINTS, 1)
	else:
		HpPoints = 20
		Con = GemRB.GetPlayerStat(1, IE_CON, 1)
		if Con > 14:
			HpPoints = HpPoints + (Con-9)*2 + (Con-14)
		else:
			HpPoints = HpPoints + (Con-9)*2

	AcLabel.SetText(str(AcPoints))
	HpLabel.SetText(str(HpPoints))
	return

def AcceptPress():
	if TotPoints and EEUI.PopupAvailable (1):
		EEUI.Popup (46782, [(46783, None, "de")])
		return

	if TotPoints:
		QuitWindow = GemRB.LoadWindow(1, "GUICG")
		TextArea = QuitWindow.GetControl(0)
		TextArea.SetText(46782)

		Button = QuitWindow.GetControl(1)
		Button.SetText("")
		Button.SetFlags(IE_GUI_BUTTON_NO_IMAGE,OP_SET)
		Button.SetState(IE_GUI_BUTTON_DISABLED)
		Button = QuitWindow.GetControl(2)
		Button.SetText(46783)
		Button.MakeDefault()
		Button.OnPress (QuitWindow.Close)
		QuitWindow.ShowModal (MODAL_SHADOW_GRAY)
		return

	if LevelUp:
		# Return to the RecordsWindow
		NewLifeWindow.Close()
		return

	#don't add con bonus, it will be calculated by the game
	#interestingly enough, the game adds only one level's con bonus
	Table = GemRB.LoadTable ("hpinit")
	x = Table.GetValue (str(GemRB.GetPlayerStat (1, IE_CON, 1)), "HP")
	
	GemRB.SetPlayerStat(1, IE_MAXHITPOINTS, x)
	GemRB.SetPlayerStat(1, IE_HITPOINTS, x + 100) # x + 100 ensures the player starts at max hp when con > 14

	GemRB.FillPlayerInfo(1) #does all the rest
	#LETS PLAY!!
	GemRB.EnterGame()
	return

def CancelPress():
	if EEUI.PopupAvailable (2):
		def confirm():
			NewLifeWindow.Close()
		EEUI.Popup (19406, [(23789, None, "e"), (23787, confirm, "d")])
		return

	QuitWindow = GemRB.LoadWindow(1, "GUICG")
	
	TextArea = QuitWindow.GetControl(0)
	TextArea.SetText(19406)
	
	def confirm():
		QuitWindow.Close()
		NewLifeWindow.Close()

	Button = QuitWindow.GetControl(1)
	Button.SetText(23787)
	Button.MakeDefault()
	Button.SetState(IE_GUI_BUTTON_ENABLED)
	Button.OnPress (confirm)

	Button = QuitWindow.GetControl(2)
	Button.SetText(23789)
	Button.MakeDefault()
	Button.OnPress (QuitWindow.Close)

	QuitWindow.ShowModal (MODAL_SHADOW_GRAY)
	return

def StrPress(btn = None, delta = 0):
	TextArea.SetText(18489)

	s = GemRB.GetPlayerStat(1, IE_STR, 1)
	strEx = GemRB.GetPlayerStat (1, IE_STREXTRA, 1)
	extras = (30, 60, 90, 99, 100)
	if delta == -1 and (s < 18 or s > 19):
		s -= 1
	elif delta == -1 and s == 19:
		s -= 1
		strEx = 100
	elif delta == -1 and s == 18:
		if strEx == 0:
			s -= 1
		elif strEx == 30:
			strEx = 0
		else:
			idx = extras.index (strEx)
			strEx = extras[idx - 1]
	elif delta == 1 and (s < 18 or s >= 19):
		s += 1
	elif delta == 1 and s == 18:
		if strEx == 100:
			s += 1
			strEx = 0
		elif strEx == 0:
			strEx = extras[0]
		else:
			idx = extras.index (strEx)
			strEx = extras[idx + 1]
	if delta != 0:
		GemRB.SetPlayerStat (1, IE_STR, s)
		GemRB.SetPlayerStat (1, IE_STREXTRA, strEx)

	toHit = CommonTables.StrMod.GetValue(s, 0)
	damage = CommonTables.StrMod.GetValue(s, 1)
	# this is for the STR==16 case, which displays only one number
	if toHit == 0:
		toHit = damage
		damage = 0
	elif s == 18 and strEx:
		toHit = toHit + CommonTables.StrModEx.GetValue (strEx, 0)
		damage = damage + CommonTables.StrModEx.GetValue (strEx, 1)

	if s == 18 and strEx > 60:
		s=19
	TextArea.Append("\n\n" + GemRB.GetString(StatTable.GetValue(s, 0), STRING_FLAGS_RESOLVE_TAGS).format(toHit, damage))
	return

def IntPress(delta = 0):
	TextArea.SetText(18488)
	intl = GemRB.GetPlayerStat(1, IE_INT, 1)
	TextArea.Append ("\n\n" + GemRB.GetString (StatTable.GetValue (intl, 1), STRING_FLAGS_RESOLVE_TAGS).format(0, 0))
	return

def WisPress(delta = 0):
	TextArea.SetText(18490)
	wis = GemRB.GetPlayerStat(1, IE_WIS, 1)
	TextArea.Append ("\n\n" + GemRB.GetString (StatTable.GetValue (wis, 2), STRING_FLAGS_RESOLVE_TAGS).format(0, 0))
	return

def DexPress(delta = 0):
	Table = GemRB.LoadTable("dexmod")
	dex = GemRB.GetPlayerStat (1, IE_DEX, 1)
	x = -Table.GetValue (dex, 2)
	TextArea.SetText(18487)
	TextArea.Append ("\n\n" + GemRB.GetString (StatTable.GetValue (dex, 3), STRING_FLAGS_RESOLVE_TAGS).format(x, 0))
	return

def ConPress(delta = 0):
	Table = GemRB.LoadTable("hpconbon")
	con = GemRB.GetPlayerStat(1, IE_CON, 1)
	x = Table.GetValue (con - 1, 1)
	TextArea.SetText(18491)
	TextArea.Append ("\n\n" + GemRB.GetString (StatTable.GetValue (con, 4), STRING_FLAGS_RESOLVE_TAGS).format(x, 0))
	return

def ChaPress(delta = 0):
	TextArea.SetText(1903)
	cha = GemRB.GetPlayerStat (1, IE_CHR, 1)
	TextArea.Append ("\n\n" + GemRB.GetString (StatTable.GetValue (cha, 5), STRING_FLAGS_RESOLVE_TAGS).format(0, 0))
	return

StatPress = [ StrPress, IntPress, WisPress, DexPress, ConPress, ChaPress ]

def PointPress():
	TextArea.SetText(18492)
	return

def AcPress():
	TextArea.SetText(18493)
	return

def HpPress():
	TextArea.SetText(18494)
	return

def DecreasePress():
	global TotPoints

	Pressed = GemRB.GetVar("Pressed")
	Sum = GemRB.GetPlayerStat(1, StatIDs[Pressed], 1)
	if Sum <= StatLowerLimit[Pressed]:
		return
	TotPoints = TotPoints+1
	if StatIDs[Pressed] != IE_STR:
		GemRB.SetPlayerStat (1, StatIDs[Pressed], Sum - 1)

	StatPress[Pressed](delta = -1)
	UpdateLabels()
	return

def IncreasePress():
	global TotPoints

	if TotPoints<=0:
		return
	Pressed = GemRB.GetVar("Pressed")
	Sum = GemRB.GetPlayerStat(1, StatIDs[Pressed], 1)
	if Sum >= StatLimit[Pressed] and (StatIDs[Pressed] != IE_STR or GemRB.GetPlayerStat(1, IE_STREXTRA, 1) == 100):
		return

	TotPoints = TotPoints-1
	if StatIDs[Pressed] != IE_STR:
		GemRB.SetPlayerStat (1, StatIDs[Pressed], Sum + 1)

	StatPress[Pressed](delta = 1)
	UpdateLabels()
	return

def OverPhoto():
	global TextArea
	TextArea.SetText (18495) # yep, the same is shown during level up
