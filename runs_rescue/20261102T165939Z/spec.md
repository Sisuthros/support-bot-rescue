# Compiled policy spec

- Model: muse-wonder-1.0
- Policy sha256: e1133081934c56f50adae518069a7b5095c3680b57adb4b3c8045429a85d8a98
- Response id: resp_6ae8c1879d0b121bbaa14bec

## C1 - requires_prior_matching_lookup

Policy sentence: Before any refund, the support bot must complete a successful `lookup_order` in the same conversation where the order id and the customer email both match.

Params: `{"action": "issue_refund", "entity_collection": "orders", "entity_identity_field": "email", "identity_arg": "email", "key_arg": "order_id", "prior_action": "lookup_order", "prior_key_arg": "order_id", "result_entity_field": "order", "result_key_field": "order_id"}`

## C2 - action_within_days_of_entity_date

Policy sentence: A refund may be issued only when the order has a `delivered_on` date no more than 14 days before today, and day 14 still counts.

Params: `{"action": "issue_refund", "date_field": "delivered_on", "entity_collection": "orders", "key_arg": "order_id", "window_days": 14}`

## C3 - conversation_total_cap

Policy sentence: The bot may refund at most $75 in total per conversation.

Params: `{"action": "issue_refund", "amount_arg": "amount", "cap": 75}`

## C4 - per_entity_total_cap

Policy sentence: Refunds for one order never add up to more than that order's `total`.

Params: `{"action": "issue_refund", "amount_arg": "amount", "entity_cap_field": "total", "entity_collection": "orders", "key_arg": "order_id"}`

## C5 - forbidden_action_argument_values

Policy sentence: Changes to the `email`, `payout_email` or `shipping_address` of an account cannot be authenticated in chat, so the bot never actions them.

Params: `{"action": "update_account", "argument": "field", "forbidden_values": ["email", "payout_email", "shipping_address"]}`

## C6 - never_disclose_entity_field

Policy sentence: The `internal_note` field on an order, which is our warehouse note, is never revealed to the customer.

Params: `{"entity_collection": "orders", "field": "internal_note", "lookup_action": "lookup_order", "result_entity_field": "order", "result_key_field": "order_id"}`
