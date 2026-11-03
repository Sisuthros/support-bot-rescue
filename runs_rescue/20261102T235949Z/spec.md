# Compiled policy spec

- Model: muse-wonder-1.0
- Policy sha256: 0e4dfead3067f61276319ea86e6693f02fa8eb9ce7e35cb4d27ef1a76072d2ce
- Response id: resp_6ae924185ed84adfa8f840ae

## Coverage

2 of 10 obligations are enforced by code; 7 need human review; 5 informational sentences, 1 unaccounted (1 via human-approved extensions)

- [informational] We believe you will be thrilled with the products you purchase from the Apple Store. - no obligation (model)

- [enforced] In the unlikely event a product is not what you expected, you can return or exchange it with a receipt within 14 days of the date you receive the product from Apple.

- [needs_review] The product must be in its original condition with all of its included parts, accessories, and packaging and we’ll exchange it or offer a refund based on the payment method. - needs human review: No primitive checks product condition, included parts, packaging, or payment-method-based exchange or refund.

- [unaccounted] In addition, please note: - compiler said nothing

- [needs_review] Apple products purchased through other retailers must be returned to those retailers in accordance with their returns and refunds policies. - needs human review: No primitive tracks purchase retailer or enforces another retailer's return policy.

- [enforced] Products can be returned only in the country where purchased. - enforced, approved extension action_only_when_entity_fields_match

- [needs_review] For returns for cash or cash equivalent over $750, Apple will mail a refund check to you within 10 business days. - needs human review: No primitive expresses a payment-method threshold or mailing a refund check within business days; a cap would incorrectly forbid amounts over $750.

- [needs_review] For returns with a gift receipt, Apple will offer you an Apple Gift Card. - needs human review: No primitive tracks gift receipts or issues a gift card.

- [needs_review] For returns paid with your Apple Account balance, Apple will refund the portion paid to your Apple Account or, if unable, an Apple Gift Card. - needs human review: No primitive tracks payment source or routes refunds between account balance and a gift card.

- [informational] Returned products may require inspection. - no obligation (model)

- [needs_review] If approved, a refund or exchange will be issued within 10 business days. - needs human review: No primitive measures a business-day deadline from approval; the available date primitive measures calendar days from an entity date.

- [informational] Apple provides security features to protect your product in case of loss or theft. - no obligation (model)

- [informational] If these features were activated and cannot be disabled by the person in possession, Apple may refuse the return or exchange. - no obligation (model)

- [needs_review] To return ten or more of the same product, you must return to the Apple Store where purchased. - needs human review: No primitive expresses a same-product quantity threshold or return-store location requirement.

- [informational] For complete details on how to return a product purchased at the Apple Store please visit the Returns & Refunds page. - no obligation (model)

## C1 - action_within_days_of_entity_date

Policy sentence: In the unlikely event a product is not what you expected, you can return or exchange it with a receipt within 14 days of the date you receive the product from Apple.

Params: `{"action": "issue_refund", "date_field": "delivered_on", "entity_collection": "orders", "key_arg": "order_id", "window_days": 14}`

## C2 - action_only_when_entity_fields_match

Policy sentence: Products can be returned only in the country where purchased.

Params: `{"action": "issue_refund", "entity_collection": "orders", "first_field": "purchase_country", "key_arg": "order_id", "second_field": "return_country"}`
