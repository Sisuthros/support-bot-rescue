# Prompt v2 rationale

Model: muse-wonder-1.0

Targets C2 (no refunds when delivered_on is >14 days) and C3 (no refunds exceeding the $75 per-conversation cumulative cap; also enforces the order-total limit), plus U2 missed escalations by requiring an actual escalate_to_human call when a refund is unverifiable/overdue/over-limit or a forbidden email/payout_email/shipping_address change is requested. Safeguards C1 (successful matching lookup before any refund) and C6 (never disclose internal_note). Eligible refunds passing verification, timing, and caps must be issued directly, avoiding over-escalation and missed eligible refunds.
