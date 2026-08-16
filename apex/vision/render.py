"""Deterministic, future-blind candidate chart snapshots — zero dependencies.

EYES-1 WS7A. A pure-Python PNG encoder (zlib + struct only), for the same
reason the Flight Deck ships no CDN: an image that feeds a challenger must
be reproducible from APEX's own canonical state, on any machine, with
nothing to install and nothing to fetch.

THE LAW OF THIS MODULE: an as-of-T snapshot may contain only what was
knowable at T. No future bars, no future outcomes, no hindsight markers,
and — for the challenger variant — no labels that tell the model the
answer it is supposed to give.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

W, H = 900, 480
BG = (18, 20, 26)
UP = (38, 166, 154)
DOWN = (239, 83, 80)
GRID = (44, 48, 58)
TEXT = (200, 205, 215)
VWAP = (255, 193, 7)


class Canvas:
    def __init__(self, w=W, h=H, bg=BG):
        self.w, self.h = w, h
        self.px = bytearray(bg * w * h)

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(c)

    def rect(self, x0, y0, x1, y1, c):
        for y in range(max(0, min(y0, y1)), min(self.h, max(y0, y1) + 1)):
            for x in range(max(0, min(x0, x1)), min(self.w, max(x0, x1) + 1)):
                self.set(x, y, c)

    def hline(self, y, x0, x1, c, dashed=False):
        for x in range(max(0, x0), min(self.w, x1)):
            if dashed and (x // 6) % 2:
                continue
            self.set(x, y, c)

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3])
                       for y in range(self.h))

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2,
                                             0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9))
                + chunk(b"IEND", b""))


# 5x7 digit/letter glyphs — enough for a token and a terse caption.
FONT = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    " ": ("000", "000", "000", "000", "000"), "-": ("000", "000", "111", "000", "000"),
    ":": ("000", "010", "000", "010", "000"), ".": ("000", "000", "000", "000", "010"),
}
for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    FONT.setdefault(ch, None)
_LETTERS = {
    "A": ("111", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("111", "100", "101", "101", "111"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"), "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"), "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"), "R": ("111", "101", "110", "101", "101"),
    "S": ("111", "100", "111", "001", "111"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
}
FONT.update(_LETTERS)


def text(cv: Canvas, x: int, y: int, s: str, c=TEXT, scale=2):
    for ch in s.upper():
        g = FONT.get(ch)
        if g:
            for r, row in enumerate(g):
                for col, on in enumerate(row):
                    if on == "1":
                        cv.rect(x + col * scale, y + r * scale,
                                x + col * scale + scale - 1,
                                y + r * scale + scale - 1, c)
        x += 4 * scale
    return x


def render_candles(bars, *, vwap=None, levels=(), caption="",
                   token: str | None = None) -> bytes:
    """bars: sequence of (open, high, low, close). Nothing else is drawn --
    no outcome markers, no direction hints, no 'BUY'."""
    cv = Canvas()
    if not bars:
        text(cv, 20, 20, "NO BARS", (239, 83, 80))
        return cv.png()

    lo = min(b[2] for b in bars)
    hi = max(b[1] for b in bars)
    if vwap is not None:
        lo, hi = min(lo, vwap), max(hi, vwap)
    for lv in levels:
        lo, hi = min(lo, lv), max(hi, lv)
    span = (hi - lo) or 1.0
    pad_t, pad_b, pad_l, pad_r = 46, 30, 20, 20
    plot_h = H - pad_t - pad_b

    def ypx(p):
        return int(pad_t + (hi - p) / span * plot_h)

    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        cv.hline(int(pad_t + f * plot_h), pad_l, W - pad_r, GRID)

    n = len(bars)
    slot = max(3, (W - pad_l - pad_r) // n)
    body = max(1, slot // 2)
    for i, (o, h_, l_, c_) in enumerate(bars):
        x = pad_l + i * slot + slot // 2
        col = UP if c_ >= o else DOWN
        cv.rect(x, ypx(h_), x, ypx(l_), col)
        cv.rect(x - body // 2, ypx(max(o, c_)), x + body // 2, ypx(min(o, c_)),
                col)

    if vwap is not None:
        cv.hline(ypx(vwap), pad_l, W - pad_r, VWAP, dashed=True)
    for lv in levels:
        cv.hline(ypx(lv), pad_l, W - pad_r, (120, 130, 150), dashed=True)

    if caption:
        text(cv, pad_l, 12, caption[:52], TEXT, 2)
    if token:
        text(cv, W - pad_r - len(token) * 8 - 8, 12, token, TEXT, 2)
    return cv.png()


def snapshot(bars, path, *, symbol, as_of, vwap=None, levels=(),
             for_challenger=False, context_hash="", token=None) -> dict:
    """Write the PNG and its metadata sidecar.

    `for_challenger=True` strips the symbol and any wording that could
    steer the model: it should see market geometry, not a hint.
    """
    caption = "" if for_challenger else f"{symbol} AS OF {str(as_of)[11:16]}"
    png = render_candles(bars, vwap=vwap, levels=levels, caption=caption,
                         token=token)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(png)
    meta = {
        "snapshot_id": hashlib.sha256(png).hexdigest()[:16],
        "symbol": ("WITHHELD_FOR_CHALLENGER" if for_challenger else symbol),
        "as_of_time": str(as_of),
        "bars_visible": len(bars),
        "future_bars": 0,
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "context_packet_hash": context_hash,
        "for_challenger": for_challenger,
        "evidence_class": "EODHD_FORWARD_OBSERVATION",
        "decision_power": "NONE_OBSERVATIONAL_EPOCH1",
    }
    Path(str(p) + ".json").write_text(__import__("json").dumps(meta, indent=2))
    return meta
