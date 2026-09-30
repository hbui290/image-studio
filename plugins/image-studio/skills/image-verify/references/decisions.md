# Decisions shared by the review scripts

`image-loop/scripts/review.py` (through `controller.py`) and `image-verify/scripts/audit_candidate.py` write `decision.json` with the same action names, checked in the same order. The first rule that applies wins.

| Order | `action` | When | Next step |
| --- | --- | --- | --- |
| 1 | `stop_invalid_review` | The review is malformed, misses a check ID, repeats one, or invents one (the audit reports this as a command error, exit 2) | Fix the review; do not count it |
| 2 | `reject_technical` | A file check failed (size, format, bit depth, transparency) or, in the audit, a pixel changed outside the mask, or a "passed" change has no changed pixel | Fix the file or composite; the candidate is not usable |
| 3 | `hold_for_inspection` | A check is `uncertain`, or a passed `keep` target changed more pixels than the reviewer acknowledged | Inspect closer or ask the user |
| 4 | `accepted_by_checks` | Every check passed | Show the person; this is not human approval |
| 5 | `stop_budget` | Failures remain and the repair limit is used up | Keep the best candidate that passed protected checks, else the source |
| 6 | `stop_repeated_failure` | The same set of checks failed in two consecutive reviews, so the last repair fixed nothing | Change the approach (crop, reference, mask, manual edit) instead of repeating it |
| 7 | `repair` | Otherwise | Run `repair-prompt.txt`, starting from the last accepted clean source or candidate |

A `repair` decision lists the failed check `ids` and `protected_failed`. When `protected_failed` is not empty, the candidate damaged something that had to stay, so never build the next repair on it.

Only `review.py` can also return `stop_provider`, when the Codex reviewer call fails or times out. The inspiration loop (`image-inspiration/scripts/advance.py`) judges between candidates, not against checks, and has its own actions described in [judging.md](../../image-inspiration/references/judging.md).

## Rounds

- Round 0 has no `--previous`. Every later round passes `--previous <previous round folder>`.
- A round continues only when the previous round decided `repair`. The repair count is the previous count plus one; `--repairs-used`, if given, must match it.
- Every round re-reviews all checks, not only the ones that failed.
- The default limit is three repairs after the first candidate (`max_repairs` in a contract, `--max-repairs` for `review.py`).
