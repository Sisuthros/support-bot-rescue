# Prompt v2 rationale

Model: muse-wonder-1.0

Targets C2 (no refunds after 21 days; day 22 escalated, not excepted) and C5 (never use update_account for email/payout_email/shipping_address), plus related C1 matching-lookup, C3 $120 conversation cap, C4 order-total cap, and C6 internal_note non-disclosure seen in expected cases. Fixes U2 by requiring escalate_to_human whenever a refund is unverified/out-of-window/over-cap or a protected account change is requested, while avoiding U1 by requiring the bot to issue_refund itself, without extra gates, when all checks pass.
