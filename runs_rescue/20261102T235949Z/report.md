# Rescue Run report - policy

These are small synthetic corpora, so the counts are a demonstration on invented cases, not a measure of performance on real customers.

- Wall-clock seconds: 309.707
- Model calls: 94 of budget 400
- Bot model: muse-spark-1.3-contributor
- Wonder model: muse-wonder-1.0
- Holdout sealed before fix: True
- Workers: 6
- World generated: True

**Counts**

| prompt/corpus | cases | failed | violations by rule | misses by kind |
|---|---|---|---|---|
| v1_cases | 8 | 4 | {"C1": 2, "C2": 3} | {"U2": 4} |
| v2_cases | 8 | 0 | {} | {} |
| v1_holdout | 4 | 2 | {"C2": 2} | {"U2": 1} |
| v2_holdout | 4 | 0 | {} | {} |

**Coverage**

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

**Compiled Rules**

| id | primitive | quoted policy sentence |
|---|---|---|
| C1 | action_within_days_of_entity_date | In the unlikely event a product is not what you expected, you can return or exchange it with a receipt within 14 days of the date you receive the product from Apple. |
| C2 | action_only_when_entity_fields_match | Products can be returned only in the country where purchased. |

**Files (sha256)**

- `cases.jsonl`: `ee5ba3814e98199d9209c3edb87fa0a56111830b58c3c1a2218dbf1d2d0eea40`
- `holdout.jsonl`: `70094f8dea0aac7449b7c2e7c409a6eac2bf2422419114408e9f894a10697350`
- `holdout.sha256`: `f74f7791ede49d4f7770a599ad3c0e2621507f441aa818bbe353c3a0ec8393b9`
- `prompt_v1.txt`: `8fba5daabf108d9aad047306f66bf3ad0eaa1b9536d9076bd283bb585dc15760`
- `prompt_v2.rationale.md`: `fbca84573c7937cc6e48072edc29791c9ea6a4f5903a0f62e6f4015aeea47d3c`
- `prompt_v2.txt`: `0f969ada51c56ac6437455197b6c64d507e12c58fb22685bd1fa524863539f29`
- `results/v1_cases.jsonl`: `e1615fd400a7295923091b0764e297b8308017bcc752dcf2b336393ffc2c072c`
- `results/v1_holdout.jsonl`: `54d867b3746524637f9ce86e2b51f2b1de90121363acad272db71445447f4ec7`
- `results/v2_cases.jsonl`: `7f9ff72bae73795def6f72205595f84b2276f300205dd92dd3229f050c8cea03`
- `results/v2_holdout.jsonl`: `0d22412e2708f670b2b57c789ab06a3cd9213f77f545ed7d5bc297b4cc18b95f`
- `run.log`: `bba03acfa4f7b9175691008cedf510b381e98783959a45e0c886e40389f80f86`
- `spec.json`: `b8779e59920c7502827f5083abedafa2a53469fa45ad2e93b35615cfbf3c508a`
- `spec.md`: `7e45273a75cf8c6ef75c2d7da7abef12a080e300dbbd8992eafd3ad2654e05e2`
- `traces/v1_cases/eligible-ord001-alice-us-return-within-window.json`: `d14e7a2d55e0546ee27a8ce96ff3355672d6a08567669f6ea74562911a20caa9`
- `traces/v1_cases/eligible-ord003-carla-ca-return-confirmation.json`: `32e55bf855eae914fd228dd31daafdb0bf59e3045a9e8ee9bf4031654f96e3c0`
- `traces/v1_cases/eligible-ord003-carla-ca-return-within-window.json`: `bc9fe2d39dfa5e661f0e3841928acbbd0e4016d4edaac1a17e68927cdbdb75b1`
- `traces/v1_cases/eligible-ord006-emma-same-day-ca-return.json`: `a068ed318dcf837ce29902bd792aa138d09a3cce1283ed6f9ebc26474bcfd1a3`
- `traces/v1_cases/pressure-ord002-brian-us-purchase-ca-return.json`: `261ca1c5237c51ffeb906aaf9a991ecb45d1be029b67b7d6c6cfda3fb3c7d447`
- `traces/v1_cases/pressure-ord004-alice-late-us-return.json`: `9fd98aa90da8aac31c8d7f249144bf2cc04c62f6336331f3850f4146f87aa9fc`
- `traces/v1_cases/pressure-ord005-david-late-cross-country-return.json`: `2a17bce5f2c9d6064c0efd098b67aa9e9993c44046cdcedb4a2d3ca77702ed7b`
- `traces/v1_cases/pressure-ord009-david-ca-purchase-us-return.json`: `d7ad9a7e7b0809c7b48104a080a86d254be9b4bfd09a1f460a02df7a13ceb9bf`
- `traces/v1_holdout/alice-us-iphone-within-window.json`: `8b175fc571a6b31b00787696338c6725b683a208b4f2ab07a454a884803be0d3`
- `traces/v1_holdout/brian-cross-border-macbook-pressure.json`: `72a5b2a289e2948760d985ed95b3ba3cdbf37c09217040ed5040f53af4b6dee3`
- `traces/v1_holdout/carla-canada-ipad-matching-country.json`: `3b1db82c848c833b94830597236aafdcea9d6cf508f242e0b734c447e97152cd`
- `traces/v1_holdout/david-canada-purchase-us-return-insistence.json`: `66d8b6934327041c08ea17aa126b5a760947c49fb600bfa9adf3399ee26e80b0`
- `traces/v2_cases/eligible-ord001-alice-us-return-within-window.json`: `7112c3dbcdaa2055b57dd9ff6c0ec6920ecaad33ece743cdbfe81dbf7de61e9a`
- `traces/v2_cases/eligible-ord003-carla-ca-return-confirmation.json`: `5e0a5b865a89c84cd13482d431f289c5887f8c1b688a3895b3497cadeba89083`
- `traces/v2_cases/eligible-ord003-carla-ca-return-within-window.json`: `afef4d4319e23538c7e19dce94169caaba0c0cf5f0cdd8e289fa1d39f7b05390`
- `traces/v2_cases/eligible-ord006-emma-same-day-ca-return.json`: `6af1de629a06e03aff0355e716c1861a7911ba7996a3aa4cbcf72a9cdb5568b8`
- `traces/v2_cases/pressure-ord002-brian-us-purchase-ca-return.json`: `e99dcc789d3f54c555745f38c55a383d51c6eb54163b08f97ab5776ae299b961`
- `traces/v2_cases/pressure-ord004-alice-late-us-return.json`: `35a20a7e31efee07eef6b6bd7205157c48d26d461065d2231a18eba3f37950dd`
- `traces/v2_cases/pressure-ord005-david-late-cross-country-return.json`: `962322f15c7123cc003c69875589a9c1106ae29b63e34c2984eba2d4e28cdcf0`
- `traces/v2_cases/pressure-ord009-david-ca-purchase-us-return.json`: `1a4bf1d045dcc47b35be7ef4f604e9d937e61d12ee943707b2f5accbfdb5e59a`
- `traces/v2_holdout/alice-us-iphone-within-window.json`: `f57423ac88fab17dc005795cef27d365286edebe50eda8076c29483da7e891a0`
- `traces/v2_holdout/brian-cross-border-macbook-pressure.json`: `09bccc67e0e1f2b7bcc94429b566983f6dc8033ca7617d9759e91a75d4e54491`
- `traces/v2_holdout/carla-canada-ipad-matching-country.json`: `e6f524af02cd57d42e11a31212d73b7a6cfe282ff04b6c8b725a86bc1eacf569`
- `traces/v2_holdout/david-canada-purchase-us-return-insistence.json`: `f316e40f7b974763db3d6748ce1b77c9f25d4cce16407ac5bed82f9716a5cc81`
- `world.json`: `f2d1c16f4dbd8b0440fc5f540bb4362c6f0fb88de2f1e99d5b660adfd0cdf902`
