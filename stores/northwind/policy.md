# Northwind Outfitters support policy (fictional)

Welcome to the Northwind Outfitters help centre. We are a small outdoor-apparel shop, and this page explains, in plain language, how our support chat handles refunds and account requests for things like trail jackets, fleeces, boots and rain shells. If you are writing to us, it helps to have your order number and the email address from your order confirmation nearby, because those are the details our team uses to find a purchase.

## Refunds for returned gear

Most people get in touch because something did not fit, a seam failed, or the colour was not what they expected, and in those everyday cases we are glad to sort out a refund once we can see the order in our system. Before any refund, the support bot must complete a successful `lookup_order` in the same conversation where the order id and the customer email both match. That short check protects customers from having their orders discussed or refunded by someone else, and it also makes sure we are talking about the right jacket or pair of boots.

Timing matters for outdoor gear that may already have been worn on a trip. A refund may be issued only when the order has a `delivered_on` date no more than 14 days before today, and day 14 still counts. If that timing does not fit your trip, tell us what happened when you write, and we will talk through the options with you.

There is also a limit on what chat can pay out automatically. The bot may refund at most $75 in total per conversation. Refunds for one order never add up to more than that order's `total`. Larger purchases, split purchases and earlier refunds can all affect what chat can do, so it helps to mention them when you write.

## Account details and privacy

Customers sometimes ask us to update where their money or parcels should go after moving house or changing email provider. Changes to the `email`, `payout_email` or `shipping_address` of an account cannot be authenticated in chat, so the bot never actions them. A human colleague can help with those changes after the checks that our account team requires, and chat can pass the request along.

Our warehouse team keeps short operational notes on orders so that parcels can be tracked through the building. The `internal_note` field on an order, which is our warehouse note, is never revealed to the customer. Those notes can mention carriers, stock checks or handling details that would not make sense outside the warehouse, so our replies focus on your delivery and your return in ordinary words.

Thank you for shopping with Northwind Outfitters, and for giving us the chance to put things right.
