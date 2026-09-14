# R5 source review and early-trigger repair

Reviewed base: `b63f24a5e854e5252f114c8fb87f040a6d091182`.
This is a bounded independent review of scheduling behavior, not approval of
the whole producer or an operational commissioning result.

## Confirmed defect and repair

`TOO_EARLY` was in `premarket_journal.DECISIVE`. The production CLI recorded
an early call, then refused the later on-time call as
`RECONCILED_DUPLICATE ... prior=TOO_EARLY`. No absorption occurred.
Both new tests failed against the unchanged R5 production code.

This also contradicts the dual-season schedule design: on a UTC host in winter,
the summer trigger runs an hour before the intended winter trigger. The early
invocation must end without ending the day's scheduled stage. This is a code
reproduction, not evidence of an observed launchd incident on Derek's Mac.

The repair removes only `TOO_EARLY` from the decisive outcome set. The original
receipt remains in the journal; no history is deleted. Completed stages still
refuse duplicate invocations. Window limits and provider behavior are unchanged.
The old R5 parameter and exact tuple assertion were updated because they pinned
the defective stage-terminal interpretation; all other decisive states remain.

## Production-path evidence

The new test starts separate processes at the actual `premarket_stage.py` entry
point. All five early calls precede the scheduled calls; the clock never rewinds.
The four absorption stages and seal each then complete exactly once, followed
by duplicate calls that do no additional work. Final persisted journal contains
four absorptions and one completed seal. Clock, market transport, Captain reply,
and output root are explicitly synthetic. All fixture data lives under pytest's
temporary directory; no provider or model service is contacted.

Before repair: both new tests fail. After repair: both pass.
R5 suite alone at base: 63 passed, 5 failed. Repaired R5 plus new tests:
64 passed, 5 failed. One obsolete TOO_EARLY parameter was superseded by the two
new tests, explaining the net increase of one.

The five failures were inspected on both runs:

| Test suffix | Actual cause in this checkout |
|---|---|
| `test_the_generated_binding_matches_the_host_and_the_schedule` | Prepared LA binding versus process timezone Asia/Kuwait |
| `test_every_prepared_plist_carries_every_local_trigger_the_host_needs` | Prepared LA triggers versus this process's timezone |
| `test_the_prepared_artifacts_have_not_drifted_from_schedule_or_host_timezone` | Same host-specific generation mismatch |
| `test_the_installed_production_files_are_byte_for_byte_unchanged` | Operator's Mac plist absent here |
| `test_no_per_stage_or_disposable_agent_is_loaded` | `launchctl` unavailable here |

Those host checks remain unchanged. They are not evidence that the Mac's
scheduler is installed, unchanged, or working. No full-tree regression was run.

## Remaining gates and integration sequence

The reported pending comparison is `602d5a2` versus `533dfbd` (R3 versus R4).
It cannot establish regression status for R5 `b63f24a`, or this repaired candidate.
Reconcile those results honestly, then validate the exact integration candidate.

The court reconstruction PR and R5 modify disjoint files. That supports combining
them for a candidate test; it does not prove their runtime compatibility.

Next functional milestone is the sealed premarket packet's downstream handoff:
persist its identity and timing as prior context, demonstrate the actual Twin
reader, and report attached versus consumed evidence separately. Then follow the
same decision through the existing model path. Four absent sources must remain
visible rather than becoming invented context. This repair grants the packet no
new trading authority.

Installation, disposable LaunchAgent proof, live-provider commissioning and
paper execution remain outside this change. No host or deployment was touched.
