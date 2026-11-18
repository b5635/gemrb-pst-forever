"""Parser for the Infinity UI.menu format (the menu/label/button blocks, not the Lua between backticks).

parse(text) -> list[Block] of the top-level `menu` blocks.

A Block has `kind` (menu, label, button, ...), `props` (list of (key, [args])) and `children`.
Args are `Tok` objects: `.v` is the text, `.q` is true when it was quoted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Tok:
    v: str
    q: bool
    line: int      # line where it starts
    end: int       # line where it ends (strings can span lines)

    def __repr__(self):
        return repr(self.v)


@dataclass
class Block:
    kind: str
    props: list = field(default_factory=list)
    children: list = field(default_factory=list)

    def get(self, key: str):
        """First property with this key (case-insensitive) as its arg list, else None."""
        key = key.lower()
        for k, a in self.props:
            if k.lower() == key:
                return a
        return None

    def all(self, key: str):
        key = key.lower()
        return [a for k, a in self.props if k.lower() == key]

    def has(self, key: str) -> bool:
        return self.get(key) is not None


_WORD = re.compile(r"[^\s{}'\"]+")


def strip_lua(text: str) -> str:
    """The file alternates menu text and `...` Lua sections; keep the even parts."""
    return "\n".join(text.split("`")[0::2])


def tokenize(text: str) -> list:
    out = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif text.startswith("--", i):
            while i < n and text[i] != "\n":
                i += 1
        elif c in "{}":
            out.append(Tok(c, False, line, line))
            i += 1
        elif c in "'\"":
            j = text.find(c, i + 1)
            if j < 0:
                j = n
            s = text[i + 1:j]
            out.append(Tok(s, True, line, line + s.count("\n")))
            line += s.count("\n")
            i = j + 1
        else:
            m = _WORD.match(text, i)
            w = m.group(0)
            # a comment can follow a word with no space: `5--note`
            k = w.find("--")
            if k > 0:
                w = w[:k]
            out.append(Tok(w, False, line, line))
            i += len(w)
    return out


_NUMLIKE = re.compile(r"^-?\d")


def _parse_block(toks: list, i: int, kind: str):
    """toks[i] is the token after `{`. Returns (Block, index after the closing brace)."""
    blk = Block(kind)
    n = len(toks)
    while i < n and not (toks[i].v == "}" and not toks[i].q):
        t = toks[i]
        if t.q or t.v == "{":      # stray quoted string or brace: skip
            i += 1
            continue
        key = t.v
        # child block: `word {`
        if i + 1 < n and toks[i + 1].v == "{" and not toks[i + 1].q:
            child, i = _parse_block(toks, i + 2, key)
            blk.children.append(child)
            continue
        i += 1
        args = []
        last = t.end
        while i < n:
            u = toks[i]
            if not u.q and u.v in "{}":
                break
            if u.line == last:
                args.append(u)
                last = u.end
                i += 1
                continue
            # continuation on a following line: first value of an empty prop, a string right
            # after a bare key, or a numeric line (boundingPoints)
            if (not args and u.line > last) or (args and not u.q and _NUMLIKE.match(u.v)
                                                 and key.lower() == "boundingpoints"):
                # a key with no args takes the next line only if it is a string or number
                if u.q or _NUMLIKE.match(u.v):
                    args.append(u)
                    last = u.end
                    i += 1
                    continue
            break
        blk.props.append((key, args))
    if kind == "slot":
        blk.props = _resplit_slot(blk.props)
    return blk, i + 1


_SLOT_KEYS = {"name", "area", "bam", "sequence", "slotinfo", "highlight", "tooltip", "use", "mosaic"}


def _resplit_slot(props):
    """`slot {name "x" area 1 2 3 4 bam "Y" ...}` is written on one line: split at the known keys."""
    toks = []
    for k, a in props:
        toks.append(Tok(k, False, 0, 0))
        toks.extend(a)
    out = []
    for t in toks:
        if not t.q and t.v.lower() in _SLOT_KEYS:
            out.append((t.v, []))
        elif out:
            out[-1][1].append(t)
    return out


def parse(text: str) -> list:
    toks = tokenize(strip_lua(text))
    menus = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i].v == "menu" and i + 1 < n and toks[i + 1].v == "{":
            blk, i = _parse_block(toks, i + 2, "menu")
            menus.append(blk)
        else:
            i += 1
    return menus
