# Control stop-time comparison before fixes

Assessment date: 2026-10-14. This adds tests and observations only; application output code and DTZ rule selection are unchanged.

## Scope and isolation

`tests/control_stop_probe.py` reads the current `DaCalc.calc_optimum()` source and compiles its existing EV output decision/publication statements and inverter stop decision/publication statements. Structural AST selectors require unique matching blocks and fail if their shape changes. The formulas and `set_datetime` calls are not copied into a replacement implementation.

Fixed synthetic post-solver values select a 50% first-interval charge stage and a 500 W inverter result below a 1000 W minimum, with a 15-minute interval. The EV uses the actual remaining first-interval fraction. The inverter uses the existing full-interval fraction. The oracle measures those same intended durations on the physical timeline, then formats HA-local time. This comparison does not validate the energy correctness of the existing inverter duration or prove that a real optimization selects these exact values.

No optimizer or application constructor is invoked. All write methods belong to a local object with no HA client, session or transport. Non-debug paths capture actual service-call arguments; separate debug cases verify that no commands are emitted. Entity names are synthetic. The tests do not send commands to Home Assistant or devices.

## Paired-process observations

Every dispatch input runs in separate `TZ=UTC` and `TZ=Europe/Amsterdam` processes with `ha_zone=Europe/Amsterdam`. Inputs and process-zone readback are checked before assertions.

| Fixed UTC start | EV stop text, both processes | Inverter text under UTC | Inverter text under Amsterdam / expected |
| --- | --- | --- | --- |
| January 14, 08:07 | 09:11 | 09:14 | 09:14 |
| July 1, 07:07 | 09:11 | 09:14 | 09:14 |
| March 29, 00:57 | 01:58 | **02:04** | **03:04** |
| October 25, 00:57 | 02:58, first occurrence | **03:04** | **02:04, second occurrence** |
| October 25, 00:07 | 02:11, first occurrence | 02:14 | 02:14, first occurrence |
| October 25, 01:07 | 02:11, second occurrence | 02:14 | 02:14, second occurrence |

All dates are in 2026. Actual payloads use `YYYY-MM-DD HH:MM`, truncating seconds as the existing application does. The occurrence descriptions in the table are oracle context; the payload itself carries neither UTC offset nor `fold`.

The EV text matches the expected HA wall-clock representation in all six cases. This does not prove that its internal epoch is correct: under UTC, the naive `.timestamp()`/`fromtimestamp()` round trip produces a different epoch but cancels the offset again when formatting these labels. The probe records both calculated and expected epochs. It does not classify an internal intermediate mismatch as a demonstrated difference in the issued EV text.

The two autumn 02:11 payloads cannot distinguish their physical occurrences. These tests do not establish which occurrence a Home Assistant integration or downstream automation chooses. No interpretation of the live installation is assumed.

## Measured failures and acceptance

The unmasked output tests report **12 passed, 2 failed**. Only inverter payload assertions for `spring-jump` and `autumn-jump` receive strict expected-failure markers. Normal output is **12 passed, 2 xfailed**. The previously green planning/reporting matrix remains unchanged; these are newly exposed output cases, not an application regression.

```bash
.venv/bin/python -m pytest -c pytest-dev.ini dao/tests/prog/test_control_stop_times.py \
  --runxfail -q
```

The unmasked command intentionally fails before the output fix. Startup, source-selector, process-zone or input mismatches cannot be hidden as expected assertion failures. After a fix, confirm strict XPASS for each resolved case before removing its marker. These tests are included in local regression selection, scenario CI and clean-install verification.
