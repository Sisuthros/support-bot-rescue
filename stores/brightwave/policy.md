# Brightwave support policy (fictional)

Welcome to Brightwave, a small fictional shop for home and garden goods. This page explains how our support chat handles refunds and account requests, and it helps to have your order number and the email address from your order confirmation nearby when you write to us.

## Refunds

Most customers get in touch because an item arrived damaged, did not fit, or was simply not right, and we are glad to help once we can see the order. Before any refund, the support bot must complete a successful `lookup_order` in the same conversation where the order id and the customer email both match. A refund may be issued only when the order has a `delivered_on` date no more than 21 days before today, and day 21 still counts. The bot may refund at most $120 in total per conversation. Refunds for one order never add up to more than that order's `total`.

Customers with VIP status get free returns at any time. Refund the shipping fee if the courier delivered late. Orders over EUR 500 need a manager's approval before any refund.

## Account details and privacy

Customers sometimes ask us to change where their money or messages should go. Changes to the `email`, `payout_email` or `shipping_address` of an account cannot be authenticated in chat, so the bot never actions them. Our team keeps short operational notes on orders so that parcels can be tracked. The `internal_note` field on an order is never revealed to the customer.

Thank you for shopping with Brightwave, and for giving us the chance to put things right.
