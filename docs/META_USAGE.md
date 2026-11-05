# Meta model usage

This project was built with Meta models. The table below states what each model did and which file or run proves it.

| Model | Role | Proof |
|---|---|---|
| `muse-wonder-1.0` | Compiled the written policy into typed rules | `runs_rescue/20261102T165939Z/spec.json` provenance (`model: muse-wonder-1.0`), `runs_rescue/20261102T165939Z/manifest.json` models field |
| `muse-wonder-1.0` | Wrote the 12 visible test cases in a dedicated call | `runs_rescue/20261102T165939Z/run.log` line 2 (`generating 12 visible cases with muse-wonder-1.0`), `response_ids.cases` |
| `muse-wonder-1.0` | Wrote the 6 sealed holdout cases in a separate call | `runs_rescue/20261102T165939Z/run.log` (`generating 6 sealed holdout cases with muse-wonder-1.0`), `response_ids.holdout`, `holdout.sha256` sealed before the fix |
| `muse-wonder-1.0` | Rewrote the support bot prompt from the failing visible traces | `runs_rescue/20261102T165939Z/prompt_v2.rationale.md` (`Model: muse-wonder-1.0`), `response_ids.fix` |
| `muse-spark-1.3-contributor` | Played the support bot under test (v1 and v2) | `runs_rescue/20261102T165939Z/manifest.json` (`bot: muse-spark-1.3-contributor`), `report.json` models field |

Concrete notes:

- The Wonder call that rewrote the prompt saw only failing visible traces. The holdout came from a separate Wonder call, and its sha256 was written to disk before the fix step started. Same model, separate calls, enforced ordering.
- The fixed prompt and the original prompt are both stored (`prompt_v1.txt`, `prompt_v2.txt`), so the change the model made is inspectable.
- Reply text in the traces is model output; the verdicts on traces are not. `compiler/spec_judge.py` and `rescue/rejudge.py` contain no model calls.
- The Maple attack corpora were also written by Muse Wonder (`attacker/attack.py`, `ATTACKER_MODEL = "muse-wonder-1.0"`), recorded with provenance files. The attacker never receives holdout cases and is never used as a judge.
- Verification needs no model and no key: `py -3 scripts/verify_claims.py` and `py -3 -m rescue.rejudge runs_rescue/<run>` recompute every count from stored files.

## Sources

- `runs_rescue/20261102T165939Z/manifest.json` (models, response_ids)
- `runs_rescue/20261102T165939Z/report.json` (models, counts)
- `runs_rescue/20261102T165939Z/run.log` (call order, seal before fix)
- `runs_rescue/20261102T165939Z/spec.json` (compile provenance)
- `runs_rescue/20261102T165939Z/prompt_v2.rationale.md`
- `rescue/rescue_run.py` (`build_fix_request` reads failing visible traces only)
- `compiler/spec_judge.py`, `rescue/rejudge.py`, `verifier/rules.py` (no model)
