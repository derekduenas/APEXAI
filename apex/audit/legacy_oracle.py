"""THE LEGACY RUNNER AS A PARITY ORACLE — the one long-sleeping morning, run against a virtual clock.

The oracle exists to answer one question: does the staged producer absorb the same world the old runner did?

TWO SUBSTITUTIONS ON THIS SIDE ONLY, and they are why this is an ORACLE and not a production path:
  1. the clock, through the same declared `premarket_runtime` seam the staged path uses;
  2. `time.sleep`, replaced with an ADVANCE of that virtual clock.

The second is unavoidable: the legacy runner really does sleep for about seventy minutes, and it really does
recompute nothing while asleep. Advancing the clock instead of blocking lets the oracle traverse its own
schedule in seconds while executing every other line of it unchanged — including `min(wait, 3600)`, which is
left exactly as it is, because the whole point of the oracle is to be the old behaviour.
"""
from __future__ import annotations

import pathlib
import sys


class VirtualSleep:
    def __init__(self, clock_file):
        self.clock_file = pathlib.Path(clock_file)
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(float(seconds))
        now = float(self.clock_file.read_text().strip())
        self.clock_file.write_text("%.6f" % (now + float(seconds)))

    def __getattr__(self, k):
        import time as _t
        return getattr(_t, k)


def run(clock_file: str) -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts"))
    import premarket_run
    vs = VirtualSleep(clock_file)
    premarket_run.time = vs
    sys.argv = ["premarket_run.py"]
    rc = premarket_run.main()
    print("ORACLE slept %d times, total %.0fs of virtual time" % (len(vs.slept), sum(vs.slept)))
    return rc


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1]))
