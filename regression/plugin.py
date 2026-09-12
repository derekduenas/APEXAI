"""FULL_REGRESSION_TEST_INVENTORY_V0 -- a minimal pytest plugin that records,
machine-readably, exactly what pytest collected and exactly what happened
to every nodeid, phase by phase. No console parsing anywhere.

Activated with `-p regression.plugin`; writes JSON to $REGRESSION_OUT.

Outcome classes (never collapsed):
  PASS   setup/call/teardown all passed
  FAIL   call failed (not xfail)
  ERROR  setup or teardown failed (a passing call with a failing teardown
         is ERROR, not PASS)
  SKIP   skipped in setup or call (reason recorded)
  XFAIL  expected failure honoured
  XPASS  expected failure passed (pytest 'xpassed'; strict xfail already
         surfaces as FAIL)
"""
from __future__ import annotations

import json
import os
import platform
import resource
import sys
import time

import pytest

_STATE = {"items": [], "collect_errors": [], "phases": {}, "t0": time.time()}


def _cgroup():
    try:
        cg = open("/proc/self/cgroup").read().strip().split("::")[-1]
        base = "/sys/fs/cgroup" + cg
        rd = lambda f: open(base + "/" + f).read().strip() if os.path.exists(base + "/" + f) else None
        return {"path": cg, "memory_max": rd("memory.max"), "memory_peak": rd("memory.peak"),
                "memory_events": rd("memory.events")}
    except Exception as e:                       # noqa: BLE001
        return {"path": None, "error": type(e).__name__}


def pytest_collection_modifyitems(session, config, items):
    for it in items:
        _STATE["items"].append({"nodeid": it.nodeid, "file": str(it.path.relative_to(config.rootpath))
                                if hasattr(it, "path") else it.location[0]})


def pytest_collectreport(report):
    if report.failed:
        _STATE["collect_errors"].append({"nodeid": report.nodeid, "longrepr": str(report.longrepr)[:2000]})


def pytest_runtest_logreport(report):
    ph = _STATE["phases"].setdefault(report.nodeid, {})
    entry = {"outcome": report.outcome, "wasxfail": hasattr(report, "wasxfail")}
    if report.outcome == "skipped":
        lr = report.longrepr
        if isinstance(lr, tuple) and len(lr) == 3:
            entry["reason"] = str(lr[2])
        else:
            entry["reason"] = str(lr)[:500]
    elif report.outcome == "failed":
        entry["longrepr"] = str(report.longrepr)[:2000]
    ph[report.when] = entry


def _classify(ph: dict) -> tuple:
    s, c, t = ph.get("setup"), ph.get("call"), ph.get("teardown")
    if s is None:
        return "UNREPORTED", None
    if s["outcome"] == "failed":
        return "ERROR", s.get("longrepr")
    if s["outcome"] == "skipped":
        return ("XFAIL", s.get("reason")) if s.get("wasxfail") else ("SKIP", s.get("reason"))
    if c is None:
        return "UNREPORTED", "no call phase"
    if c["outcome"] == "failed":
        return "FAIL", c.get("longrepr")
    if c["outcome"] == "skipped":
        return ("XFAIL", c.get("reason")) if c.get("wasxfail") else ("SKIP", c.get("reason"))
    if c["outcome"] == "passed" and c.get("wasxfail"):
        return "XPASS", None
    if t is not None and t["outcome"] == "failed":
        return "ERROR", "teardown: " + str(t.get("longrepr"))
    return "PASS", None


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("REGRESSION_OUT")
    if not out:
        return
    results = {}
    for it in _STATE["items"]:
        cls, detail = _classify(_STATE["phases"].get(it["nodeid"], {}))
        results[it["nodeid"]] = {"file": it["file"], "outcome": cls, "detail": detail}
    ru = resource.getrusage(resource.RUSAGE_SELF)
    doc = {"inventory_version": "FULL_REGRESSION_TEST_INVENTORY_V0",
           "collected": _STATE["items"], "collected_count": len(_STATE["items"]),
           "collect_errors": _STATE["collect_errors"],
           "results": results, "exitstatus": int(exitstatus),
           "totals": {k: sum(1 for r in results.values() if r["outcome"] == k)
                      for k in ("PASS", "FAIL", "ERROR", "SKIP", "XFAIL", "XPASS", "UNREPORTED")},
           "env": {"python": sys.version.split()[0], "pytest": pytest.__version__,
                   "platform": platform.platform(), "cwd": os.getcwd(), "argv": sys.argv,
                   "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED")},
           "resource": {"ru_maxrss_MiB": round(ru.ru_maxrss / 1024, 1), "cgroup": _cgroup(),
                        "elapsed_s": round(time.time() - _STATE["t0"], 2)}}
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=1)
    os.replace(tmp, out)
