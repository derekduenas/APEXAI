"""WM-0E-R7.1 §3-§7: R7_1_RUNNER_QUALIFICATION_V0.

The EXACT production run_cell path executes one complete cell for each of the
six control types on DEVELOPMENT-ONLY seeds under a test-only court identity
(namespace WM0E_R7_1_RUNNER_QUALIFICATION_DEV_V0, purpose
RUNNER_QUALIFICATION_DEVELOPMENT_ONLY). Full lifecycle: world(s), roles, fit,
bootstrap, geometry, provenance, identity, persist, reload-validate; then
exactly-once and corruption refusals on the same artifacts. This module never
derives, instantiates, executes or inspects an acceptance seed: the acceptance
NAMESPACE is None while this suite is qualified, and the module asserts it.
"""
import json
import os

import pytest

from apex.world_model import bootstrap as BS
from courts import final_court as F
from regression import runner as RR

FROZEN_ENGINE = "af3ae117a69ee485bf8ac2fa86c7b962db7f21ab639507dffb6389ed0a2f35ac"
FROZEN_SURFACE = "f6b87f2947e2bf62403a04dcaeda0805bc62e8ca1cfebacdc7b14ef10856439d"
QUAL_NS = F.QUALIFICATION_NAMESPACE


@pytest.fixture(scope="module")
def qual(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("r71_qualification"))
    defn = F.define("QUALIFICATION", 0.0, FROZEN_SURFACE, namespace=QUAL_NS,
                    purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    cells = {ctl: F.run_cell(defn, ctl, 0, out) for ctl in F.CONTROLS}      # the REAL path, index 0
    return {"out": out, "defn": defn, "cells": cells}


def test_qualification_never_touches_an_acceptance_namespace():
    """At the repair commit (0b92c0b7a) NAMESPACE was None and this suite
    passed with the acceptance tests skipped -- that is the historical proof
    that no acceptance seed existed during qualification. The PERMANENT
    invariant is phase-independent: the qualification namespace is a
    development namespace, distinct from any acceptance or consumed one, and
    it can never be used for acceptance."""
    assert "DEV" in QUAL_NS and QUAL_NS not in F.CONSUMED_NAMESPACES and QUAL_NS != F.NAMESPACE
    with pytest.raises(F.CourtIntegrityFailure):
        F.define("X", 0.0, FROZEN_SURFACE, namespace=QUAL_NS, purpose="ACCEPTANCE")
    if F.NAMESPACE is None:
        with pytest.raises(F.CourtIntegrityFailure):
            F.seed_manifest()


def test_runner_identity_and_frozen_contracts():
    assert F.RUNNER_VERSION == "FINAL_COURT_RUNNER_V0.1" and "WM-IMPL-002" in F.RUNNER_HISTORY["V0"]
    assert BS.content_identity() == FROZEN_ENGINE and RR.scientific_surface_hash(".")["hash"] == FROZEN_SURFACE
    src = open(F.__file__).read()
    assert "bootstrap_result = BS.bootstrap_test" in src and "b = BS.bootstrap_test" not in src and "b.config" not in src


@pytest.mark.parametrize("ctl", F.CONTROLS)
def test_end_to_end_cell_lifecycle(qual, ctl):
    c = qual["cells"][ctl]; defn = qual["defn"]
    assert c["control"] == ctl and c["index"] == 0 and c["court_id"] == defn.court_id and c["court_hash"] == defn.court_hash
    assert c["namespace"] == QUAL_NS and c["purpose"] == "RUNNER_QUALIFICATION_DEVELOPMENT_ONLY" and c["runner"] == "FINAL_COURT_RUNNER_V0.1"
    assert c["primary_seed"] == F.derive_seed(ctl, F.PRIMARY_ROLE[ctl], 0, QUAL_NS)
    exp_eval, exp_train = F.EXPECTED_GEOMETRY[ctl]
    assert c["n_eval"] == exp_eval == 1860 and c["n_train"] == exp_train
    assert c["verdict"] in ("SIGNAL_DETECTED", "NO_SIGNAL") and 0 < c["p"] <= 1 and c["block"]["block_length"] >= 15
    assert isinstance(c["t_obs"], float) and isinstance(c["mean_d"], float) and c["executed_split_hash"]
    assert set(c["secondary"]) == {"hac_t", "hac_verdict", "non_overlap_z", "non_overlap_verdict", "legacy_iid_z"}
    if ctl in ("N0", "N3"):
        assert len(c["worlds"]) == 2 and c["companion_seed"] not in (None, c["primary_seed"])
        assert len(set(c["worlds"].values())) == 2                                  # two distinct world hashes
    else:
        assert list(c["worlds"]) == ["world"] and c["companion_seed"] is None
    if ctl == "N1":
        assert c["n_train"] == 501
    # persisted and reload-validated by the real path
    path = os.path.join(qual["out"], "cells", "%s_00.json" % ctl)
    assert os.path.exists(path) and oct(os.stat(path).st_mode)[-3:] == "444"
    on_disk = json.load(open(path))
    assert on_disk["cell_id"] == c["cell_id"] == F.cell_id(defn.court_id, ctl, 0, c["worlds"])
    assert on_disk["worlds"] == c["worlds"] and on_disk["p"] == c["p"] and on_disk["block"] == c["block"]
    assert F.load_cell(path, defn)["cell_id"] == c["cell_id"]


def test_six_distinct_cells_persisted_once_each(qual):
    files = sorted(os.listdir(os.path.join(qual["out"], "cells")))
    assert files == sorted("%s_00.json" % c for c in F.CONTROLS)
    ids = [c["cell_id"] for c in qual["cells"].values()]
    assert len(set(ids)) == 6


# ---------------------------------------------------------------- §5 exactly-once
def test_second_execution_of_same_cell_is_refused(qual):
    with pytest.raises(F.CourtIntegrityFailure):
        F.run_cell(qual["defn"], "N2", 0, qual["out"])
    with pytest.raises(FileExistsError):
        F._write_once(os.path.join(qual["out"], "cells", "N2_00.json"), {"x": 1})
    assert json.load(open(os.path.join(qual["out"], "cells", "N2_00.json")))["cell_id"] == qual["cells"]["N2"]["cell_id"]


def test_reload_refuses_wrong_court_identity(qual):
    other = F.define("OTHERCOMMIT", 0.0, FROZEN_SURFACE, namespace=QUAL_NS, purpose="RUNNER_QUALIFICATION_DEVELOPMENT_ONLY")
    assert other.court_id != qual["defn"].court_id
    with pytest.raises(F.CourtIntegrityFailure):
        F.load_cell(os.path.join(qual["out"], "cells", "P0_00.json"), other)


def test_reload_refuses_unexpected_seed_and_corruption(qual, tmp_path):
    good = json.load(open(os.path.join(qual["out"], "cells", "N4_00.json")))
    bad = dict(good); bad["primary_seed"] = good["primary_seed"] + 1
    p = tmp_path / "seed.json"; p.write_text(json.dumps(bad))
    with pytest.raises(F.CourtIntegrityFailure):
        F.load_cell(str(p), qual["defn"])
    bad2 = dict(good); bad2["worlds"] = {"world": "deadbeef"}          # cell_id no longer recomputes
    p2 = tmp_path / "id.json"; p2.write_text(json.dumps(bad2))
    with pytest.raises(F.CourtIntegrityFailure):
        F.load_cell(str(p2), qual["defn"])
    p3 = tmp_path / "corrupt.json"; p3.write_text("{not json")
    with pytest.raises(F.CourtIntegrityFailure):
        F.load_cell(str(p3), qual["defn"])
    bad4 = dict(good); bad4["n_train"] = 700
    p4 = tmp_path / "geom.json"; p4.write_text(json.dumps(bad4))
    with pytest.raises(F.CourtIntegrityFailure):
        F.load_cell(str(p4), qual["defn"])


def test_acceptance_definition_refuses_consumed_and_qualification_namespaces():
    for ns in F.CONSUMED_NAMESPACES + (QUAL_NS,):
        with pytest.raises(F.CourtIntegrityFailure):
            F.define("X", 0.0, FROZEN_SURFACE, namespace=ns, purpose="ACCEPTANCE")
