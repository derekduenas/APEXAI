"""APEX FRONTIER NEXT-GEN — Desk B's successor intelligence organs.

Structurally separate from `apex.frontier` (which stays exactly as it
is) and from `apex.hunter` / `apex.captain` / `apex.execution` (which
this package may read the OUTPUTS of via result ledgers, but must never
import). See results/frontier/FRONTIER_NEXTGEN_BUILD_MAP.md for the full
architecture map and the firewall this package is held to.

FRONTIER2_POWER = "NONE_FRONTIER_SHADOW": every record any module in this
package writes carries this value. Nothing here can authorize Capital,
alter Epoch-1 records, mint official Hunter matches, move stops, size
positions, place orders, or claim calibration. See
tests/test_frontier2_firewall.py for the mechanical proof.
"""

FRONTIER2_POWER = "NONE_FRONTIER_SHADOW"
