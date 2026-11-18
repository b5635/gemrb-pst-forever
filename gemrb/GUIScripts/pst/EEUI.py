# SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# EEUI.py - builds Enhanced Edition style windows from the JSON layouts that
# tools/eeui/build.py writes into <ee_ui>/layout/. See EE_UI_PLAN.md.
#
# Screens call Available(menu) and, if true, Build(menu) instead of loading a CHU window.
# Build returns (window, controls); controls are keyed by the EE control name, and every
# control (named or not) by its integer index in the menu.

import json
import os
import GemRB
from GUIDefines import *

LOGICAL_W = 1280
LOGICAL_H = 720
WINDOW_PACK = "START"

_layouts = {}
_styles = None
_fonts = None
_nextWindow = [0x7000]
_missing = set ()

def Enabled ():
	return GemRB.GetSystemVariable (SV_EEUI) == 1

def Root ():
	return GemRB.GetSystemVariable (SV_EEUIPATH)

def Load (menu):
	if menu not in _layouts:
		path = os.path.join (Root (), "layout", menu + ".json")
		try:
			with open (path, "r", encoding="utf-8") as f:
				_layouts[menu] = json.load (f)
		except (OSError, ValueError):
			_layouts[menu] = None
	return _layouts[menu]

def Available (menu):
	"""True when the EE layer is on and a converted layout exists for the menu."""
	if not Enabled ():
		return False
	doc = Load (menu)
	return doc is not None and len (doc["controls"]) > 0

def _Warn (msg):
	if msg not in _missing:
		_missing.add (msg)
		print ("EEUI:", msg)

# -- text styles ------------------------------------------------------------------------

def _Styles ():
	global _styles
	if _styles is None:
		try:
			with open (os.path.join (Root (), "styles.json"), "r", encoding="utf-8") as f:
				_styles = json.load (f)["styles"]
		except (OSError, ValueError):
			_styles = {}
	return _styles

def _FontTable ():
	global _fonts
	if _fonts is None:
		_fonts = GemRB.LoadTable ("eeuifont", 1)
	return _fonts

def _HasRow (tbl, style):
	return bool (tbl) and tbl.GetRowIndex (style) >= 0

def StyleFont (style):
	"""Classic bitmap font for an EE style name (eeuifont.2da, FONTDLG when unknown)."""
	tbl = _FontTable ()
	if _HasRow (tbl, style):
		return tbl.GetValue (style, "FONT")
	return "FONTDLG"

def StyleColor (style):
	"""{'r','g','b'} for an EE style, from styles.json (the 2da COLOR column overrides as RRGGBB)."""
	tbl = _FontTable ()
	if _HasRow (tbl, style):
		hexval = tbl.GetValue (style, "COLOR")
		if hexval and hexval != "*" and len (hexval) == 6:
			return {'r': int (hexval[0:2], 16), 'g': int (hexval[2:4], 16), 'b': int (hexval[4:6], 16)}
	rgba = _Styles ().get (style, {}).get ("rgba")
	if rgba:
		return {'r': rgba[0], 'g': rgba[1], 'b': rgba[2]}
	return {'r': 255, 'g': 255, 'b': 255}

def StyleFlags (style):
	"""IE_FONT_* alignment flags from the style's halign/valign."""
	st = _Styles ().get (style, {})
	flags = {"left": IE_FONT_ALIGN_LEFT, "center": IE_FONT_ALIGN_CENTER, "right": IE_FONT_ALIGN_RIGHT}.get (st.get ("halign", "left"), 0)
	v = st.get ("valign", "top")
	if v == "center":
		flags |= IE_FONT_ALIGN_MIDDLE
	elif v == "bottom":
		flags |= IE_FONT_ALIGN_BOTTOM
	else:
		flags |= IE_FONT_ALIGN_TOP
	return flags

# -- strings ----------------------------------------------------------------------------

def Text (spec):
	"""A layout string object -> what Control.SetText takes (a strref int or a str), or None."""
	if not spec:
		return None
	if "strref" in spec:
		return spec["strref"]
	if "text" in spec:
		return spec["text"]
	if "literal" in spec:
		return spec["literal"]
	return None

# -- building ---------------------------------------------------------------------------

def PlateOf (doc):
	"""Name of the background picture the menu is drawn over (EE's Infinity_SetBackground)."""
	pm = doc.get ("plate_menu")
	if not pm:
		return None
	pdoc = Load (pm)
	if not pdoc:
		return None
	for c in pdoc["controls"]:
		if c.get ("mosaic"):
			return c["mosaic"]
	return None

def _ApplyText (ctl, c, single=False):
	text = Text (c.get ("text"))
	style = c.get ("style")
	if style:
		ctl.SetFont (StyleFont (style))
		ctl.SetColor (StyleColor (style))
	if text is not None:
		ctl.SetText (text)

_origin = [0, 0]   # origin of the window being built (popups sit at their bbox)

def _Frame (c):
	x, y, w, h = c["frame"]
	return x - _origin[0], y - _origin[1], w, h

def _Tooltip (ctl, c):
	tip = Text (c.get ("tooltip"))
	if tip is not None:
		ctl.SetTooltip (tip)

_slotDy = [0]

def _MakeButton (win, cid, c):
	x, y, w, h = _Frame (c)
	if not (c.get ("bam") or c.get ("mosaic") or c.get ("text")) and w <= 60 and h <= 60:
		y -= _slotDy[0]     # icon-sized plain buttons are slots in all but name: same offset as slots
	b = win.CreateButton (cid, x, y, w, h)
	if c.get ("bam") and isinstance (c.get ("sequence", 0), int):
		# EE button cycles: 0 normal, 1 highlighted, 2 pressed, 3 disabled
		b.SetSprites (c["bam"], c.get ("sequence", 0), 0, 2, 0, 3)
	elif c.get ("mosaic"):
		b.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
		b.SetPicture (c["mosaic"])
	else:
		b.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
	if c.get ("text"):
		style = c.get ("style", "button")
		b.SetFont (StyleFont (style))
		b.SetColor (StyleColor (style))
		b.SetText (Text (c["text"]))
	_Tooltip (b, c)
	return b

def ControlFlags (c, style):
	"""IE_FONT_* alignment for a control: its own `text align h v`, else the style's."""
	al = c.get ("text_opts", {}).get ("align")
	if not al or not isinstance (al, list):
		return StyleFlags (style)
	h = {"left": IE_FONT_ALIGN_LEFT, "center": IE_FONT_ALIGN_CENTER, "right": IE_FONT_ALIGN_RIGHT}.get (al[0], IE_FONT_ALIGN_LEFT)
	v = {"top": IE_FONT_ALIGN_TOP, "center": IE_FONT_ALIGN_MIDDLE, "bottom": IE_FONT_ALIGN_BOTTOM}.get (al[1] if len (al) > 1 else "center", IE_FONT_ALIGN_MIDDLE)
	return h | v

def _MakeLabel (win, cid, c):
	x, y, w, h = _Frame (c)
	style = c.get ("style", "label")
	lab = win.CreateLabel (cid, x, y, w, h, StyleFont (style), "", ControlFlags (c, style))
	if c.get ("mosaic"):
		lab.SetBackground (c["mosaic"])
	elif c.get ("bam") and isinstance (c.get ("sequence", 0), int):
		lab.SetBackground (GemRB.GetSprite (c["bam"], -1, c.get ("sequence", 0), 0))
	lab.SetColor (StyleColor (style))
	if c.get ("text"):
		lab.SetText (Text (c["text"]))
	return lab

def _MakeTextArea (win, cid, c):
	x, y, w, h = _Frame (c)
	style = c.get ("style", "normal")
	ta = win.CreateTextArea (cid, x, y, w, h, StyleFont (style))
	ta.SetColor (StyleColor (style))
	if c.get ("text"):
		ta.SetText (Text (c["text"]))
	return ta

def Alias (name, ext="bam"):
	"""Name to use for an EE art file whose classic namesake exists (aliases.txt: EE_NAME ALIAS)."""
	global _aliases
	try:
		_aliases
	except NameError:
		_aliases = {}
		try:
			with open (os.path.join (Root (), "aliases.txt"), "r") as f:
				for line in f:
					p = line.split ()
					if len (p) == 2:
						_aliases[p[0].upper ()] = p[1]
		except OSError:
			pass
	return _aliases.get ("%s.%s" % (name.upper (), ext.upper ()), name)

def Controls (menu):
	"""The menu's layout control dicts (empty list when there is none)."""
	doc = Load (menu)
	return doc["controls"] if doc else []

# EE controls whose text is set by Lua at run time (`text lua "name"`)
LUA_TEXT = {
	"versionString": lambda: GemRB.Version,
}

def Find (menu, **match):
	"""Index of the first control of the menu whose fields equal all of `match`
	(for example Find ("START_MAIN", type="button", bam="STARTBUT", sequence=4)), else None."""
	doc = Load (menu)
	if doc is None:
		return None
	for c in doc["controls"]:
		if all (c.get (k) == v for k, v in match.items ()):
			return c["index"]
	return None

def Build (menu, windowId=None, plate=None, skip=(), override=None, ids=None, first=None, reverse=False, fullscreen=False):
	"""Create the window for an EE menu. Returns (window, controls).

	plate: a background picture name to draw behind the controls; None uses the menu's own
	plate (EE's Infinity_SetBackground), False draws none.
	skip: control indices to leave out (EE-only controls that have no classic function).
	override: {index: 'button' | 'textarea' | 'label'} to build a control as another kind.
	first: callable(win) run after the window exists and before any control is made; controls made
	there are drawn on top of all the others.
	reverse: create controls last to first. The engine draws the first-created control on top, so use
	this when the EE menu relies on later controls overlapping earlier ones (text over a picture).
	fullscreen: build a modal menu as a full-screen window on its plate instead of a popup box.
	ids: {index: control id} to give controls the id the classic script expects (default index + 1)."""
	override = override or {}
	ids = ids or {}
	doc = Load (menu)
	if doc is None:
		raise RuntimeError ("EEUI: no layout for " + menu)
	if windowId is None:
		windowId = _nextWindow[0]
		_nextWindow[0] += 1
	_slotDy[0] = doc.get ("slot_dy", 0)
	popup = bool (doc.get ("modal") and doc.get ("bbox")) and not fullscreen
	if popup:
		# popups: a window the size of the menu, where EE puts it
		bx, by, bw, bh = doc["bbox"]
		_origin[0], _origin[1] = bx, by
		frame = {'x': bx, 'y': by, 'w': bw, 'h': bh}
		if plate is None:
			plate = False
	else:
		_origin[0], _origin[1] = 0, 0
		frame = {'x': 0, 'y': 0, 'w': LOGICAL_W, 'h': LOGICAL_H}
	win = GemRB.CreateWindow (windowId, WINDOW_PACK, frame)
	if plate is None:
		plate = PlateOf (doc)
	if plate:
		win.SetBackground (plate)
	controls = {}
	if first:
		first (win)
	if popup:
		# the full-size backdrop label becomes the window background (keeps it under every control)
		for c in doc["controls"]:
			if c["type"] == "label" and c.get ("mosaic") and c.get ("frame") == doc["bbox"]:
				win.SetBackground (c["mosaic"])
				skip = set (skip) | {c["index"]}
				break
	for c in (reversed (doc["controls"]) if reverse else doc["controls"]):
		kind = override.get (c["index"], c["type"])
		cid = ids.get (c["index"], (0x3000 if ids else 1) + c["index"])
		if "frame" not in c or c["index"] in skip:
			continue
		if kind == "button":
			ctl = _MakeButton (win, cid, c)
		elif kind == "slot":
			x, y, w, h = _Frame (c)
			# EE slot areas are measured from the menu's top, not the centred menu box: measured
			# against the inventory plate they sit exactly the menu's vertical offset too low
			y -= doc.get ("slot_dy", 0)
			ctl = win.CreateButton (cid, x, y, w, h)
			ctl.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
		elif kind == "label":
			ctl = _MakeLabel (win, cid, c)
		elif kind == "text":
			ctl = _MakeLabel (win, cid, c)
		elif kind in ("list", "textarea"):
			ctl = _MakeTextArea (win, cid, c)
		else:
			_Warn ("{}: control type '{}' is not built yet ({})".format (menu, kind, c.get ("name", c["index"])))
			continue
		lua = c.get ("text_opts", {}).get ("lua")
		if lua in LUA_TEXT:
			style = c.get ("style", "label")
			ctl.SetColor (StyleColor (style))
			text = LUA_TEXT[lua] ()
			fr = ctl.GetFrame ()
			grow = max (0, 12 * len (text) - fr['w'])    # run-time text can be wider than EE's box
			fr['x'] -= grow // 2
			fr['w'] += grow
			ctl.SetFrame (fr)
			ctl.SetText (text)
		controls[c["index"]] = ctl
		if c.get ("name"):
			controls[c["name"]] = ctl
	return win, controls


# -- popups -----------------------------------------------------------------------------

# menu used for 1, 2 and 3 buttons, and the control index of each button from left to right
_POPUPS = {
	1: ("POPUP_INFO", (3,)),
	2: ("QuitMenu", (3, 4)),
	3: ("POPUP_THREEBUTTON", (5, 4, 3)),
}


def PopupAvailable (nbuttons):
	return nbuttons in _POPUPS and Available (_POPUPS[nbuttons][0])

def Popup (text, buttons, image=None, shadow=None):
	"""A modal EE message box. text: strref or str. buttons: [(label, handler, flags)] from left to
	right, flags a string with 'd' (default key) and/or 'e' (escape key); handler may be None to
	just close. Returns the window, already shown. The caller must check PopupAvailable first."""
	menu, slots = _POPUPS[len (buttons)]
	win, ctl = Build (menu)
	if shadow is None:
		shadow = MODAL_SHADOW_GRAY
	# the layout's text label (lua text in EE) and the picture
	doc = Load (menu)
	for c in doc["controls"]:
		if c["type"] == "label" and c.get ("style") == "label_parchment" and c["index"] in ctl:
			ctl[c["index"]].SetText (text)
			ctl[c["index"]].SetColor (StyleColor ("label_parchment"))
		if image is not None and c["type"] == "label" and c.get ("bam") == "POPUPIMG" and c["index"] in ctl:
			ctl[c["index"]].SetBackground (GemRB.GetSprite ("POPUPIMG", -1, image, 0))
	for (label, handler, flags), idx in zip (buttons, slots):
		b = ctl[idx]
		style = "button"
		b.SetFont (StyleFont (style))
		b.SetColor (StyleColor (style))
		b.SetText (label)
		b.OnPress (win.Close if handler is None else _Closing (win, handler))
		if "d" in flags:
			b.MakeDefault ()
		if "e" in flags:
			b.MakeEscape ()
	win.ShowModal (shadow)
	return win

def _Closing (win, handler):
	def press ():
		win.Close ()
		handler ()
	return press


# -- list rows --------------------------------------------------------------------------

def BuildRows (win, menu, listIndex, count, idBase=0x100, sel_pictures=None):
	"""Create `count` rows of the list's row template (EE draws these per saved game).

	Returns (rows, frame): each row is a dict of controls by role: select (a button over the whole
	row whose picture is the row background), preview, name, time, area, portraits[6]. frame is
	the list's frame. sel_pictures = (normal, selected) pictures for the row backgrounds."""
	lst = None
	for c in Controls (menu):
		if c["index"] == listIndex:
			lst = c
	tmpl = lst["columns"][0]["controls"]
	x0, y0, lw, lh = lst["frame"]
	x0, y0 = x0 - _origin[0], y0 - _origin[1]
	rowh = tmpl[0]["frame"][3]
	rows = []
	for i in range (count):
		ry = y0 + i * rowh
		base = idBase + i * 32
		row = {"portraits": [None] * 6}
		# controls created first are drawn on top: transparent click catcher first, the row
		# background last
		sel = win.CreateButton (base, x0, ry, tmpl[0]["frame"][2], rowh)
		sel.SetFlags (IE_GUI_BUTTON_NO_IMAGE, OP_SET)
		row["select"] = sel
		for k, c in enumerate (tmpl[1:]):
			fx, fy, fw, fh = c["frame"]
			lua = c.get ("text_opts", {}).get ("lua", "")
			bmp = c.get ("bitmap_lua", "")
			cid = base + 1 + k
			if bmp:
				b = win.CreateButton (cid, x0 + fx, ry + fy, fw, fh)
				b.SetFlags (IE_GUI_BUTTON_NO_IMAGE | IE_GUI_BUTTON_PICTURE, OP_SET)
				b.SetState (IE_GUI_BUTTON_LOCKED)
				if bmp.endswith ("screenshot"):
					row["preview"] = b
				elif "portrait" in bmp:
					row["portraits"][int (bmp[-1])] = b
			elif lua:
				style = c.get ("style", "label")
				flags = StyleFlags (style)
				# the row template left-aligns its texts
				flags = (flags & ~IE_FONT_ALIGN_CENTER & ~IE_FONT_ALIGN_RIGHT) | IE_FONT_ALIGN_LEFT
				lab = win.CreateLabel (cid, x0 + fx, ry + fy, fw, fh, StyleFont (style), "", flags)
				lab.SetColor (StyleColor (style))
				if lua.endswith ("slotName"):
					row["name"] = lab
				elif lua.endswith (".time"):
					row["time"] = lab
				elif lua.endswith ("areaName"):
					row["area"] = lab
		bg = win.CreateLabel (base + 31, x0, ry, tmpl[0]["frame"][2], rowh, "FONTDLG", "", 0)
		if sel_pictures:
			bg.SetBackground (sel_pictures[0])
		row["bg"] = bg
		rows.append (row)
	return rows, lst["frame"]


# -- spell book (mage and priest share EE's SPELLS menu) ---------------------------------------

def BuildSpellBook (arrowsAndName=True):
	"""EE SPELLS as a full-screen window with the controls the classic mage/priest scripts expect
	(ids: 0 previous level, 1 next level, 2-13 memorized, 14-33 known, 0x10000027 name,
	0x10000026 level). EE's memorized grid has 20 slots; the classic scripts use 12. Returns the window."""
	ids = {3: 0, 4: 1, 2: 0x10000027, 7: 0x10000026}
	skip = set ()
	for i in range (20):
		ids[10 + i] = 2 + i if i < 12 else 0x3000 + 10 + i
		if i >= 12:
			skip.add (10 + i)
		ids[30 + i] = 14 + i
	win, ctl = Build ("SPELLS", ids=ids, skip=skip, fullscreen=True, reverse=True)
	return win
