# DealFlow360 — System Workflow

How a deal moves through the platform, which rules fire where, and the exact algorithms behind
the four "hard" behaviours: risk scoring, warehouse splitting, proration, and anomaly detection.

---

## 1. Architecture at a glance

```
┌─────────────────────────────────────────────────────────────────────┐
│  Next.js 15 (App Router, TypeScript)                                │
│                                                                     │
│  /login   ── AuthProvider (mock today, Firebase later) ── role ──┐  │
│                                                                  │  │
│  (app) group — INTERNAL, requires role ∈ {ADMIN,REP,MGR,FIN}     │  │
│   /dashboard /quotations /approvals /fulfillment /subscriptions  │  │
│   /invoices /deal-health /reports /products /settings/discounts  │  │
│                                                                  │  │
│  /portal — EXTERNAL, requires a portal token scoped to ONE quote │  │
│   /portal/quotations/[id]                                        │  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │  fetch(), Bearer <token>
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Django Ninja API — /api/*                                          │
│                                                                     │
│  ROUTERS (thin: parse, authorise, delegate, serialise)              │
│   auth · catalog · governance · quotations · approvals ·            │
│   fulfillment · subscriptions · billing · portal · insights         │
│                                                                     │
│  SERVICES (all business rules live here, never in routers)          │
│   quotations/services.py   recalculate → risk → route → audit       │
│   governance/risk.py       ★ pure function, no DB                   │
│   fulfillment/planner.py   ★ pure function, no DB                   │
│   subscriptions/proration.py ★ pure function, no DB                 │
│   insights/health.py       stalled / anomaly / slippage sweep       │
│                                                                     │
│  MODELS (Django ORM)  ──────────────────────────────────────────┐   │
└─────────────────────────────────────────────────────────────────┼───┘
                                                                  ▼
                                                    PostgreSQL (Supabase)
```

**The one architectural rule:** routers never contain business logic, and the four starred modules
never touch the database. They take plain data in, return plain data out. That's what makes them
unit-testable in a hackathon where nobody has time for integration tests, and it's what lets the
portal re-approval path reuse the identical scoring code the builder uses.

---

## 2. End-to-end happy path

```
 ADMIN                REP                    MANAGER      FINANCE     CUSTOMER
   │                   │                        │            │            │
   │ configure         │                        │            │            │
   │ products, tiers,  │                        │            │            │
   │ ceilings, chains, │                        │            │            │
   │ warehouses, plans │                        │            │            │
   ├──────────────────►│                        │            │            │
   │                   │ create quotation       │            │            │
   │                   │ add lines, discounts   │            │            │
   │                   │                        │            │            │
   │              ┌────▼──────────────────┐     │            │            │
   │              │ ON EVERY LINE CHANGE: │     │            │            │
   │              │  recalculate totals   │     │            │            │
   │              │  resolve ceilings     │     │            │            │
   │              │  compute risk score   │     │            │            │
   │              │  refresh upsells      │     │            │            │
   │              │  emit audit event     │     │            │            │
   │              └────┬──────────────────┘     │            │            │
   │                   │ submit                 │            │            │
   │                   │                        │            │            │
   │         ┌─────────▼─────────┐              │            │            │
   │         │ band == NONE?     │──yes────────────────────┐ │            │
   │         │ (no line over,    │              │          │ │            │
   │         │  order within)    │              │          │ │            │
   │         └─────────┬─────────┘              │          │ │            │
   │                   │ no                     │          │ │            │
   │                   │ create approval_request│          │ │            │
   │                   │ materialise steps      │          │ │            │
   │                   ├───────────────────────►│          │ │            │
   │                   │              approve / reject /   │ │            │
   │                   │              return for revision  │ │            │
   │                   │                        │ HIGH?    │ │            │
   │                   │                        ├─────────►│ │            │
   │                   │                        │  approve │ │            │
   │                   │◄───────────────────────┴──────────┤ │            │
   │                   │                                   │ │            │
   │                   │            APPROVED ◄──────────────┴─┘            │
   │                   │                                                  │
   │                   │ send to customer (mints portal_token)            │
   │                   ├─────────────────────────────────────────────────►│
   │                   │                                                  │ views quote
   │                   │                                    counter 20%   │ comments
   │                   │◄─────────────────────────────────────────────────┤ submits
   │                   │ UNDER_NEGOTIATION                                │
   │                   │ rep accepts → discounts rewritten                │
   │                   │ → risk re-scored → NEW approval_request ─────────┼──► loop
   │                   │                                                  │
   │                   │                                     confirm ◄────┤
   │                   │                                                  │
   │              ┌────▼───────────────────────────────┐                  │
   │              │ ON CONFIRM:                        │                  │
   │              │  1. plan warehouse split (ONE_TIME)│                  │
   │              │  2. reserve stock                  │                  │
   │              │  3. create subscriptions (RECURRING)                  │
   │              │  4. issue one-time invoice         │                  │
   │              │  5. schedule first recurring invoice│                 │
   │              └────┬───────────────────────────────┘                  │
   │                   │                                                  │
   │            accept split / manual override → ship → record payment    │
   │                   │                                                  │
   │        ╔══════════▼══════════════════════════════════════════╗       │
   │        ║ THROUGHOUT: deal-health sweep flags stalled quotes,  ║       │
   │        ║ discount anomalies, delivery slippage → nudge/escalate║      │
   │        ╚═════════════════════════════════════════════════════╝       │
```

---

## 3. Quotation state machine

```
                    ┌─────────┐
                    │  DRAFT  │◄──────────────────┐
                    └────┬────┘                   │ return for revision
                         │ submit                 │
              ┌──────────▼──────────┐             │
       band?  │                     │             │
   NONE ──────┤  PENDING_APPROVAL   ├─────────────┘
     │        └──────────┬──────────┘
     │                   │ all steps approved      ┌──────────┐
     │                   │                    ┌───►│ REJECTED │ (terminal)
     ▼                   ▼                    │    └──────────┘
  ┌──────────┐      ┌──────────┐              │
  │ APPROVED │◄─────┤ APPROVED │──────────────┘
  └────┬─────┘      └──────────┘
       │ send to customer (mint portal token)
       ▼
  ┌──────────┐   customer submits request   ┌────────────────────┐
  │   SENT   ├─────────────────────────────►│ UNDER_NEGOTIATION  │
  └────┬─────┘                              └─────────┬──────────┘
       │                                              │ rep accepts counter
       │ customer confirms, terms unchanged           │
       │                                    ┌─────────▼──────────┐
       │                                    │ re-score risk      │
       │                                    │ band > NONE?       │
       │                                    └────┬──────────┬────┘
       │                                     yes │          │ no
       │                                         ▼          │
       │                              PENDING_APPROVAL      │
       │                                    (new request)   │
       ▼                                                    ▼
  ┌───────────┐
  │ CONFIRMED │  → fulfillment plan + subscriptions + invoices
  └───────────┘
```

Guards, enforced in `quotations/services.py::transition()`:

| From → To | Guard |
|---|---|
| `DRAFT` → `PENDING_APPROVAL` | ≥1 line, risk band ≠ `NONE` |
| `DRAFT` → `APPROVED` | ≥1 line, risk band == `NONE` (auto-approve, still audited) |
| `PENDING_APPROVAL` → `APPROVED` | every `approval_step` is `APPROVED` |
| `PENDING_APPROVAL` → `DRAFT` | a step was `RETURNED`; note is mandatory |
| `APPROVED` → `SENT` | portal token minted, customer has `contact_email` |
| `UNDER_NEGOTIATION` → `CONFIRMED` | re-scored band == `NONE`, else forced back to approval |
| `* ` → `CONFIRMED` | every line's product is active and priced |

**Anything not in that table raises `InvalidTransition`.** The state machine is a dict in one file,
not `if` statements sprinkled through views — which is the difference between "we implemented a
workflow" and "we implemented some buttons".

---

## 4. Algorithm: blended discount risk score

`backend/apps/governance/risk.py` — pure, no DB, fully unit-tested.

**Input** per line: `line_subtotal`, `discount_percent`, `category_ceiling`.
Plus `tier_ceiling`, `order_discount_percent`, and a `RiskConfig`.

```python
for each line i:
    allowed_i = min(tier_ceiling, category_ceiling_i)
    excess_i  = max(0, discount_i - allowed_i)          # "points over"
    weight_i  = line_subtotal_i / Σ line_subtotal

worst        = max(excess_i)                             # single worst offender
blended      = Σ (excess_i × weight_i)                   # value-weighted mean excess
effective    = (total_discount_value / gross_subtotal) × 100
order_level  = max(0, effective - tier_ceiling)

score = 100 × ( w_worst   × min(1, worst   / cap_worst)     # 0.50, cap 10
              + w_blended × min(1, blended / cap_blended)   # 0.30, cap  5
              + w_order   × min(1, order_level / cap_order) ) # 0.20, cap  5

requires_approval = (worst > 0) or (order_level > 0)
band = NONE                        if not requires_approval
     = MEDIUM                      if score <  high_band_threshold (60)
     = HIGH                        otherwise
```

The chain for a band is then read from `approval_rule` — `[]`, `["SALES_MANAGER"]`, or
`["SALES_MANAGER", "FINANCE"]`.

### Worked example — the brief's own scenario

Gold customer (tier ceiling 15%). Hardware ceiling 15%, Services ceiling 10%.

| Line | Subtotal | Given | Allowed | Excess | Weight |
|---|---|---|---|---|---|
| Laptop Pro 14 × 2 (Hardware) | $2,400 | 12% | min(15,15)=15 | **0** | 0.792 |
| Onsite Setup Service (Services) | $450 | 18% | min(15,10)=**10** | **8.0** | 0.148 |
| Extended Warranty (Hardware) | $180 | 10% | 15 | 0 | 0.059 |

```
worst       = 8.0
blended     = 0×0.792 + 8×0.148 + 0×0.059 = 1.19
discount $  = 288 + 81 + 18 = 387 ; gross = 3030 → effective = 12.77%
order_level = max(0, 12.77 − 15) = 0

score = 100 × (0.50×min(1, 8.0/10) + 0.30×min(1, 1.19/5) + 0.20×0)
      = 100 × (0.50×0.80 + 0.30×0.2376 + 0)
      = 100 × (0.400 + 0.0713) = 47.13  →  MEDIUM  →  Sales Manager
```

> Both worked examples in this section are asserted verbatim in
> `backend/apps/governance/tests.py`. If someone retunes the weights, those tests fail loudly
> instead of the demo drifting quietly.

Exactly the intended outcome: 18% "looks fine" for a Gold customer, but Services has a stricter
ceiling, one line is 8 points over, and the quote is flagged. Nobody had to ask.

### Worked example — death by a thousand cuts

Five equal $1,000 Hardware lines (ceiling 15%) at 17%, 18%, 17%, 18%, 17%:

```
excess     = 2, 3, 2, 3, 2   → worst = 3.0   (unremarkable on its own)
weights    = 0.2 each        → blended = 2.4
effective  = 17.4% vs 15%    → order_level = 2.4

score = 100 × (0.50×0.30 + 0.30×0.48 + 0.20×0.48) = 100 × (0.15+0.144+0.096) = 39.0 → MEDIUM
```

No single line looks alarming, and a naive "flag the worst line > 5 points" rule would let this
through. The blended and order-level terms catch it. **This is the case we demo second.**

---

## 5. Algorithm: multi-warehouse fulfillment split

`backend/apps/fulfillment/planner.py` — pure, no DB.

Objective, in strict priority order: **(1) fewest shipments, (2) lowest shipping cost,
(3) least backorder.** Fewer parcels beats marginally cheaper parcels — that's the real-world
preference and it's what `shipping_cost_weight` is for.

```
INPUT: demands  [(line_id, product, variant, qty)]
       stock    {(warehouse, product, variant): available}
       warehouses with shipping_cost_weight, base_shipment_cost

STEP 1 — Try single-warehouse fulfillment
  for each warehouse ordered by (shipping_cost_weight asc):
      if it can cover EVERY demand in full:
          return 1 shipment, cost = base × weight        ← optimal, done

STEP 2 — Greedy multi-warehouse
  remaining = demands
  chosen    = []
  while remaining and warehouses left:
      score each unused warehouse by:
          coverage = Σ min(available, remaining_qty) × unit_value   (desc)
          then shipping_cost_weight                                  (asc)
      pick the best, allocate everything it can cover
      subtract from remaining
  → allocations, shipments = len(chosen)

STEP 3 — Backorder
  anything still in `remaining` becomes an allocation with is_backorder = True,
  assigned to the warehouse with the earliest replenishment (else the cheapest).

STEP 4 — Cost
  estimated_cost = Σ over chosen warehouses of (base_shipment_cost × shipping_cost_weight)
```

Greedy is not provably optimal — bin-packing isn't — and that's a deliberate trade. It runs in
milliseconds, it always produces the single-warehouse answer when one exists (step 1 is exact),
and a rep can override it. Optimality here would be a research project that changes no demo outcome.

**Seeded demo case:** Laptop Pro 14 × 24. Main Warehouse has 22 available (40 on hand less 18
reserved), East Depot has 4 (10 less 6). No single warehouse covers 24, so step 1 finds nothing
and step 2 allocates Main 22 + East 2 — two shipments, `42×1.0 + 29×1.4 = $82.60`. Screen 8
renders exactly these rows with **Accept Suggested Split** / **Manual Override**.

**Manual override** posts explicit `(line, warehouse, qty)` allocations. The service validates
availability, then marks the plan `OVERRIDDEN` and writes an audit event naming the user. Overrides
are allowed; unrecorded overrides are not.

**Backorder consolidation:** a `RESTOCK` stock move fires `check_backorders(product, warehouse)`.
If an open `is_backorder` allocation can now be filled from the restocked warehouse, the plan gets a
`consolidation_available` flag and screen 8 surfaces the **"Consolidate Remaining Backorder"**
prompt. The prompt appears because stock arrived, not because someone refreshed.

---

## 6. Algorithm: subscription proration

`backend/apps/subscriptions/proration.py` — pure, no DB. Day-accurate.

```
period      = [current_period_start, current_period_end)
period_days = (end − start).days
elapsed     = (effective_date − start).days
remaining   = period_days − elapsed

QUANTITY CHANGE (old_qty → new_qty), proration_mode = DAILY:
    delta_units  = new_qty − old_qty
    amount       = delta_units × unit_price × (remaining / period_days)
    amount > 0  → PRORATION invoice, due immediately
    amount < 0  → credit_note for |amount|
    amount == 0 → event logged, no financial document

PLAN CHANGE (monthly → yearly):
    credit  unused remainder of the old plan   (remaining / period_days × old_price)
    charge  full new plan period from effective_date
    net     into a single PRORATION invoice or credit note

CANCELLATION:
    policy IMMEDIATE + refund PRORATED
        → credit_note = qty × unit_price × (remaining / period_days)
        → status CANCELLED, next_bill_date = NULL
    policy END_OF_PERIOD
        → status stays ACTIVE until current_period_end, no refund
        → cancellation_effective_date = current_period_end, next_bill_date = NULL

proration_mode = NONE        → amount always 0, change applies next period
proration_mode = FULL_PERIOD → charge/credit the whole period regardless of elapsed days
```

**Worked example.** Care Plan 2yr, monthly, $46/unit, period Sep 1 → Oct 1 (30 days).
On Sep 16 the customer goes 1 → 3 units.

```
remaining = 30 − 15 = 15
amount    = (3−1) × 46 × (15/30) = 2 × 46 × 0.5 = $46.00  → PRORATION invoice for $46.00
next regular invoice on Oct 1 = 3 × 46 = $138.00
```

Downgrade 3 → 1 on the same date gives `−$46.00` → a $46 credit note. Symmetric by construction,
because it's one formula with a signed result rather than two code paths.

**Renewal.** On `next_bill_date`, `renew()` rolls the window forward by the interval, issues a
`RECURRING` invoice for `quantity × unit_price` (in advance, per `bill_in_advance`), and writes a
`RENEWED` event. In the hackathon this is triggered from an endpoint and a management command
(`python manage.py run_billing --as-of 2026-10-01`) so the demo can time-travel; in production it's
a nightly Celery beat.

---

## 7. Algorithm: deal health & anomaly detection

`backend/apps/insights/health.py::run_sweep()`. Runs on dashboard load and after every quotation
write. Idempotent — it updates open alerts rather than creating duplicates.

```
STALLED
    for quotations in {DRAFT, PENDING_APPROVAL, SENT, UNDER_NEGOTIATION}:
        idle = today − last_activity_at
        if idle ≥ config.stalled_days_threshold (7):
            upsert alert STALLED, severity by idle (7→LOW, 14→MEDIUM, 21→HIGH)
            message "Idle {idle} days"

DISCOUNT ANOMALY
    per rep, trailing 90 days, over quotations with ≥1 line:
        avg = mean(effective_order_discount)      → cached in rep_discount_stat
        skip reps with < config.anomaly_min_quotes (3) quotes — one quote is not a pattern
    for each active quotation:
        if effective_discount > avg × config.anomaly_multiplier (2.0):
            upsert alert DISCOUNT_ANOMALY
            message "Discount {d}% vs avg {avg}%"

DELIVERY SLIPPAGE
    for open fulfillment_allocations with promised_date:
        if not shipped and today > promised_date + grace:
            upsert alert DELIVERY_SLIPPAGE on the parent quotation
            message "Promise date passed by {n} days"
```

Anomaly detection is **relative to the rep**, not absolute. A 22% discount from someone who
averages 8% is the signal; the same 22% from an enterprise rep who averages 20% is not. That
comparison is the whole reason `rep_discount_stat` exists.

**Actions.** From an alert: `NUDGE` writes an `alert_action` + a `quotation_event` (so it shows in
the deal's own history) and marks the alert `ACKNOWLEDGED`. `ESCALATE` additionally reassigns
visibility to the team manager. Both are auditable; neither silently mutates the deal.

---

## 8. Upsell / cross-sell ranking

Runs on every line change, feeding the panel beside the cart (screen 4).

```
candidates = product_pairing where source ∈ cart products, target ∉ cart products, is_active

for each candidate:
    unit_price = resolve_unit_price(product, customer.price_list)
    margin_pct = (unit_price − cost_price) / unit_price × 100
    DROP if margin_pct < upsell_config.min_margin_percent     ← never suggest a margin-killer

    score = co_purchase_score
          + (upsell_config.promoted_boost if product.is_promoted else 0)
          + 0.1 × (number of cart products that pair to it)   ← corroboration bonus

    margin_delta = (unit_price − cost_price) × default_qty     ← what screen 4 shows as "+$46"

return top 3 by score desc
```

Adding a suggestion goes through the **same** `add_line` service as any other product — so totals,
margin, ceilings and risk all recompute identically, and the margin indicator moves immediately.
There is no "upsell add" special case, which is precisely why the numbers can't drift.

Every impression, add and dismiss is written to `upsell_suggestion_log`, which is where screen 15's
"Top Upsold Product" tile comes from.

---

## 9. Authentication & authorisation

### Phase 1 (day 1) — mock, but with real roles

- `POST /api/auth/login` takes email + password, checks against the seeded Django user table
  (real `check_password`, not a string compare), returns `{ token, user }` where the token is a
  signed, short-lived opaque string.
- Frontend `AuthProvider` stores it in `localStorage`, exposes `{ user, role, login, logout }`.
- Route groups enforce role: `(app)/layout.tsx` bounces non-internal roles to `/portal`,
  `/portal/layout.tsx` bounces internal-only surfaces.
- Backend `require_role("SALES_MANAGER", "ADMIN")` is a Ninja dependency on every mutating route.

### Phase 2 (end of day) — Firebase, same interface

- Firebase Web SDK does email/password on the client, hands back an ID token.
- `AuthProvider` swaps its `login()` implementation; **nothing else in the frontend changes.**
- Backend adds `firebase_admin.auth.verify_id_token()` in the auth dependency, matches
  `firebase_uid` → local `user` row, and keeps reading `user.role` from Postgres.

**Roles stay in our database, never in Firebase custom claims.** Firebase proves *who you are*;
Postgres decides *what you may do*. That split is why the swap is a one-file change, and why an
approval chain can be reconfigured without touching an identity provider.

### The portal is genuinely separate

This is an explicit requirement in the brief, so it's worth being precise about what makes it real:

| | Internal workspace | Customer portal |
|---|---|---|
| Route group | `/(app)/*` | `/portal/*` |
| Layout & nav | Full 9-item top nav | 3 items: My Quotation, Messages, Profile |
| API namespace | `/api/quotations/*` | `/api/portal/*` — **different routers** |
| Authorisation | Session token + role check | Session token **+ `portal_token` scoped to one quotation** |
| Data exposed | Everything, incl. `cost_price`, margin, risk score, internal notes | Line description, qty, price, discount, status. **Never cost, margin, risk, or approval history.** |
| Serialiser | `QuotationDetailOut` | `PortalQuotationOut` — a separate, narrower schema |

A customer holding a valid session but no token for quotation X gets a 404 on X — not a 403,
because the existence of another customer's quote isn't theirs to learn either. The narrow
serialiser is the real defence: margin data has no code path that reaches the portal.

---

## 10. Frontend data flow

```
Server Component (page.tsx)
  └─ initial fetch via lib/api.ts server helper → renders immediately, no spinner
       └─ Client Component (the interactive bits: cart, discount inputs, approval buttons)
            └─ mutate via lib/api.ts client helper
                 └─ on success: router.refresh()   ← re-runs the server component
```

No Redux, no React Query, no client cache. The quotation builder is the only screen with real
local state (the cart being edited), and it holds a single `QuotationDetail` object returned by
the API after each mutation.

**The rule that keeps the demo honest:** every mutation returns the **full recomputed quotation**,
including totals, margin, per-line `allowed_discount_percent` / `discount_excess_points`, risk score
and band. The frontend never computes money or risk — it renders what the backend decided. That's
how the `OVER (+8pt)` badge and the margin bar stay in sync with what the approval screen will
later say, and it's why "discount is checked live, as soon as it is entered" (screen 4's own note)
costs us nothing extra.

---

## 11. Error handling contract

| HTTP | When | Body |
|---|---|---|
| 400 | Validation failed | `{ "detail": "...", "field_errors": { "discount_percent": "..." } }` |
| 401 | Missing/expired token | `{ "detail": "Not authenticated" }` |
| 403 | Authenticated, wrong role | `{ "detail": "Requires role SALES_MANAGER" }` |
| 404 | Not found **or not yours** | `{ "detail": "Not found" }` |
| 409 | Illegal state transition | `{ "detail": "Cannot confirm a quotation pending approval", "current_status": "PENDING_APPROVAL" }` |
| 422 | Business rule violation | `{ "detail": "Insufficient stock", "context": { ... } }` |

409 is the one worth building deliberately: it's how the UI knows to refresh rather than retry,
and it's what happens when two people act on the same approval at once.
