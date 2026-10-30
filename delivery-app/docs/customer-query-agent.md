# Customer Query Agent — Simple Version

**Status:** Built. The chat agent is published and active in the `delivery-agent` scratch org. The original `delivery-mgmt` org has the same lookup as a screen flow, because that org has no Einstein license.
**App:** Delivery Management (`delivery-mgmt` scratch org).
**Data:** `Delivery__c` and `Driver__c` already deployed, with the sample drivers and deliveries loaded.
**This version:** One read-only assistant that answers a question about an existing delivery. No record updates, no new channels, no extra objects.

Review the sections below and mark each as **Keep**, **Change**, or **Drop** before any agent is created.

---

## 1. What it does

A dispatcher types a customer’s question. The agent finds the matching delivery and answers in a short sentence using only fields on that record.

The customer does not log in. There is still no portal. The dispatcher is the person using the agent, so they can read the answer back to the customer.

Example:

> Where is the Cedar School delivery?

> Delivery DLV-0004 for Cedar School is In Transit. It is scheduled for October 29, 2026. The driver is Jordan Lee. Pickup is 100 Warehouse Rd, Austin, TX. Dropoff is 55 Campus Drive, Austin, TX.

If nothing matches, the agent says it could not find a delivery. It does not guess a status, a date, or a driver.

## 2. Who uses it

| | V1 | Later |
| --- | --- | --- |
| User | Dispatcher already in the Delivery Management app | A customer, on a channel we have not built |
| Can change records | No | Only if we add that on purpose |

## 3. Questions it answers

It answers only when the question is about one delivery the org already has.

| Question | How it finds the record | What it may say |
| --- | --- | --- |
| Status by delivery number | `Delivery__c.Name`, for example `DLV-0004` | Status |
| Status by customer name | `Customer_Name__c` | Status, and the delivery number so the customer can confirm |
| When is it scheduled? | Same lookup | `Scheduled_Date__c` |
| Who is the driver? | Driver lookup | Driver **name** only |
| Where is pickup or dropoff? | Same lookup | `Pickup_Address__c`, `Dropoff_Address__c` |
| Has it been delivered? | Same lookup | Status, and `Delivered_On__c` when that field has a value |

Fields it may read:

- Delivery number, customer name, status, priority, scheduled date
- Pickup address, dropoff address, delivered on
- Driver name

Fields it must not read aloud:

- `Notes__c` (internal)
- Driver phone, email, status, and vehicle

## 4. Lookup rules

1. A delivery number (`DLV-` plus digits) is an exact match on `Name`.
2. A customer name is an exact match on `Customer_Name__c`.
3. One match: answer from that record.
4. Several matches: list delivery number, status, and scheduled date, and ask which delivery they mean. Do not pick one.
5. No match: say it was not found and ask for the delivery number or customer name.
6. The answer uses the words stored on the record. It does not estimate arrival time, traffic, or distance.

## 5. What it refuses

- Change status, assign a driver, or edit any field
- Create a delivery or a driver
- Send email, SMS, or any other message
- Answer from notes, maps, or anything outside the two objects
- Invent a delivery when the lookup returns nothing

If the question is not about a delivery, it says it can only look up a delivery.

## 6. How the simple agent is shaped

One agent. One topic. One read action.

| Piece | V1 |
| --- | --- |
| Agent | **Delivery Assistant** |
| Topic | **Delivery status** — questions about an existing delivery |
| Action | **Get Delivery** — read `Delivery__c` and the related driver name. No create, update, or delete |
| Instructions | Follow the lookup rules and the refusal list. Quote field values. Keep the reply to a few sentences |

The original scratch org cannot host Agentforce. The agent runs in `delivery-agent`, created from `config/agentforce-scratch-def.json`. Sample delivery numbers start at `DLV-0000`, so Cedar School is `DLV-0004`.

## 7. Sample questions to try after it exists

These use the records already loaded.

| Ask | Expected shape of the answer |
| --- | --- |
| What is the status of DLV-0004? | In Transit, Cedar School, driver Jordan Lee |
| Has the Elm Street Books delivery been delivered? | Delivered, and the delivered-on time |
| Where does the Harbor Clinic delivery go? | Rush, status New, dropoff 800 Medical Pkwy. No driver yet |
| What about Northwind? | One or more matches listed, not a guessed status |
| Cancel the florist delivery | Refuses. Does not change the record |

## 8. Out of scope until we extend

- Customer login, Experience Cloud, chat widget, SMS, or email
- Matching the caller by phone number
- Creating or updating deliveries from the conversation
- Driver assignment, notifications, or status automation
- Maps, ETAs, or “how far away is the driver”
- More than one topic
- Custom Apex, Lightning web components, or a package

## 9. Build plan after you approve

1. Confirm the scratch org can host an Agentforce agent. If it cannot, stop and say what is missing.
2. Add one read action that accepts a delivery number or a customer name and returns the allowed fields.
3. Add the Delivery Assistant agent with the single Delivery status topic and the instructions in this document.
4. Ask the five sample questions and check that refusals do not change data.

## 10. Review checklist

Reply with Keep, Change, or Drop.

| ID | Piece | Your decision |
| --- | --- | --- |
| A1 | Dispatcher-only chat that answers from delivery records | |
| A2 | Lookup by delivery number or exact customer name | |
| A3 | Read-only. No edits, no messages, no notes or driver contact details | |
| A4 | One topic and one Get Delivery action | |

Later extensions, not part of this version:

- Let the customer ask directly, after they give a delivery number
- Match `Contact_Phone__c` so the caller does not need the delivery number
- A second topic that files a request for the dispatcher, still without changing the delivery itself
