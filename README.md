# DealFlow360

**An intelligent, self-governing sales operations platform.**

DealFlow360 takes a B2B deal from quotation to cash and enforces the rules along the way:
multi-tier discount governance with automatic approval routing, live upsell suggestions with
margin impact, multi-warehouse fulfillment splitting with backorders, hybrid billing (one-time
products and recurring subscriptions on one order), a real customer-facing negotiation portal,
and a deal health dashboard that flags stalled or anomalous deals before they die quietly.

---

## 1. What makes this more than a quote-to-invoice form

| Capability | The hard part we actually implement |
|---|---|
| Discount governance | A **blended risk score** across every line, checked against both tier ceilings and category ceilings, that decides whether a quote is auto-approved, needs a Sales Manager, or needs Manager → Finance |
| Upsell / cross-sell | Ranked suggestions from co-purchase pairings + promotions, filtered by a minimum-margin floor, showing the **margin delta** before you add |
| Fulfillment | A splitter that minimises **shipment count first, shipping cost second**, across live per-warehouse stock, with manual override and backorder consolidation |
| Hybrid billing | One order producing a one-time invoice **and** a recurring billing schedule, with day-accurate mid-cycle proration and automatic credit notes |
| Customer portal | A genuinely separate, token-scoped, restricted surface — not an internal screen with a different label |
| Deal health | Stalled-deal detection, per-rep discount anomaly detection, delivery-promise slippage, each with a nudge/escalate action |

---

## 2. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | **Next.js 16** (App Router, TypeScript, Tailwind) | All 18 screens from the mockup, one route each |
| Backend | **Django 5 + Django Ninja** | Typed schemas, auto OpenAPI at `/api/docs` |
| Database | **PostgreSQL (Supabase)** | Plain Postgres over the Supabase pooler; no Supabase client SDK |
| Auth | **Firebase Auth** (deferred) | Day 1 ships a mock provider with real role selection; Firebase drops in behind the same interface |
| Deploy | Vercel (frontend) + Render/Railway (backend) | Optional, only if time allows |

**Why the auth is deferred to the end:** every screen depends on "who am I and what role do I
have", and nothing depends on *how* that was proven. So day 1 ships a single `AuthProvider`
whose `login()` posts to our own `/auth/login` — real Django password hashing, a signed
expiring token, real role-based route guards. On the last hour, `login()` starts calling the
Firebase Web SDK and `resolve_token()` starts calling `verify_id_token()`. Two functions
change; no screen does.

Roles stay in Postgres, never in Firebase custom claims: Firebase proves *who you are*, our
database decides *what you may do*. That's what keeps the swap to two functions.

---

## 3. Repository layout

```
DealFlow/
├── README.md              ← you are here
├── IMPLEMENTATION.md      ← hour-by-hour plan + who owns what
├── WORKFLOW.md            ← end-to-end business workflow & state machines
├── DATABASE.md            ← full data model, every table and column
├── frontend/              ← Next.js app
│   └── src/
│       ├── app/           ← one folder per screen (App Router)
│       ├── components/    ← shared UI primitives + shell (SHARED — see ownership rules)
│       ├── lib/           ← api client, auth, formatting (SHARED)
│       └── types/         ← the frontend↔backend contract (SHARED)
└── backend/               ← Django + Ninja
    ├── config/            ← settings, root urls, api registry
    └── apps/
        ├── accounts/      ← users, roles, teams, customers
        ├── catalog/       ← products, variants, price lists, pairings
        ├── governance/    ← discount ceilings, approval rules, risk engine
        ├── quotations/    ← quotes, lines, audit events, upsell service
        ├── approvals/     ← approval requests & steps
        ├── fulfillment/   ← warehouses, stock, split planner
        ├── subscriptions/ ← recurring plans, subscriptions, proration
        ├── billing/       ← invoices, payments, credit notes
        ├── negotiation/   ← portal tokens, threads, counter-offers
        └── insights/      ← deal health alerts, reporting aggregates
```

---

## 4. Screen map (mockup number → route → owner)

| # | Screen | Frontend route | Backend app | Owner |
|---|---|---|---|---|
| 1 | Login / Signup | `/login` | accounts | **sinjeki** |
| 2 | Sales Dashboard | `/dashboard` | insights | **sinjeki** |
| 3 | Quotations List (Kanban) | `/quotations` | quotations | **the-steelix-flame** |
| 4 | Quotation Detail / Builder | `/quotations/[id]` | quotations | **the-steelix-flame** |
| 5 | Approvals List | `/approvals` | approvals | **the-steelix-flame** |
| 6 | Approval Detail | `/approvals/[id]` | approvals + governance | **the-steelix-flame** |
| 7 | Fulfillment & Stock List | `/fulfillment` | fulfillment | **anubhaw0raj** |
| 8 | Fulfillment Detail (split) | `/fulfillment/[id]` | fulfillment | **anubhaw0raj** |
| 9 | Subscriptions List | `/subscriptions` | subscriptions | **anubhaw0raj** |
| 10 | Billing Detail | `/subscriptions/[id]` | subscriptions + billing | **anubhaw0raj** |
| 11 | Customer Portal Negotiation | `/portal/quotations/[id]` | negotiation | **the-steelix-flame** |
| 12 | Invoices List | `/invoices` | billing | **anubhaw0raj** |
| 13 | Invoice Detail | `/invoices/[id]` | billing | **anubhaw0raj** |
| 14 | Deal Health Dashboard | `/deal-health` | insights | **anubhaw0raj** |
| 15 | Admin Reporting | `/reports` | insights | **sinjeki** |
| 16 | Product Catalog | `/products` | catalog | **sinjeki** |
| 17 | Product Detail & Pricelist | `/products/[id]` | catalog | **sinjeki** |
| 18 | Discount Tiers & Approval Chains | `/settings/discounts` | governance | **sinjeki** |

Shared, owned by **sinjeki**, changed only by PR-style agreement: `components/ui/*`,
`components/shell/*`, `lib/*`, `types/index.ts`, `config/*`, `apps/accounts/*`.

---

## 5. Getting started

### Prerequisites
- Node 20+ (we're on 22), Python 3.11+ (we're on 3.12)
- A Supabase project (free tier) → grab the Postgres connection string

> **This scaffold boots.** Migrations, seed data, the 28 unit tests, the full
> quotation→approval→confirm→split→invoice→payment chain, the portal
> counter-offer re-approval loop, and hybrid billing have all been run
> end-to-end on a clean database. Start from a working system, not a hopeful one.

**First thing, before anyone writes code:** `git init && git add -A && git commit -m "scaffold"`
and push it somewhere the three of you can pull from. Three people editing this
locally without a remote is the single most likely way to lose a morning.

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

copy .env.example .env          # then fill in DATABASE_URL from Supabase
python manage.py migrate
python manage.py seed_demo      # products, warehouses, tiers, customers, users
python manage.py runserver 8000
```

- API root: `http://localhost:8000/api/`
- Interactive docs: `http://localhost:8000/api/docs`
- Django admin: `http://localhost:8000/admin` (`admin@dealflow360.test` / `dealflow`)

**Fallback if Supabase is unreachable during the hack:** leave `DATABASE_URL` empty and the
settings module falls back to local SQLite. Everything except a couple of Postgres-specific
aggregates works identically.

### Frontend

```bash
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`. You land on `/login`.

### Demo logins (seeded)

| Email | Password | Role | Lands on |
|---|---|---|---|
| `rep@dealflow360.test` | `dealflow` | Sales Rep | `/dashboard` |
| `manager@dealflow360.test` | `dealflow` | Sales Manager | `/dashboard` |
| `finance@dealflow360.test` | `dealflow` | Finance / Ops | `/dashboard` |
| `admin@dealflow360.test` | `dealflow` | Admin | `/dashboard` |
| `buyer@acme.test` | `dealflow` | Customer | `/portal/quotations/...` |

---

## 6. The blended discount risk score (the centrepiece)

Every line is judged against **its own** ceiling, not one ceiling for the whole order.

```
allowed_i   = min( tier_ceiling(customer.tier), category_ceiling(line.category) )
excess_i    = max(0, discount_i − allowed_i)          # "points over" for this line
weight_i    = line_subtotal_i / order_subtotal        # value share of the order

worst       = max(excess_i)                            # the single worst offender
blended     = Σ (excess_i × weight_i)                  # value-weighted average excess
order_level = max(0, effective_order_discount − tier_ceiling)

score = 100 × ( 0.50·min(1, worst/10)
              + 0.30·min(1, blended/5)
              + 0.20·min(1, order_level/5) )
```

Routing (configurable in screen 18, stored in `approval_rule`):

| Condition | Band | Chain |
|---|---|---|
| `worst == 0 and order_level == 0` | **NONE** | auto-approved, still audit-logged |
| otherwise, `score < 60` | **MEDIUM** | Sales Manager |
| otherwise | **HIGH** | Sales Manager → Finance |

Two properties this gives us, both demoable:

1. **One bad line is enough.** A Gold customer at 18% on a Services line (ceiling 10%) is flagged
   even though 18% < the 15% Gold tier ceiling would suggest — because Services is stricter.
2. **Death by a thousand cuts is caught.** Five lines each 2–3 points over produce no dramatic
   `worst`, but the weighted `blended` term pushes the score into approval territory anyway.

Implementation lives in `backend/apps/governance/risk.py` as a pure function over line data —
no DB access — so it is unit-testable and reusable by the portal re-approval path.

---

## 7. Demo script (the eight-step verification from the brief)

1. Log in as `rep@`, confirm backend data exists (tier ceilings, 2 warehouses, a recurring plan).
2. New quotation for **Acme Corp** (Gold). Add *Laptop Pro 14* @ 12% and *Onsite Setup Service* @ 18%.
   → the Services line lights up `OVER (+8pt)` **live, on keystroke**, before submit.
3. Submit. It routes to Sales Manager automatically — the rep never asks for approval.
4. Accept the *Care Plan 2yr* upsell → cart total and the margin bar both move immediately.
5. Log in as `manager@`, approve, then confirm. Fulfillment suggests **Main Warehouse 22 +
   East Depot 2**, two shipments, $82.60 — because Main has only 22 of the 24 available
   (40 on hand less 18 already reserved) and no single warehouse can cover the order.
6. Order has both a one-time invoice (`INV-…` hardware + service) and a monthly schedule for the
   Care Plan — separate invoices, separate lifecycles, same order.
7. Open the portal as `buyer@acme.test`, counter at 20% → status flips to `UNDER_NEGOTIATION`
   and, on accept, the quote **re-enters approval automatically** at the new (higher) band.
8. Confirm, record a payment on the invoice → status `OPEN` → `PAID`, delivery reconciled.

Second flow, if time allows: mid-cycle quantity change on the Care Plan → prorated credit note.

---

## 8. What the scaffold already does, and what's left

Know exactly where the floor is before you start building on it.

### Working and verified end to end

| Area | State |
|---|---|
| Auth | Login/signup, real password hashing, signed tokens, role guards on every router |
| Risk engine | Complete, pure, **12 unit tests** covering both brief scenarios and the edge cases |
| Quotation services | Create, add/update/remove line, order discount, recalculate, submit, confirm, full audit trail |
| Approvals | Chain materialised from config, approve/reject/return, multi-step Manager→Finance |
| Split planner | Complete, pure, **6 unit tests**; single-warehouse, multi-warehouse, backorder |
| Proration | Complete, pure, **10 unit tests**; quantity, plan change, cancellation, month-end arithmetic |
| Hybrid billing | Confirmed: one order → separate one-time and recurring invoices with distinct periods |
| Portal | Token-scoped access, narrow serialiser, counter-offer → **automatic re-approval** |
| Deal health | Stalled + discount-anomaly detection, nudge/escalate, idempotent sweep |
| Frontend | All 18 routes build and render against live API data |

### Deliberately left as TODO (each marked in-code with the owner's name)

| What | Where | Owner |
|---|---|---|
| Manual override modal for the warehouse split | `fulfillment/[id]/page.tsx` — backend endpoint is done and tested | anubhaw0raj |
| Backorder consolidation button | same file — the `consolidation_available` flag already fires | anubhaw0raj |
| Product variant CRUD UI | `products/[id]/page.tsx` — variants are seeded and shown read-only | sinjeki |
| PDF / XLS export | `reports/page.tsx` — buttons are present and disabled | sinjeki |
| Firebase swap | `accounts/tokens.py::_resolve_firebase_token` + `lib/auth.tsx::login` | sinjeki |
| Rep-side negotiation inbox | backend routes exist at `/portal/internal/requests` | the-steelix-flame |
| Kanban drag-and-drop | `quotations/page.tsx` — clicking a card works today | the-steelix-flame |

Nothing in that second list blocks the demo script. They are all enhancements on top of a
chain that already runs.

---

## 9. Deliverables checklist

- [x] Working app (backend + frontend) with seed data
- [x] Architecture diagram — see `WORKFLOW.md §1` (module map) and `DATABASE.md §2` (ERD)
- [x] Business rules in application logic, not hardcoded per-demo
- [x] Customer portal as a real, separately-authorised, restricted surface
- [ ] 5-minute live demo covering two full flows (script above)
- [ ] "What we'd build next" — see `IMPLEMENTATION.md §7`

---

## 10. Team

| Person | Lane |
|---|---|
| **sinjeki** | App shell, auth & roles, product catalog, discount/approval configuration, reporting |
| **the-steelix-flame** | Quotation builder, risk engine, approvals, customer portal negotiation |
| **anubhaw0raj** | Fulfillment & warehouse split, subscriptions & proration, invoicing & payments, deal health |

Working agreement, integration order and the hour-by-hour plan are in **`IMPLEMENTATION.md`**.
