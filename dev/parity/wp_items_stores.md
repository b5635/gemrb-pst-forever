# Items and stores (track C), judged against PST:EE

Done: store prices, store theft, item usability (companion and faction bits). Not done: charges/recharge on rest,
`NOCHARGE`, `SLTSTEAL` (creature pickpocket slots), identify, PST inventory slots (`ITMSLOTS`, `avslots.2da`).
IDs `ST-<n>` (stores), `IT-<n>` (items). `CStore::` has no PST branch in EE: the generic rules are the target.

STO V1.1 fields used below (`iesdp.py format sto_v1.1`): `0x14` sell markup (store sells), `0x18` buy markup (store
buys), `0x1C` depreciation, `0x20` steal failure %; item entries are 88 bytes, `+0x18` infinite supply. EE's `CStore`
keeps the header from offset 0 (`this+2` type, `this+5` sell markup, `this+6` buy markup, `this+7` depreciation).
PST data: 42 stores, markups mostly 120/80; 611 items for sale, **275 with infinite supply in 34 stores**.

### ST-1 Selling an item the store stocks without limit: EE pays at most 20 %
- **Status:** V      **Severity:** 2      **Uses:** 275 infinite stock entries (KNIFE 11 stores, the charms 5-9, BANDAGE 9, NEEDLE 9…)      **By:** opus
- **EE:** `CStore::GetItemSellValue:42-170`: if the store's own entry for that resref has the infinite flag, the rate
  is min(buy markup, 20) %; otherwise buy markup − depreciation × (copies in stock; stacks count every unit), floored at
  min(buy markup, 20). Amulets, rings, gems (types 1, 10, 34) skip depreciation. Unidentified: 1 coin.
- **GemRB:** `GUISTORE.py GetRealPrice` "buy" mode: `GemRB.FindStoreItem` returns 0 for infinite stock, so the full buy
  markup (80 %) is paid; depreciation by `AmountInStock`, floor `max(mod, 20)` (raises a markup below 20 to 20).
  Unidentified: 1 coin (P).
- **Difference:** selling a Knife (or a charm) to a store that stocks it infinitely: EE 20 % of the base, GemRB 80 %:
  4× the money, and buy-low-sell-high loops become possible.
- **Re-check:** `python tools/parity/dumps.py lines ee "CStore::GetItemSellValue(" 60 110`;
  `sed -n '/def GetRealPrice/,/return effprice/p' gemrb/GUIScripts/GUISTORE.py`.

### ST-2 Buying: charisma multiplies the markup in EE, GemRB adds it
- **Status:** V      **Severity:** 3      **By:** opus
- **EE:** `CStore::GetItemBuyValue` → `CRuleTables::AdjustStoreMarkup`: markup × (`REPMODST`[rep] + `CHRMODST`[CHR]) / 100
  (reputation forced to 10 when the store has flag `0x2000`); then × base / 100, at least 1.
- **GemRB:** "sell" mode: markup + `CHRMODST` bonus; in PST no reputation factor at all (`RepModTable` loaded only for
  other games). With PST's reputation at 10 (`REPMODST` 100) the two agree in shape but not in numbers: markup 120 %,
  CHR 18 (−15): EE 102 %, GemRB 105 %; CHR 25 (−25): EE 90 %, GemRB 95 %.
- **Re-check:** `python tools/parity/dumps.py show ee "CRuleTables::AdjustStoreMarkup(" --all`.

### ST-3 Charged items: EE prices all three headers and treats rechargeable ones as full
- **Status:** V      **Severity:** 3      **By:** opus
- **EE:** both price functions prorate by (charges left)/(max charges) summed over abilities 0-2; when selling, an
  ability with recharge flag (`ability[39] & 8`) counts as full.
- **GemRB:** `GetRealPrice`: `Usages0 / MaxCharge` of the first header only, no recharge exception.

### ST-4 Failed store theft: the owner isn't attacked in GemRB
- **Status:** V      **Severity:** 2      **By:** opus
- **EE:** `CScreenStore::OnStealItemButtonClick:82-277`: chance = Pick Pockets − steal failure % (0 when failure = 100);
  each selected item rolls d100 ≤ chance; at the first failure, **PST only**: the thief speaks feedback line 50 and the
  owner gets `ATTACKEDBY` (thief), then everyone gets `STEALFAILED`, the store closes.
- **GemRB:** `GUISTORE.py StealPressed`: one item, success if Pick Pockets > d100 + failure (1 % lower); failure →
  `GemRB.StealFailed` adds `StealFailed` only, `AttackedBy` only with `StealIsAttack`, which PST's `gemrb.ini` sets to 0.
- **Difference:** in EE a caught thief is attacked by the shopkeeper's `AttackedBy` blocks; in GemRB only scripts that
  test `StealFailed` react. Same rule as T14 (creature pickpocketing), store side.
- **Re-check:** `python tools/parity/dumps.py lines ee "CScreenStore::OnStealItemButtonClick(" 193 252`;
  `grep -n StealIsAttack gemrb/unhardcoded/pst/gemrb.ini`.

### IT-1 Anarchist faction: the "not usable by Anarchists" bit is missing
- **Status:** V      **Severity:** 2      **Uses:** 12 items with usability bit `0x200`      **By:** opus
- **EE:** `CRuleTables::GetUsabilityBits` (PST branch): companion bit by script name (Nameless One `0x40000000`, Annah
  `0x10000000`, Ignus `0x1000000`, Grace `0x200000`, Nordom `0x4000000`, Vhailor `0x800000`, Morte `0x2000000`, Dakkon
  `0x100000`) plus a faction bit from the CRE faction byte, for the Nameless One OR-ed with the `Join_*` globals
  (Sensates 4, Dustmen 2, Anarchists 5, Chaosmen 1 or 3 → 8, Godsmen 6 → 3): 0 → `0x1000`, 2 → `0x4000`, 3 → `0x100`,
  4 → `0x40`, **5 → `0x200`**, 8 → `0x400`, 9 → `0x10000`, 12 → `0x8000`.
- **GemRB:** `itemuse.2da` (pst) → `factions.2da` `UNUSABLE`: same bits except **ANARCHIST = 0**; companion bits in
  `avslots.2da` match EE.
- **Difference:** an Anarchist Nameless One can use AXASC, DDMACE, DUSTEAR, ENLIGHT, GKISS, INDEPEAR, RATCHARM, REASON,
  TPUNCH, TTSENS1, TTSENS2, TTSOURCE in GemRB; in EE he can't. Also: EE ORs the `Join_*` values, so two joined
  factions give a combined value (e.g. Dustmen 2 | Godsmen 3 = 3 → Godsmen bit); GemRB uses the single `IE_FACTION`
  stat (B1).
- **Re-check:** `python tools/parity/dumps.py lines ee "CRuleTables::GetUsabilityBits(" 22 124`;
  `cat gemrb/unhardcoded/pst/factions.2da`.

### Parity
| Item | Note |
|---|---|
| unidentified items sell for 1 | EE `GetItemSellValue:47-52`, GemRB `SHOP_ID` → 1 |
| resting heals | `CInfGame::RestPartyPrivate:646-660`: op 17, mode 4 (full) for the protagonist in PST: A-296 (EE: same) |
