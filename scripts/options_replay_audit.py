"""Integrity audit of an options causal replay result file.

Checks the PLUMBING, not the profit. The economics are printed only so
the operator can see the machine produced real numbers -- 105 symbol-
days of HISTORICAL_DEVELOPMENT_REPLAY is not evidence of an edge and
never becomes so by being summarised.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def main(path: str) -> int:
    d = json.loads(Path(path).read_text())
    recs = [r for r in d["records"] if r.get("status") == "RESOLVED"]

    violations, per = [], {}
    for r in recs:
        for name, v in r["counterfactuals"].items():
            pnl, cap = v.get("pnl"), v.get("capital")
            s = per.setdefault(name, {"n": 0, "ne": 0, "pnl": [],
                                      "pedigree": set(), "basis": set()})
            s["pedigree"].add(v.get("execution_pedigree"))
            s["basis"].add(v.get("risk_basis"))
            if not isinstance(pnl, (int, float)):
                s["ne"] += 1
                continue
            s["n"] += 1
            s["pnl"].append(pnl)
            # DEBIT-STRUCTURE INVARIANT, correctly stated: the debit
            # bounds the loss AT EXPIRY. Our pre-declared exit is a
            # quoted-side round trip, which crosses two further
            # spreads, so the true bound is debit + exit friction.
            # Breaching THAT is a defect; breaching the expiry bound
            # alone is real market friction and is reported separately.
            if name != "STOCK" and cap and pnl < -cap - 1e-6:
                s.setdefault("expiry_bound_exceeded", []).append(pnl)
            # THE DEFECT TEST is the accounting identity, not a bound:
            # pnl = mid_change - entry_friction - exit_friction. A loss
            # that satisfies it came from the market. A loss that
            # violates it came from us.
            ident = v.get("friction_identity_holds")
            if ident is not None:
                s.setdefault("identity", []).append(ident)
            if name != "STOCK" and ident is False:
                violations.append({"symbol": r["symbol"],
                                   "session": r["session"],
                                   "clock": r["clock_et"], "expr": name,
                                   "pnl": pnl, "capital": cap})

    print("=== INTEGRITY ===")
    print(f"resolved decisions        {len(recs)}")
    print(f"friction-identity failures {len(violations)}  "
          f"(pnl != mid_change - entry_friction - exit_friction)")
    for k, v in sorted(per.items()):
        idents = v.get("identity") or []
        held = sum(1 for i in idents if i is True)
        ne = sum(1 for i in idents if i == "NOT_ESTIMABLE")
        if idents:
            print(f"  {k:14} identity held {held}/{len(idents)}"
                  f"{f', {ne} not estimable' if ne else ''}")
    for k, v in sorted(per.items()):
        eb = v.get("expiry_bound_exceeded") or []
        if eb:
            print(f"  {k}: {len(eb)} exits cost more than the EXPIRY "
                  f"bound -- real spread friction, not a defect "
                  f"(worst {min(eb):.0f})")
    for v in violations[:10]:
        print("   ", v)

    winners = {r.get("winner") for r in recs}
    print(f"expression winners emitted "
          f"{sorted(w[:20] for w in winners if w)}")

    print("\n=== ECONOMICS (replay only, NOT evidence of edge) ===")
    hdr = (f'{"expression":16}{"resolved":>9}{"n/e":>6}'
           f'{"total$":>11}{"median$":>10}{"win%":>7}  pedigree')
    print(hdr)
    for k, s in sorted(per.items()):
        if not s["n"]:
            print(f'{k:16}{0:>9}{s["ne"]:>6}{"-":>11}{"-":>10}{"-":>7}')
            continue
        w = 100 * sum(1 for x in s["pnl"] if x > 0) / s["n"]
        ped = ",".join(sorted(str(p) for p in s["pedigree"]))
        print(f'{k:16}{s["n"]:>9}{s["ne"]:>6}{sum(s["pnl"]):>11.0f}'
              f'{statistics.median(s["pnl"]):>10.1f}{w:>7.0f}  {ped}')

    print("\nrisk bases in force:",
          {k: sorted(str(b) for b in v["basis"]) for k, v in per.items()})
    sa = d["summary"]["sample_accounting"]
    print(f"\nn_raw {sa['n_raw']} -> n_effective_lower_bound "
          f"{sa['n_effective_lower_bound']} "
          f"({sa['unique_symbols']} symbols, {sa['unique_sessions']} dates)")
    print("evidence_class:", d["summary"]["evidence_class"])
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
