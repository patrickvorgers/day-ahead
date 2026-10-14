# Ruff adoption batches and implementation status

Assessment date: 2026-10-14. Ruff version: 0.16.10. This is a review snapshot, not a permanent finding baseline.

The assessment removes the explicit lint selection from a temporary copy of ruff.toml while preserving repository discovery and Python target settings. It reports 750 diagnostics across 39 files. Counts include overlapping diagnostics and do not represent unique edits. Files overlap between batches; corrections can change later counts.

## Proposed pull requests

| Batch | Diagnostics | Files | Risk | Rules |
| --- | ---: | ---: | --- | --- |
| 1. Local simplifications and explicit intent | 67 | 18 | Low to medium; review every change | C408, ISC004, PERF102, PIE790, PLR0402, PLR1711, PLW0602, RET501, RUF010, RUF022, RUF023, RUF059, SIM102, SIM114, SIM117, SIM118, SIM210, SIM401 |
| 2. Logging | 400 | 14 | Medium; preserve handlers, levels, propagation and output | LOG015, TRY401 |
| 3. Annotations and class state | 37 | 12 | Medium to high; inspect runtime annotation consumers and shared state | PYI016, PYI034, PYI041, RUF012, RUF013 |
| 4. Dates and time zones | 186 | 26 | High; preserve database/API boundaries, local wall time and daylight-saving behavior | DTZ001, DTZ002, DTZ005, DTZ006, DTZ007, DTZ011 |
| 5. Error handling and control flow; finalize selection | 60 | 22 | Medium to high; preserve failure contracts and deliberately review exceptions | BLE001, S110, TRY002, TRY004, PLW1508, PLW1510, SIM115, PLR1704, PLR1730, SIM113, SIM201, RUF100 |
| 6. Formatting and enforcement | Separate from the 750 lint diagnostics | 60 files currently need formatting | Low runtime risk, large mechanical diff and merge-conflict exposure | Default formatter, format on save, formatter hook, formatter CI check |

The five lint batches account for all 750 current diagnostics: 67 + 400 + 37 + 186 + 60. The final lint batch includes 51 error/control-flow diagnostics and nine unused-suppression diagnostics. RUF100 is deferred until the final selection is established: several current suppressions refer to rules enabled by the existing gate but not by the assessed defaults. Do not remove valid suppressions merely because an assessment configuration disables their rules.

## First pull request - implemented and acceptance verified

Branch: `chore/ruff-first-batch`. The branch includes the acceptance-criteria change from the former adoption-plan branch. Submit this batch separately from the developer-environment PR; while that PR is open, review against `chore/development-environment` to isolate the batch diff.

Suggested title: Adopt the first Ruff default-rule batch across local simplifications.

Implemented: the current lint selection is retained and all 18 individual codes in batch 1 are enabled using `extend-select`. Checking this combined configuration produces the same 67 diagnostics in 18 files. Do not enable entire SIM, RUF, PLR or PERF families in this batch. Keep the pinned version and unsafe-fixes setting unchanged.

The first batch covers four review categories within one PR:

1. Redundant statements and unused bindings: 23 diagnostics (PIE790, PLR1711, PLW0602, RET501, RUF059).
2. Dictionary construction, membership and iteration: 14 diagnostics (C408, PERF102, SIM118, SIM401).
3. Nested conditions and context managers: 18 diagnostics (SIM102, SIM114, SIM117).
4. Imports, string representation, ordering and boolean expressions: 12 diagnostics (PLR0402, RUF010, RUF022, RUF023, ISC004, SIM210).

There are 63 distinct starting lines in these 67 diagnostics. Ruff labels 34 fixes safe, 17 unsafe, and offers no fix for 16. Apply only safe automatic fixes; implement the remaining corrections manually after verifying the concrete types and behavior. In particular, confirm normal dict semantics before changing mapping operations, preserve short-circuit evaluation and evaluation order, and preserve intentionally concatenated strings by parenthesizing them.

The adoption acceptance criteria are included in this branch and first PR; there is no separate documentation PR. The version/effective-settings checks and 18 invalid/corrected fixtures are implemented in `tests/test_developer_tools.py` and `tests/ruff_adoption_cases.json`. Both Windows and Linux CI jobs run these checks through the configured hook, the actual CI command and the real Ruff language server. `tests/vscode_ruff_adoption` supplies a separate actual VS Code extension-host suite for diagnostics, explicit save actions and corrected documents. It requires a trusted workspace and the pinned project launcher; language-server-only checks are not reported as editor save verification. Formatting remains out of scope.

## Second pull request - module logging

Branch: `chore/ruff-logging`, based on `chore/ruff-first-batch`. Review this draft against the first-batch branch so that neither its changes nor the developer-environment changes are offered for review again. Do not merge it back into that branch while the earlier pull requests are pending. After those changes merge upstream, align this branch with upstream and submit the logging batch separately.

The logging assessment reports 400 diagnostics in 14 files: 399 LOG015 root-logger calls and one TRY401 redundant exception message. This batch enables both codes in the shared configuration and replaces emitting calls with `_LOGGER = logging.getLogger(__name__)` per module. Root logging remains responsible for configuration, handlers and levels. Module loggers inherit the effective level and propagate records to the existing handlers; no module adds a handler or changes the log format. The source module is available in each record's name without changing the text consumed by scenario parsers.

The Nordpool failure path retains two ERROR records and its existing return behavior. The exception record now supplies provider/date context while the exception type, message and traceback remain attached through `exception()`. The second error message is retained. No changes to exception policy, price retrieval or scenario baselines are included.

Verification:

- All 400 logging diagnostics are resolved without suppressions; repository lint passes. The refreshed standard-default assessment reports 286 remaining diagnostics, including findings introduced by the new first-batch regression fixtures since the original snapshot.
- Sixteen added behavioral cases cover inherited logger levels and propagation, existing scenario capture, console/file output, notification delivery, task failure return codes and tracebacks, Nordpool failure context and the dashboard configuration-error fallback. The local regression selection and CI include them.
- Full isolated Linux regression suite: 182 passed, 58 skipped. All 40 synthetic scenarios passed.
- Windows and Linux tooling acceptance: 12 tests passed on each platform. The invalid/corrected rule fixtures now cover all 20 adopted rules through the configured hook, actual CI command and real language server.
- Actual native Windows VS Code 1.141.1 verification: all 20 rule fixtures passed diagnostics, explicit-save and correction checks in the trusted workspace using the pinned Ruff 0.16.10 launcher. Neither new logging rule has a safe automatic fix; saving agrees with CLI behavior and manual corrections clear the diagnostics.
- GitHub CI results are recorded in the logging draft pull request.

## Third pull request - annotations and report state

Branch: `chore/ruff-annotations-state`, based on `chore/ruff-logging`. Review against the logging branch to keep both earlier batches and the developer-environment changes outside this diff. Keep the dependent drafts separate until their upstream merges, then align this branch with upstream before submitting it there.

This batch resolves 37 diagnostics across 12 files and enables `PYI016`, `PYI034`, `PYI041`, `RUF012` and `RUF013` together in the shared configuration:

- Twenty-eight optional parameter annotations explicitly include `None`; defaults and function bodies are preserved.
- Four numeric parameter unions omit redundant `int` members. Integers remain accepted under the typing numeric convention; no runtime conversion is added.
- Two context-manager return annotations use `Self`, reflecting the returned instance and preserving inherited context behavior.
- One duplicate `None` union member is removed from the reporting configuration. Python already normalizes that union; configuration validation, serialization, generated schema and documentation remain unchanged.
- The replay `_FakeLoader.secrets` dictionary is explicitly annotated `ClassVar`, preserving its existing shared, read-only use. It is not presented as a demonstrated bug fix.
- `Report.periodes` is initialized per instance. Previously, constructing another report or recalculating its periods could overwrite the first report's periods because both used the class dictionary. This is an intentional bug fix, isolated in its own commit rather than hidden among annotation changes. It does not change period calculations or time-zone policy within one report.

Verification:

- Both report-isolation regression tests failed on the original code and passed after the fix. They cover different reference dates, recalculation and custom period keys. The former class-level monkeypatch in the HA-query fixture is removed so those tests also use the instance dictionary.
- Nine additional cases cover CO2 configuration roundtrips/validation and inherited debug-context identity, cleanup and exception propagation. All 11 new cases are included in local verification and CI.
- Full isolated Linux regression suite: 193 passed, 58 skipped. Synthetic scenario results and GitHub CI are recorded in the draft pull request.
- Windows/Linux tooling acceptance and actual VS Code verification cover all 25 adopted rule fixtures; results are recorded in the draft pull request. Neither server-only checks nor the native editor check are presented as container-editor verification.
- Repository lint passes without suppressions; the refreshed standard-default assessment reports 249 remaining diagnostics. Regenerating `SETTINGS.md` and `config_schema.json` produces no changes.

## Fourth batch preparation - timezone regression baseline

Branch: `chore/ruff-timezone-tests`, based on `chore/ruff-annotations-state`. This branch records the behavior before timezone fixes and adds report-period and price-boundary fixes in separate commits. It does not yet enable the six DTZ rules. Review against batch 3 to keep earlier changes outside the diff.

The new Linux subprocess matrix runs identical HA configuration and canonical planning data under UTC and Europe/Amsterdam, with seven fixed UTC anchors covering winter, summer, local midnight, both DST transitions and both occurrences of 02:30 during the autumn transition. It exercises report periods, scheduler dispatch, provider bounds, actual EV availability and a real optimizer solve. No live HA, database or provider access is needed.

The pre-fix measurement is 21 passed and 28 failed assertions across 49 checks, with no setup errors. Those exact case/function combinations are recorded as strict expected failures, not passing coverage. A fix that makes one pass produces strict XPASS until its marker is removed; unexpected setup errors and regressions in passing cases still fail CI. See [the timezone baseline](ruff-timezone-baseline.md) for the complete result matrix, input contract and unmasked reproduction command.

The first fix makes report-period generation use the HA clock, including conversion of aware reference instants and the local 13:00 horizon cutoff. Naive reference inputs remain HA-local and period bounds retain their database representation. Four former expected failures were proven to pass before removing their markers; matrix output is now 25 passed and 24 xfailed. Five additional reference-time cases cover conversion and compatibility; three of these failed on the original code. The historical pre-fix matrix is retained in the baseline document.

The second fix makes default price-request dates and the noon cutoff use HA time and advances calendar dates before localizing midnight. ENTSO-E interprets explicit bounds in HA time before selecting complete local days. Six additional expected failures were proven to pass before their markers were removed; current matrix output is 31 passed and 18 xfailed. Ten added request-boundary cases verify 23-/25-hour days, 47-/49-hour two-day windows, local midnight/noon, configured timezone selection and explicit bounds. Six failed before the fix and all ten now pass. The shared default request setup also supplies the other providers; their individual fetching loops and response processing are unchanged.

The matrix and added boundary cases are included in local regression verification, scenario CI and clean-install. Later timezone fixes must turn the remaining expected failures into ordinary passing assertions while preserving the fixed HA-time contract. Batch 4 remains incomplete until the remaining fixes, rule activation and shared integration acceptance checks are reviewed and verified.

## Completion and sequencing

Each PR activates its rules in the shared configuration together with corrections and justified narrow exceptions. VS Code, hooks and CI therefore receive the same new checks as soon as the PR is merged. PR #916 remains unchanged; prepare the first batch on a dependent branch and adjust its base after #916 merges.

After all lint batches, compare the final effective selection with both the pinned standard defaults and the previously enforced rules. Make any removal of an existing check explicit rather than silently weakening the gate. Standard compliance can include necessary documented exceptions; never change application behavior solely to silence a diagnostic.

Six PRs are a planning estimate, not a requirement. Split the time-zone or error-handling batch only if review reveals independently significant behavior changes. Formatting can proceed as an independent track; coordinate timing to avoid unnecessary rebases of the lint batches.

## Verification status

- Current expanded lint selection: passes across the repository. All 67 original batch diagnostics are resolved; the temporary standard-default assessment now reports 683 remaining diagnostics. A follow-on dictionary pop diagnostic exposed by membership cleanup was resolved while preserving missing-key behavior.
- Windows acceptance suite: 12 tests passed.
- Linux acceptance suite: 12 tests passed.
- Isolated application regression suite: 166 passed, 58 skipped, including both chart-boolean outcomes and 22 targeted cases for scheduler dispatch, task-state expiry, solar-menu updates and report forecast inclusion. The new cases use mocked task execution, temporary state files and an in-memory SQLite database; both the local regression selection and scenario CI include them.
- Synthetic scenarios: all 40 passed. Final targeted web regression checks: 27 passed.
- Actual native Windows VS Code diagnostics/save verification: all 18 rules passed in VS Code 1.141.1, with `workspaceTrusted: true` and Ruff 0.16.10. The server log confirms the project launcher. Unsafe fixes remained manual, safe save fixes matched CLI output, and corrected documents cleared diagnostics. Untrusted/bundled-version runs were excluded from acceptance evidence.
- GitHub CI for the implementation: Ruff lint, model documentation, both Windows/Linux developer-tool jobs, both scenario jobs and clean-install passed. The isolated editor prepare/run procedure was smoke-tested successfully after closing the earlier test window; final helper changes are submitted for a new CI run.

The editor verifier now prepares a separate native workspace and uses a normal development extension host. It preserves normal trust prompts and avoids opening a Windows virtual environment inside a Linux container. Use `scripts/verify_ruff_editor.py` as documented in the developer guide.
