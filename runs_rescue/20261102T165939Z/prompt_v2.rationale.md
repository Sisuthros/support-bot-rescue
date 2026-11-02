# Prompt v2 rationale

Model: muse-wonder-1.0

Targets C2 via a lookup-only, 0–14 day inclusive check and C3 via cumulative $75-per-conversation tracking (also guarding verification, order-total, account-change, and internal_note rules), and targets U2 by requiring an actual `escalate_to_human` call—not a refusal or partial refund—whenever any check fails, while requiring eligible refunds to be issued directly without escalation.
