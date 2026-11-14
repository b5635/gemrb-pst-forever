# Run repeatedly (dev.ps1 pyfile) during a staged turn based fight: on each party turn it orders
# moves the way a confirmed click does and checks the walk ends where the preview promised.
import GemRB, math, random
st = globals().setdefault('tbMove', {'pending': None, 'ok': 0, 'bad': [], 'partial': 0, 'nopath': 0, 'moves': 0, 'turnMoves': {}})
b = GemRB.GetTurnBudget()
o = GemRB.GetTurnOrder()
if not b or not o:
	print('no fight')
elif not b['OwnTurn']:
	print('waiting', o['Active'])
elif b['Busy']:
	print('walking', b['ID'])
else:
	p = st['pending']
	if p and p['id'] == b['ID']:
		err = math.hypot(b['X'] - p['sx'], b['Y'] - p['sy'])
		if err <= 1.5:
			st['ok'] += 1
		else:
			st['bad'].append((b['ID'], p['from'], (p['sx'], p['sy']), (b['X'], b['Y']), round(err, 1), p['partial']))
		st['pending'] = None
	key = (o['Round'], b['ID'])
	n = st['turnMoves'].get(key, 0)
	if b['Move'] < 3 or n >= 4:
		GemRB.EndTurn()
		print('end', b['ID'])
	else:
		st['turnMoves'][key] = n + 1
		r = random.uniform(2, b['Move'] * 1.6) * 16
		a = random.uniform(0, 2 * math.pi)
		x = int(b['X'] + r * math.cos(a))
		y = int(b['Y'] + r * math.sin(a) * 0.75)
		pr = GemRB.TurnMoveTo(x, y)
		st['moves'] += 1
		if not pr['HasPath']:
			st['nopath'] += 1
		else:
			st['partial'] += pr['Partial']
			st['pending'] = {'id': b['ID'], 'from': (b['X'], b['Y']), 'sx': pr['StopX'], 'sy': pr['StopY'], 'partial': pr['Partial']}
		print('move', b['ID'], (x, y), pr)
print('summary moves=%d ok=%d bad=%d partial=%d nopath=%d' % (st['moves'], st['ok'], len(st['bad']), st['partial'], st['nopath']))
for e in st['bad'][-8:]:
	print('  BAD id=%d from=%s promised=%s got=%s err=%s partial=%d' % e)
