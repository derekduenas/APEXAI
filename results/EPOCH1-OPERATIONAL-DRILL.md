# EPOCH 1 OPERATIONAL DRILL — 2026-09-14 14:56:49.638049+00:00

- **PASS** credentials resolve: keychain resolves (value not logged)
- **PASS** EODHD authenticates: 960 bars for SPY 08-14 (network)
- **FAIL** calendar: AssertionError: 
- **PASS** timezone: UTC->ET conversion OK (10:56 EDT)
- **FAIL** state->scan->capital->ledger->resolver->scoreboard: FileNotFoundError: [Errno 2] No such file or directory: 'data/snapshots/sharadar/current/universe_candidates.csv'
- **PASS** single failed symbol degrades: raised IntradayDataError (clock isolates per-symbol)
- **PASS** partially written ledger: writer links past tear; recovery stamped
- **PASS** disk space: 12GB free
- **PASS** launchd wrapper runs: wrapper exit 0 (Saturday fast-exit path)
- **PASS** graceful restart: unload/load cycle; job re-listed
- **FAIL** production ledger untouched: AssertionError: 

Notes: reboot/sleep-wake rely on launchd StartInterval re-firing post-wake (missed ticks are skipped, never queued — by design); duplicate manual invocation remains a procedural rule (F-14, recorded); no strategy logic touched.

## VERDICT: FAILURES ABOVE
