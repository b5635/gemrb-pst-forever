# SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# DevConsole.py - file based remote console for testing and automation.
#
# Every POLL_MS the game looks for dev\cmd.py in its working directory. If present, the file is
# run as Python (with GemRB, GUIDefines and a few helpers in scope), deleted, and everything it
# printed (or the traceback) is written to dev\out.txt, followed by a final "#done <n>" line.
# tools\dev.ps1 wraps this:  dev.ps1 py "print(here())"
#
# Helpers available to commands:
#   here()                  current area resref
#   act(action, slot=1)     run a game script action on a party slot (GemRB.ExecuteString)
#   goto(area, x, y)        move the party to another area (same path as an area exit)
#   pc(slot=1)              GemRB.GetPlayerName / position summary of a party member

import os
import sys
import io
import traceback
import GemRB

POLL_MS = 250
DIR = "dev"
CMD = os.path.join (DIR, "cmd.py")
OUT = os.path.join (DIR, "out.txt")

Counter = 0
Started = False
Namespace = {}

def here ():
	return GemRB.GetGameString (1) # STR_AREANAME

def act (action, slot = 1):
	GemRB.ExecuteString (action, slot)

def goto (area, x = -1, y = -1):
	act ('LeaveAreaLUA("%s","",[%d.%d],0)' % (area, x, y))

def pc (slot = 1):
	return GemRB.GetPlayerName (slot, 1)

def Poll ():
	global Counter
	if not os.path.exists (CMD):
		return
	try:
		with open (CMD, "r", encoding = "utf-8") as f:
			src = f.read ()
		os.remove (CMD)
	except OSError:
		return # still being written, next poll
	Counter += 1
	buf = io.StringIO ()
	old = sys.stdout, sys.stderr
	sys.stdout = sys.stderr = buf
	try:
		code = compile (src, "<devcmd>", "exec")
		exec (code, Namespace)
	except BaseException:
		traceback.print_exc ()
	finally:
		sys.stdout, sys.stderr = old
	tmp = OUT + ".tmp"
	with open (tmp, "w", encoding = "utf-8") as f:
		f.write (buf.getvalue ())
		f.write ("\n#done %d\n" % Counter)
	os.replace (tmp, OUT)

def Start ():
	"""Starts polling once per process; safe to call from any OnLoad."""
	global Started
	if Started:
		return
	Started = True
	try:
		os.makedirs (DIR, exist_ok = True)
		if os.path.exists (CMD):
			os.remove (CMD) # stale command from a previous run
	except OSError:
		pass
	import GUIDefines
	Namespace.update (GemRB = GemRB, GUIDefines = GUIDefines, here = here, act = act, goto = goto, pc = pc)
	GemRB.SetTimer (Poll, POLL_MS)
	print ("[DevConsole] polling %s" % os.path.abspath (CMD))
