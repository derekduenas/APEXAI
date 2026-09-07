"""Runtime audit hook. Records every file opened outside the tree under test,
and every subprocess launched, so external dependencies are observed rather
than inferred from a source scan.

Loaded by being first on PYTHONPATH; writes outside the candidate tree.
"""
import os
import sys

_WT = os.environ.get("APEX_AUDIT_WT", "")
_LOG = os.environ.get("APEX_AUDIT_LOG", "")
_seen = set()


def _record(kind, value):
    key = (kind, value)
    if key in _seen:
        return
    _seen.add(key)
    try:
        with open(_LOG, "a") as fh:
            fh.write("%s\t%s\n" % (kind, value))
    except OSError:
        pass


def _hook(event, args):
    try:
        if event == "open":
            p = args[0]
            if isinstance(p, (str, bytes, os.PathLike)):
                p = os.fspath(p)
                if isinstance(p, bytes):
                    p = p.decode("utf-8", "replace")
                if p.startswith("/"):
                    ap = os.path.abspath(p)
                    if not ap.startswith(_WT) and not ap.startswith("/tmp") \
                            and not ap.startswith("/proc") and not ap.startswith("/sys") \
                            and "/site-packages/" not in ap and not ap.startswith("/usr/lib") \
                            and not ap.startswith("/opt/apex/shared/venv/lib"):
                        _record("OPEN_OUTSIDE", ap)
        elif event == "subprocess.Popen":
            _record("SUBPROCESS", str(args[0])[:300])
    except Exception:
        pass


if _WT and _LOG:
    sys.addaudithook(_hook)
