# DealFlow360 — Data Model

PostgreSQL (Supabase). Django ORM owns the schema; migrations are the source of truth.
This document is the design intent behind those migrations.

---

## 1. Conventions

- Every table has `id BIGSERIAL PRIMARY KEY`, plus `created_at` / `updated_at` where mutation matters.
- Money is `NUMERIC(12, 2)`. Percentages are `NUMERIC(5, 2)` (so `12.50` means 12.5%). **Never floats.**
- Enums are Django `TextChoices` stored as short `VARCHAR` — readable in psql, no migration pain.
- Soft delete only where a demo needs it (`is_active`); everything else hard-deletes.
- Anything a human decided gets an audit row. Approvals, edits and negotiations are append-only logs,
  never in-place mutations.
- Denormalised money columns (`quotation.total`, `line.line_total`) are **computed by the service layer
  on every write**, never trusted from the client, and never computed in a template.

---

## 2. Module map / ERD

```
                         ┌──────────────┐
                         │  sales_team  │
                         └──────┬───────┘
                                │
┌──────────┐            ┌───────▼──────┐          ┌──────────────┐
│  user    │◄───────────┤   customer   ├─────────►│  price_list  │
│ (+role)  │ owner_rep  │  (+tier)     │ tier     └──────┬───────┘
└────┬─────┘            └──────┬───────┘                 │
     │                         │                    ┌────▼──────────────┐
     │                         │                    │ price_list_rule   │
     │                         │                    └────┬──────────────┘
     │                  ┌──────▼────────┐                │
     │                  │   quotation   │           ┌────▼──────┐   ┌────────────────────┐
     ├─ owner_rep ─────►│  (+status)    │           │  product  ├──►│ product_category   │
     │                  │  (+risk_score)│           │ (+cost)   │   └────────┬───────────┘
     │                  └──────┬────────┘           └────┬──────┘            │
     │                         │                         │           ┌───────▼──────────────────┐
     │                  ┌──────▼──────────┐              │           │ category_discount_ceiling│
     │                  │ quotation_line  ├──────────────┘           └──────────────────────────┘
     │                  │ (+allowed_disc) │              │
     │                  │ (+excess_pts)   │       ┌──────▼─────────────┐  ┌──────────────────┐
     │                  └──┬────┬────┬────┘       │ product_variant    │  │ tier_discount_   │
     │                     │    │    │            │ product_attribute  │  │ ceiling          │
     │  ┌──────────────────┘    │    └──────────┐ │ product_attr_value │  └──────────────────┘
     │  │                       │               │ └────────────────────┘
     │  ▼                       ▼               ▼
┌────┴──────────────┐  ┌────────────────┐  ┌──────────────────┐   ┌──────────────────┐
│ approval_request  │  │ fulfillment_   │  │  subscription    │   │ product_pairing  │
│  └ approval_step  │  │ plan           │  │  └ subscription_ │   │ (upsell graph)   │
└───────────────────┘  │  └ allocation  │  │     event        │   └──────────────────┘
                       └───────┬────────┘  └────────┬─────────┘
┌───────────────────┐          │                    │
│ quotation_event   │   ┌──────▼──────┐      ┌──────▼──────────┐   ┌──────────────┐
│ (audit trail)     │   │ stock_item  │      │    invoice      ├──►│   payment    │
└───────────────────┘   │ stock_move  │      │  └ invoice_line │   └──────────────┘
                        │ warehouse   │      └──────┬──────────┘
┌───────────────────┐   └─────────────┘             │           ┌──────────────┐
│ negotiation_*     │                               └──────────►│ credit_note  │
│ portal_token      │   ┌──────────────┐                        └──────────────┘
└───────────────────┘   │ deal_alert   │
                        │ alert_action │
                        └──────────────┘
```

Ten Django apps: `accounts`, `catalog`, `governance`, `quotations`, `approvals`, `fulfillment`,
`subscriptions`, `billing`, `negotiation`, `insights`.

---

## 3. accounts

### `sales_team`
| Column | Type | Notes |
|---|---|---|
| `name` | varchar(120) | "West Team", "Enterprise" |
| `manager_id` | FK user, null | The approver for this team |

### `user` (extends `AbstractUser`)
| Column | Type | Notes |
|---|---|---|
| `email` | varchar, **unique** | This is the login field; `USERNAME_FIELD = "email"` |
| `full_name` | varchar(150) | |
| `role` | varchar(20) | `ADMIN` \| `SALES_REP` \| `SALES_MANAGER` \| `FINANCE` \| `CUSTOMER` |
| `sales_team_id` | FK sales_team, null | Used by reporting filters |
| `firebase_uid` | varchar(128), null, unique | Populated only after Firebase is wired in |
| `is_active` | bool | |

> Role lives on the user, not in Django Groups. It's one field, one source of truth, and the
> Ninja auth dependency reads it directly. Groups buy us nothing at this scale.

### `customer`
| Column | Type | Notes |
|---|---|---|
| `name` | varchar(150) | "Acme Corp" |
| `tier` | varchar(10) | `BRONZE` \| `SILVER` \| `GOLD` — drives the tier discount ceiling |
| `currency` | varchar(3) | `USD` default; multi-currency is a bonus |
| `contact_email` | varchar | Where the portal link is sent |
| `owner_rep_id` | FK user | The responsible rep |
| `portal_user_id` | FK user, null | The `CUSTOMER`-role user who can open the portal |
| `default_price_list_id` | FK price_list, null | |

---

## 4. catalog

### `product_category`
`name`, `code` (unique, e.g. `HARDWARE`, `SERVICES`, `SUBSCRIPTION`).
Category is what the category discount ceiling hangs off, so it is a real table, not a string.

### `product`
| Column | Type | Notes |
|---|---|---|
| `name`, `sku` (unique), `description` | | |
| `category_id` | FK product_category | |
| `unit` | varchar(20) | "Each", "Recurring" |
| `base_price` | numeric(12,2) | List price before price list rules |
| `cost_price` | numeric(12,2) | **Required for margin.** Never exposed to the portal. |
| `tax_percent` | numeric(5,2) | |
| `is_subscription` | bool | If true, `recurring_plan_id` must be set |
| `recurring_plan_id` | FK recurring_plan, null | |
| `is_promoted` | bool | Boosts ranking in the upsell panel |
| `is_active` | bool | |

`quantity_on_hand` is **not** a column here — it is derived from `stock_item` across warehouses.
Screen 17 shows it as a computed field. Storing it in two places is how demos desync.

### `product_attribute` / `product_attribute_value` / `product_variant`
| Table | Columns |
|---|---|
| `product_attribute` | `product_id`, `name` ("Color", "RAM", "Manufacturer") |
| `product_attribute_value` | `attribute_id`, `value` ("Blue"), `extra_price` numeric(12,2) |
| `product_variant` | `product_id`, `sku_suffix`, `extra_price` (sum of its values, cached), `is_active` |
| `product_variant_values` | M2M join `variant_id` ↔ `attribute_value_id` |

Variant price = `product.base_price + variant.extra_price`, then price list rules apply.

### `price_list` / `price_list_rule`
| Table | Columns |
|---|---|
| `price_list` | `name`, `tier` (nullable — a list can target a tier), `currency`, `is_active` |
| `price_list_rule` | `price_list_id`, `product_id` (null = category-wide), `category_id` (null = all), `rule_type` (`FIXED` \| `PERCENT_OFF`), `value`, `priority` int |

Resolution order for a line's unit price:
`most specific rule (product > category > global) by priority` → else `base_price + variant extra`.
Implemented once in `catalog/pricing.py::resolve_unit_price()`.

### `product_pairing` (upsell graph)
| Column | Notes |
|---|---|
| `source_product_id` → `target_product_id` | Directed: "people who bought source also bought target" |
| `co_purchase_score` | numeric(5,2), 0–1, seeded from fake history |
| `is_active` | |

### `upsell_config` (singleton row)
`min_margin_percent` (suggestions below this margin are never shown), `promoted_boost` (score bonus for `is_promoted`).

### `upsell_suggestion_log`
`quotation_id`, `product_id`, `action` (`SHOWN` \| `ADDED` \| `DISMISSED`), `margin_delta`, `actor_id`, `created_at`.
Feeds the "Top Upsold Product" tile on screen 15.

---

## 5. governance

### `tier_discount_ceiling`
`tier` (unique), `max_discount_percent`. Seed: Bronze 5, Silver 10, Gold 15.

### `category_discount_ceiling`
`category_id` (unique), `max_discount_percent`. Seed: Hardware 15, Services 10, Subscription 10.

### `approval_rule`
| Column | Notes |
|---|---|
| `name` | "Within limits", "Over limit, medium", "Over limit, high" |
| `min_score` / `max_score` | numeric(5,2), inclusive/exclusive band on the blended score |
| `required_roles` | JSON array, ordered: `[]`, `["SALES_MANAGER"]`, `["SALES_MANAGER","FINANCE"]` |
| `sequence` | int, evaluation order |
| `is_active` | |

This table **is** screen 18's bottom panel. The chain is data, not an `if` statement, which is
exactly what "must be implemented in application logic, not hardcoded" is asking for.

### `risk_config` (singleton row)
`weight_worst` (0.50), `weight_blended` (0.30), `weight_order` (0.20),
`cap_worst` (10.0), `cap_blended` (5.0), `cap_order` (5.0), `high_band_threshold` (60.0).
Tuning the score is a config change, not a deploy.

---

## 6. quotations

### `quotation`
| Column | Type | Notes |
|---|---|---|
| `number` | varchar(20), unique | `Q-1042`, generated |
| `customer_id` | FK customer | |
| `owner_rep_id` | FK user | |
| `price_list_id` | FK price_list, null | Snapshot of which list priced this quote |
| `currency` | varchar(3) | |
| `status` | varchar(24) | See the state machine in `WORKFLOW.md §3` |
| `order_discount_percent` | numeric(5,2) | Order-level discount **on top of** line discounts |
| `subtotal`, `discount_total`, `tax_total`, `total` | numeric(12,2) | Recomputed on every line change |
| `margin_amount`, `margin_percent` | numeric | Drives the live margin indicator |
| `blended_risk_score` | numeric(5,2) | Output of the risk engine |
| `risk_band` | varchar(10) | `NONE` \| `MEDIUM` \| `HIGH` |
| `requires_approval` | bool | Derived, stored so the list view doesn't recompute |
| `valid_until` | date, null | |
| `last_activity_at` | timestamptz | **Stalled-deal detection reads this.** Touched by any event. |
| `created_at`, `updated_at` | | |

Indexes: `(status)`, `(owner_rep_id, status)`, `(last_activity_at)` — the last one because the
deal-health sweep scans it every time the dashboard loads.

### `quotation_line`
| Column | Type | Notes |
|---|---|---|
| `quotation_id` | FK, `related_name="lines"` | |
| `product_id`, `variant_id` | FK, variant nullable | |
| `line_type` | varchar(12) | `ONE_TIME` \| `RECURRING` — **this is what splits hybrid billing** |
| `description` | varchar | Snapshot of the product name at add-time |
| `quantity` | numeric(10,2) | |
| `unit_price` | numeric(12,2) | Resolved price, **snapshotted** — later price list edits don't rewrite history |
| `unit_cost` | numeric(12,2) | Snapshotted for stable margin |
| `discount_percent` | numeric(5,2) | What the rep gave |
| `allowed_discount_percent` | numeric(5,2) | `min(tier, category)` at time of computation |
| `discount_excess_points` | numeric(5,2) | `max(0, given − allowed)` — the `OVER (+8pt)` badge |
| `tax_percent` | numeric(5,2) | |
| `line_subtotal`, `line_total`, `margin_amount` | numeric(12,2) | |
| `recurring_plan_id` | FK recurring_plan, null | Set when `line_type = RECURRING` |
| `position` | int | Display order |

> `allowed_discount_percent` and `discount_excess_points` are **stored per line**, not computed at
> render time. The approval screen has to show *why the quote was flagged* months later, and the
> ceilings may have changed since. Storing the judgement makes the audit trail honest.

### `quotation_event` — the audit trail
| Column | Notes |
|---|---|
| `quotation_id`, `actor_id` (null for system) | |
| `event_type` | `CREATED`, `LINE_ADDED`, `LINE_REMOVED`, `DISCOUNT_CHANGED`, `SUBMITTED`, `APPROVED`, `REJECTED`, `RETURNED`, `SENT_TO_CUSTOMER`, `NEGOTIATION_OPENED`, `COUNTER_RECEIVED`, `CONFIRMED`, `UPSELL_ADDED`, `NUDGED`, `ESCALATED` |
| `payload` | JSONB — before/after values |
| `note` | text — the human reason ("Requested justification") |
| `created_at` | |

Append-only. Every write to a quotation goes through `quotations/services.py`, which emits an
event and bumps `last_activity_at` in the same transaction. Screens 6 and 14 both read this table.

---

## 7. approvals

### `approval_request`
`quotation_id`, `risk_score`, `risk_band`, `status` (`PENDING` \| `APPROVED` \| `REJECTED` \| `RETURNED`),
`current_step_id` FK, `created_at`, `closed_at`.
A quotation can have **many** requests over its life — the portal re-approval path opens a new one
rather than reopening the old, so the history stays readable.

### `approval_step`
| Column | Notes |
|---|---|
| `request_id`, `sequence` | 1 = Sales Manager, 2 = Finance |
| `role_required` | varchar(20) |
| `assignee_id` | FK user, null — resolved from the team manager, else any user with the role |
| `status` | `PENDING` \| `APPROVED` \| `REJECTED` \| `RETURNED` \| `SKIPPED` |
| `decision_note` | text — mandatory on reject/return |
| `acted_at`, `acted_by_id` | |

Steps are materialised **when the request is created**, from `approval_rule.required_roles`. That
means screen 6's stepper is a straight read of rows, and "Finance only shown when required" is
literally "there is no Finance row".

---

## 8. fulfillment

### `warehouse`
`name`, `code` (unique), `address`, `shipping_cost_weight` numeric(6,2) (cost multiplier used by the
splitter), `base_shipment_cost` numeric(12,2), `is_active`.

### `stock_item`
`warehouse_id`, `product_id`, `variant_id` (null), `quantity_on_hand` int, `quantity_reserved` int,
`reorder_point` int, `reorder_quantity` int.
**Unique together:** `(warehouse, product, variant)`.
`available = quantity_on_hand − quantity_reserved` — screen 7's third column, computed, never stored.

### `stock_move`
`stock_item_id`, `delta` int (signed), `reason` (`RESERVE`, `RELEASE`, `SHIP`, `RESTOCK`, `ADJUST`),
`ref_type`/`ref_id` (what caused it), `actor_id`, `created_at`.
Append-only ledger. `quantity_on_hand` is the running total; the ledger is how we prove it and how
the "stock arrived → consolidate backorder" prompt gets triggered (a `RESTOCK` move fires a check).

### `fulfillment_plan`
`quotation_id` (one active plan per confirmed quote), `status` (`SUGGESTED` \| `ACCEPTED` \|
`OVERRIDDEN` \| `PARTIALLY_SHIPPED` \| `SHIPPED` \| `BACKORDER`), `estimated_shipments` int,
`estimated_cost` numeric(12,2), `is_manual_override` bool, `created_at`, `accepted_at`.

### `fulfillment_allocation`
`plan_id`, `quotation_line_id`, `warehouse_id`, `quantity` int, `is_backorder` bool,
`shipped_at` timestamptz null, `promised_date` date null.
`promised_date` vs `shipped_at` is what the **delivery slippage** indicator on screen 14 compares.

---

## 9. subscriptions

### `recurring_plan`
| Column | Notes |
|---|---|
| `name` | "Care Plan 2yr", "Support SLA" |
| `interval` | `WEEKLY` \| `MONTHLY` \| `QUARTERLY` \| `YEARLY` |
| `proration_mode` | `DAILY` (default) \| `NONE` \| `FULL_PERIOD` |
| `cancellation_policy` | `IMMEDIATE` \| `END_OF_PERIOD` |
| `refund_mode` | `PRORATED` \| `NONE` |
| `bill_in_advance` | bool, default true — "invoiced at the beginning of the period" per screen 17 |
| `is_active` | |

### `subscription`
| Column | Notes |
|---|---|
| `customer_id`, `quotation_id`, `quotation_line_id` | Provenance: which order created it |
| `plan_id`, `product_id` | |
| `quantity` numeric(10,2), `unit_price` numeric(12,2) | Current values |
| `status` | `ACTIVE` \| `PAUSED` \| `CANCELLED` |
| `start_date` | date |
| `current_period_start`, `current_period_end` | date — the window proration divides by |
| `next_bill_date` | date — screen 9's "Next Bill" column; nulled when paused/cancelled |
| `cancelled_at`, `cancellation_effective_date` | |

### `subscription_event`
`subscription_id`, `event_type` (`CREATED`, `QUANTITY_CHANGED`, `PLAN_CHANGED`, `PAUSED`,
`RESUMED`, `CANCELLED`, `RENEWED`), `effective_date`, `old_quantity`, `new_quantity`,
`proration_amount` numeric(12,2) (signed), `invoice_id` null, `credit_note_id` null,
`actor_id`, `created_at`.

This is the proration history screen 10 shows. Signed `proration_amount`: **positive → an extra
invoice line, negative → a credit note.** One rule, both directions.

---

## 10. billing

### `invoice`
| Column | Notes |
|---|---|
| `number` | `INV-1042`, unique |
| `customer_id`, `quotation_id` (null for pure-recurring), `subscription_id` (null for one-time) | |
| `invoice_type` | `ONE_TIME` \| `RECURRING` \| `PRORATION` |
| `status` | `DRAFT` \| `OPEN` \| `PARTIALLY_PAID` \| `PAID` \| `VOID` |
| `issue_date`, `due_date` | |
| `period_start`, `period_end` | Only for `RECURRING` |
| `currency`, `subtotal`, `tax_total`, `total`, `amount_paid` | |

`amount_due = total − amount_paid`, computed. Status transitions on payment, in the service layer.
**A one-time order and its subscription produce different invoice rows** — that separation is the
whole point of hybrid billing, so it is structural, not a filter.

### `invoice_line`
`invoice_id`, `description`, `quantity`, `unit_price`, `discount_percent`, `tax_percent`,
`line_total`, `quotation_line_id` (null), `subscription_id` (null).

### `payment`
`invoice_id`, `amount`, `method` (`BANK_TRANSFER` \| `CARD` \| `CHEQUE` \| `OTHER`), `reference`,
`paid_at`, `recorded_by_id`.
Multiple payments per invoice → `PARTIALLY_PAID` is real, not decorative.

### `credit_note`
`number` (unique), `customer_id`, `invoice_id` (null), `subscription_event_id` (null), `amount`,
`reason`, `status` (`ISSUED` \| `APPLIED` \| `VOID`), `created_at`.

---

## 11. negotiation (customer portal)

### `portal_token`
`token` (uuid, unique, indexed), `customer_id`, `quotation_id`, `expires_at`, `used_at`, `created_at`.
**This is what makes the portal a genuinely separate surface.** A portal request authorises against
a token scoped to *one* quotation, not against an internal session. Even a valid `CUSTOMER` user
cannot read a quotation they hold no token for.

### `negotiation_thread`
`quotation_id`, `status` (`OPEN` \| `RESOLVED`), `created_at`.

### `negotiation_message`
`thread_id`, `quotation_line_id` (null = order-level), `author_type` (`CUSTOMER` \| `REP`),
`author_id`, `body`, `created_at`.
Line-scoped messages are screen 11's "Line / Customer Comment" table.

### `negotiation_request`
| Column | Notes |
|---|---|
| `quotation_id`, `thread_id` | |
| `requested_discount_percent` | numeric(5,2), null |
| `requested_delivery_date` | date, null |
| `status` | `SUBMITTED` \| `ACCEPTED` \| `REJECTED` \| `COUNTERED` |
| `resolved_by_id`, `resolved_at`, `resolution_note` | |

Accepting a request rewrites line discounts **through the normal quotation service**, which
re-runs the risk engine, which may open a new `approval_request`. The portal gets no special path —
that's why re-approval is automatic rather than something we remembered to call.

---

## 12. insights (deal health & reporting)

### `deal_health_config` (singleton)
`stalled_days_threshold` (7), `anomaly_multiplier` (2.0 — flag when a rep's discount exceeds
2× their trailing average), `anomaly_min_quotes` (3 — don't judge a rep on one quote),
`slippage_grace_days` (0).

### `rep_discount_stat`
`rep_id`, `avg_discount_percent`, `quote_count`, `window_start`, `window_end`, `computed_at`.
Recomputed by the sweep. Cheap to store, expensive to recompute per dashboard render.

### `deal_alert`
| Column | Notes |
|---|---|
| `quotation_id` | Clicking the alert opens this quote (screen 14 requirement) |
| `alert_type` | `STALLED` \| `DISCOUNT_ANOMALY` \| `DELIVERY_SLIPPAGE` |
| `severity` | `LOW` \| `MEDIUM` \| `HIGH` |
| `message` | "Idle 9 days", "Discount 22% vs avg 8%" |
| `detected_at`, `status` (`OPEN` \| `ACKNOWLEDGED` \| `RESOLVED`), `resolved_at` | |

**Unique together** `(quotation, alert_type, status=OPEN)` via a partial index, so a re-run of the
sweep updates the existing alert instead of spamming duplicates.

### `alert_action`
`alert_id`, `action_type` (`NUDGE` \| `ESCALATE`), `actor_id`, `note`, `created_at`.
A `NUDGE` also writes a `quotation_event`, so the nudge shows up in the deal's own history.

---

## 13. Seed data (`python manage.py seed_demo`)

Sized so the demo script works on a clean database and every screen has non-empty state.

| Entity | What gets created |
|---|---|
| Users | 1 admin, 2 reps, 1 manager, 1 finance, 2 customer portal users |
| Teams | "West Team" (manager: M. Shah), "East Team" |
| Customers | Acme Corp (Gold), Beta Industries (Silver), Nova Retail (Gold), Zenith Co (Bronze), Delta LLC (Silver), Orion Ltd (Gold) |
| Categories | Hardware, Services, Subscription |
| Products | Laptop Pro 14 ($1200/$820), Docking Station ($180/$110), Wireless Mouse ($45/$22), Onsite Setup Service ($450/$300), Extended Warranty ($180/$60), Care Plan 2yr ($46/mo), Support SLA ($300/qtr) |
| Variants | Laptop: Color × RAM × Manufacturer; Docking: Color |
| Price lists | Bronze/USD (no adjustment), Gold/USD+EUR (base − 10%) |
| Ceilings | Bronze 5 / Silver 10 / Gold 15; Hardware 15 / Services 10 / Subscription 10 |
| Approval rules | The three bands from screen 18 |
| Warehouses | Main Warehouse (weight 1.0), East Depot (weight 1.4) |
| Stock | Laptop: Main 40/res 18, East 10/res 6 → forces the two-warehouse split in the demo |
| Plans | Monthly, Quarterly, Yearly — daily proration, prorated refunds |
| Quotations | One per pipeline column: Acme Draft $12,400 · Beta Pending $28,900 · Nova Approved $9,750 · Zenith Negotiation $15,300 (idle 9 days → stalled alert) · Orion Confirmed $41,000 |
| Invoices | INV-1042 unpaid $2,730 · INV-1043 paid $46 (recurring) · INV-1038 paid $9,750 |
| Alerts | Zenith stalled 9 days · Delta discount 22% vs 8% avg |

Seeding is **idempotent** — `get_or_create` throughout, safe to re-run mid-demo when someone
inevitably breaks the data.

---

## 14. Deliberate non-goals

Things we consciously left out, and why — worth saying out loud to the judges:

- **No multi-tenancy / company column.** Bonus, not requirement. Adding it later is one FK and one
  manager mixin; adding it now costs an hour we don't have.
- **No full double-entry accounting.** Invoices, payments and credit notes are enough to show
  reconciliation. A general ledger proves nothing extra in a five-minute demo.
- **No background worker.** The deal-health sweep runs on dashboard load and on write, inside the
  request. At seed-data scale it's a few milliseconds. Celery is the first thing we'd add next.
- **No `quantity_on_hand` cached on `product`.** Derived from `stock_item`. Two sources of truth for
  stock is exactly the bug that ruins a fulfillment demo.
