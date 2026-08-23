"""Forensic probe: why did a long vertical lose more than its debit?"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apex.predators.options import expression, state, underlying_bridge
from apex.predators.options.replay import ReplayWorld

ROOT = Path(sys.argv[1])
SYM, SESSION, CLOCK = sys.argv[2], sys.argv[3], sys.argv[4]

w = ReplayWorld.load(ROOT, SYM, SESSION)
instants = w.instants()
T = next(t for t in instants
         if str(t).replace(" ", "T")[:16] >= f"{SESSION}T{CLOCK}")
exit_T = instants[-1]
frozen = w.at(T)
ost = state.build(frozen)
ug = underlying_bridge.build(frozen, direction="SHORT")
cands = expression.build_candidates(
    frozen, "SHORT", iv=ost.atm_iv if ost.data_quality == "FULL" else None)
v = next(c for c in cands if c.expression == "PUT_VERTICAL")

print(f"{SYM} {SESSION} T={T} exit={exit_T} exp={v.expiration}")
print("ENTRY legs (action, right, strike, price):")
for lg in v.legs:
    print("   ", lg)
print(f"   net debit paid {v.debit}   width "
      f"{abs(v.legs[0][2] - v.legs[1][2]) * 100}")

fq, _fb = w.reveal_after(str(T), "x" * 64)
rows = [r for r in fq if r["timestamp"] == exit_T
        and str(r["expiration"]) == str(v.expiration)]
by = {float(r["strike"]): r for r in rows
      if r["right"].upper().startswith("P")}
lk, wk = v.legs[0][2], v.legs[1][2]
print("EXIT quotes for those exact contracts:")
for label, k in (("long  (BUY, sell at BID)", lk),
                 ("short (SELL, buy at ASK)", wk)):
    r = by.get(k)
    print(f"   {label} K={k}: "
          f"{'bid ' + r['bid'] + ' / ask ' + r['ask'] if r else 'MISSING'}")
if lk in by and wk in by:
    lb, sa = float(by[lk]["bid"]), float(by[wk]["ask"])
    print(f"\n   round trip value = long BID {lb} - short ASK {sa} "
          f"= {lb - sa:.2f} per share  -> {(lb - sa) * 100:.0f} per contract")
    print(f"   P&L = {(lb - sa) * 100:.0f} - {v.debit} = "
          f"{(lb - sa) * 100 - v.debit:.0f}")
    lo, so = by[lk], by[wk]
    print(f"\n   long  K={lk} spread "
          f"{float(lo['ask']) - float(lo['bid']):.2f}")
    print(f"   short K={wk} spread "
          f"{float(so['ask']) - float(so['bid']):.2f}")
    print(f"   mid-to-mid value = "
          f"{((float(lo['bid']) + float(lo['ask'])) / 2 - (float(so['bid']) + float(so['ask'])) / 2) * 100:.0f}")
    print("\n   INTERPRETATION: if mid-to-mid is >= 0 and inside the "
          "width, the structure is sound and the loss is the cost of "
          "crossing BOTH spreads on exit -- real, not a defect.")
