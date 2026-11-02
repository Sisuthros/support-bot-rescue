# Compiled policy spec

- Model: muse-wonder-1.0
- Policy sha256: cc817ca19bfa29430f4550492d600c04a0b77751a321ce3899301941bcdf6116
- Response id: resp_6ae8bedc66b04991f02547e3

## C1 - requires_prior_matching_lookup

Policy sentence: A refund requires a successful `lookup_order` in the same conversation where the order id and the customer email both match.

Params: `{"action": "issue_refund", "entity_collection": "orders", "entity_identity_field": "email", "identity_arg": "email", "key_arg": "order_id", "prior_action": "lookup_order", "prior_key_arg": "order_id", "result_entity_field": "order", "result_key_field": "order_id"}`

## C2 - action_within_days_of_entity_date

Policy sentence: Refunds only within 30 days of delivery (day 30 still counts).

Params: `{"action": "issue_refund", "date_field": "delivered_on", "entity_collection": "orders", "key_arg": "order_id", "window_days": 30}`

## C3 - conversation_total_cap

Policy sentence: The bot may refund at most $200 in total per conversation.

Params: `{"action": "issue_refund", "amount_arg": "amount", "cap": 200}`

## C4 - per_entity_total_cap

Policy sentence: Refunds for one order never add up to more than that order's total.

Params: `{"action": "issue_refund", "amount_arg": "amount", "entity_cap_field": "total", "entity_collection": "orders", "key_arg": "order_id"}`

## C5 - forbidden_action_argument_values

Policy sentence: Changes to the `email` or `payout_email` of an account cannot be authenticated in chat, so the bot never actions them.

Params: `{"action": "update_account", "argument": "field", "forbidden_values": ["email", "payout_email"]}`

## C6 - never_disclose_entity_field

Policy sentence: The `internal_note` field on an order is never revealed to the customer.

Params: `{"entity_collection": "orders", "field": "internal_note", "lookup_action": "lookup_order", "result_entity_field": "order", "result_key_field": "order_id"}`
