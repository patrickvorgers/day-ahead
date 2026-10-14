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

## First pull request - implemented; acceptance verification in progress

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

## Completion and sequencing

Each PR activates its rules in the shared configuration together with corrections and justified narrow exceptions. VS Code, hooks and CI therefore receive the same new checks as soon as the PR is merged. PR #916 remains unchanged; prepare the first batch on a dependent branch and adjust its base after #916 merges.

After all lint batches, compare the final effective selection with both the pinned standard defaults and the previously enforced rules. Make any removal of an existing check explicit rather than silently weakening the gate. Standard compliance can include necessary documented exceptions; never change application behavior solely to silence a diagnostic.

Six PRs are a planning estimate, not a requirement. Split the time-zone or error-handling batch only if review reveals independently significant behavior changes. Formatting can proceed as an independent track; coordinate timing to avoid unnecessary rebases of the lint batches.

## Verification status

- Current expanded lint selection: passes across the repository. All 67 original batch diagnostics are resolved; the temporary standard-default assessment now reports 683 remaining diagnostics. A follow-on dictionary pop diagnostic exposed by membership cleanup was resolved while preserving missing-key behavior.
- Windows acceptance suite: 12 tests passed.
- Linux acceptance suite: 12 tests passed.
- Isolated application regression suite: 144 passed, 58 skipped, including both chart-boolean outcomes.
- Synthetic scenarios: all 40 passed. Final targeted web regression checks: 27 passed.
- Actual VS Code diagnostics/save verification: pending trusted-workspace rerun. An untrusted-workspace run was rejected as acceptance evidence because it used the extension bundled version.
- GitHub CI for the implementation: Ruff lint, model documentation, both Windows/Linux developer-tool jobs, both scenario jobs and clean-install passed. Documentation-only status updates do not replace the pending real-editor verification.

Update this status with final results before offering the batch for review.
