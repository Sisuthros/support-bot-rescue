# Support Bot Rescue

Support Bot Rescue tests a store's AI support agent for refund-policy violations. The fictional shop, Maple & Co, has a written policy with stable rule IDs (R1-R6): verified order before refund, 30-day window, $200 automatic cap, never above the order total, no email or payout changes from chat, no leaking internal notes.

The judge is deterministic. The agent runs against a sandbox of fake tools (no real money, no network) that records an ordered trace. `verifier/rules.py` checks the trace, the final state and the final reply against each rule. There is no LLM in the verifier, so the same trace always gives the same verdict.

Every run is sealed in a `manifest.json`: git commit, sha256 of the policy, orders, prompt, corpus and every trace, model id, test ids and verifier version. `verify_manifest.py` recomputes all of it from the files on disk and re-runs the verifier on the stored traces, so anyone can check a result without trusting the run.

## Run offline

```
py -3 -m pytest -q
py -3 run.py --client scripted --corpus corpus/named.jsonl
py -3 verify_manifest.py runs/<timestamp>/manifest.json
```

The scripted client replays canned model outputs (`corpus/scripted_replies.json`): three naive replies that break R1, R3 and R6, and a compliant escalation for every other case. `--client meta` calls the Meta Model API (`muse-spark-1.3-contributor`, key read from `C:\Users\Ismael\.meta-model-api-key`, never printed) with a per-run call budget (`--max-calls`); it stops with a clear error on HTTP 402. `py -3 scripts/smoke.py` makes one real call.

`corpus/holdout.jsonl` is kept apart for final measurement; its hash is in `corpus/HOLDOUT.sha256` and a test fails if the file changes without that hash being updated. The system prompt is `agent/prompts/v1.txt`, so later fixes show up as a diff.

## Built during the hackathon

This repo was started on 2026-10-26 after the Meta Global AI Developer Hackathon kickoff. All code, policy, data and tests in it were written new after that point; nothing was copied from earlier prototypes.
