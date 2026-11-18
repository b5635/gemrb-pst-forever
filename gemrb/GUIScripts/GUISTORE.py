# SPDX-FileCopyrightText: 2003 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later


# GUISTORE.py - script to open the store/inn/temple windows

###################################################

import GemRB
import GameCheck
import GUICommon
import GUICommonWindows
import InventoryCommon
from CommonWindow import AddScrollbarProxy
from GUIDefines import *
from ie_stats import *
from ie_slots import *
from ie_sounds import *
from ie_feats import FEAT_MERCANTILE_BACKGROUND
import CommonTables
if GameCheck.IsPST ():
	import EEUI
else:
	EEUI = None

StoreWindow = None

RentConfirmWindow = None
LeftButton = None
RightButton = None
CureTable = None
RaiseDeadTable = None

ITEM_PC    = 0
ITEM_STORE = 1
ITEM_BAG   = 2

STORE_MAIN = 0
STORE_BAG  = 1

Inventory = None
Store = None
Bag = None
inventory_slots = ()
total_price = 0
total_income = 0
if GameCheck.IsIWD2 () or GameCheck.IsAnyEE ():
	ItemButtonCount = 6
else:
	ItemButtonCount = 4
RepModTable = None
SpellTable = None
PreviousPC = 0
BestCharmer = 0
MaxAmount = 0
BuySum = 0
SellSum = 0

# 0 - Store
# 1 - Tavern
# 2 - Inn
# 3 - Temple
# 4 - Container
# 5 - Container

# 0 - buy/sell
# 1 - identify
# 2 - steal
# 3 - heal
# 4 - donate
# 5 - drink
# 6 - rent

storetips = (14288,14292,14291,12138,15013,14289,14287)
roomdesc = (17389,17517,17521,17519)
roomnames = (14294, 14295, 14296, 14297)
windowIDs = { 'shop' : 2, 'ident' : 4, 'steal' : 6, 'donate' : 9, 'heal' : 5, 'rumour' : 8, 'rent' : 7, 'iteminfo' : 12,  'cureinfo' : 14, 'rentconfirm' : 11, 'error' : 10 }
strrefs = { 'done' : 11973, 'cancel' : 13727, 'buy' : 13703, 'sell' : 13704, 'identify' : 14133, 'steal' : 14179, 'donate' : 15101, 'heal' : 8786, 'rumors' : 14144, 'rent' : 14293, 'itemnamecost' : 10162, 'restedfor' : 16476, 'rest' : 17199, 'confirmrest' : 15358, 'itemstoocostly' : 11047, 'spelltoocostly' : 11048, 'drinktoocostly' : 11049, 'toodrunk' : 10832, 'idtoocostly' : 11050, 'roomtoocostly' : 11051, 'donorgood' : 10468, 'donorfail' : 10469 }
store_funcs = None
StoreButtonCount = 4
ShopCount = ItemButtonCount   # item rows of the buy/sell window (the EE layout has 6)
EEShop = False                # the buy/sell window is the EE layout
EEBar = False                 # the tab bar is the EE layout
EEIdent = EEHeal = EERent = False   # the identify / heal / rent pages are EE layouts
IdRows = HealRows = ItemButtonCount
RowHooks = {}
if GameCheck.IsIWD1():
	# no bam for bags
	storebams = ("STORSTOR","STORTVRN","STORINN","STORTMPL","STORSTOR","STORSTOR")
elif GameCheck.IsPST():
	#             Buy/Sell Identify   Steal      Aid        Donate    Drink     Rent
	storebams = ("SSBBS", "SSBIDNT", "SSBSTEL", "SSBHEAL", "SSBDON", "SSBRMR", "SSBRENT")
	storetips =  (44970,   44971,     44972,     67294,     45121,    45119,    45120)
	roomdesc = (66865, 66866, 66867, 66868)
	roomnames = (45308, 45310, 45313, 45316)
	windowIDs = { 'shop' : 4, 'ident' : 5, 'steal' : 7, 'donate' : 10, 'heal' : 6, 'rumour' : 9, 'rent' : 8, 'iteminfo' : 13,  'cureinfo' : 13, 'rentconfirm' : 12, 'error' : 11 }
	strrefs = { 'done' : 1403, 'cancel' : 4196, 'identify' : 44971, 'buy' : 45303, 'sell' : 45304, 'steal' : 45305, 'rent' : 45306, 'donate' : 45307, 'heal' : 8836, 'rumors' : 0, 'itemnamecost' : 45374, 'restedfor' : 19262, 'rest' : 4242, 'confirmrest' : 4241, 'itemstoocostly' : 50081, 'spelltoocostly' : 50082, 'drinktoocostly' : 50083, 'toodrunk' : 0, 'idtoocostly' : 50084, 'roomtoocostly' : 50085, 'donorgood' : 26914, 'donorfail' : 26914}
	StoreButtonCount = 7
else:
	storebams = ("STORSTOR","STORTVRN","STORINN","STORTMPL","STORBAG","STORBAG")
	if GameCheck.IsBG1 ():
		strrefs["heal"] = strrefs["buy"]
Buttons = [-1] * StoreButtonCount

# center the windows according to game needs and available space
StoreWindowPlacement = WINDOW_HCENTER | WINDOW_VCENTER
ResolutionH = GemRB.GetSystemVariable (SV_HEIGHT)
# iwd2 keeps everything displayed, so we only vertically center when
# there's enough room to fit bottom windows (934 = (600-433)*2 + 600)
if ResolutionH < 600 or (GameCheck.IsIWD2 () and ResolutionH < 934):
	StoreWindowPlacement = WINDOW_HCENTER | WINDOW_TOP

def SetupScrollBar(ScrollBar, VarName, Count, Proxy, Callback):
	ScrollBar.SetVarAssoc(VarName, GemRB.GetVar(VarName) or 0, 0, max(0, Count))
	ScrollBar.OnChange(Callback) # must come after SetVarAssoc
	if Proxy:
		AddScrollbarProxy(ScrollBar.Window, ScrollBar, Proxy)
	return ScrollBar

def CloseStoreWindow ():
	global StoreWindow, CureTable
	
	if StoreWindow:
		StoreWindow.Close ()

	global Bag
	if Bag:
		UnselectBag ()
		GemRB.CloseRighthandStore ()
		Bag = None

	GemRB.LeaveStore ()

	OptionsWindow = GemRB.GetView ("OPTWIN")
	if OptionsWindow:
		OptionsWindow.SetDisabled (False)
	PortraitWindow = GemRB.GetView ("PORTWIN")
	if PortraitWindow:
		PortraitWindow.SetDisabled (False)

	CureTable = None

	if Inventory:
		# reopen the inventory
		import GUIINV
		GUIINV.OpenInventoryWindow ()
	else:
		GemRB.GamePause (0, 3)
		GUICommonWindows.SetSelectionChangeHandler( None )
		GUICommonWindows.CloseTopWindow()
	return

def PositionStoreWinRelativeTo(win):
	storewin = GemRB.GetView("WIN_STORE")
	if not storewin:
		return
	
	# ignore the esc key, normally it would be fine, but we have multiple windows that join together.
	EscButton = win.CreateButton (99, 0, 0, 0, 0);
	EscButton.MakeEscape ()

	if EEBar:
		return   # the EE tab bar is a full-screen window that already sits where it belongs

	winframe = win.GetFrame()
	storeframe = storewin.GetFrame()

	if GameCheck.IsIWD2():
		win.SetFlags(WF_ALPHA_CHANNEL, OP_OR)
		storeframe['x'] = winframe['x']
		storeframe['y'] = winframe['y']
	else:
		storeframe['x'] = winframe['x']
		storeframe['y'] = winframe['y'] + winframe['h']

	storewin.SetFrame(storeframe)

# EE store layouts (phase 16). EE's tab icon sequence in STRCHOOS for each classic store action
# (buy/sell, identify, steal, heal, donate, drink, rent)
EE_TAB_SEQ = (0, 1, 2, 4, 3, 5, 6)
EE_ROW_PICTURES = ("STRROW",)
EE_SELECTED = {'r': 255, 'g': 255, 'b': 255}   # label colour of a selected row
EE_STORE_DY = {"STORE_BUYSELL": -52, "STORE_IDENTIFY": -97, "STORE_HEALING": -97, "STORE_ROOMS": -97}
EE_CHOOSER_DY = 197

def EEStoreAvailable (menu):
	return EEUI is not None and EEUI.Available (menu)

def LoadStoreBar ():
	"""The tab bar and Done button: EE's STORE_CHOOSER when present, else the classic window 3."""
	global EEBar
	EEBar = EEStoreAvailable ("STORE_CHOOSER")
	if not EEBar:
		return GemRB.LoadWindow (3, "GUISTORE", StoreWindowPlacement)
	# the Done button is control 0; the four EE tab slots are replaced by one button per classic
	# action (controls 0x5100-0x5106; small ids are taken), placed on the same strip
	win, ctl = EEUI.Build ("STORE_CHOOSER", ids = {1: 0}, skip = {0, 2, 3, 4, 5}, plate = False, dy = EE_CHOOSER_DY)
	doc = EEUI.Load ("STORE_CHOOSER")
	tabs = [c for c in doc["controls"] if c.get ("bam") == "STRCHOOS"]
	x0, y0 = tabs[0]["frame"][0], tabs[0]["frame"][1] + EE_CHOOSER_DY
	step = tabs[1]["frame"][0] - tabs[0]["frame"][0]
	actions = Store['StoreButtons']
	shown = [i for i in range (StoreButtonCount) if actions[i] is not None]
	# later tabs are drawn over earlier ones, and the engine draws the first-created control on top
	for n in range (len (shown) - 1, -1, -1):
		i = shown[n]
		b = win.CreateButton (0x5100 + i, x0 + n * step, y0, tabs[0]["frame"][2], tabs[0]["frame"][3])
		b.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
	for i in range (StoreButtonCount):
		if i not in shown:
			b = win.CreateButton (0x5100 + i, 0, 0, 1, 1)
			b.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	return win

def CloseOldPage ():
	"""EE pages reuse the classic control ids, which must be free before the next page is built."""
	top = GemRB.GetView ("WIN_TOP")
	if top:
		top.Close ()

def EEPage (base, menu, build):
	"""Window loader for a store page that has an EE layout: build (menu) -> window, else the CHU window."""
	def load (id, pack, pos):
		if GemRB.GetView (pack, id) or not EEStoreAvailable (menu):
			return base (id, pack, pos), False
		if base is GUICommonWindows.ToggleWindow and GemRB.GetView ("WIN_STORE"):
			return None, False
		CloseOldPage ()
		win = build ()
		win.AddAlias (pack, id)
		return win, True
	return load

def BuildEEPage (menu, ids, skip, override = None):
	win, ctl = EEUI.Build (menu, ids = ids, skip = skip, dy = EE_STORE_DY[menu], reverse = True, override = override)
	for c in EEUI.Controls (menu):
		if c.get ("text", {}).get ("literal") == "font" and c["index"] in ctl:
			ctl[c["index"]].SetText ("")
	return win, ctl

def ButtonStyle (btn):
	btn.SetFont (EEUI.StyleFont ("button"))
	btn.SetColor (EEUI.StyleColor ("button"))

def LoadIdentifyWindow (base):
	def build ():
		global IdRows
		IdRows = 6
		RowHooks.clear ()
		win, ctl = BuildEEPage ("STORE_IDENTIFY", {0: 0x0fffffff, 1: 0x10000002, 4: 0x10000000, 6: 0x10000001, 9: 4, 10: 14}, {2, 3, 7, 8}, {10: 'textarea'})
		ButtonStyle (ctl[9])
		lst = [c for c in EEUI.Controls ("STORE_IDENTIFY") if c["type"] == "list"][0]
		BuildRows (win, "STORE_IDENTIFY", lst, IdRows, 6, 0x10000009, 5, "id", 0x4200)
		return win
	inner = EEPage (base, "STORE_IDENTIFY", build)
	def load (id, pack, pos):
		global EEIdent, IdRows
		win, ee = inner (id, pack, pos)
		if win:
			if not ee:
				IdRows = ItemButtonCount
			EEIdent = ee
		return win
	return load

def LoadHealWindow (base):
	def build ():
		global HealRows
		HealRows = 6
		RowHooks.clear ()
		win, ctl = BuildEEPage ("STORE_HEALING", {0: 0x0fffffff, 2: 0x10000000, 6: 0x10000001, 8: 3, 9: 13}, {1, 3, 4, 7}, {9: 'textarea'})
		ButtonStyle (ctl[8])
		lst = [c for c in EEUI.Controls ("STORE_HEALING") if c["type"] == "list"][0]
		BuildRows (win, "STORE_HEALING", lst, HealRows, 5, 0x10000008, 4, "heal", 0x4300)
		return win
	inner = EEPage (base, "STORE_HEALING", build)
	def load (id, pack, pos):
		global EEHeal, HealRows
		win, ee = inner (id, pack, pos)
		if win:
			if not ee:
				HealRows = ItemButtonCount
			EEHeal = ee
		return win
	return load

def LoadRentWindow (base):
	def build ():
		RowHooks.clear ()
		win, ctl = BuildEEPage ("STORE_ROOMS", {0: 0x1000000a, 4: 0x1000000c, 6: 9, 7: 0x1000000b, 9: 8}, {1, 2, 3, 5}, {6: 'textarea'})
		ButtonStyle (ctl[9])
		lst = [c for c in EEUI.Controls ("STORE_ROOMS") if c["type"] == "list"][0]
		x, y, w, h = lst["frame"]
		y += EE_STORE_DY["STORE_ROOMS"]
		rowh = lst["columns"][0]["controls"][0]["frame"][3]
		for i in range (4):
			# room icon buttons 0-3 are only state holders in the EE page
			win.CreateButton (i, 0, 0, 1, 1).SetVisible (False)
			b = win.CreateButton (4 + i, x, y + i * rowh, lst["columns"][0]["controls"][0]["frame"][2], rowh)
			b.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
			b.SetFont (EEUI.StyleFont ("label"))
			b.SetColor (EEUI.StyleColor ("normal"))
			bg = win.CreateLabel (0x4400 + i, x, y + i * rowh, lst["columns"][0]["controls"][0]["frame"][2], rowh, "FONTDLG", "", 0)
			bg.SetBackground (EE_ROW_PICTURES[0])
		return win
	inner = EEPage (base, "STORE_ROOMS", build)
	def load (id, pack, pos):
		global EERent
		win, ee = inner (id, pack, pos)
		if win:
			EERent = ee
		return win
	return load

def EETabPicture (btn, action, active):
	# the picture is scaled down to the tab by the button; frame 2 of the cycle is the pressed look
	btn.SetPicture (GemRB.GetSprite ("STRCHOOS", -1, EE_TAB_SEQ[action], 2 if active else 0))

def EETabPress (win, action):
	for i in range (StoreButtonCount):
		if Store['StoreButtons'][i] is not None:
			EETabPicture (win.GetControl (0x5100 + i), Store['StoreButtons'][i], i == action)
	store_funcs[action] ()
	win.Focus () # keep the tab bar above the page
def LoadShopWindow (base):
	"""Window loader for the buy/sell page: EE's STORE_BUYSELL when present, else the CHU window."""
	def load (id, pack, pos):
		global EEShop
		if GemRB.GetView (pack, id) or not EEStoreAvailable ("STORE_BUYSELL"):
			if not GemRB.GetView (pack, id):
				EEShop = False
			return base (id, pack, pos)
		if base is GUICommonWindows.ToggleWindow and GemRB.GetView ("WIN_STORE"):
			return None
		EEShop = True
		CloseOldPage ()
		ids = {0: 0x10000001, 1: 0x10000005, 2: 0x10000002, 4: 0x10000003, 5: 0x10000004, 9: 0, 10: 1, 13: 50}
		win, ctl = EEUI.Build ("STORE_BUYSELL", ids = ids, skip = {6, 7, 8, 11, 12, 14, 15}, dy = EE_STORE_DY["STORE_BUYSELL"], reverse = True)
		win.AddAlias (pack, id)
		ctl[0].SetText ("")
		for i in (9, 10, 13):
			ctl[i].SetFont (EEUI.StyleFont ("button"))
			ctl[i].SetColor (EEUI.StyleColor ("button"))
		ctl[13].SetVisible (False)
		# the classic scripts write to these; the EE layout has no use for them
		for cid in (25, 44):
			win.CreateButton (cid, 0, 0, 1, 1).SetVisible (False)
		for cid in (0xfffffff, 0x1000002f, 0x10000030):
			win.CreateLabel (cid, 0, 0, 1, 1, "NUMBER", "", 0).SetVisible (False)
		BuildShopRows (win)
		return win
	return load

def BuildShopRows (win):
	"""The two item lists of the EE buy/sell page: ShopCount rows each, with the classic control ids
	(item button 8+i / 17+i, label 0x1000000b+i / 0x10000014+i, scroll bar 7 / 16)."""
	global ShopCount
	ShopCount = 6
	RowHooks.clear ()
	lists = [c for c in EEUI.Controls ("STORE_BUYSELL") if c["type"] == "list"]
	BuildRows (win, "STORE_BUYSELL", lists[0], ShopCount, 8, 0x1000000b, 7, True, 0x4000)
	BuildRows (win, "STORE_BUYSELL", lists[1], ShopCount, 17, 0x10000014, 16, False, 0x4000)

def BuildRows (win, menu, lst, count, firstBtn, firstLbl, bar, key, obase):
	"""count rows of an EE list template: a click catcher (obase + button id), the name/price text,
	the item icon button and the row picture, plus the list's scroll bar. RowHooks[(key, i)]."""
	x, y, w, h = lst["frame"]
	y += EE_STORE_DY[menu]
	tmpl = lst["columns"][0]["controls"]
	rowh = tmpl[0]["frame"][3]
	icon, name = tmpl[1]["frame"], tmpl[2]["frame"]
	for i in range (count):
		ry = y + i * rowh
		# drawn top to bottom in creation order: click catcher, text, icon, row picture
		over = win.CreateButton (obase + firstBtn + i, x, ry, tmpl[0]["frame"][2], rowh)
		over.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
		lab = win.CreateLabel (firstLbl + i, x + name[0], ry + name[1], 223, name[3], EEUI.StyleFont ("normal"), "", IE_FONT_ALIGN_LEFT | IE_FONT_ALIGN_MIDDLE)
		lab.SetColor (EEUI.StyleColor ("normal"))
		btn = win.CreateButton (firstBtn + i, x + icon[0], ry + icon[1], icon[2], icon[3])
		btn.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
		bg = win.CreateLabel (obase + 0x100 + firstBtn + i, x, ry, tmpl[0]["frame"][2], rowh, "FONTDLG", "", 0)
		bg.SetBackground (EE_ROW_PICTURES[0])
		RowHooks[(key, i)] = (bg, over, lab)
	win.CreateScrollBar (bar, {'x': x + w - 24, 'y': y, 'w': 24, 'h': h}, EEUI.Alias ("CGSCRL1"))

def RowHook (left, i, state):
	"""Called by SetupItems for each item button with its new state (None: empty row)."""
	hook = RowHooks.get ((left, i))
	if not hook:
		return
	bg, over, lab = hook
	bg.SetVisible (state is not None)
	over.SetState (IE_GUI_BUTTON_DISABLED if state is None else IE_GUI_BUTTON_ENABLED)
	lab.SetColor (EE_SELECTED if state == IE_GUI_BUTTON_SELECTED else EEUI.StyleColor ("normal"))

def OpenStoreWindow ():
	global Store
	global StoreWindow
	global store_funcs
	global SpellTable, RepModTable
	global Inventory
	global CureTable

	Inventory = GemRB.GetView ("WIN_INV") is not None

	def ChangeStoreView(func):
		# WIN_TOP needs to be focused for us to change it (see CreateTopWinLoader)
		top = GemRB.GetView("WIN_TOP")
		if top:
			top.Focus()

		PortraitWindow = GemRB.GetView ("PORTWIN")
		if PortraitWindow:
			PortraitWindow.SetDisabled (False)
		return func()
	
	store_funcs = (lambda: ChangeStoreView(OpenStoreShoppingWindow),
					lambda: ChangeStoreView(OpenStoreIdentifyWindow),
					lambda: ChangeStoreView(OpenStoreStealWindow),
					lambda: ChangeStoreView(OpenStoreHealWindow),
					lambda: ChangeStoreView(OpenStoreDonateWindow),
					lambda: ChangeStoreView(OpenStoreRumourWindow),
					lambda: ChangeStoreView(OpenStoreRentWindow) )
	
	Store = GemRB.GetStore ()
	#based on shop type, these buttons will change
	store_buttons = Store['StoreButtons']
	
	# we have to load the "top win" first
	# the code doesn't permit a "normal win" to sit between 2 "top win"
	# normal windows are considered children of the "top win" below them
	topwin = store_funcs[store_buttons[0]] ()

	if GameCheck.IsPST():
		CureTable = GemRB.LoadTable("speldesc") #additional info not supported by core
	else:
		if not GameCheck.IsIWD2(): # present from before, resulting in a 10x price increase
			RepModTable = GemRB.LoadTable ("repmodst")
		SpellTable = GemRB.LoadTable ("storespl", 1)

	if not Inventory:
		# pause the game, so we don't get interrupted
		GemRB.GamePause (1, 3)

	GemRB.SetVar ("Action", 0)

	StoreWindow = Window = LoadStoreBar ()
	StoreWindow.SetFlags (IE_GUI_VIEW_IGNORE_EVENTS, OP_OR)
	if EEBar:
		StoreWindow.Focus () # drawn above the full-screen EE page
	if GameCheck.IsIWD2():
		# IWD2 has weird overlay windows
		StoreWindow.SetFlags(WF_ALPHA_CHANNEL, OP_OR)
	Window.AddAlias("WIN_STORE")

	PositionStoreWinRelativeTo(topwin)

	OptionsWindow = GemRB.GetView ("OPTWIN")
	if OptionsWindow:
		OptionsWindow.SetDisabled (True)

	# Done
	Button = Window.GetControl (0)
	Button.SetText (strrefs["done"])
	Button.OnPress (CloseStoreWindow)
	Button.MakeEscape()

	#Store type icon
	if not GameCheck.IsIWD2() and not EEBar:
		Button = Window.GetControl (5)
		Button.SetSprites (storebams[Store['StoreType']],0,0,0,0,0)

	for i in range (StoreButtonCount):
		Buttons[i] = Button = Window.GetControl ((0x5100 + i) if EEBar else (i+1))
		Action = store_buttons[i]
		Button.SetVarAssoc ("Action", i)
		# iwd2 has no steal window
		if GameCheck.IsIWD2() and Action == 2:
			Action = None
		if Action is not None:
			Button.SetFlags (IE_GUI_BUTTON_RADIOBUTTON, OP_OR)
			if GameCheck.IsIWD1() or GameCheck.IsIWD2():
				Button.SetSprites ("GUISTBBC", Action, 1,2,0,0)
			elif EEBar:
				EETabPicture (Button, Action, i == 0)
			elif GameCheck.IsPST():
				Button.SetSprites (storebams[Action], 0, 0,1,2,0)
			else:
				Button.SetSprites ("GUISTBBC", Action, 0,1,2,0)
			Button.SetTooltip (storetips[Action])
			Button.OnPress ((lambda Action=Action: EETabPress (Window, Action)) if EEBar else store_funcs[Action])
			Button.SetState (IE_GUI_BUTTON_ENABLED)
		else:
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
			Button.SetTooltip ("")
			Button.OnPress (None)
			Button.SetState (IE_GUI_BUTTON_DISABLED)

	return

def SetupBorders (btn):
		UnusableColor = {'r' : 255, 'g' : 128, 'b' : 128, 'a' : 64}
		DisabledColor = {'r': 61, 'g': 47, 'b': 24, 'a': 100}

		if GameCheck.IsBG2OrEE ():
			IDColor = {'r' : 0, 'g' : 0, 'b' : 128, 'a' : 160}
		elif GameCheck.IsPST():
			IDColor = {'r' : 128, 'g' : 0, 'b' : 0, 'a' : 100}
		else:
			IDColor = {'r' : 32, 'g' : 32, 'b' : 192, 'a' : 128}

		btn.SetBorder (0, IDColor, 0, 1)
		btn.SetBorder (1, UnusableColor, 0, 1)
		btn.SetBorder (2, DisabledColor, 0, 1)

def InitStoreShoppingWindow (Window):
	global LeftButton, RightButton, Inventory
	global BestCharmer

	global ShopCount
	if not EEShop:
		ShopCount = ItemButtonCount
	Window.AddAlias('WINSHOP')
	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs
		# strings must be able to fit into a resref (<= 8 char)
		aliases = { 'STOLBTN' : 0, 'STORBTN' : 1,
					'STOSBARR' : 16, 'STOSBARL' : 7,

					'PRICEB' : 0x10000003, 'PRICES' : 0x10000004,
					'STOTITLE' : 0x10000001, 'STONAME' : 0x10000005, 'STOGOLD' : 0x10000002,
					}

		Window.AliasControls ({'LBTN' + str(x) : x+8 for x in range(ShopCount)})
		Window.AliasControls ({'RBTN' + str(x) : x+17 for x in range(ShopCount)} )
		Window.AliasControls ({'RLBL' + str(x) : x+0x10000014 for x in range(ShopCount)} )
		Window.AliasControls ({'LLBL' + str(x) : x+0x1000000b for x in range(ShopCount)} )

	else:
		aliases = { 'STOLBTN' : 2, 'STORBTN' : 3,
					'STOSBARR' : 12, 'STOSBARL' : 11,

					'PRICEB' : 0x1000002b, 'PRICES' : 0x1000002c,
					'STOTITLE' : 0x10000003, 'STONAME' : 0x1000002e, 'STOGOLD' : 0x1000002a,
					}

		Window.AliasControls ({'LBTN' + str(x) : x+5 for x in range(ItemButtonCount)})
		Window.AliasControls ({'RBTN' + str(x) : x+13 for x in range(ItemButtonCount)} )
		Window.AliasControls ({'RLBL' + str(x) : x+0x1000001e for x in range(ItemButtonCount)} )
		Window.AliasControls ({'LLBL' + str(x) : x+0x10000012 for x in range(ItemButtonCount)} )


	Window.AliasControls (aliases)

	if Inventory:
		# Title
		Label = Window.GetControl (0xfffffff)
		if GameCheck.IsIWD1() or GameCheck.IsIWD2():
			Label.SetText (26291)
		elif GameCheck.IsBG2OrEE ():
			Label.SetText (51881)
		else:
			Label.SetText ("")

		# buy price ...
		Label = Window.GetControl (0x1000002f)
		Label.SetText ("")
		# sell price ...
		Label = Window.GetControl (0x10000030)
		Label.SetText ("")

	# buy price ...
	Label = Window.GetControlAlias ('PRICEB')
	Label.SetText ("")
	# sell price ...
	Label = Window.GetControlAlias ('PRICES')
	Label.SetText ("")

	for i in range (ShopCount):
		Button = Window.GetControlAlias ('LBTN' + str(i))
		Button.SetVarAssoc ("LeftIndex", i)
		SetupBorders (Button)
		Button.OnPress (SelectBuy)
		Button.OnDoublePress (lambda: OpenItemAmountWindow(Window))
		Button.OnRightPress (InfoLeftWindow)
		Button.SetFont ("NUMBER")
		Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM | IE_GUI_BUTTON_PICTURE, OP_OR)

		Button = Window.GetControlAlias ('RBTN' + str(i))
		Button.SetVarAssoc ("RightIndex", i)
		if GameCheck.IsBG2OrEE ():
			Button.SetSprites ("GUIBTBUT", 0, 0,1,2,5)

		SetupBorders (Button)
		if Store['StoreType'] != 3: # can't sell to temples
			Button.OnPress (SelectSell)
			Button.OnDoublePress (lambda: OpenBag(Window))
		Button.OnRightPress (InfoRightWindow)
		Button.SetFont ("NUMBER")
		Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM | IE_GUI_BUTTON_PICTURE, OP_OR)

	if EEShop:
		# the transparent row catchers act like the item buttons they cover
		for i in range (ShopCount):
			over = Window.GetControl (0x4000 + 8 + i)
			over.SetVarAssoc ("LeftIndex", i)
			over.OnPress (SelectBuy)
			over.OnDoublePress (lambda: OpenItemAmountWindow(Window))
			over.OnRightPress (InfoLeftWindow)
			over = Window.GetControl (0x4000 + 17 + i)
			over.SetVarAssoc ("RightIndex", i)
			if Store['StoreType'] != 3:
				over.OnPress (SelectSell)
				over.OnDoublePress (lambda: OpenBag(Window))
			over.OnRightPress (InfoRightWindow)

	GemRB.SetVar ("RightIndex", 0)
	GemRB.SetVar ("LeftIndex", 0)
	UnselectNoRedraw ()

	# Buy
	LeftButton = Button = Window.GetControlAlias ('STOLBTN')
	if Inventory:
		if GameCheck.IsIWD1() or GameCheck.IsIWD2():
			Button.SetText (26287)
		elif GameCheck.IsBG2OrEE ():
			Button.SetText (51882)
		else:
			Button.SetText ("")
		Button.OnPress (ToBackpackPressed)
	else:
		Button.SetText (strrefs["buy"])
		Button.OnPress (BuyPressed)

	# Sell
	RightButton = Button = Window.GetControlAlias ('STORBTN')
	if Inventory:
		if GameCheck.IsIWD1() or GameCheck.IsIWD2():
			Button.SetText (26288)
		elif GameCheck.IsBG2OrEE ():
			Button.SetText (51883)
		else:
			Button.SetText ("")
		Button.OnPress (ToBagPressed)
	else:
		Button.SetText (strrefs["sell"])
		if Store['StoreType'] != 3: # can't sell to temples
			Button.OnPress (SellPressed)

	# inactive button (close container)
	Button = Window.GetControl (50)
	if Button:
		Button.SetState (IE_GUI_BUTTON_DISABLED)
		Button.SetText (24892)
		Button.OnPress (lambda: CloseBag(Window))

	#backpack
	BackpackButton = Window.GetControl (44)
	if BackpackButton:
		BackpackButton.SetState (IE_GUI_BUTTON_LOCKED)

	# encumbrance
	if GameCheck.IsPST():
		Button = Window.GetControl (25)
		Button.SetState (IE_GUI_BUTTON_LOCKED)
		Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
		Button.SetFont ('NUMBER')
	else:
		BackpackButton.CreateLabel (0x10000043, "NUMBER", "0:",
			IE_FONT_ALIGN_LEFT|IE_FONT_ALIGN_TOP|IE_FONT_SINGLE_LINE)
		BackpackButton.CreateLabel (0x10000044, "NUMBER", "0:",
			IE_FONT_ALIGN_RIGHT|IE_FONT_ALIGN_BOTTOM|IE_FONT_SINGLE_LINE)

	# find pc with highest charisma for pricing purposes
	PartySize = GemRB.GetPartySize ()
	maxCha = 0
	for pc in range(1, PartySize + 1):
		cha = GemRB.GetPlayerStat (pc, IE_CHR)
		if cha > maxCha:
			maxCha = cha
			BestCharmer = pc

	return

def UpdateStoreShoppingWindow (Window):
	global Bag, Store, inventory_slots

	#reget store in case of a change
	Store = GemRB.GetStore ()
	pc = GetPC()
	Bag = GemRB.GetStore (STORE_BAG)

	callback = lambda: RedrawStoreShoppingWindow(Window)
	LeftCount = Store['StoreItemCount'] - ShopCount
	# left scrollbar
	SetupScrollBar(Window.GetControlAlias('STOSBARL'), "LeftTopIndex", LeftCount, Window.GetControlAlias('LBTN0'), callback)

	if Bag:
		RightCount = Bag['StoreItemCount'] - ShopCount
	else:
		inventory_slots = GemRB.GetSlots (pc, SLOT_INVENTORY)
		RightCount = len(inventory_slots) - ShopCount

	# right scrollbar
	SetupScrollBar(Window.GetControlAlias('STOSBARR'), "RightTopIndex", RightCount, Window.GetControlAlias('RBTN0'), callback)

	Button = Window.GetControl (50)
	if Button:
		if Bag:
			Button.SetState (IE_GUI_BUTTON_ENABLED)
		else:
			Button.SetState (IE_GUI_BUTTON_DISABLED)
		if EEShop:
			Button.SetVisible (bool (Bag))

	RedrawStoreShoppingWindow (Window)
	return

ToggleStoreShoppingWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["shop"], "GUISTORE", LoadShopWindow (GUICommonWindows.ToggleWindow), InitStoreShoppingWindow, UpdateStoreShoppingWindow, False, StoreWindowPlacement)
OpenStoreShoppingWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["shop"], "GUISTORE", LoadShopWindow (GUICommonWindows.OpenWindowOnce), InitStoreShoppingWindow, UpdateStoreShoppingWindow, False, StoreWindowPlacement)

def InitStoreIdentifyWindow (Window):
	global LeftButton

	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs
		Window.AliasControls ({ 'IDSBAR' : 5, 'IDLBTN' : 4, 'IDTA' : 14,
								'IDPRICE' : 0x10000001, 'STOGOLD' : 0x10000000,
								'STOTITLE' : 0x0fffffff, 'STONAME' : 0x10000002
							  } )
		Window.AliasControls ({'IDBTN' + str(x) : 6+x for x in range(IdRows)})
	else:
		Window.AliasControls ({ 'IDSBAR' : 7, 'IDLBTN' : 5, 'IDTA' : 23,
								'IDPRICE' : 0x10000003, 'STOGOLD' : 0x10000001,
								'STOTITLE' : 0x10000000, 'STONAME' : 0x10000005
							  } )
		Window.AliasControls ({'IDBTN' + str(x) : 8+x for x in range(ItemButtonCount)})

	TextArea = Window.GetControlAlias ('IDTA')
	TextArea.SetFlags (IE_GUI_TEXTAREA_AUTOSCROLL)

	# Identify
	LeftButton = Button = Window.GetControlAlias ('IDLBTN')
	Button.SetText (strrefs["identify"])
	Button.OnPress (lambda: IdentifyPressed (Window))
	Button.OnRightPress (InfoIdentifyWindow)

	# price ...
	Label = Window.GetControlAlias ('IDPRICE')
	Label.SetText ("0")

	# 8-11 item slots, 0x1000000c-f labels
	for i in range (IdRows):
		Button = Window.GetControlAlias ("IDBTN" + str(i))
		Button.SetVarAssoc ("Index", i)

		if GameCheck.IsIWD1() or GameCheck.IsIWD2():
			Button.SetSprites ("GUISTMSC", 0, 1,2,0,3)

		SetupBorders (Button)
		Button.OnPress (SelectID)
		Button.OnRightPress (InfoIdentifyWindow)
		Button.SetFont ("NUMBER")
		Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT|IE_GUI_BUTTON_ALIGN_BOTTOM, OP_OR)

		if EEIdent:
			over = Window.GetControl (0x4200 + 6 + i)
			over.SetVarAssoc ("Index", i)
			over.OnPress (SelectID)
			over.OnRightPress (InfoIdentifyWindow)

	GemRB.SetVar ("Index", None)
	UnselectNoRedraw ()
	return

def UpdateStoreIdentifyWindow (Window):
	global inventory_slots

	pc = GetPC()
	inventory_slots = GemRB.GetSlots (pc, SLOT_INVENTORY)

	callback = lambda: RedrawStoreIdentifyWindow(Window)
	Count = len(inventory_slots) - IdRows
	ScrollBar = Window.GetControlAlias('IDSBAR')
	SetupScrollBar (ScrollBar, "TopIndex", Count, Window.GetControlAlias('IDBTN0'), callback)

	RedrawStoreIdentifyWindow (Window)
	return

ToggleStoreIdentifyWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["ident"], "GUISTORE", LoadIdentifyWindow (GUICommonWindows.ToggleWindow), InitStoreIdentifyWindow, UpdateStoreIdentifyWindow, False, StoreWindowPlacement)
OpenStoreIdentifyWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["ident"], "GUISTORE", LoadIdentifyWindow (GUICommonWindows.OpenWindowOnce), InitStoreIdentifyWindow, UpdateStoreIdentifyWindow, False, StoreWindowPlacement)

def InitStoreStealWindow (Window):
	global LeftButton

	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs

		Window.AliasControls ({ 'STEAL' : 0, 'SWLSBAR' : 4, 'SWRSBAR' : 13,
								'STONAME' : 0x10000002, 'STOTITLE' : 0x10000000, 'STOGOLD' : 0x10000001
								} )

		Window.AliasControls ({'SWLBTN' + str(x) : x+5 for x in range(ItemButtonCount)} )
		Window.AliasControls ({'SWRBTN' + str(x) : x+14 for x in range(ItemButtonCount)} )
		Window.AliasControls ({'SWRLBL' + str(x) : x+0x10000011 for x in range(ItemButtonCount)} )
		Window.AliasControls ({'SWLLBL' + str(x) : x+0x10000008 for x in range(ItemButtonCount)} )
	else:
		offset = 1 if GameCheck.IsAnyEE () else 0 # sigh, random id changes

		Window.AliasControls ({ 'STEAL' : 1, 'SWLSBAR' : 9 + offset, 'SWRSBAR' : 10 + offset,
								'STONAME' : 0x10000027, 'STOTITLE' : 0x10000002, 'STOGOLD' : 0x10000023
							  } )

		Window.AliasControls ({'SWLBTN' + str(x) : x+4 for x in range(ItemButtonCount)} )
		Window.AliasControls ({'SWRBTN' + str(x) : x + 11 + offset for x in range(ItemButtonCount)})
		Window.AliasControls ({'SWRLBL' + str(x) : x+0x10000019 for x in range(ItemButtonCount)} )
		Window.AliasControls ({'SWLLBL' + str(x) : x+0x1000000f for x in range(ItemButtonCount)} )

	for i in range (ItemButtonCount):
		Button = Window.GetControlAlias ('SWLBTN' + str(i))
		Button.SetVarAssoc ("LeftIndex", i)
		SetupBorders (Button)
		Button.OnRightPress (InfoLeftWindow)
		Button.OnPress (SelectSteal)
		Button.SetFont ("NUMBER")
		Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM | IE_GUI_BUTTON_PICTURE, OP_OR)

		Button = Window.GetControlAlias ('SWRBTN' + str(i))
		Button.SetVarAssoc ("RightIndex", i)
		SetupBorders (Button)
		Button.OnRightPress (InfoRightWindow)
		Button.SetFont ("NUMBER")
		Button.SetFlags (IE_GUI_BUTTON_ALIGN_RIGHT | IE_GUI_BUTTON_ALIGN_BOTTOM | IE_GUI_BUTTON_PICTURE, OP_OR)

	GemRB.SetVar ("RightIndex", None)
	GemRB.SetVar ("LeftIndex", None)
	UnselectNoRedraw ()

	# Steal
	LeftButton = Button = Window.GetControlAlias ('STEAL')
	Button.SetText (strrefs["steal"])
	Button.OnPress (StealPressed)

	# bag icon
	Button = Window.GetControl (37)
	if Button:
		Button.SetState (IE_GUI_BUTTON_LOCKED)

	# encumbrance
	if GameCheck.IsPST():
		Button = Window.GetControl (22)
		Button.SetState (IE_GUI_BUTTON_LOCKED)
		Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
		Button.SetFont ('NUMBER')
	else:
		Button.CreateLabel (0x10000043, "NUMBER", "0:",
			IE_FONT_ALIGN_LEFT|IE_FONT_ALIGN_TOP|IE_FONT_SINGLE_LINE)
		Button.CreateLabel (0x10000044, "NUMBER", "0:",
			IE_FONT_ALIGN_RIGHT|IE_FONT_ALIGN_BOTTOM|IE_FONT_SINGLE_LINE)

	return

def UpdateStoreStealWindow (Window):
	global Store, inventory_slots

	#reget store in case of a change
	Store = GemRB.GetStore ()

	pc = GetPC()
	inventory_slots = GemRB.GetSlots (pc, SLOT_INVENTORY)

	# left scrollbar
	callback = lambda: RedrawStoreStealWindow(Window)
	LeftCount = Store['StoreItemCount'] - ItemButtonCount
	SetupScrollBar(Window.GetControlAlias('SWLSBAR'), "LeftTopIndex", LeftCount, Window.GetControlAlias('SWLBTN0'), callback)

	# right scrollbar
	RightCount = len(inventory_slots) - ItemButtonCount
	SetupScrollBar(Window.GetControlAlias('SWRSBAR'), "RightTopIndex", RightCount, Window.GetControlAlias('SWRBTN0'), callback)

	LeftButton.SetState (IE_GUI_BUTTON_DISABLED)
	RedrawStoreStealWindow (Window)
	return

ToggleStoreStealWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["steal"], "GUISTORE", GUICommonWindows.ToggleWindow, InitStoreStealWindow, UpdateStoreStealWindow, False, StoreWindowPlacement)
OpenStoreStealWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["steal"], "GUISTORE", GUICommonWindows.OpenWindowOnce, InitStoreStealWindow, UpdateStoreStealWindow, False, StoreWindowPlacement)

def InitStoreDonateWindow (Window):
	Window.AddAlias('WINDONAT')

	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs
		Window.AliasControls ({ 'DONATE' : 2, 'STOTEDIT' : 3, 'STOPLUS' : 4,
								'STOMINUS' : 5, 'STOTITLE' : 0x10000005, 'STOGOLD' : 0x10000006
							  } )
	else:
		Window.AliasControls ({ 'DONATE' : 3, 'STOTEDIT' : 5, 'STOPLUS' : 6,
								'STOMINUS' : 7, 'STOTITLE' : 0x10000007, 'STOGOLD' : 0x10000008
							  } )

	# graphics
	Button = Window.GetControl (10)
	if Button:
		Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_OR)
		Button.SetState (IE_GUI_BUTTON_LOCKED)

	# Donate
	Button = Window.GetControlAlias ('DONATE')
	Button.SetText (strrefs["donate"])
	Button.OnPress (DonateGold)
	Button.MakeDefault()

	# Entry
	Field = Window.GetControlAlias ('STOTEDIT')
	Field.SetText ("0")
	Field.OnChange (lambda: UpdateStoreDonateWindow(Window))
	Field.SetFlags (IE_GUI_TEXTEDIT_ALPHACHARS, OP_NAND)
	Field.Focus()

	def SetItemAmount (Number):
		MaxAmount = GemRB.GameGetPartyGold()
		if Number < 0:
			Number = 0
		elif Number > MaxAmount:
			Number = MaxAmount
		Field.SetText (str(Number))
		Button = Window.GetControlAlias ("DONATE")
		Button.SetDisabled (not Number)

	# +
	Button = Window.GetControlAlias ('STOPLUS')
	Button.OnPress (lambda: SetItemAmount(Field.QueryInteger() + 1))
	Button.SetActionInterval (50)
	# -
	Button = Window.GetControlAlias ('STOMINUS')
	Button.OnPress (lambda: SetItemAmount(Field.QueryInteger() - 1))
	Button.SetActionInterval (50)
	return

def UpdateStoreDonateWindow (Window):
	UpdateStoreCommon (Window, "STOTITLE", None, "STOGOLD")
	Field = Window.GetControl (5)
	donation = int("0"+Field.QueryText ())
	gold = GemRB.GameGetPartyGold ()
	if donation>gold:
		donation = gold
		Field.SetText (str(gold) )

	Button = Window.GetControlAlias ("DONATE")
	Button.SetDisabled(not donation)
	return

ToggleStoreDonateWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["donate"], "GUISTORE", GUICommonWindows.ToggleWindow, InitStoreDonateWindow, UpdateStoreDonateWindow, False, StoreWindowPlacement)
OpenStoreDonateWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["donate"], "GUISTORE", GUICommonWindows.OpenWindowOnce, InitStoreDonateWindow, UpdateStoreDonateWindow, False, StoreWindowPlacement)

def InitStoreHealWindow (Window):
	Window.AddAlias('WINHEAL')

	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs
		Window.AliasControls ({ 'HWSBAR' : 4, 'HEALBTN' : 3, 'HWTA' : 13,
								 'HWPRICE' : 0x10000001, 'STOGOLD' : 0x10000000, 'STOTITLE' : 0x0fffffff
								 } )
		Window.AliasControls ({'HWLBTN' + str(x) : x+5 for x in range(HealRows)} )
	else:
		Window.AliasControls ({ 'HWSBAR' : 7, 'HEALBTN' : 5, 'HWTA' : 23,
								 'HWPRICE' : 0x10000003, 'STOGOLD' : 0x10000001, 'STOTITLE' : 0x10000000
								 } )
		Window.AliasControls ({'HWLBTN' + str(x) : x+8 for x in range(ItemButtonCount)})

	#spell buttons
	for i in range (HealRows):
		Button = Window.GetControlAlias ('HWLBTN' + str(i))
		Button.SetFlags (IE_GUI_BUTTON_RADIOBUTTON, OP_OR)
		Button.OnPress (lambda: UpdateStoreHealWindow(Window))
		Button.OnRightPress (InfoHealWindow)
		Button.SetVarAssoc ("Index", i)
		if EEHeal:
			over = Window.GetControl (0x4300 + 5 + i)
			over.SetFlags (IE_GUI_BUTTON_RADIOBUTTON, OP_OR)
			over.OnPress (lambda: UpdateStoreHealWindow(Window))
			over.OnRightPress (InfoHealWindow)
			over.SetVarAssoc ("Index", i)

	UnselectNoRedraw ()

	# price tag
	Label = Window.GetControlAlias ('HWPRICE')
	Label.SetText ("0")

	# Heal
	Button = Window.GetControlAlias ('HEALBTN')
	Button.SetText (strrefs["heal"])
	Button.OnPress (BuyHeal)
	Button.SetDisabled (True)

	callback = lambda: UpdateStoreHealWindow(Window)
	Count = Store['StoreCureCount'] - HealRows
	SetupScrollBar(Window.GetControlAlias('HWSBAR'), "TopIndex", Count, Window.GetControlAlias('HWLBTN0'), callback)

	return

def UpdateStoreHealWindow (Window):
	UpdateStoreCommon (Window, "STOTITLE", None, "STOGOLD")
	TopIndex = GemRB.GetVar ("TopIndex")
	Index = GemRB.GetVar ("Index") + TopIndex
	pc = GemRB.GameGetSelectedPCSingle ()
	labelOffset = 0x1000000c
	if GameCheck.IsIWD2():
		labelOffset += 1 # grrr
	elif GameCheck.IsPST():
		labelOffset = 0x10000008

	for i in range (HealRows):
		Cure = GemRB.GetStoreCure (TopIndex+i)
		if EEHeal:
			RowHook ("heal", i, None if not Cure else (IE_GUI_BUTTON_SELECTED if TopIndex + i == Index else IE_GUI_BUTTON_ENABLED))

		Button = Window.GetControlAlias ('HWLBTN' + str(i))
		Label = Window.GetControl (labelOffset+i)
		if Cure:
			Spell = GemRB.GetSpell (Cure['CureResRef'])
			Button.SetSpellIcon (Cure['CureResRef'], 1)
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_NAND)
			Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_OR)
			dead = GemRB.GetPlayerStat (pc, IE_STATE_ID) & STATE_DEAD
			# toggle raise dead/resurrect based on state
			# unfortunately the flags are not set properly in iwd
			if not GameCheck.IsIWD1() and not GameCheck.IsPST() and (  # 3 - non-living
							 (dead and Spell["SpellTargetType"] != 3) or \
							 (not dead and Spell["SpellTargetType"] == 3)):
				# locked and shaded
				Button.SetDisabled (True)
				color = {'r' : 200, 'g' : 0, 'b' : 0, 'a' : 100}
				Button.SetBorder (0, color, 1,1)
			else:
				Button.SetDisabled (False)
				Button.SetBorder (0, None, 0,0)

			CurePrice = str(GetRealCurePrice (Cure))
			GemRB.SetToken ("ITEMNAME", GemRB.GetString (Spell['SpellName']))
			GemRB.SetToken ("ITEMCOST", CurePrice)
			Label.SetText (strrefs["itemnamecost"])

			if TopIndex + i == Index:
				TextArea = Window.GetControlAlias ("HWTA")
				TextArea.SetText (Cure['Description'])
				Label = Window.GetControlAlias ("HWPRICE")
				Label.SetText (CurePrice)
				Button = Window.GetControlAlias ("HEALBTN")
				Button.SetDisabled (False)
		else:
			Button.SetDisabled (True)
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
			Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_NAND)
			Button.SetBorder (0, None, 0,0)
			Label.SetText ("")

	return

ToggleStoreHealWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["heal"], "GUISTORE", LoadHealWindow (GUICommonWindows.ToggleWindow), InitStoreHealWindow, UpdateStoreHealWindow, False, StoreWindowPlacement)
OpenStoreHealWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["heal"], "GUISTORE", LoadHealWindow (GUICommonWindows.OpenWindowOnce), InitStoreHealWindow, UpdateStoreHealWindow, False, StoreWindowPlacement)

def InitStoreRumourWindow (Window):
	Window.AddAlias('WINRUMOR')

	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs
		# ... in case any mod adds rumours, since there are no such stores by default
		Window.AliasControls ({ 'STOTITLE' : 0x1000000a, 'STOGOLD' : 0x1000000b})
		Window.DeleteControl (16)
	else:
		Window.AliasControls ({ 'STOTITLE' : 0x10000011, 'STOGOLD' : 0x10000012})

	#removing those pesky labels
	if not (GameCheck.IsIWD2 () or GameCheck.IsBG1 ()):
		for i in range (5):
			Window.DeleteControl (0x10000005+i)

	TextArea = None
	if GameCheck.IsIWD2() or GameCheck.IsPST():
		TextArea = Window.GetControl (13)
	else:
		TextArea = Window.GetControl (11)
	TextArea.SetText (strrefs["rumors"])

	#tavern quality image
	if GameCheck.IsBG1() or GameCheck.IsBG2OrEE ():
		BAM = "TVRNQUL%d"% ((Store['StoreFlags']>>9)&3)
		Button = Window.GetControl (12)
		Button.SetSprites (BAM, 0, 0, 0, 0, 0)
		Button.SetState (IE_GUI_BUTTON_LOCKED)

	# this scrollbar must be unhidden because it is falsely linked to a TextArea
	ScrollBar = Window.GetControl (5)
	ScrollBar.SetVisible(True)

	callback = lambda: UpdateStoreRumourWindow(Window)
	Count = Store['StoreDrinkCount'] - 5
	SetupScrollBar(ScrollBar, "TopIndex", Count, None, callback)

	UpdateStoreRumourWindow(Window)
	return

def UpdateStoreRumourWindow (Window):
	UpdateStoreCommon (Window, "STOTITLE", None, "STOGOLD")
	TopIndex = GemRB.GetVar ("TopIndex")
	DrinkButtonCount = ItemButtonCount + 1
	offset = 0
	if GameCheck.IsIWD2():
		offset = 40
		DrinkButtonCount += 1 # shows even more than with inventories
	for i in range (DrinkButtonCount):
		Drink = GemRB.GetStoreDrink (TopIndex+i)
		Button = Window.GetControl (i+offset)
		Button.SetVarAssoc ("Index", i)
		if Drink:
			if GameCheck.IsIWD2():
				Button.SetText (GemRB.GetString (Drink['DrinkName']))
				CostLabel = Window.GetControl (0x10000000+29+i)
				CostLabel.SetText (str(Drink['Price']))
			else:
				GemRB.SetToken ("ITEMNAME", GemRB.GetString (Drink['DrinkName']))
				GemRB.SetToken ("ITEMCOST", str(Drink['Price']) )
				Button.SetText (strrefs["itemnamecost"])
				if GameCheck.IsBG1 ():
					CostLabel = Window.GetControl (0x10000005 + i)
					CostLabel.SetText (str(Drink['Price']))
					Button.SetText (Drink['DrinkName'])
			Button.SetState (IE_GUI_BUTTON_ENABLED)
			Button.OnPress (GulpDrink)
		else:
			Button.SetText ("")
			Button.SetDisabled (True)
			if GameCheck.IsIWD2():
				CostLabel = Window.GetControl (0x10000000+29+i)
				CostLabel.SetText ("")
			elif GameCheck.IsBG1 ():
				CostLabel = Window.GetControl (0x10000005 + i)
				CostLabel.SetText ("")
	return

ToggleStoreRumourWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["rumour"], "GUISTORE", GUICommonWindows.ToggleWindow, InitStoreRumourWindow, UpdateStoreRumourWindow, False, StoreWindowPlacement)
OpenStoreRumourWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["rumour"], "GUISTORE", GUICommonWindows.OpenWindowOnce, InitStoreRumourWindow, UpdateStoreRumourWindow, False, StoreWindowPlacement)

def InitStoreRentWindow (Window):
	Window.AddAlias('WINRENT')

	PositionStoreWinRelativeTo(Window)

	if GameCheck.IsPST():
		# remap controls, so we can avoid too many ifdefs
		Window.AliasControls ({ 'RENTBTN' : 8, 'RENTTA' : 9,
								 'STOTITLE' : 0x1000000a, 'STOGOLD' : 0x1000000b, 'RENTLBL' : 0x1000000c
								 } )
	else:
		Window.AliasControls ({ 'RENTBTN' : 11, 'RENTTA' : 12,
								 'STOTITLE' : 0x10000008, 'STOGOLD' : 0x10000009, 'RENTLBL' : 0x1000000d
								 } )

	# room types
	RentIndex = -1
	for i in range (4):
		ok = Store['StoreRoomPrices'][i] or 0
		if ok >= 0:
			RentIndex = i
			break

	# RentIndex needs to be set before SetVarAssoc
	GemRB.SetVar ("RentIndex", RentIndex)

	for i in range (4):
		ok = Store['StoreRoomPrices'][i]
		Button = Window.GetControl (i)
		Button.OnPress (lambda: UpdateStoreRentWindow(Window))
		if not ok:
			Button.SetState (IE_GUI_BUTTON_DISABLED) #disabled room icons are selected, not disabled
		else:
			Button.SetVarAssoc ("RentIndex", i)

		Button = Window.GetControl (i+4)
		Button.SetText (roomnames[i])
		if EERent:
			Button.SetFont (EEUI.StyleFont ("label"))
		Button.OnPress (lambda: UpdateStoreRentWindow(Window))
		Button.SetFlags (IE_GUI_BUTTON_RADIOBUTTON, OP_OR)
		
		if GameCheck.IsBG1():
			#these bioware guys screw up everything possible
			#remove this line if you fixed guistore
			Button.SetSprites ("GUISTROC",0, 1,2,0,3)
		
		if not ok:
			Button.SetState (IE_GUI_BUTTON_DISABLED)
		else:
			Button.SetVarAssoc ("RentIndex", i)

	# Rent
	Button = Window.GetControlAlias ('RENTBTN')
	Button.SetText (strrefs["rent"])
	Button.OnPress (RentRoom)
	return

def UpdateStoreRentWindow (Window):
	PortraitWindow = GemRB.GetView ("PORTWIN")
	if PortraitWindow:
		PortraitWindow.SetDisabled (True)

	UpdateStoreCommon (Window, "STOTITLE", None, "STOGOLD")
	RentIndex = GemRB.GetVar ("RentIndex")
	if EERent:
		for i in range (4):
			Window.GetControl (i + 4).SetColor (EE_SELECTED if i == RentIndex else EEUI.StyleColor ("normal"))
	Button = Window.GetControlAlias ('RENTBTN')
	Label = Window.GetControlAlias ('RENTLBL')
	if RentIndex is not None:
		TextArea = Window.GetControlAlias ('RENTTA')
		TextArea.SetText (roomdesc[RentIndex])
		price = Store['StoreRoomPrices'][RentIndex] or 0
		Label.SetText (str(price) )
		Button.SetState (IE_GUI_BUTTON_ENABLED)
	else:
		Label.SetText ("0" )
		Button.SetState (IE_GUI_BUTTON_DISABLED)
	return

ToggleStoreRentWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["rent"], "GUISTORE", LoadRentWindow (GUICommonWindows.ToggleWindow), InitStoreRentWindow, UpdateStoreRentWindow, False, StoreWindowPlacement)
OpenStoreRentWindow = GUICommonWindows.CreateTopWinLoader(windowIDs["rent"], "GUISTORE", LoadRentWindow (GUICommonWindows.OpenWindowOnce), InitStoreRentWindow, UpdateStoreRentWindow, False, StoreWindowPlacement)

def UpdateStoreCommon (Window, title, name, gold):
	if Store['StoreName'] != -1:
		Label = Window.GetControlAlias (title)
		if GameCheck.IsIWD2():
			# targos store is a good test - wouldn't fit as uppercase either
			Label.SetText (Store['StoreName'])
		else:
			Label.SetText (GemRB.GetString (Store['StoreName']).upper ())

	if name:
		Label = Window.GetControlAlias (name)
		if Bag:
			Label.SetText (Bag['StoreName'])
		else:
			pc = GemRB.GameGetSelectedPCSingle ()
			Label.SetText (GemRB.GetPlayerName (pc, 0))

	Label = Window.GetControlAlias (gold)
	Label.SetText (str(GemRB.GameGetPartyGold ()))
	return

def GetPC():
	global PreviousPC

	if PreviousPC:
		pc = GemRB.GameGetSelectedPCSingle ()
		if PreviousPC != pc:
			PreviousPC = pc
			# reset the store indices, to prevent overscrolling
			GemRB.SetVar ("RightIndex", 0)
			GemRB.SetVar ("RightTopIndex", 0)
			GemRB.SetVar ("Index", 0)
			GemRB.SetVar ("TopIndex", 0)
			UnselectBag ()
			GemRB.CloseRighthandStore ()
			UnselectNoRedraw ()
	else:
		PreviousPC = GemRB.GameGetSelectedPCSingle ()
		pc = PreviousPC

	return pc

# Unselects all the selected buttons, so they are not preselected in other windows
def UnselectNoRedraw ():
	pc = GemRB.GameGetSelectedPCSingle ()
	LeftCount = Store['StoreItemCount']
	for i in range (LeftCount, 0, -1):
		Flags = GemRB.IsValidStoreItem (pc, i-1, ITEM_STORE)&SHOP_SELECT
		if Flags:
			GemRB.ChangeStoreItem (pc, i-1, SHOP_BUY|SHOP_SELECT)

	RightCount = len (inventory_slots)
	for Slot in range (RightCount):
		Flags = GemRB.IsValidStoreItem (pc, inventory_slots[Slot], ITEM_PC) & SHOP_SELECT
		if Flags:
			GemRB.ChangeStoreItem (pc, inventory_slots[Slot], SHOP_SELL|SHOP_SELECT)
			# same code for ID, so no repeat needed

def SelectID (btn):
	pc = GemRB.GameGetSelectedPCSingle ()
	Index = btn.Value + GemRB.GetVar ("TopIndex")
	GemRB.ChangeStoreItem (pc, inventory_slots[Index], SHOP_ID|SHOP_SELECT)
	RedrawStoreIdentifyWindow (btn.Window)
	return

def SelectBuy (btn):
	pc = GemRB.GameGetSelectedPCSingle ()
	LeftIndex = btn.Value + GemRB.GetVar("LeftTopIndex")
	GemRB.ChangeStoreItem (pc, LeftIndex, SHOP_BUY|SHOP_SELECT)
	RedrawStoreShoppingWindow (GemRB.GetView('WINSHOP'))
	return
	
def SelectSteal(btn):
	pc = GemRB.GameGetSelectedPCSingle ()
	LeftIndex = btn.Value + GemRB.GetVar("LeftTopIndex")
	isSelected = GemRB.IsValidStoreItem (pc, LeftIndex, ITEM_STORE) & SHOP_SELECT
	UnselectNoRedraw()

	if not isSelected:
		GemRB.ChangeStoreItem (pc, LeftIndex, SHOP_STEAL | SHOP_SELECT)
	else:
		GemRB.SetVar("LeftIndex", None)
	RedrawStoreStealWindow (btn.Window)
	return

def ToBackpackPressed ():
	pc = GemRB.GameGetSelectedPCSingle ()
	LeftCount = Store['StoreItemCount']
	#going backwards because removed items shift the slots
	for i in range (LeftCount, 0, -1):
		Flags = GemRB.IsValidStoreItem (pc, i-1, ITEM_STORE)&SHOP_SELECT
		if Flags:
			GemRB.ChangeStoreItem (pc, i-1, SHOP_BUY)

	UpdateStoreShoppingWindow (GemRB.GetView('WINSHOP'))
	return

def BuyPressed ():
	if (BuySum>GemRB.GameGetPartyGold ()):
		ErrorWindow (strrefs["itemstoocostly"])
		return

	pc = GemRB.GameGetSelectedPCSingle ()
	LeftCount = Store['StoreItemCount']
	#going backwards because removed items shift the slots
	for i in range (LeftCount, 0, -1):
		Flags = GemRB.IsValidStoreItem (pc, i-1, ITEM_STORE)&SHOP_SELECT
		if Flags:
			Slot = GemRB.GetStoreItem (i-1)
			Item = GemRB.GetItem (Slot['ItemResRef'])
			Price = GetRealPrice (pc, "sell", Item, Slot) * Slot['Purchased']
			if Price <= 0:
				Price = Slot['Purchased']

			if GemRB.ChangeStoreItem (pc, i-1, SHOP_BUY):
				GemRB.GameSetPartyGold (GemRB.GameGetPartyGold ()-Price)

	UpdateStoreShoppingWindow (GemRB.GetView('WINSHOP'))
	return

def SelectSell (btn):
	pc = GemRB.GameGetSelectedPCSingle ()
	RightIndex = btn.Value + GemRB.GetVar("RightTopIndex")
	if not Bag:
		RightIndex = inventory_slots[RightIndex]
	#bags may be clickable despite not being sellable
	Flags = GemRB.IsValidStoreItem (pc, RightIndex, ITEM_BAG if Bag else ITEM_PC)
	if Flags & SHOP_SELL:
		GemRB.ChangeStoreItem (pc, RightIndex, SHOP_SELL|SHOP_SELECT)
		RedrawStoreShoppingWindow (GemRB.GetView('WINSHOP'))
	return

def ToBagPressed ():
	pc = GemRB.GameGetSelectedPCSingle ()
	RightCount = len (inventory_slots)
	#no need to go reverse
	for Slot in range (RightCount):
		Flags = GemRB.IsValidStoreItem (pc, inventory_slots[Slot], ITEM_PC)
		if Flags & SHOP_SELECT:
			GemRB.ChangeStoreItem (pc, inventory_slots[Slot], SHOP_SELL)

	UpdateStoreShoppingWindow (GemRB.GetView('WINSHOP'))
	return

def SellPressed ():
	pc = GemRB.GameGetSelectedPCSingle ()
	if Bag:
		RightCount = Bag['StoreItemCount']
		#going backwards because removed items shift the slots
		for Slot in range (RightCount-1, -1, -1):
			Flags = GemRB.IsValidStoreItem (pc, Slot, ITEM_BAG)
			if Flags & SHOP_SELECT:
				#NOTE: what if the transaction fails?
				GemRB.ChangeStoreItem (pc, Slot, SHOP_SELL)
	else:
		RightCount = len (inventory_slots)
		#no need to go reverse
		for Slot in range (RightCount):
			Flags = GemRB.IsValidStoreItem (pc, inventory_slots[Slot], ITEM_PC) & SHOP_SELECT
			if Flags:
				GemRB.ChangeStoreItem (pc, inventory_slots[Slot], SHOP_SELL)

	GemRB.GameSetPartyGold (GemRB.GameGetPartyGold ()+SellSum)
	GemRB.PlaySound(DEF_SOLD)
	UpdateStoreShoppingWindow (GemRB.GetView('WINSHOP'))
	return

def OpenBag (Window):
	if Bag:
		#nested containers are not openable in bg2,
		#but double-click has another function here
		OpenItemAmountWindow (Window, STORE_BAG)
		return
	if Inventory:
		return
	pc = GemRB.GameGetSelectedPCSingle ()
	RightIndex = GemRB.GetVar ("RightIndex")
	Slot = GemRB.GetSlotItem (pc, inventory_slots[RightIndex])
	Item = GemRB.GetItem (Slot['ItemResRef'])
	if Item['Function'] & ITM_F_CONTAINER:
		GemRB.SetVar ("RightIndex", 0)
		GemRB.SetVar ("RightTopIndex", 0)
		GemRB.SetVar ("Index", 0)
		GemRB.SetVar ("TopIndex", 0)
		UnselectNoRedraw ()
		GemRB.LoadRighthandStore (Slot['ItemResRef'])
		UpdateStoreShoppingWindow (Window)
	return

def CloseBag (Window):
	if not Bag:
		return
	GemRB.SetVar ("RightIndex", 0)
	GemRB.SetVar ("RightTopIndex", 0)
	GemRB.SetVar ("Index", 0)
	GemRB.SetVar ("TopIndex", 0)
	UnselectBag ()
	GemRB.CloseRighthandStore ()
	UnselectNoRedraw ()
	UpdateStoreShoppingWindow (Window)
	return

def UnselectBag ():
	if not Bag:
		return
	pc = GemRB.GameGetSelectedPCSingle ()
	RightCount = Bag['StoreItemCount']
	for Slot in range (RightCount):
		Flags = GemRB.IsValidStoreItem (pc, Slot, ITEM_BAG)
		if Flags & SHOP_SELECT:
			GemRB.ChangeStoreItem (pc, Slot, SHOP_SELL|SHOP_SELECT)
	return

def RedrawStoreShoppingWindow (Window):
	global BuySum, SellSum

	UpdateStoreCommon (Window, "STOTITLE", "STONAME", "STOGOLD")
	pc = GemRB.GameGetSelectedPCSingle ()

	LeftTopIndex = GemRB.GetVar ("LeftTopIndex")
	RightTopIndex = GemRB.GetVar ("RightTopIndex")
	LeftCount = Store['StoreItemCount']
	BuySum = 0
	selected_count = 0
	for i in range (LeftCount):
		if GemRB.IsValidStoreItem (pc, i, ITEM_STORE) & SHOP_SELECT:
			Slot = GemRB.GetStoreItem (i)
			Item = GemRB.GetItem (Slot['ItemResRef'])
			selected_count += 1
			if Inventory:
				Price = 1
			else:
				Price = GetRealPrice (pc, "sell", Item, Slot) * Slot['Purchased']
			if Price <= 0:
				Price = Slot['Purchased']
			BuySum = BuySum + Price

	if Bag:
		RightCount = Bag['StoreItemCount']
	else:
		RightCount = len(inventory_slots)
	SellSum = 0
	for i in range (RightCount):
		if Bag:
			Flags = GemRB.IsValidStoreItem (pc, i, ITEM_BAG)
		else:
			Flags = GemRB.IsValidStoreItem (pc, inventory_slots[i], ITEM_PC)
		if Flags & SHOP_SELECT:
			if Bag:
				Slot = GemRB.GetStoreItem (i, STORE_BAG)
			else:
				Slot = GemRB.GetSlotItem (pc, inventory_slots[i])
			Item = GemRB.GetItem (Slot['ItemResRef'])
			if Inventory:
				Price = 1
			else:
				Price = GetRealPrice (pc, "buy", Item, Slot)
				if Bag:
					Price *= Slot['Purchased']
			if Flags & SHOP_ID:
				Price = 1
			SellSum = SellSum + Price

	Label = Window.GetControlAlias ('PRICEB')
	if Inventory:
		Label.SetText ("")
	else:
		Label.SetText (str(BuySum) )

	# shade the inventory icon if it is full
	free_slots = len(GemRB.GetSlots (pc, SLOT_INVENTORY, -1))
	Button = Window.GetControl (44)
	if Button:
		if free_slots == 0:
			Button.SetState (IE_GUI_BUTTON_PRESSED)
		else:
			Button.SetState (IE_GUI_BUTTON_LOCKED)

	# also disable the button if the inventory is full
	if BuySum and selected_count <= free_slots:
		LeftButton.SetState (IE_GUI_BUTTON_ENABLED)
	else:
		LeftButton.SetState (IE_GUI_BUTTON_DISABLED)

	Label = Window.GetControlAlias ('PRICES')
	if Inventory:
		Label.SetText ("")
	else:
		Label.SetText (str(SellSum) )
	if SellSum:
		RightButton.SetState (IE_GUI_BUTTON_ENABLED)
	else:
		RightButton.SetState (IE_GUI_BUTTON_DISABLED)

	if GameCheck.IsBG2OrEE ():
		CloseBagButton = Window.GetControl (50)
		if Bag:
			CloseBagButton.SetText (37452)
			CloseBagButton.SetState (IE_GUI_BUTTON_ENABLED)
			CloseBagButton.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_NAND)
		else:
			CloseBagButton.SetText (None)
			CloseBagButton.SetState (IE_GUI_BUTTON_LOCKED)
			CloseBagButton.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)

	for i in range (ShopCount):
		if i+LeftTopIndex<LeftCount:
			Slot = GemRB.GetStoreItem (i+LeftTopIndex)
		else:
			Slot = None
		Button = Window.GetControlAlias ('LBTN' + str(i))
		Label = Window.GetControlAlias ('LLBL' + str(i))
		SetupItems (pc, Slot, Button, Label, i, ITEM_STORE)

		if i+RightTopIndex<RightCount:
			if Bag:
				Slot = GemRB.GetStoreItem (i+RightTopIndex, STORE_BAG)
			else:
				Slot = GemRB.GetSlotItem (pc, inventory_slots[i+RightTopIndex])
		else:
			Slot = None
		Button = Window.GetControlAlias ('RBTN' + str(i))
		Label = Window.GetControlAlias ('RLBL' + str(i))
		SetupItems (pc, Slot, Button, Label, i, ITEM_BAG if Bag else ITEM_PC)

	if GameCheck.IsPST():
		InventoryCommon.SetEncumbranceLabels (Window, 25, None, pc)
	else:
		InventoryCommon.SetEncumbranceLabels (Window, 0x10000043, 0x10000044, pc)
	return

def OpenItemAmountWindow (ShopWin, store = STORE_MAIN):
	global MaxAmount

	wid = 16
	if GameCheck.IsIWD2() or GameCheck.IsIWD1():
		wid = 20
	elif GameCheck.IsBG2OrEE ():
		pass
	else:
		return

	Window = GemRB.LoadWindow (wid, "GUISTORE")
	if store == STORE_MAIN:
		Index = GemRB.GetVar ("LeftIndex") + GemRB.GetVar ("LeftTopIndex")
	else:
		Index = GemRB.GetVar ("RightIndex") + GemRB.GetVar ("RightTopIndex")
	Slot = GemRB.GetStoreItem (Index, store)
	Amount = Slot['Purchased']
	if Amount == 0:
		Amount = 1
	MaxAmount = Slot['Amount']
	if MaxAmount == -1:
		MaxAmount = 999

	# item icon
	Icon = Window.GetControl (0)
	Icon.SetFlags (IE_GUI_BUTTON_PICTURE | IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	Icon.SetItemIcon (Slot['ItemResRef'])

	# item amount
	Text = Window.GetControl (6)
	Text.SetText (str (Amount))
	Text.SetFlags (IE_GUI_TEXTEDIT_ALPHACHARS, OP_NAND)
	Text.Focus()

	def SetItemAmount (Number):
		if Number < 0:
			Number = 0
		elif Number > MaxAmount:
			Number = MaxAmount
		Text.SetText (str (Number))

	# Decrease
	Button = Window.GetControl (4)
	Button.OnPress (lambda: SetItemAmount(Text.QueryInteger() - 1))
	Button.SetActionInterval (200)

	# Increase
	Button = Window.GetControl (3)
	Button.OnPress (lambda: SetItemAmount(Text.QueryInteger() + 1))
	Button.SetActionInterval (200)

	def CloseAmountWindow():
		Window.Close()
		UpdateStoreShoppingWindow(ShopWin)

	def Confirm():
		ConfirmItemAmount(Text.QueryInteger(), store, Index)
		CloseAmountWindow()

	# Done
	Button = Window.GetControl (2)
	Button.SetText (11973)
	Button.OnPress (Confirm)
	Button.MakeDefault ()

	# Cancel
	Button = Window.GetControl (1)
	Button.SetText (13727)
	Button.OnPress (CloseAmountWindow)

	Window.ShowModal (MODAL_SHADOW_GRAY)
	return

def ConfirmItemAmount (Number, store, Index):
	global MaxAmount

	if Number > MaxAmount:
		Number = MaxAmount
	elif Number < 0:
		Number = 0
	GemRB.SetPurchasedAmount (Index, Number, store)

	return

def RedrawStoreIdentifyWindow (Window):
	UpdateStoreCommon (Window, "STOTITLE", "STONAME", "STOGOLD")
	TopIndex = GemRB.GetVar ("TopIndex")
	pc = GemRB.GameGetSelectedPCSingle ()
	Count = len(inventory_slots)
	IDPrice = Store['IDPrice']

	Selected = 0
	for Slot in range (0, Count):
		flags = GemRB.IsValidStoreItem (pc, inventory_slots[Slot], ITEM_PC)
		if flags & SHOP_ID and flags & SHOP_SELECT:
			Selected += 1

	for i in range (IdRows):
		if TopIndex+i<Count:
			Slot = GemRB.GetSlotItem (pc, inventory_slots[TopIndex+i])
		else:
			Slot = None
		Button = Window.GetControlAlias ("IDBTN" + str(i))
		# TODO: recheck iwd2 vs non-pst really differ
		if GameCheck.IsIWD2():
			Label = Window.GetControl (0x1000000d+i)
		elif GameCheck.IsPST():
			Label = Window.GetControl (0x10000009+i)
		else:
			Label = Window.GetControl (0x1000000c+i)

		if Slot:
			Flags = GemRB.IsValidStoreItem (pc, inventory_slots[TopIndex+i], ITEM_PC)
			Item = GemRB.GetItem (Slot['ItemResRef'])
			Button.SetItemIcon (Slot['ItemResRef'], 0)
			if Item['MaxStackAmount'] > 1:
				Button.SetText (str(Slot['Usages0']))
			else:
				Button.SetText ("")
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_NAND)
			Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_OR)
			if Flags & SHOP_ID:
				if Flags & SHOP_SELECT:
					Button.SetState (IE_GUI_BUTTON_SELECTED)
				else:
					Button.SetState (IE_GUI_BUTTON_ENABLED)

				GemRB.SetToken ("ITEMNAME", GemRB.GetString (Item['ItemName']))
				GemRB.SetToken ("ITEMCOST", str(IDPrice) )
				Button.EnableBorder (0, True)
			else:
				Button.SetState (IE_GUI_BUTTON_DISABLED)
				GemRB.SetToken ("ITEMNAME", GemRB.GetString (Item['ItemNameIdentified']))
				GemRB.SetToken ("ITEMCOST", str(0) )
				Button.EnableBorder (0, False)

			Label.SetText (strrefs["itemnamecost"])
			if EEIdent:
				RowHook ("id", i, IE_GUI_BUTTON_SELECTED if Flags & SHOP_ID and Flags & SHOP_SELECT else IE_GUI_BUTTON_ENABLED)
		else:
			Button.SetState (IE_GUI_BUTTON_DISABLED)
			Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
			Button.SetFlags (IE_GUI_BUTTON_PICTURE, OP_NAND)
			Button.SetText ("")
			Label.SetText ("")
			if EEIdent:
				RowHook ("id", i, None)

	Button = Window.GetControlAlias ("IDLBTN")
	Label = Window.GetControlAlias ("IDPRICE")
	if Selected:
		Button.SetState (IE_GUI_BUTTON_ENABLED)
		Label.SetText (str(IDPrice * Selected) )
	else:
		Button.SetState (IE_GUI_BUTTON_DISABLED)
		Label.SetText (str(0) )
	return

def IdentifyPressed (Window):
	pc = GemRB.GameGetSelectedPCSingle ()
	Count = len(inventory_slots)

	# get all the selected items
	toID = []
	for Slot in range (0, Count):
		Flags = GemRB.IsValidStoreItem (pc, inventory_slots[Slot], ITEM_PC)
		if Flags & SHOP_SELECT and Flags & SHOP_ID:
			toID.append(Slot)

	# enough gold?
	EndGold = GemRB.GameGetPartyGold () - Store['IDPrice'] * len(toID)
	if EndGold < 0:
		ErrorWindow (strrefs["idtoocostly"])
		return

	# identify
	TextArea = Window.GetControlAlias ("IDTA")
	for i in toID:
		GemRB.ChangeStoreItem (pc, inventory_slots[i], SHOP_ID)
		Slot = GemRB.GetSlotItem (pc, inventory_slots[i])
		Item = GemRB.GetItem (Slot['ItemResRef'])
		# FIXME: some items have the title, some don't - figure it out
		TextArea.Append(Item['ItemNameIdentified'])
		TextArea.Append("\n\n")
		TextArea.Append(Item['ItemDescIdentified'])
		TextArea.Append("\n\n\n")
	GemRB.GameSetPartyGold (EndGold)

	UpdateStoreIdentifyWindow (Window)
	return

def InfoIdentifyWindow ():
	Index = GemRB.GetVar ("Index")
	pc = GemRB.GameGetSelectedPCSingle ()
	Count = len(inventory_slots)
	if Index >= Count:
		return
	Slot = GemRB.GetSlotItem (pc, inventory_slots[Index])
	Item = GemRB.GetItem (Slot['ItemResRef'])
	InfoWindow (Slot, Item)
	return

def InfoLeftWindow (btn):
	Index = btn.Value + GemRB.GetVar("LeftTopIndex")
	Slot = GemRB.GetStoreItem (Index)
	Item = GemRB.GetItem (Slot['ItemResRef'])
	InfoWindow (Slot, Item)
	return

def InfoRightWindow (btn):
	Index = btn.Value + GemRB.GetVar("RightTopIndex")
	if Bag:
		Slot = GemRB.GetStoreItem (Index, STORE_BAG)
		Item = GemRB.GetItem (Slot['ItemResRef'])
	else:
		pc = GemRB.GameGetSelectedPCSingle ()
		Count = len(inventory_slots)
		if Index >= Count:
			return
		Slot = GemRB.GetSlotItem (pc, inventory_slots[Index])
		Item = GemRB.GetItem (Slot['ItemResRef'])
	InfoWindow (Slot, Item)
	return

def InfoWindow (Slot, Item):
	Identify = Slot['Flags'] & IE_INV_ITEM_IDENTIFIED

	Window = GemRB.LoadWindow (windowIDs["iteminfo"], "GUISTORE", StoreWindowPlacement)

	# TODO: check if we can simplify bg2 vs non-pst games to see which label is which
	if GameCheck.IsBG2OrEE ():
		NameLabel = Window.GetControl (0x10000000)
		FakeLabel = Window.GetControl (0x10000007)
	elif GameCheck.IsPST():
		NameLabel = Window.GetControl (0x0fffffff)
		FakeLabel = Window.GetControl (0x10000000)
	else:
		NameLabel = Window.GetControl (0x10000007)
		FakeLabel = Window.GetControl (0x10000000)

	if GameCheck.IsPST():
		aliases = { "INFTA": 4, "INFBTN": 3, "INFIMG": 6 }
	else:
		aliases = { "INFTA": 5, "INFBTN": 4, "INFIMG": 7 }
	Window.AliasControls (aliases)

	#fake label
	FakeLabel.SetText ("")

	#description bam
	if GameCheck.IsBG1() or GameCheck.IsBG2OrEE () or GameCheck.IsPST():
		Button = Window.GetControlAlias ("INFIMG")
		Button.SetFlags (IE_GUI_BUTTON_PICTURE | IE_GUI_BUTTON_CENTER_PICTURES | IE_GUI_BUTTON_NO_IMAGE, OP_OR)
		Button.SetState (IE_GUI_BUTTON_LOCKED)
		if GameCheck.IsPST():
			Button.SetItemIcon (Slot['ItemResRef'], 1)
		else:
			Button.SetItemIcon (Slot['ItemResRef'], 2)

	#slot bam
	Button = Window.GetControl (2)
	Button.SetState (IE_GUI_BUTTON_LOCKED)
	Button.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_OR)
	Button.SetItemIcon (Slot['ItemResRef'], 0)

	TextArea = Window.GetControlAlias ("INFTA")
	if GameCheck.IsIWD1 ():
		TextArea.SetFont ("TOOLFONT", 1)
	if Identify:
		NameLabel.SetText (Item['ItemNameIdentified'])
		TextArea.SetText (Item['ItemDescIdentified'])
	else:
		NameLabel.SetText (Item['ItemName'])
		TextArea.SetText (Item['ItemDesc'])

	#Done
	Button = Window.GetControlAlias ("INFBTN")
	Button.SetText (strrefs["done"])
	Button.OnPress (Window.Close)

	# hide the empty button
	if GameCheck.IsBG2OrEE () or GameCheck.IsIWD2():
		Window.DeleteControl (9)

	Window.ShowModal (MODAL_SHADOW_GRAY)
	return

def StealPressed (btn):
	LeftIndex = GemRB.GetVar("LeftIndex")
	pc = GemRB.GameGetSelectedPCSingle ()
	#percentage skill check, if fails, trigger StealFailed
	#if difficulty = 0 and skill=100, automatic success
	#if difficulty = 0 and skill=50, 50% success
	#if difficulty = 50 and skill=50, 0% success
	skill = GemRB.GetPlayerStat (pc, IE_PICKPOCKET)
	difficulty = GemRB.Roll (1, 100, Store['StealFailure'])
	if skill > difficulty:
		GemRB.ChangeStoreItem (pc, LeftIndex, SHOP_STEAL)
		GemRB.PlaySound(DEF_STOLEN)
		UpdateStoreStealWindow (btn.Window)
	else:
		GemRB.StealFailed ()
		CloseStoreWindow ()
	return

def RedrawStoreStealWindow (Window):
	UpdateStoreCommon (Window, "STOTITLE", "STONAME", "STOGOLD")
	LeftTopIndex = GemRB.GetVar ("LeftTopIndex")
	RightTopIndex = GemRB.GetVar ("RightTopIndex")
	pc = GemRB.GameGetSelectedPCSingle ()
	RightCount = len(inventory_slots)
	for i in range (ItemButtonCount):
		Slot = GemRB.GetStoreItem (i+LeftTopIndex)
		Button = Window.GetControlAlias ('SWLBTN' + str(i))
		Label = Window.GetControlAlias ('SWLLBL' + str(i))
		SetupItems (pc, Slot, Button, Label, i, ITEM_STORE, True)

		if i+RightTopIndex<RightCount:
			Slot = GemRB.GetSlotItem (pc, inventory_slots[i+RightTopIndex])
		else:
			Slot = None
		Button = Window.GetControlAlias ('SWRBTN' + str(i))
		Label = Window.GetControlAlias ('SWRLBL' + str(i))
		SetupItems (pc, Slot, Button, Label, i, ITEM_PC, True)

	# shade the inventory icon if it is full
	free_slots = len(GemRB.GetSlots (pc, SLOT_INVENTORY, -1))
	Button = Window.GetControl (37)
	if Button:
		if free_slots == 0:
			Button.SetState (IE_GUI_BUTTON_PRESSED)
		else:
			Button.SetState (IE_GUI_BUTTON_LOCKED)

	# also disable the button if the inventory is full
	if GemRB.GetVar("LeftIndex") is not None and free_slots:
		LeftButton.SetState (IE_GUI_BUTTON_ENABLED)
	else:
		LeftButton.SetState (IE_GUI_BUTTON_DISABLED)

	if GameCheck.IsPST():
		InventoryCommon.SetEncumbranceLabels (Window, 22, None, pc)
	else:
		InventoryCommon.SetEncumbranceLabels (Window, 0x10000043, 0x10000044, pc)
	return

def SetupItems (pc, Slot, Button, Label, i, storetype, steal = False):
	Button.EnableBorder (0, False)
	Button.EnableBorder (1, False)
	Button.EnableBorder (2, False)

	if Slot == None:
		# BG1 doesnt have empty slots on the window bg
		# instead of GameChecking, just clear data for all instead of setting visibility
		Button.SetPicture(None)
		Button.SetState(IE_GUI_BUTTON_DISABLED)
		Button.SetText("")
		Label.SetVisible(False)
		if EEShop:
			RowHook (storetype == ITEM_STORE, i, None)
		return

	Item = GemRB.GetItem (Slot['ItemResRef'])
	Button.SetItemIcon (Slot['ItemResRef'], 0)
	Label.SetVisible(True)
	if Item['MaxStackAmount'] > 1:
		Button.SetText ( str(Slot['Usages0']) )
	else:
		Button.SetText ("")

	state = IE_GUI_BUTTON_DISABLED
	Price = None
	
	if not GemRB.CanUseItemType (SLOT_ANY, Slot['ItemResRef'], pc):
		Button.EnableBorder (1, True)

	if storetype == ITEM_STORE:
		LeftTopIndex = GemRB.GetVar("LeftTopIndex")
		Price = max(1, GetRealPrice (pc, "buy", Item, Slot))
		Flags = GemRB.IsValidStoreItem (pc, i + LeftTopIndex, storetype)
		if Flags & SHOP_SELECT:
			state = IE_GUI_BUTTON_SELECTED
		elif (Flags & SHOP_STEAL) and steal:
			state = IE_GUI_BUTTON_ENABLED
		elif (Flags & SHOP_BUY) and not steal:
			state = IE_GUI_BUTTON_ENABLED

		if not Inventory:
			Price = max(1, GetRealPrice (pc, "sell", Item, Slot))
	else:
		RightTopIndex = GemRB.GetVar("RightTopIndex")
		index = RightTopIndex + i
		if not Bag:
			index = inventory_slots[index]

		Flags = GemRB.IsValidStoreItem (pc, index, storetype)
		if not steal:
			Price = 1 if Inventory else GetRealPrice(pc, "buy", Item, Slot)

			if Item['Function'] & ITM_F_CONTAINER and not Bag and not Inventory:
				# containers are always clickable
				state = IE_GUI_BUTTON_ENABLED
			elif Flags & SHOP_SELECT:
				state = IE_GUI_BUTTON_SELECTED
			elif Flags & SHOP_SELL and Price > 0:
				state = IE_GUI_BUTTON_ENABLED
			else:
				Button.EnableBorder (2, True)
				state = IE_GUI_BUTTON_DISABLED

	Button.SetState(state)
	if EEShop:
		RowHook (storetype == ITEM_STORE, i, state)
	if Flags & SHOP_ID:
		Name = GemRB.GetString (Item['ItemName'])
		Button.EnableBorder (0, True)
	else:
		Name = GemRB.GetString (Item['ItemNameIdentified'])

	GemRB.SetToken ("ITEMNAME", Name)
	GemRB.SetToken ("ITEMCOST", str(Price))
	# only show the item name?
	if (Inventory or steal) and not GameCheck.IsPST():
		if GameCheck.IsIWD1() or GameCheck.IsIWD2():
			LabelText = GemRB.GetString (24890)
		elif GameCheck.IsBG2OrEE ():
			LabelText = GemRB.GetString (28337)
		elif steal:
			LabelText = Name
		else:
			LabelText = ""
	else:
		LabelText = GemRB.GetString (strrefs["itemnamecost"])

	if (storetype == ITEM_STORE and not steal) or storetype == ITEM_BAG:
		if Slot["Amount"] != -1:
			LabelText = LabelText + " (" + str(Slot["Amount"]) + ")"
	Label.SetText (LabelText)
	return

# handle raisdead.2da price override for raising and resurrecting
def GetRealCurePrice (cure):
	global RaiseDeadTable

	if not RaiseDeadTable:
		RaiseDeadTable = GemRB.LoadTable ("raisdead")
	pc = GemRB.GameGetSelectedPCSingle ()
	raisingPrice = RaiseDeadTable.GetValue (str(GemRB.GetPlayerStat(pc, IE_CLASSLEVELSUM)), "VALUE")
	if cure['CureResRef'].lower() == "sppr504":
		return raisingPrice
	if cure['CureResRef'].lower() == "sppr712":
		return 150 * raisingPrice // 100
	return cure['Price']

def GetRealPrice (pc, mode, Item, Slot):
	# get the base from the item
	price = Item['Price']

	if Item['MaxStackAmount']>1:
		price = price * Slot['Usages0']
	elif Item['MaxCharge']>0:
		price = price * Slot['Usages0'] // Item['MaxCharge']

	# modifier from store properties (in percent)
	if mode == "buy":
		mod = Store['BuyMarkup']
		if GemRB.HasFeat(pc, FEAT_MERCANTILE_BACKGROUND):
			mod += 5
	else:
		mod = Store['SellMarkup']
		if GemRB.HasFeat(pc, FEAT_MERCANTILE_BACKGROUND):
			mod -= 5

	# depreciation works like this:
	# - if you sell the item the first time, SellMarkup is used;
	# - if you sell the item the second time, SellMarkup-DepreciationRate is used;
	# - if you sell the item any more times (N), SellMarkup-N*DepreciationRate is used.
	# NB: there is a minimal price of 20 %, regardless of the amount of depreciation
	# If the storekeep has an infinite amount of the item, only SellMarkup is used.
	# The amount of items sold at the same time doesn't matter! Selling three bows
	# separately will produce less gold then selling them at the same time.
	# We don't care who is the seller, so if the store already has 2 items, there'll be no gain
	if mode == "buy":
		count = GemRB.FindStoreItem (Slot["ItemResRef"])
		if count:
			# jewelry doesn't suffer from deprecation, at least in BG2
			if Item['Type'] in [CommonTables.ItemType.GetRowIndex ("GEM"),
			                    CommonTables.ItemType.GetRowIndex ("RING"),
			                    CommonTables.ItemType.GetRowIndex ("AMULET")]:
				count = 0
			# give at least 20 %
			mod -= count * Store['Depreciation']
			mod = max(mod, 20)
	else:
		# charisma modifier (in percent)
		# a QoL improvement is to grab the best pc for the task
		BarteringPC = BestCharmer if BestCharmer else GemRB.GetVar ("BARTER_PC")
		mod += GemRB.GetAbilityBonus (IE_CHR, GemRB.GetPlayerStat (BarteringPC, IE_CHR) - 1, 0)

		# reputation modifier (in percent, but absolute)
		if RepModTable and not (Store['StoreFlags'] & SHOP_NOREPADJ):
			mod = mod * RepModTable.GetValue (0, GemRB.GameGetReputation() // 10 - 1) // 100

	effprice = price * mod // 100
	#in bg2 even 1gp items can be sold for at least 1gp
	if effprice == 0 and Item['Price'] > 0:
		effprice = 1
	return effprice

def DonateGold ():
	Window = GemRB.GetView('WINDONAT')

	TextArea = Window.GetControl (0)
	TextArea.SetFlags (IE_GUI_TEXTAREA_AUTOSCROLL)

	Button = Window.GetControl (10)
	if Button:
		Button.SetAnimation ("DONATE", 0, A_ANI_PLAYONCE)

	Field = Window.GetControl (5)
	donation = int("0"+Field.QueryText ())

	# for some reason temple donations get a boost to rumour generation,
	# even though comparatively they're higher than drink prices and with
	# the default factor of 3, very quickly guarantee a rumour
	RumourTable = GemRB.LoadTable ("donarumr")
	RumourFactor = RumourTable.GetValue ("RUMORRATE", "VALUE", GTV_INT)
	RumourChance = min(RumourFactor * donation, 100) # cap is from the original
	text = GemRB.GetRumour (RumourChance, Store['TempleRumour'])
	GemRB.GameSetPartyGold (GemRB.GameGetPartyGold ()-donation)
	feedbackSound = DEF_DONATE2
	feedbackString = strrefs['donorfail']
	if GemRB.IncreaseReputation (donation):
		feedbackSound = DEF_DONATE1
		feedbackString = strrefs['donorgood']

	TextArea.Append (feedbackString)
	TextArea.Append ("\n\n")
	if text > -1:
		TextArea.Append (text)
		TextArea.Append ("\n\n")
	GemRB.PlaySound (feedbackSound)
	UpdateStoreDonateWindow (Window)
	return

def InfoHealWindow ():
	Window = GemRB.GetView('WINHEAL')

	UpdateStoreHealWindow (Window)
	Index = GemRB.GetVar ("Index") + GemRB.GetVar ("TopIndex")
	Cure = GemRB.GetStoreCure (Index)
	Spell = GemRB.GetSpell (Cure['CureResRef'])

	Window = GemRB.LoadWindow (windowIDs["cureinfo"], "GUISTORE", StoreWindowPlacement)

	Label = Window.GetControl (0x10000000)
	Label.SetText (Spell['SpellName'])

	Button = Window.GetControl (2)
	Button.SetSpellIcon (Cure['CureResRef'], 1)
	if GameCheck.IsPST():
		Button = Window.GetControl (6)
		Button.SetSpellIcon (Cure['CureResRef'], 2)
		aliases = { "HEALBTN": 3, "HEALTA": 4 }
	else:
		aliases = { "HEALBTN": 5, "HEALTA": 3 }
	Window.AliasControls (aliases)

	TextArea = Window.GetControlAlias ("HEALTA")
	TextArea.SetText (Spell['SpellDesc'])

	#Done
	Button = Window.GetControlAlias ("HEALBTN")
	Button.SetText (strrefs["done"])
	Button.OnPress (Window.Close)

	Window.ShowModal (MODAL_SHADOW_GRAY)
	return

def BuyHeal ():
	Window = GemRB.GetView('WINHEAL')

	Index = GemRB.GetVar ("Index") + GemRB.GetVar ("TopIndex")
	Cure = GemRB.GetStoreCure (Index)
	gold = GemRB.GameGetPartyGold ()
	price = GetRealCurePrice (Cure)
	if gold < price:
		ErrorWindow (strrefs["spelltoocostly"])
		return

	GemRB.GameSetPartyGold (gold - price)
	pc = GemRB.GameGetSelectedPCSingle ()
	Spell = GemRB.GetSpell (Cure['CureResRef'])
	# for anything but raise/resurrect, the talker should be the caster, so
	# self-targeting spells work properly. Raise dead is an exception as
	# the teleporting to the temple would not work otherwise
	if Spell["SpellTargetType"] == 3: # non-living
		GemRB.ApplySpell (pc, Cure['CureResRef'], Store['StoreOwner'])
	else:
		GemRB.ApplySpell (pc, Cure['CureResRef'], pc)

	if SpellTable:
		sound = SpellTable.GetValue(Cure['CureResRef'], "SOUND")
	elif CureTable:
		sound = CureTable.GetValue(Cure['CureResRef'], "SOUND_EFFECT")
	else:
		#if there is no table, simply use the spell's own completion sound
		Spell = GemRB.GetSpell(Cure['CureResRef'])
		sound = Spell['Completion']
	GemRB.PlaySound (sound)
	UpdateStoreHealWindow (Window)
	return

def GulpDrink (btn):
	Window = GemRB.GetView('WINRUMOR')

	TextArea = Window.GetControl (13)
	TextArea.SetFlags (IE_GUI_TEXTAREA_AUTOSCROLL)
	pc = GemRB.GameGetSelectedPCSingle ()
	intox = GemRB.GetPlayerStat (pc, IE_INTOXICATION, 1)
	if intox > 80:
		TextArea.Append (strrefs["toodrunk"])
		TextArea.Append ("\n\n")
		return

	gold = GemRB.GameGetPartyGold ()
	Index = btn.Value + GemRB.GetVar("TopIndex")
	Drink = GemRB.GetStoreDrink (Index)
	if gold < Drink['Price']:
		ErrorWindow (strrefs["drinktoocostly"])
		return

	GemRB.GameSetPartyGold (gold-Drink['Price'])
	GemRB.SetPlayerStat (pc, IE_INTOXICATION, intox+Drink['Strength'])
	text = GemRB.GetRumour (Drink['Strength'], Store['TavernRumour'])
	if text > -1:
		TextArea.Append (text)
		TextArea.Append ("\n\n")
	GemRB.PlaySound (DEF_DRUNK)
	UpdateStoreRumourWindow (Window)
	return

def RentConfirm (Window0):
	RentIndex = GemRB.GetVar ("RentIndex")
	price = Store['StoreRoomPrices'][RentIndex] or 0
	Gold = GemRB.GameGetPartyGold ()
	GemRB.GameSetPartyGold (Gold-price)
	RestTable = GemRB.LoadTable ("restheal")
	healFor = RestTable.GetValue (RentIndex, 0, GTV_INT)
	# TODO: run GemRB.RunRestScripts ()
	# 18 = check that everyone is close by + don't repeat rests
	info = GemRB.RestParty (18, 1, healFor)
	cutscene = info["Cutscene"]

	if RentConfirmWindow:
		RentConfirmWindow.Close ()
	if info["Error"]:
		# notify why resting isn't possible
		ErrorWindow (info["ErrorMsg"])

	Window = GemRB.GetView('WINRENT')
	if cutscene:
		CloseStoreWindow ()
	elif not info["Error"]:
		TextArea = Window.GetControlAlias('RENTTA')
		GemRB.SetToken ("HP", str(healFor))
		TextArea.SetText (strrefs["restedfor"])
		GemRB.SetVar ("RentIndex", None)
		Button = Window.GetControl (RentIndex+4)
		Button.SetState (IE_GUI_BUTTON_ENABLED)
	return

def RentRoom ():
	global RentConfirmWindow

	RentIndex = GemRB.GetVar ("RentIndex")
	price = Store['StoreRoomPrices'][RentIndex] or 0
	Gold = GemRB.GameGetPartyGold ()
	if Gold<price:
		ErrorWindow (strrefs['roomtoocostly'])
		return

	RentConfirmWindow = Window = GemRB.LoadWindow (windowIDs["rentconfirm"], "GUISTORE")

	#confirm
	Button = Window.GetControl (0)
	Button.SetText (strrefs["rest"])
	Button.OnPress (RentConfirm)
	Button.MakeDefault()

	#deny
	Button = Window.GetControl (1)
	Button.SetText (strrefs["cancel"])
	Button.OnPress (Window.Close)
	Button.MakeEscape()

	#textarea
	TextArea = Window.GetControl (3)
	TextArea.SetText (strrefs["confirmrest"])

	Window.ShowModal (MODAL_SHADOW_GRAY)
	return

def ErrorWindow (strref):
	Window = GemRB.LoadWindow (windowIDs["error"], "GUISTORE")

	TextArea = Window.GetControl (3)
	TextArea.SetText (strref)

	#done
	Button = Window.GetControl (0)
	Button.SetText (strrefs["done"])
	Button.OnPress (Window.Close)

	Window.ShowModal (MODAL_SHADOW_GRAY)
	return

###################################################
# End of file GUISTORE.py
