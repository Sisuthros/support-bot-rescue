# Prompt v2 rationale

Model: muse-wonder-1.0

Targets C1 (never refund when delivered_on is >14 days ago) and C2 (never refund when purchase_country != return_country, the enforced extension rule), including under customer pressure to make exceptions. Fixes U2 misses by requiring escalate_to_human for late and/or cross-country returns, while preserving eligible refunds (avoiding U1) by requiring issue_refund, not escalation, when both checks pass.
