"""Track 3: options expression engine (Build Directive v4.0 section 1).

Consumes a DISTRIBUTION over forward returns plus a chain snapshot; compares
defined-risk structures against common stock under a config-declared
objective. Options amplify alpha, they do not create it (v1.0 section 22):
the engine must be capable of choosing common stock, and across realistic
inputs it mostly should. Never wired to live options data, a broker, or
capital.
"""
