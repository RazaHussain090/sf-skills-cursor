# Delivery Management — Feature Specification

**Status:** Draft for review. Nothing in this document is built yet.
**Org:** Scratch org alias `delivery-mgmt` (Developer edition).
**Username:** `test-dsg1gg801uz3@example.com`
**Instance:** `https://agility-force-22-dev-ed.scratch.my.salesforce.com`
**Expires:** 2026-11-05 (7 days from creation on 2026-10-29)
**Dev Hub:** `razahussain090@gmail.com`
**Scope:** A small internal app for scheduling and tracking deliveries. No packages, no AppExchange installs, metadata only.

Review the features below and mark each as **Keep**, **Change**, or **Drop** before implementation starts.

---

## 1. What the app does

Dispatchers create a delivery, assign a driver, and move it through a short status path until it is delivered or cancelled. Drivers and deliveries live in the same internal app. There is no customer portal, no maps, and no payments in this version.

## 2. Who uses it

One internal user type for this version: a dispatcher who can create drivers and deliveries and update status. Separate driver logins, profiles, and permission sets are out of scope unless you ask for them.

## 3. Proposed features

### F1. Delivery Management app

A Lightning app named **Delivery Management** with:

- App navigation for Deliveries and Drivers
- Standard Salesforce list views, record pages, and page layouts (no custom Lightning web components)

### F2. Driver object (`Driver__c`)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| Name | Text (standard name) | Yes | Driver's name |
| Phone | Phone | No | |
| Email | Email | No | |
| Status | Picklist | Yes | Available, On Route, Off Duty. Default: Available |
| Vehicle | Text (80) | No | Free-text vehicle description, for example "Van 12" |

List view: **All Drivers**.

### F3. Delivery object (`Delivery__c`)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| Delivery Number | Auto Number (name) | Yes | Format `DLV-{0000}` |
| Customer Name | Text (80) | Yes | |
| Contact Phone | Phone | No | |
| Pickup Address | Long Text (255) | Yes | Single text field, not a compound address |
| Dropoff Address | Long Text (255) | Yes | Single text field, not a compound address |
| Scheduled Date | Date | Yes | |
| Priority | Picklist | Yes | Standard, Rush. Default: Standard |
| Status | Picklist | Yes | New, Assigned, In Transit, Delivered, Cancelled. Default: New |
| Driver | Lookup to Driver | No | Optional until the delivery is assigned |
| Notes | Long Text Area | No | |
| Delivered On | Date/Time | No | Filled when status becomes Delivered |

List views:

- **All Deliveries**
- **Unassigned** — Status = New and Driver is blank
- **In Transit** — Status = In Transit
- **Rush** — Priority = Rush and Status is not Delivered or Cancelled

### F4. Record pages and layouts

- Delivery page layout grouped into Customer, Schedule, Assignment, and Notes
- Driver page layout with contact details and a related list of deliveries
- Compact layouts so list views and lookups show Delivery Number, Customer Name, Status, and Scheduled Date

### F5. Sample data

Five drivers and ten deliveries inserted with `sf data create record` (or one `sf data import tree` file) so the org is usable right after deploy. Statuses cover New, Assigned, In Transit, and Delivered.

## 4. Explicitly out of scope

These stay out unless you add them in review:

- Customer accounts, contacts, or orders (no standard Account/Contact model)
- Maps, geocoding, routes, or distance
- SMS, email alerts, or scheduled jobs
- Customer portal or Experience Cloud
- Mobile-only UI, offline, or signature capture
- Inventory, proof of delivery files, or payments
- Automatic driver assignment
- Custom Apex, triggers, flows, or Lightning web components
- Packaging (unlocked package or managed package)

Status changes are manual. No validation rule forces Delivered On to be filled, and no automation copies driver status when a delivery is assigned.

## 5. Build plan after you approve

1. Add custom objects, fields, layouts, list views, tabs, and the Lightning app under `force-app`.
2. Deploy with `sf project deploy start` to the `delivery-mgmt` scratch org.
3. Load the sample drivers and deliveries with `sf` data commands.
4. Open the org with `sf org open` so you can click through the app.

No other CLI, npm packages, or AppExchange installs.

## 6. Review checklist

Reply with Keep, Change, or Drop, plus any edits.

| ID | Feature | Your decision |
| --- | --- | --- |
| F1 | Lightning app with Deliveries and Drivers tabs | |
| F2 | Driver object (name, phone, email, status, vehicle) | |
| F3 | Delivery object and the four list views | |
| F4 | Page layouts, compact layouts, related list | |
| F5 | Sample data (5 drivers, 10 deliveries) | |

Optional changes to call out now:

- Link deliveries to standard **Account** instead of a free-text customer name
- Add a validation that **Delivered** requires **Delivered On**
- Add a simple record-triggered flow that sets the driver to **On Route** when a delivery is **In Transit**
