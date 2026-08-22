"""APEX RESEARCH LIBRARY — knowledge infrastructure, not trading
authority. Preserves research, mechanisms, evidence, hypotheses,
falsification logic, source provenance, and research lineage, and
makes them retrievable by authorized research/intelligence components.

RESEARCH_LIBRARY_POWER = "NONE_RESEARCH_MEMORY": nothing in this package
can modify Hunter, Captain, Frontier-2, Capital, Shadow Paper, execution,
playbooks, or thresholds; promote a research finding; treat research
prose as alpha; or spend an experiment credit. It cannot even import the
modules that could (proven mechanically in
tests/test_research_library_firewall.py, same discipline as
apex/frontier2's own firewall).

This package is DELIBERATELY SEPARATE from apex.research (the existing,
CERTIFIED discovery/hypothesis-registration pipeline with real credit
consumption and holdout access). apex.research_library never imports
apex.research and apex.research never imports this package -- they are
two different systems that happen to share the word "research": one
tests hypotheses against sealed data under governance; this one stores
what has been read and thought, for humans and bounded machine
consumers to retrieve later.
"""

RESEARCH_LIBRARY_POWER = "NONE_RESEARCH_MEMORY"
