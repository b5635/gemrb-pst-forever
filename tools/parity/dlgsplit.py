"""A7: split every DLG trigger/action string the way GemRB's DLGImporter does (GetStrings, whitespace
removed) and compare with PST:EE's own DLG files, whose strings Beamdog rewrote one statement per line.
python tools/parity/dlgsplit.py [--show N]   -> counts + first N differences"""
import sys, struct, re, collections
sys.path.insert(0, __import__("os").path.dirname(__file__)); import pstres

def action_length(s, i):
    level, quotes, j = 0, True, i
    while j < len(s):
        c = s[j]; j += 1
        if c == '"': quotes = not quotes
        elif c == '(' and quotes: level += 1
        elif c == ')' and quotes and level:
            level -= 1
            if level == 0: return j - i
        elif c in '\r\n' and not quotes: return j - 1 - i
    return j - i

def gemrb_split(s):
    # count pass (GetStrings)
    level, quotes, ignore, count, j = 0, True, False, 0, 0
    while j < len(s):
        c = s[j]; j += 1
        if c == '/' and j < len(s) and s[j] == '/': j += 1; ignore = True
        elif c == '"': quotes = not quotes
        elif c == '(' and quotes: level += 1
        elif c == ')' and quotes and level:
            level -= 1
            if level == 0:
                if not ignore: count += 1
                ignore = False
        elif c in '\r\n' and (not quotes or ignore):
            level, quotes, ignore = 0, True, False; count += 1
    out, p, i = [], 0, 0
    while i < count:
        while p < len(s) and s[p] in ' \n\r': p += 1
        if s[p:p+2] == '.,': p += 1
        if s.startswith(';\r\nSetGlobal', p): p += 1
        n = action_length(s, p)
        if s[p:p+2] == '//': p += n; continue
        piece = s[p:p+n]; p += n; i += 1
        out.append(re.sub(r'\s', '', piece.replace('.,', ',')))
    return [x for x in out if x]

def ee_split(s):
    return [re.sub(r'\s', '', l) for l in s.splitlines() if l.strip() and not l.strip().startswith('//')]

def strings(d):
    if not d or len(d) < 0x30: return None
    h = struct.unpack_from('<10I', d, 8)
    def get(off, cnt):
        r = []
        for i in range(cnt):
            o, l = struct.unpack_from('<II', d, off + 8 * i); r.append(d[o:o+l].decode('latin1'))
        return r
    return {'state': get(h[4], h[5]), 'trans': get(h[6], h[7]), 'action': get(h[8], h[9])}

def main():
    show = int(sys.argv[sys.argv.index('--show') + 1]) if '--show' in sys.argv else 15
    g, e = pstres.gemrb(), pstres.ee()
    stats, diffs = collections.Counter(), []
    for name in g.names('dlg'):
        a, b = strings(g.res(name, 'dlg')), strings(e.res(name, 'dlg'))
        if a is None or b is None: stats['missing in EE'] += 1; continue
        for kind in a:
            if len(a[kind]) != len(b[kind]): stats[kind + ' count differs (file)'] += 1; continue
            for i, (x, y) in enumerate(zip(a[kind], b[kind])):
                gx, ey = gemrb_split(x), ee_split(y)
                if [s.lower() for s in gx] == [s.lower() for s in ey]: stats[kind + ' same'] += 1
                else:
                    stats[kind + ' differ'] += 1
                    # classify: same statements but EE changed content vs. a split problem
                    joined_g, joined_e = ''.join(gx).lower(), ''.join(ey).lower()
                    cls = 'split' if joined_g == joined_e else 'content'
                    stats[kind + ' differ/' + cls] += 1
                    diffs.append((cls, name, kind, i, gx, ey))
    for k in sorted(stats): print(f'{k:32} {stats[k]}')
    for cls in ('split', 'content'):
        print('\n==', cls)
        for d in [d for d in diffs if d[0] == cls][:show]:
            print(d[1], d[2], d[3], '\n  gemrb:', d[4], '\n  ee   :', d[5])

if __name__ == '__main__':
    main()
