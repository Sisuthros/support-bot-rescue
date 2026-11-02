# Compiled policy spec

- Model: muse-wonder-1.0
- Policy sha256: 0e4dfead3067f61276319ea86e6693f02fa8eb9ce7e35cb4d27ef1a76072d2ce
- Response id: resp_6ae91a828dda0e8a34424d40

## Coverage

1 of 12 obligations are enforced by code; 10 need human review; 3 informational sentences, 1 unaccounted

- [informational] We believe you will be thrilled with the products you purchase from the Apple Store. - no obligation (model)

- [enforced] In the unlikely event a product is not what you expected, you can return or exchange it with a receipt within 14 days of the date you receive the product from Apple.

- [needs_review] The product must be in its original condition with all of its included parts, accessories, and packaging and we’ll exchange it or offer a refund based on the payment method. - needs human review: No primitive can verify product condition or completeness, or enforce the payment-method-based refund method.

- [unaccounted] In addition, please note: - compiler said nothing

- [needs_review] Apple products purchased through other retailers must be returned to those retailers in accordance with their returns and refunds policies. - needs human review: No primitive records the retailer of purchase or enforces retailer-specific return routing.

- [needs_review] Products can be returned only in the country where purchased. - needs human review: No primitive or order field records the purchase or return country.

- [needs_review] For returns for cash or cash equivalent over $750, Apple will mail a refund check to you within 10 business days. - needs human review: No primitive enforces mailing a refund check based on payment type and amount or the associated deadline.

- [needs_review] For returns with a gift receipt, Apple will offer you an Apple Gift Card. - needs human review: No primitive records gift-receipt status or issues a gift card.

- [needs_review] For returns paid with your Apple Account balance, Apple will refund the portion paid to your Apple Account or, if unable, an Apple Gift Card. - needs human review: No primitive records the Apple Account payment portion or enforces that refund destination.

- [needs_review] Returned products may require inspection. - needs human review: No primitive records or requires product inspection before a return.

- [needs_review] If approved, a refund or exchange will be issued within 10 business days. - needs human review: No primitive records an approval date or enforces a 10-business-day issuance deadline after approval.

- [informational] Apple provides security features to protect your product in case of loss or theft. - no obligation (model)

- [needs_review] If these features were activated and cannot be disabled by the person in possession, Apple may refuse the return or exchange. - needs human review: No primitive records security-feature activation or whether it can be disabled.

- [needs_review] To return ten or more of the same product, you must return to the Apple Store where purchased. - needs human review: No primitive enforces a quantity-based requirement to use the purchasing store.

- [informational] For complete details on how to return a product purchased at the Apple Store please visit the Returns & Refunds page. - no obligation (model)

## C1 - action_within_days_of_entity_date

Policy sentence: In the unlikely event a product is not what you expected, you can return or exchange it with a receipt within 14 days of the date you receive the product from Apple.

Params: `{"action": "issue_refund", "date_field": "delivered_on", "entity_collection": "orders", "key_arg": "order_id", "window_days": 14}`
