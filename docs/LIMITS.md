# Limits

Plain statement of what Support Bot Rescue covers and what it does not.

## Covered

- Checks a support bot against the written refund policy it was given, on synthetic cases built from that policy.
- Reports two things separately: policy violations (the bot broke a rule) and usefulness misses (the bot failed to help when the policy made the right action clear).
- Seals a holdout before any fix exists and scores the fix on it.
- Recomputes every count offline from stored traces: `verify_claims.py` (18 repo-backed claims) and `rescue.rejudge`.

## Not covered

- Small synthetic sets: 12 visible cases, 6 sealed. This is a demonstration on invented cases, not a measure of performance on real customers.
- One run per configuration. The bot under test is non-deterministic and has no seed, so a fresh run can produce different traces and different counts.
- Same model family wrote the policy rules, the test cases, the holdout and the prompt fix. The fixer never saw the holdout, but the holdout is sealed and hash-locked, not virgin, and this is not an independent red team.
- Only the written policy is tested. Anything the policy does not state cannot be checked, and sentences the compiler cannot express are labeled needs-review, informational or unaccounted rather than enforced. Text-only policy claims with no action are not caught by the rules: our incident replay shows the Air Canada text-only promise and Cursor's invented usage rule as not caught by the rules, and a deterministic text check flags both as ungrounded policy claims for human review, while the Meta account-change action and the Air Canada refund action are caught.
- The sandbox is not money and not a store. Tool calls record actions; no real refund, account change or disclosure happens.
- The firewall pattern (authority between bot and money) exists in `sandbox/authority.py` but is opt-in per run, not the default path. A prompt rewrite alone asks the bot to behave; only the authority blocks it.

## Sources

- `runs_rescue/20261102T165939Z/report.json` (disclaimer, counts, one-run shape)
- `runs_rescue/20261102T165939Z/run.log` (seal order)
- `README.md` ("What these numbers do not show")
- `sandbox/authority.py` (opt-in firewall)
- `compiler/coverage.py` (sentence labels)
