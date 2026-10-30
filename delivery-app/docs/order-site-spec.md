# Order Site — Specification

**Status:** The order component is in the Delivery Management app on the Place Order tab for testing. The public site is not created yet.
**Org:** `delivery-agent`, where the warehouses, products, stock, and deliveries already live.
**This version:** One public page where a customer orders products that are on the shelf. Placing the order creates a delivery and its pick lines. No login, no payment, no stock change.

Review the sections below and mark each as **Keep**, **Change**, or **Drop** before anything is built.

---

## 1. What the customer does

A customer opens a public page. They do not log in. They see products the warehouse can still fill, choose quantities, and enter where the order should go.

Example:

> Paper Towels, case, 40 on hand at Austin Main. Quantity 2.
> Coffee Beans, case, 12 on hand at Austin Main. Quantity 1.
> Name: Northwind Market. Phone: 555-2001. Dropoff: 14 Oak Street, Austin, TX. Date: October 31, 2026.

They place the order. The page shows the new delivery number, for example `DLV-0011`, and says the warehouse will pick it.

The warehouse clerk then sees that delivery in the existing app: status New, fulfillment To Pick, warehouse Austin Main, and two delivery lines at To Pick. A dispatcher assigns a driver only after it is packed. The rest of the delivery path stays as it is.

## 2. Why a site and one Lightning web component

The customer is not a Salesforce user, so the page cannot live inside the Delivery Management app.

The page is an Experience Cloud site with one Lightning web component, `orderCatalog`. A guest user can open it. The component shows the catalog, the cart, and the delivery details, then calls Apex to create the records.

A screen flow can collect a name and an address, and it is a poor catalog. An outside website would need its own host and a new public API. The site keeps the order on the same records the clerk and the dispatcher already use.

Before building, confirm `delivery-agent` can host an Experience Cloud site. The scratch org definition does not enable Communities today. If the org cannot host a site, stop and say what is missing.

## 3. What the page shows

One product row for each product that has quantity on hand greater than zero at a warehouse whose status is Open.

| Shown | Hidden |
| --- | --- |
| Product name, unit, quantity on hand | SKU, bin, product description |
| Warehouse name | Warehouse phone |
| Quantity the customer wants | Driver, notes, other customers' orders |

If the same product is on hand at more than one open warehouse, the row uses the warehouse that can fill the largest quantity. Exam Gloves are at Austin Main (24) and Supply Court (4), so the page offers Austin Main.

The customer cannot type a quantity above the number on hand. The cart total is the sum of the quantities, not a price. There is no price on the product.

## 4. One warehouse per order

A delivery leaves from one warehouse. Every line in the cart must come from that same warehouse.

The first product the customer adds chooses the warehouse. Products stocked only at another warehouse stay visible and cannot be added. The page says those items ship from the other warehouse and need a separate order.

Dental Bibs are only at Supply Court. Paper Towels are only at Austin Main. A customer who wants both places two orders.

## 5. What they submit

| Field | Required | Written to |
| --- | --- | --- |
| Customer name | Yes | `Delivery__c.Customer_Name__c` |
| Phone | No | `Delivery__c.Contact_Phone__c` |
| Dropoff address | Yes | `Delivery__c.Dropoff_Address__c` |
| Date | Yes | `Delivery__c.Scheduled_Date__c` |
| Warehouse | Chosen by the cart | `Delivery__c.Warehouse__c` |
| Pickup address | Copied from the warehouse | `Delivery__c.Pickup_Address__c` |

The new delivery is status New, priority Standard, and fulfillment To Pick. Each cart row becomes a delivery line for that product and quantity, status To Pick.

Placing the order does not change quantity on hand. The clerk still reduces the shelf count when the goods leave the bin. Two customers can order the last case until a clerk updates stock.

If the customer submits an empty cart, a missing name, a missing dropoff, or a missing date, the page asks for those and does not create a delivery.

## 6. After the order

The page shows the delivery number, the warehouse, the dropoff, the date, and each line with its quantity. It tells the customer to keep the delivery number.

A second box on the same page looks up an existing order. The customer types a delivery number. The page returns status, fulfillment, scheduled date, dropoff, and, while the delivery is In Transit, the last reported location. It does not return the driver name, driver phone, notes, or bin.

## 7. Who can do what

| Person | Where | Can |
| --- | --- | --- |
| Customer | Public site | See in-stock products, place one order, look up one delivery number |
| Warehouse clerk | Delivery Management | Pick and pack the new lines, update quantity on hand |
| Dispatcher | Delivery Management | Assign a driver after the order is packed |

The guest user can create a delivery and its lines, and can read the fields in sections 3 and 6. The guest user cannot edit a delivery, assign a driver, change a status, or read driver contact details.

## 8. What it refuses

- Payment, tax, or a price
- A customer login, account, or saved address
- Changing quantity on hand, reserving stock, or blocking the last unit
- An order whose lines come from two warehouses
- Choosing a driver, a priority, or a status
- Editing or cancelling an order from the site
- Showing bins, SKUs, notes, or driver phone and email

## 9. Build plan after you approve

1. Confirm `delivery-agent` can host an Experience Cloud site. If it cannot, stop.
2. Add Apex that lists in-stock products for open warehouses, creates one delivery and its lines, and reads one delivery back by number.
3. Add the `orderCatalog` component and a public site page that hosts it.
4. Place an order for Paper Towels and Coffee Beans from Austin Main. Confirm `DLV-` number, fulfillment To Pick, and two lines at To Pick. Confirm stock quantities are unchanged.
5. Try to add Dental Bibs to that same cart. Confirm the page blocks it.
6. Look up the new delivery number. Confirm the status is New and the driver is not shown.

## 10. Review checklist

Reply with Keep, Change, or Drop.

| ID | Piece | Your decision |
| --- | --- | --- |
| S1 | Public site, no login. One Lightning web component for the catalog, cart, and delivery details | |
| S2 | Show only products with stock at an open warehouse. Hide SKU, bin, and driver details | |
| S3 | One warehouse per order. The first item chooses it | |
| S4 | Submit creates a New delivery, fulfillment To Pick, and lines at To Pick. Stock quantity stays the same | |
| S5 | Confirmation shows the delivery number. The same page can look up a delivery number afterward | |
