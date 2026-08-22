"""APEX cross-session memory — durable, dated artifacts that one
session writes and a LATER session reads.

THE YESTERDAY_STATE LAW: everything in this package is labeled with the
session it describes and is surfaced to a later session as
YESTERDAY_STATE (or OLDER_STATE), never as CURRENT_TRUTH. A memory
record is what was observed on a specific past day; it is not a belief
about today, and nothing here may be read as one.

decision_power = NONE_MEMORY: this package records and retrieves. It
authorizes nothing, promotes nothing, and changes no threshold.
"""

MEMORY_POWER = "NONE_MEMORY"
