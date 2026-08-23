"""How much of the options P&L was decided by the spread?

Uses the exact identity pnl = mid_change - entry_friction -
exit_friction to split each outcome into the part the thesis earned and
the part the market took. This is the number that decides whether an
options expression is worth attacking at all at small size.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def main(path: str) -> int:
    d = json.loads(Path(path).read_text())
    recs = [r for r in d["records"] if r.get("status") == "RESOLVED"]
    per = {}
    for r in recs:
        for name, v in r["counterfactuals"].items():
            if name == "STOCK":
                continue
            pnl, mid = v.get("pnl"), v.get("mid_change")
            ex = v.get("exit_friction")
            if not all(isinstance(x, (int, float)) for x in (pnl, mid, ex)):
                continue
            s = per.setdefault(name, {"pnl": [], "mid": [], "fric": [],
                                      "cap": []})
            s["pnl"].append(pnl)
            s["mid"].append(mid)
            s["fric"].append(mid - pnl)          # total round-trip cost
            s["cap"].append(v.get("capital") or 0)

    print("Each outcome split by the exact identity: what the thesis")
    print("earned on mid, minus what the round trip cost.\n")
    print(f'{"expression":16}{"n":>5}{"mid P&L":>10}{"friction":>10}'
          f'{"net P&L":>10}{"fric/cap":>10}{"mid win%":>10}{"net win%":>10}')
    for k, s in sorted(per.items()):
        n = len(s["pnl"])
        mw = 100 * sum(1 for x in s["mid"] if x > 0) / n
        nw = 100 * sum(1 for x in s["pnl"] if x > 0) / n
        fc = 100 * sum(s["fric"]) / max(1e-9, sum(s["cap"]))
        print(f'{k:16}{n:>5}{sum(s["mid"]):>10.0f}{sum(s["fric"]):>10.0f}'
              f'{sum(s["pnl"]):>10.0f}{fc:>9.0f}%{mw:>9.0f}%{nw:>9.0f}%')

    tot_mid = sum(sum(s["mid"]) for s in per.values())
    tot_fri = sum(sum(s["fric"]) for s in per.values())
    tot_cap = sum(sum(s["cap"]) for s in per.values())
    print(f'\nacross all option expressions: mid P&L {tot_mid:.0f}, '
          f'friction {tot_fri:.0f}, net {tot_mid - tot_fri:.0f}')
    print(f'friction as a share of capital deployed: '
          f'{100 * tot_fri / max(1e-9, tot_cap):.0f}%')

    # how often did friction alone flip a winner into a loser?
    flips = sum(1 for s in per.values()
                for m, p in zip(s["mid"], s["pnl"]) if m > 0 >= p)
    wins = sum(1 for s in per.values() for m in s["mid"] if m > 0)
    print(f'\ntrades right on mid but losing after the round trip: '
          f'{flips} of {wins} ({100 * flips / max(1, wins):.0f}%)')
    med = statistics.median([f for s in per.values() for f in s["fric"]])
    print(f'median round-trip cost per contract: {med:.0f} dollars')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
