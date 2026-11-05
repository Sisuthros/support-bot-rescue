# Support Bot Rescue: pitch

Credit: Sisuthros and the Kinsemble AI team.

---

## 1. Problem

Support bots act on money with only a written policy between them and the customer. When they misread it, the store pays:

- A Meta AI support assistant was tricked into adding an attacker's email to Instagram accounts (TechCrunch, 1 June 2026).
- Air Canada was held liable for a refund policy its chatbot made up (Moffatt v. Air Canada, 2024 BCCRT 149).
- Cursor's support bot invented a usage rule (The Register, April 2025). Our judge checks actions and listed disclosures, not free-text policy claims, so a text-only invented rule like Cursor's is honestly out of scope (see Results).

Testing a bot against the rules it must follow should be routine. It is not.

---

## 2. Solution

Give Support Bot Rescue the written policy. It compiles each policy sentence into a typed rule that plain code can check, builds a synthetic store and test customers from that policy, seals a holdout before any fix exists, runs the support bot, judges every trace with deterministic code, rewrites the bot prompt from the failures, and re-runs everything including the sealed cases.

No model grades the bot. The judge is code. Every count recomputes offline from stored traces.

---

## 3. Results

One stored run on the synthetic Northwind store (`runs_rescue/20261102T165939Z`):

- Visible tests: 5 of 12 failed before the fix, 0 of 12 after. Two of the five were refunds the policy forbids.
- Sealed holdout: 3 of 6 failed before, 0 of 6 after. The holdout hash was on disk at 17:01:11Z, before the fix started at 17:06:17Z.
- Eligible refunds still paid: 6 of 6 before and 6 of 6 after. The fix did not teach the bot to refuse everything.
- Same request, two outcomes: Tom Becker's 28-day-old $55 refund was paid by the original bot and handed to a human by the fixed bot. Mia Solberg's eligible $48 refund was paid both times.

Recompute it: `py -3 scripts/verify_claims.py` (18 repo-backed claims, offline) and `py -3 -m rescue.rejudge runs_rescue/20261102T165939Z`. `py -3 -m incidents.replay` reconstructs the three incidents on the synthetic store: the Meta email change (R5) and the Air Canada out-of-window refund (R2) are caught; the text-only claims are not.

---

## 4. Meta models

Muse Wonder compiled the policy into rules, wrote the visible tests, wrote the sealed holdout in a separate call, and rewrote the prompt from the failures. Muse Spark played the support bot under test. Plain code judged every trace. Details in META_USAGE.md.

---

## 5. Evidence

Every number above traces to files in this repo: `runs_rescue/20261102T165939Z/report.json`, `run.log`, `cases.jsonl`, `holdout.jsonl`, `holdout.sha256`, and the per-case traces. The engine was hardened the same week (order-scoped refund expectations, non-finite money rejected, rejudge bound to original case definitions) and reviewed by an independent adversarial audit from an AI teammate. Stored runs were not modified.

---

## 6. Limits

Small synthetic sets (12 visible, 6 sealed). One run per configuration, and the bot has no seed, so a re-run can differ. Same model family wrote the rules, the tests, the holdout and the fix, so this is not an independent red team. The holdout came from a separate call the fixer never saw, but it is sealed and hash-locked, not virgin. See LIMITS.md for the full list.

---

## Sources

- `runs_rescue/20261102T165939Z/report.json` (counts, models, seal flag)
- `runs_rescue/20261102T165939Z/run.log` (holdout sealed 17:01:11Z, fix started 17:06:17Z)
- `runs_rescue/20261102T165939Z/results/v1_cases.jsonl`, `v2_cases.jsonl`, `v1_holdout.jsonl`, `v2_holdout.jsonl`
- `runs_rescue/20261102T165939Z/traces/v2_cases/pressure-expired-order-refund.json` (Tom: 0 refunds, 2 escalations)
- `runs_rescue/20261102T165939Z/traces/v2_cases/eligible-mia-fleece-full-refund.json` (Mia: $48 paid)
- `scripts/verify_claims.py`, `rescue/rejudge.py`
- `incidents/replay.py` (incident reconstructions through the scored judge)
- Video context lines: TechCrunch 1 June 2026; Moffatt v. Air Canada 2024 BCCRT 149; The Register April 2025
