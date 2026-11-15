"""Quick check that the layered index and parsers read real PST data."""

from pst_data import Resources, Tlk, GAME, parse_spl, parse_pro, parse_vvc, parse_bam, parse_ids

res = Resources()
print("missing bifs:", res.chitin.missing_bifs[:5], "found", res.chitin.found_bifs)
for ext in ("spl", "pro", "vvc", "bam", "itm", "ids", "2da", "eff", "vef"):
    print(ext, len(res.names(ext)), res.count_by_layer(ext))
tlk = Tlk(GAME / "Dialog.tlk")
for name in ("SPWI101", "SPWI909", "SPPR101", "SPIN101"):
    s = parse_spl(res.get(name, "spl"))
    print(name, res.source(name, "spl"), tlk(s["name_strref"]), s["type"], s["level"], [h["projectile_raw"] for h in s["headers"]])
print(parse_pro(res.get("CHOST", "pro")))
print(parse_vvc(res.get("IGNUSORB", "vvc")))
b = parse_bam(res.get("S091GATE", "bam"))
print(len(b["frames"]), b["frames"][:3], b["cycles"])
print("projectl in data:", res.has("PROJECTL", "ids"), res.source("PROJECTL", "ids"))
ids = parse_ids(res.get("GEMPRJTL", "ids"))
print(len(ids), ids.get(253))
