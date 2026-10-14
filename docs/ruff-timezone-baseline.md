# Timezone contracts before batch 4 fixes

Assessment date: 2026-10-14. The original measurement below precedes application fixes. Separate report-period, price-boundary and scheduler fixes now follow that baseline on the same branch, based on batch 3. Timezone rules are not activated yet.

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

## Report-period fix

Report-period generation now obtains the current clock in Home Assistant's configured timezone. A supplied timezone-aware reference instant is converted to that zone; a naive reference remains HA-local wall time. Calendar calculations and naive database-boundary representation are preserved, including the existing 13:00 horizon cutoff.

Before removing any markers, the matrix produced strict XPASS for exactly four former failures: report-period equality and HA day boundaries for `local-midnight` and `fall-back`. Only those four markers were removed. All 14 report assertions now pass across the seven paired process-zone cases, including the 23-/25-hour day boundaries. The historical matrix above remains unchanged as pre-fix evidence.

Five additional reference-time cases cover summer/autumn midnight conversion, the HA-local 13:00 cutoff and compatibility with naive reference times. The three aware-reference cases failed before the fix; both naive-reference cases already passed.

## Price-boundary fix

Default price request dates and the noon cutoff now use the configured HA timezone. The shared request setup advances calendar dates before localizing midnight rather than adding fixed 24-hour durations. ENTSO-E continues requesting complete local days, converting aware explicit bounds into the configured timezone before selecting their dates; naive bounds are HA-local. Provider-specific Nordpool iteration and other provider response processing are outside this fix.

Before marker removal, exactly six price checks produced strict XPASS: process-zone equality for `local-midnight` and `fall-back`, and calendar-day coverage for those two cases plus `first-0230` and `second-0230`. Only those six entries were removed. All 14 price assertions now pass across the paired-process matrix.

Ten additional isolated cases inspect the actual ENTSO-E client arguments, with network access mocked. They assert explicit UTC boundary instants and elapsed lengths of 23/25 hours for transition days and 47/49 hours for two-day windows spanning those transitions. They also cover HA midnight, both sides of the local noon cutoff, a configured London timezone, and explicit naive/UTC-aware bounds. Before this fix six cases failed and four passed, including the already-correct spring day; all ten now pass.

## Scheduler transition contract and fix

The scheduler now advances and waits using UTC-aware instants, converts each target minute to the configured HA timezone for pattern matching, and tracks the last physical target minute rather than its minute number. Time logs include the UTC offset. The original paired-process matrix checks individual dispatches; additional continuous-clock tests establish the transition behavior below.

- Match supported `HHMM` and `xxMM` patterns against Home Assistant's local clock. During an autumn transition, both physical occurrences of a matching minute are eligible: `0230` runs twice, one hour apart, and `xx30` runs in both repeated hours. This is eligibility, not a delivery guarantee when the scheduler is stopped or busy.
- Skip nonexistent local minutes during the spring transition; do not move a `0230` entry to `0300` or catch it up later.
- Identify a dispatch by its schedule entry and physical UTC minute, not just its local clock label. Avoid duplicate dispatch of that entry for the same physical minute within one running scheduler process. Restart persistence and overlapping schedule-entry deduplication are separate concerns.
- Interpret the configured start offset as elapsed seconds before the physical scheduled minute. Use the physical timeline for minute progression and waiting, converting to HA time for pattern matching.
- Do not introduce catch-up after restarts or blocking tasks. Preserve sequential task execution. Include the UTC offset in scheduler time logs so the two occurrences of 02:30 can be distinguished.
- `02xx` is recognized by the dispatch code but rejected by the configuration validator. It is not a supported configuration pattern; adding it is outside this timezone fix.

No built-in scheduler action has a verified exactly-once-per-calendar-day requirement. This does not establish that all actions are idempotent. Optimization can write HA controls and send notifications; a second run an hour later is a new calculation with possible external effects. Collection can repeat provider requests, training and baseload calculation can repeat work and replace outputs, and cleanup/consolidation can run again. Do not silently add action-specific suppression during this fix. Users needing daily maintenance outside the repeated hour can schedule it at a valid time such as 04:00 in Europe/Amsterdam; other zones need their own transition check.

Continuous tests exercise every physical minute across both transitions under UTC and Europe/Amsterdam, with start offsets of 0, 10 and 60 seconds: two eligible `0230` executions during autumn, none during spring, all `xxMM` matches and correct elapsed start offsets. Separate cases cover repeated selection of the same physical minute, missed minutes during a blocking task and an inactive scheduler. The existing dispatch-order/multiplicity tests remain in place; their fake base now supplies the HA timezone and an aware clock. All 21 scheduler cases pass. On the original scheduler, six of the 15 added cases fail, all six autumn-transition combinations; four existing matching cases also fail with the corrected aware-clock fixture.

Clock advancement and task execution are simulated; no external controls are changed. These tests verify scheduling semantics, not operating-system wake precision or exactly-once delivery across crashes or restarts.

Before marker removal, exactly the seven scheduler matrix cases produced strict XPASS. Only those entries were removed; all seven now pass normally. The probe's fixed-clock adapter supplies aware UTC values for the scheduler's explicit UTC clock reads, preserving the same physical anchors and HA configuration.

## Running and retiring known failures

The original 28 failures had narrow case/function entries in `KNOWN_FAILURES`, with `xfail(strict=True, raises=AssertionError)`. After the report fix, 24 remained; after the price-boundary fix, 18 remained. With the scheduler fix, routine matrix output is **38 passed, 11 xfailed**. The remaining failures concern EV availability and optimizer behavior; they are explicitly unresolved and are never reported as passing coverage. A newly passing known case produces a strict XPASS failure until its entry is removed. Unexpected exceptions and failures of previously passing cases fail CI normally.

The original full isolated regression suite reported **214 passed, 58 skipped, 28 xfailed**. After the report fix and five additional reference-time cases it reported **223 passed, 58 skipped, 24 xfailed**. With the price-boundary fix and its ten additional cases it reported **239 passed, 58 skipped, 18 xfailed**. With the scheduler fix and 15 added scheduler cases it reports **261 passed, 58 skipped, 11 xfailed**. The existing 58 skips retain their previous meaning; they are separate from the measured timezone failures.

Run the complete matrix in a Linux development environment:

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_timezone_contracts.py -q -rxX
```

Expose the remaining failures (run on the original baseline revision to reproduce the pre-fix measurement):

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_timezone_contracts.py \
  --runxfail --junitxml=.local/timezone-unmasked.xml -q
```

The unmasked command intentionally exits nonzero while defects remain. The matrix is included in the local isolated test selection, scenario CI regression step and Dev Container clean-install verification. For each batch 4 fix, remove only the corresponding known-failure entries and confirm those assertions pass in both process zones. Keep the HA contract and physical fixture unchanged unless a separately reviewed interface change requires adapting the replay transport representation.
