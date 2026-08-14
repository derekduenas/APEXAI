# Small-Cap Universe Pivot — Independent Justification Memo

Status: DRAFT FOR THE HUMAN GATE. Nothing here registers anything or spends
anything. This memo exists because the contamination rule demands it.

## 1. The charge to answer

APEX-003 (gross profitability, large-cap universe) closed FAILURE at t=2.525
vs the registered 2.92 — a near-miss. The most tempting next move is "run the
same signal in small caps, because it almost passed." **That reasoning is a
descendant of failure**: a failed result selecting its successor. Under the
contamination rules it is inadmissible on its own. A small-cap experiment is
registrable only if the universe pivot stands on grounds that do not include
APEX-003's outcome. This memo states those grounds and, deliberately, the
grounds that do NOT count.

## 2. Grounds that are independent of APEX-003's result

**2a. The cost-gate arithmetic, committed before the result existed.**
Commit `dc156b0` ("Credit-3 prep: minimal monetisation evaluator, viability
gate") predates the APEX-003 validation run. It encodes the declared cost
model under which the frozen large-cap universe needs roughly 4.9%/yr gross
decile spread to clear the 2% net viability bar. That arithmetic — the
large-cap universe is close to unmonetisable for published fundamental
factors at this cost model — was true, committed, and known **before** the
credit was spent. It motivates a universe where gross premia are larger,
regardless of what APEX-003 later showed.

**2b. Published prior art on the size interaction, all predating this
program.** Fama–French (2008, "Dissecting Anomalies") and the Hou–Xue–Zhang
replication literature document that most cross-sectional anomalies are
substantially stronger outside the largest-cap segment; Asness et al. (2018,
"Size Matters, If You Control Your Junk") documents the quality/size
interaction specifically. None of this evidence was produced by, or filtered
through, any APEX experiment.

**2c. Capital fit.** At this operation's capital, capacity in a
$100M–$2B-cap universe is not a binding constraint — the one structural
advantage a small operator has over the institutions that arbitrage
large-cap factors. This is a fact about the operator, not about any result.

**2d. The data is already on disk.** The frozen snapshot contains the full
CRSP-like Sharadar universe; the pivot is a config-level universe
redefinition, not a data purchase. Zero marginal spend.

## 3. Grounds that are NOT admissible, stated so the gate can check

- "APEX-003 almost passed, so the signal is probably real." — Inadmissible.
  The near-miss may not be used to size, select, or justify anything.
- "t=2.525 in large caps implies t>2.92 in small caps." — Inadmissible and
  also not implied; small-cap IC has different breadth, noise, and cost.
- Any decile figure, IC, or robustness statistic from APEX-003. The
  experiment is closed; its numbers are provenance-tainted for selection.

## 4. What the honest failure mode looks like

If the gate finds that, stripped of §3, the case in §2 would not by itself
justify spending a credit — then the pivot dies here, and that is the system
working. The signature below is the ruling, not a formality.

## 5. Disclosure

The signal proposed for the small-cap experiment (gross profitability) is the
same signal APEX-003 tested. The universe argument (§2) is independent of the
result; the SIGNAL CHOICE cannot be fully laundered of the fact that a GP
execution path now exists and is certified. The draft protocol therefore
carries `Descendant of failure: CONTESTED — human ruling required` rather
than a clean NO. Alternatives the gate may prefer: register H3
(quality-conditioned value, dossier 123f67fa, already screened) in the
small-cap universe instead, which shares the §2 grounds but not the
tested-signal overlap.

---

Gate ruling: **APPROVED — H-GP-SC (gross profitability, small-cap universe),
with the STRICTER legacy bar t >= 2.92 retained** (true size 0.872% under the
derived null — the operator chose credibility over the exact-1% 2.85). The
CONTESTED descendant-of-failure disclosure in §5 is accepted as part of the
record, not erased by this ruling. Ruled by the operator, 2026-08-13, via
recorded selection; the protocol header signature at registration is the
final human act and remains pending.
