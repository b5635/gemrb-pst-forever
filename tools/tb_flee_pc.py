# DevConsole command: on a party member's turn, make it RunAwayFrom the target given in
# tbFleeTarget (global ID), to exercise the director's flee walking. Run it repeatedly.
import GemRB
b = GemRB.GetTurnBudget()
t = globals().get('tbFleeTarget', 10068)
done = globals().setdefault('tbFled', set())
o = GemRB.GetTurnOrder()
if o and b and not b['Busy']:
	key = (o['Round'], b['ID'])
	if key not in done:
		done.add(key)
		print('flee', b['ID'], GemRB.ExecuteActionAt(b['ID'], 'RunAwayFrom([-1],30)', t))
	else:
		GemRB.EndTurn()
		print('end', b['ID'])
print(o and o['Round'], o and o['Active'], b and b['Move'])
