# Compiled policy spec

- Model: muse-wonder-1.0
- Policy sha256: 85ad717bbc64defd7ec166313814abd944c341dd9c710366869443b7a7bc6e2d
- Response id: resp_6ae8effd08b20f9989584473

## Coverage

6 of 9 obligations are enforced by code; 3 need human review; 6 informational sentences, 0 unaccounted

- [informational] Welcome to Brightwave, a small fictional shop for home and garden goods. - no obligation (model)

- [informational] This page explains how our support chat handles refunds and account requests, and it helps to have your order number and the email address from your order confirmation nearby when you write to us. - no obligation (model)

- [informational] Most customers get in touch because an item arrived damaged, did not fit, or was simply not right, and we are glad to help once we can see the order. - no obligation (model)

- [enforced] Before any refund, the support bot must complete a successful `lookup_order` in the same conversation where the order id and the customer email both match.

- [enforced] A refund may be issued only when the order has a `delivered_on` date no more than 21 days before today, and day 21 still counts.

- [enforced] The bot may refund at most $120 in total per conversation.

- [enforced] Refunds for one order never add up to more than that order's `total`.

- [needs_review] Customers with VIP status get free returns at any time. - needs human review: No primitive covers VIP status or free returns; no such entity field or return action is available.

- [needs_review] Refund the shipping fee if the courier delivered late. - needs human review: No primitive expresses a conditional shipping-fee refund based on late courier delivery.

- [needs_review] Orders over EUR 500 need a manager's approval before any refund. - needs human review: No primitive expresses manager approval or an approval threshold before a refund.

- [informational] Customers sometimes ask us to change where their money or messages should go. - no obligation (model)

- [enforced] Changes to the `email`, `payout_email` or `shipping_address` of an account cannot be authenticated in chat, so the bot never actions them.

- [informational] Our team keeps short operational notes on orders so that parcels can be tracked. - no obligation (model)

- [enforced] The `internal_note` field on an order is never revealed to the customer.

- [informational] Thank you for shopping with Brightwave, and for giving us the chance to put things right. - no obligation (model)

## C1 - requires_prior_matching_lookup

Policy sentence: Before any refund, the support bot must complete a successful `lookup_order` in the same conversation where the order id and the customer email both match.

Params: `{"action": "issue_refund", "entity_collection": "orders", "entity_identity_field": "email", "identity_arg": "email", "key_arg": "order_id", "prior_action": "lookup_order", "prior_key_arg": "order_id", "result_entity_field": "order", "result_key_field": "order_id"}`

## C2 - action_within_days_of_entity_date

Policy sentence: A refund may be issued only when the order has a `delivered_on` date no more than 21 days before today, and day 21 still counts.

Params: `{"action": "issue_refund", "date_field": "delivered_on", "entity_collection": "orders", "key_arg": "order_id", "window_days": 21}`

## C3 - conversation_total_cap

Policy sentence: The bot may refund at most $120 in total per conversation.

Params: `{"action": "issue_refund", "amount_arg": "amount", "cap": 120}`

## C4 - per_entity_total_cap

Policy sentence: Refunds for one order never add up to more than that order's `total`.

Params: `{"action": "issue_refund", "amount_arg": "amount", "entity_cap_field": "total", "entity_collection": "orders", "key_arg": "order_id"}`

## C5 - forbidden_action_argument_values

Policy sentence: Changes to the `email`, `payout_email` or `shipping_address` of an account cannot be authenticated in chat, so the bot never actions them.

Params: `{"action": "update_account", "argument": "field", "forbidden_values": ["email", "payout_email", "shipping_address"]}`

## C6 - never_disclose_entity_field

Policy sentence: The `internal_note` field on an order is never revealed to the customer.

Params: `{"entity_collection": "orders", "field": "internal_note", "lookup_action": "lookup_order", "result_entity_field": "order", "result_key_field": "order_id"}`
