# Timezone contracts before batch 4 fixes

Assessment date: 2026-10-14. The original measurement below precedes application fixes. Separate report-period, price-boundary, scheduler, optimizer start-clock and EV elapsed-time fixes now follow that baseline on the same branch, based on batch 3. Timezone rules are not activated yet.

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

## Optimizer start-clock diagnosis before the EV fix

This follow-up adds observation and regression controls only. Application code and the previously measured EV/optimizer failures remain unchanged.

The probe records the real `calc_optimum()` locals after the initial epoch-to-calendar conversions, price-coverage calculation, forecast-end conversion and EV availability calculation. It also records the return location. The two new matrix assertions separate physical start correctness from HA calendar correctness: all seven epoch checks pass; all seven HA-calendar checks fail under UTC and have narrow strict expected-failure entries. The label assertion accepts either naive HA-local or aware HA-local representations, while verifying the physical instant when an offset is present.

The physical `start_ts` is correct. The calculator initially reads process-local `now()`, then explicitly reconstructs `start_dt` and `start_interval_dt` with timezone-free `datetime.fromtimestamp(...)`. Those reconstructed labels follow the process zone rather than HA. At the winter anchor `2026-01-14 08:00 UTC`, both processes retain epoch `1768377600`, but the UTC process uses `08:00` where HA time is `09:00`. The first explicit epoch-to-calendar conversions are the `start_dt` and `start_interval_dt` assignments near the beginning of `calc_optimum()`; this mismatch already exists before EV deadline subtraction.

Two observed downstream consequences:

- At `2026-07-01 22:30 UTC`, HA time is July 2 at 00:30. With identical 96-quarter input and matching snapshot hashes, UTC checks price coverage from July 1 at 22:00 and expects 105 quarters; Amsterdam checks from July 2 at 00:00 and expects 97. The UTC calculation returns `False` at the missing-price coverage guard before EV availability is reached; Amsterdam continues and solves. This pins the early stop to mixed process-local and HA-local calendar labels, rather than absent canonical input.
- At the winter anchor both calculations solve. UTC reports four available hours until the HA deadline 12:00; Amsterdam reports three. The naive forecast-end label January 15 at 09:00 also becomes epoch `1768467600` under UTC instead of the input horizon end `1768464000`. The traced `.timestamp()` conversion therefore shifts that query boundary by one hour. ReplayIO returns copied frames without filtering on the requested bounds, so this observation does not establish the resulting real SQL row selection.

Fix start-clock/calendar preprocessing before changing EV duration arithmetic. Start-clock correction alone is not presented as sufficient to fix DST elapsed-time subtraction or every optimizer difference. The historical 49-check matrix remains 38 passed/11 expected failures; the expanded 63-check matrix is 45 passed/18 expected failures because seven passing epoch assertions and seven independently measured calendar failures were added, not because application behavior regressed.

## Optimizer start-clock fix

The calculator now reads the current instant in HA time, interprets naive debug/reference dates as HA-local (preserving `fold`) and converts aware references to that zone. Interval rounding remains epoch-based. It reconstructs start, interval and price-request hour labels explicitly in HA time, retaining naive labels for the existing frame/device-window interfaces. This is a boundary correction, not a migration of all optimizer arithmetic to aware datetimes.

Before marker removal, exactly 15 previously failing assertions produced strict XPASS: all seven start-calendar checks, all four previously failing optimizer comparisons, and available-hours checks for `winter`, `summer`, `local-midnight` and `second-0230`. Only those entries were removed. The expanded matrix now has 60 passed and three expected failures; the original 49 checks alone have 46 passed and three expected failures. Equality of these synthetic plans does not establish correct elapsed charging time across every transition.

Eight added entry-path tests stop before database/model work. They exercise naive HA and aware UTC references, unchanged next-quarter rounding, and both occurrences of the autumn repeated minute under both process zones. Four failed before the fix; all eight pass afterward.

The remaining expected failures are elapsed charging hours for `spring-forward`, `fall-back` and `first-0230`. The existing subtraction of naive local labels is unchanged. Other previously observed conversions, including the forecast-end `.timestamp()` boundary, also remain outside this start-clock fix and require separate work even though ReplayIO's unfiltered frames allow the optimizer comparisons to pass.

## EV elapsed-time fix

Available charging hours now subtract the physical start epoch from the HA-local deadline's epoch, clamped at zero. Direct charging uses the last physical grid epoch plus its interval length as the horizon end. It no longer subtracts local wall-clock labels to measure elapsed time. Existing deadline parsing and local input interpretation remain in place; this fix does not add a new policy for ambiguous/nonexistent deadline strings or migrate all later deadline/index handling.

Exactly the last three known matrix cases produced strict XPASS before marker removal: `spring-forward`, `fall-back` and `first-0230`. Only those three markers were removed, together with the now-unused expected-failure fixture. All 63 expanded matrix checks pass normally.

Eight added subprocess cases run identical high-demand EV inputs under UTC and Europe/Amsterdam and observe the actual pre-solver energy-budget calculation. They verify 1/3/2/1 physical hours across spring and the autumn occurrences, a zero-hour expired deadline, an ordinary winter control and direct-charge horizons spanning both transitions. They assert the selected charge mode, maximum achievable energy, clipped energy requirement and adjusted target SOC for a synthetic 100 kWh battery. The direct-charge fixtures explicitly configure their synthetic activation entities. Both physical 24-hour direct-charge horizons now measure 24 hours, where the old wall-clock subtraction measured 25 and 23. Three deadline cases and both direct-charge cases failed before the fix; all eight now pass.

The probe captures final hours after the direct-charge override. Budget-only cases deliberately stop after actual target/energy limiting and before constraint building/solving; they do not claim to verify a high-demand optimal plan. The original matrix still runs real solves, and all 40 existing synthetic scenarios pass after this fix. No live HA, database, provider or device writes are used.

## Running and retiring known failures

The original 28 failures had narrow case/function entries in `KNOWN_FAILURES`, with `xfail(strict=True, raises=AssertionError)`. After the report fix, 24 remained; after the price-boundary fix, 18 remained. With the scheduler fix, the original matrix output was **38 passed, 11 xfailed**. Added optimizer start-clock controls expanded it to **45 passed, 18 xfailed** before the fix. The start-clock fix produced **60 passed, 3 xfailed**. After the EV elapsed-time fix, current output is **63 passed, zero expected failures**. All known-failure markers and the obsolete marker fixture are removed. Each marker was retired only after a measured strict XPASS; the historical measurements remain above.

The original full isolated regression suite reported **214 passed, 58 skipped, 28 xfailed**. After the report fix and five additional reference-time cases it reported **223 passed, 58 skipped, 24 xfailed**. With the price-boundary fix and its ten additional cases it reported **239 passed, 58 skipped, 18 xfailed**. With the scheduler fix and 15 added scheduler cases it reported **261 passed, 58 skipped, 11 xfailed**. The start-clock diagnostic controls expanded it to **268 passed, 58 skipped, 18 xfailed** without application changes. With the start-clock fix and eight entry-path tests it reported **291 passed, 58 skipped, 3 xfailed**. With physical EV elapsed time and eight budget cases it reports **302 passed, 58 skipped, zero expected failures**. The existing 58 skips retain their previous meaning; they are separate from the former timezone failures.

Run the complete matrix in a Linux development environment:

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_timezone_contracts.py -q -rxX
```

Reproduce the unmasked pre-fix failures by running this command on the original baseline revision; on the current revision it succeeds:

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_timezone_contracts.py \
  --runxfail --junitxml=.local/timezone-unmasked.xml -q
```

The matrix and added EV budget tests are included in local isolated verification, scenario CI and Dev Container clean-install verification. A green matrix covers these fixtures; it does not establish full timezone correctness or complete DTZ adoption. In particular, the separately traced forecast-end timestamp conversion and other untested paths still require review. Keep the HA contract and physical fixture unchanged unless a separately reviewed interface change requires adapting the replay transport representation.
