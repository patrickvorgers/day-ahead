# Timezone contracts before batch 4 fixes

Assessment date: 2026-10-14. This change adds tests only; it does not activate timezone rules or fix application behavior. It is based on batch 3 and must remain separate from the preceding draft pull requests.

## Intended contract

Home Assistant's configured timezone determines local planning times and report calendar boundaries. A Python process running in UTC or Europe/Amsterdam must produce the same physical schedule, report bounds and provider requests for identical HA configuration, input data and UTC instant. Elapsed charging time is measured on the physical timeline rather than by subtracting local clock labels.

## Reproducible test design

`dao/tests/prog/test_timezone_contracts.py` runs seven cases in separate subprocesses using `TZ=UTC` and `TZ=Europe/Amsterdam`. Both receive `ha_zone=Europe/Amsterdam` and the same fixed UTC instant. Windows skips this Linux application matrix because it requires POSIX `tzset`; no Windows timezone setting is changed.

`tests/timezone_probe.py` executes the real reporting constructor/period generation, one scheduler dispatch iteration, the real ENTSO-E request boundary path and a real synthetic `DaCalc.calc_optimum()` solve. HA, databases and provider access are isolated with mocks and ReplayIO; it does not contact live services. Scheduler waits and task execution are mocked; this checks dispatch selection, not long-running scheduler timing or an agreed duplicate-hour execution policy.

Scenario helper imports normally force UTC. The probe restores the requested process timezone after those imports, disables ReplayIO's naive-UTC frozen clock, and supplies a fixed physical instant through process-local `now()`. A physical 15-minute input grid covers the skipped and repeated hours; the current replay format supplies HA-local labels plus explicit prognosis epochs. A SHA-256 comparison verifies identical canonical snapshots before accepting any application result. Subprocess startup, timeout, timezone and fixture-identity failures remain errors and cannot be classified as expected application failures.

The optimizer fixture uses one solver thread, fixed seed 17, distinct increasing quarter-hour prices and the application's minimum absolute MIP-gap tolerance (0.00001). It compares solved status, physical start, the calculator's own epoch-grid charging timestamps/energy and objective value. It does not reinterpret display labels using the process timezone. Available hours are observed from the actual calculator frame, rather than by copying its expression into a test. Warnings and early returns are retained in the assertion evidence when the calculator cannot reach that point. Both `now()` and `today()` use the fixed physical instant.

## Measured baseline

The unmasked run reports **21 passed, 28 failed, zero setup errors** across 49 checks. The same result was reproduced with the tighter solver tolerance. These are failing assertions, not 28 independent bugs.

| Case | Report periods | HA day boundaries | Scheduler | Price equality | Price calendar | EV elapsed hours | Optimizer plan/cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| winter | PASS | PASS | FAIL | PASS | PASS | FAIL | FAIL |
| summer | PASS | PASS | FAIL | PASS | PASS | FAIL | FAIL |
| local-midnight | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL |
| spring-forward | PASS | PASS | FAIL | PASS | PASS | FAIL | FAIL |
| fall-back | FAIL | FAIL | FAIL | FAIL | FAIL | FAIL | PASS |
| first-0230 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS |
| second-0230 | PASS | PASS | FAIL | PASS | FAIL | FAIL | PASS |

Case anchors (all UTC): winter `2026-01-14 08:00`, summer `2026-07-01 08:00`, local-midnight `2026-07-01 22:30`, spring-forward `2026-03-29 00:30`, fall-back `2026-10-24 23:30`, first-0230 `2026-10-25 00:30`, second-0230 `2026-10-25 01:30`. The last two represent different physical instants with the same Amsterdam clock label.

Findings:

- Report comparisons and HA day-boundary assertions fail at local-midnight and fall-back because the UTC process selects a different calendar date. Other cases retain the expected local day bounds, including 23- and 25-hour days when those boundaries are interpreted in HA time.
- Scheduler selection fails in all seven paired cases: the process-local hour is used instead of the configured HA hour.
- Provider boundary equality fails at local-midnight and fall-back. Correct calendar-day coverage also fails for both occurrences of 02:30 on the wintertime day; the ENTSO-E request can have identical start and end instants.
- The EV elapsed-hours checks fail in all seven cases. Some runs return early before reaching the EV availability calculation because of the existing timestamp/grid mismatch; those failures are recorded as unreachable availability, not as measured arithmetic results.
- Optimizer plan/cost equality fails for winter, summer, local-midnight and spring-forward. The three autumn optimizer comparisons pass for this small charging demand; that does not cancel their failing availability checks or prove all autumn plans correct.

## Running and retiring known failures

The measured 28 failures have narrow case/function entries in `KNOWN_FAILURES`, with `xfail(strict=True, raises=AssertionError)`. Routine CI therefore reports **21 passed, 28 xfailed** for this module; those failures are explicitly unresolved and are never reported as passing coverage. A newly passing known case produces a strict XPASS failure until its entry is removed. Unexpected exceptions and failures of previously passing cases fail CI normally.

The full isolated regression suite with this baseline reports **214 passed, 58 skipped, 28 xfailed**. The existing 58 skips retain their previous meaning; they are separate from the measured timezone failures.

Run the complete matrix in a Linux development environment:

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_timezone_contracts.py -q -rxX
```

Expose the actual pre-fix failures and save a baseline report:

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_timezone_contracts.py \
  --runxfail --junitxml=.local/timezone-before-fixes.xml -q
```

The unmasked command intentionally exits nonzero while defects remain. The matrix is included in the local isolated test selection, scenario CI regression step and Dev Container clean-install verification. For each batch 4 fix, remove only the corresponding known-failure entries and confirm those assertions pass in both process zones. Keep the HA contract and physical fixture unchanged unless a separately reviewed interface change requires adapting the replay transport representation.
