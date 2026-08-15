"""The LLM producer pair -- the component the harness actually exists to test.

Two variants per subject, ALWAYS emitted together:

  llm_full      structured market context (raw numbers, no pre-computed APEX
                rank -- the model must reason, not launder our own signal)
  llm_stripped  the IDENTICAL prompt with the market block replaced by an
                explicit withholding notice. The ticker remains -- that is
                the point: whatever the model "knows" from its weights plus
                fluency is exactly what this twin measures. If llm_full does
                not beat llm_stripped, its confidence is not information.

Directive v2.0 rule 17: these are NEVER backtested. They emit only on live
dates, forward, and their record accrues in calendar time.

The runner is injected (default: `claude -p --model haiku` headless CLI) so
tests never make live calls. Model + prompt hash are part of the producer id;
changing either creates a NEW producer with a fresh record, not a quiet
continuation of the old one.
"""

from __future__ import annotations

import json
import re
import subprocess

from apex.reality.harness import Prediction, canonical_hash, make_prediction

MODEL = "haiku"
HORIZON = 20
TIER = 3                      # judgment claims, the lowest-authority tier
CLAMP = (0.02, 0.98)          # certainty is never warranted, LLMs love 0.95

INSTRUCTIONS = """You are one voice in a forecasting panel. Estimate the
probability that the stock below OUTPERFORMS the median of its universe
(US small-cap common stocks, $100M-$2B market cap) over the next 20 trading
days. Respond with ONLY a JSON object: {"probability": <float in (0,1)>}.
No prose. Overconfidence is scored against you via log loss."""

WITHHELD = "[market data withheld for this variant]"


def market_block(context: dict) -> str:
    return (f"ticker: {context['ticker']}\n"
            f"as-of date: {context['trade_date']}\n"
            f"close: {context['close']:.2f}\n"
            f"market cap ($M): {context['mcap_m']:.0f}\n"
            f"trailing returns: 20d {context['r20']:+.1%}, "
            f"60d {context['r60']:+.1%}, 120d {context['r120']:+.1%}\n"
            f"gross profits / assets: {context['gp_assets']:.3f}\n"
            f"book / market: {context['btm']:.3f}")


def build_prompts(context: dict) -> tuple[str, str]:
    full = f"{INSTRUCTIONS}\n\n{market_block(context)}"
    stripped = (f"{INSTRUCTIONS}\n\nticker: {context['ticker']}\n"
                f"as-of date: {context['trade_date']}\n{WITHHELD}")
    return full, stripped


def parse_probability(text: str) -> float | None:
    m = re.search(r'\{[^{}]*"probability"[^{}]*\}', text, re.DOTALL)
    if not m:
        return None
    try:
        p = float(json.loads(m.group(0))["probability"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    if not (0.0 < p < 1.0):
        return None
    return min(max(p, CLAMP[0]), CLAMP[1])


def cli_runner(prompt: str) -> str:
    """Headless call through the local Claude CLI. Never used in tests."""
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", MODEL],
        capture_output=True, text=True, timeout=120)
    return out.stdout


def llm_predictions(context: dict, peers, created_at: str,
                    run_fn=cli_runner) -> list[Prediction]:
    """Emit the full/stripped PAIR for one subject. If either call fails to
    parse, NEITHER is recorded -- an unpaired variant would bias the
    comparison the pair exists to make."""
    full_prompt, stripped_prompt = build_prompts(context)
    results = []
    for variant, prompt, inputs in (
        ("llm_full", full_prompt, context),
        ("llm_stripped", stripped_prompt,
         {"ticker": context["ticker"], "trade_date": context["trade_date"]}),
    ):
        p = parse_probability(run_fn(prompt))
        if p is None:
            return []
        producer = f"{variant}/{MODEL}/{canonical_hash(INSTRUCTIONS)[:8]}"
        results.append(make_prediction(
            trade_date=context["trade_date"], horizon_days=HORIZON,
            subject=context["security_id"], claim_type="relative",
            probability=p, epistemic_tier=TIER, producer=producer,
            inputs=inputs, rationale={"variant": variant, "model": MODEL},
            resolution_rule="relative_vs_peer_median",
            resolution_params={"peers": list(peers)}, created_at=created_at))
    return results
