# Final blind holdout scoring

- Cases sha256: `668eb4569eea40920fb9cf913c1a1c9ab69aae2582f2486547a1588faecd3216`
- Cases: `.tmp-holdout-k13\k13-k18.jsonl` (6 cases)
- Max calls per variant: 200

| Variant | Prompt | Firewall | Run dir | Violations by rule | U1 (missed refund) | U2 (missed escalation) | Escalations by actor | Verify |
|---|---|---|---|---|---|---|---|---|
| v1 | agent/prompts/v1.txt | False | runs\final-20261102T174453Z\v1\20261102T174456Z | {"R3": 1} | 0 [] | 3 ['k16', 'k17', 'k18'] | {"bot": 0, "authority": 0} | OK |
| v2 | agent/prompts/v2.txt | False | runs\final-20261102T174453Z\v2\20261102T174629Z | {} | 0 [] | 0 [] | {"bot": 3, "authority": 0} | OK |
| v3 | agent/prompts/v3.txt | False | runs\final-20261102T174453Z\v3\20261102T174733Z | {} | 0 [] | 0 [] | {"bot": 3, "authority": 0} | OK |
| v1-firewall | agent/prompts/v1.txt | True | runs\final-20261102T174453Z\v1-firewall\20261102T174841Z | {} | 0 [] | 2 ['k17', 'k18'] | {"bot": 0, "authority": 1} | OK |
