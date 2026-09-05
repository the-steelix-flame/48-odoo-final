# DealFlow360 — Implementation Plan

Three people, one day, no merge conflicts. This document is the contract between us.

---

## 1. The split

Lanes are drawn so that **each person owns a vertical slice** — their screens, their API routers,
their models, their services. Nobody waits on anybody after hour 2.

| | **sinjeki** | **the-steelix-flame** | **anubhaw0raj** |
|---|---|---|---|
| **Theme** | Platform & configuration | The deal engine | Operations & money |
| **Screens** | 1 Login · 2 Dashboard · 15 Reports · 16 Products · 17 Product Detail · 18 Discount Config | 3 Quotations · 4 Builder · 5 Approvals · 6 Approval Detail · 11 Customer Portal | 7 Fulfillment · 8 Split Detail · 9 Subscriptions · 10 Billing Detail · 12 Invoices · 13 Invoice Detail · 14 Deal Health |
| **Django apps** | `accounts` `catalog` `governance` | `quotations` `approvals` `negotiation` | `fulfillment` `subscriptions` `billing` `insights` |
| **Key algorithm** | price list resolution | **blended risk score** | **warehouse split + proration** |
| **Also owns** | app shell, `lib/*`, `types/*`, `components/ui/*`, seed data | upsell ranking | deal-health sweep |

### Why this split and not "one does frontend, one does backend"

Splitting by layer means every feature needs two people to finish and nobody can demo anything
alone. Splitting vertically means at hour 6 we have three independently working slices, and if one
person falls behind we lose *one screen*, not *all the backends*. It also matches the brief's
grading: business logic is the score, and each lane owns a marquee algorithm.

---

## 2. Ownership rules (how we avoid conflicts)

**Shared files — sinjeki owns them. Everyone else: ask before editing, or add, never restructure.**

```
frontend/src/types/index.ts          ← the API contract. Additive changes only.
frontend/src/lib/api.ts              ← fetch wrapper, auth header, error mapping
frontend/src/lib/auth.tsx            ← AuthProvider + useAuth
frontend/src/components/ui/*         ← Button, Card, Table, Badge, Field, StatCard
frontend/src/components/shell/*      ← TopNav, PageHeader
frontend/src/app/(app)/layout.tsx    ← internal shell + role guard
backend/config/*                     ← settings, urls, api.py router registry
backend/apps/accounts/*              ← User, Customer, auth dependency
```

**Everything else is single-owner.** Your screens live in your own folders, your routers in your
own app. If you need a shared component that doesn't exist, build it inside your own folder first
and tell sinjeki to promote it later — don't block.

**Adding a router** is the only edit to `config/api.py`, and it's one line. Do it in your first
commit so the file settles early:

```python
api.add_router("/quotations/", quotations_router, tags=["quotations"])
```

**Commit discipline:** small commits, push every 45 minutes, never push a broken `main`. If you must
break something shared, say so in chat *before* pushing, not after.

---

## 3. Hour-by-hour

Assumes a ~12-hour hackathon starting at H0. Adjust proportionally.

### H0 – H1 · Everyone: setup (do this together, out loud)

- [ ] Clone, `npm install`, `pip install -r requirements.txt`
- [ ] One person creates the Supabase project, shares `DATABASE_URL` in chat
- [ ] `python manage.py migrate` succeeds for all three
- [ ] `npm run dev` renders `/login` for all three
- [ ] Agree on the enum values in `types/index.ts` **now** — renaming `PENDING_APPROVAL` at H8 costs an hour

### H1 – H3 · Foundations (sequential-ish, then it opens up)

| Who | Task | Unblocks |
|---|---|---|
| **sinjeki** | `accounts` models + `/api/auth/login` + `AuthProvider` + TopNav + `(app)` guard | **everyone** — do this first, ruthlessly |
| **sinjeki** | `catalog` + `governance` models, `seed_demo` v1 (products, categories, ceilings, customers) | steelix's risk engine, anubhaw's stock |
| **the-steelix-flame** | `quotations` models + `governance/risk.py` **as a pure function with tests** | your own H3+ |
| **anubhaw0raj** | `fulfillment` + `subscriptions` + `billing` models, `planner.py` + `proration.py` pure functions | your own H3+ |

> **Critical path is `seed_demo`.** Until there are products and customers in the DB, the other two
> are writing against imagination. sinjeki ships a rough seed by H2 even if it's ugly; polish later.

### H3 – H6 · Core build, fully parallel

**sinjeki**
- [ ] Screen 16 Products list + Screen 17 Product detail (general info, variants, price lists)
- [ ] Screen 18 Discount tiers / category ceilings / approval chain config — **must be editable**, it's what proves the rules are data
- [ ] `catalog/pricing.py::resolve_unit_price()`

**the-steelix-flame**
- [ ] `quotations/services.py`: `recalculate()` → totals, margin, per-line allowed/excess, risk score, band
- [ ] `POST/PATCH/DELETE /api/quotations/{id}/lines` — each returns the **full recomputed quotation**
- [ ] Screen 3 Kanban list, Screen 4 Builder with live `OVER (+Npt)` badges and margin bar

**anubhaw0raj**
- [ ] `fulfillment/planner.py` wired to real stock; `POST /api/fulfillment/{quote}/plan`
- [ ] Screen 7 stock + orders-awaiting list, Screen 8 split detail with Accept / Manual Override
- [ ] `subscriptions` create-from-quotation + `billing` invoice generation

### H6 – H8 · The flows that cross lanes (this is where it gets real)

- [ ] **steelix**: submit → `approval_request` + steps materialised from `approval_rule`; Screens 5, 6 with approve / reject / return + audit trail
- [ ] **anubhaw**: confirm → plan split + reserve stock + create subscriptions + issue invoices; Screens 12, 13 with Record Payment
- [ ] **sinjeki**: Screen 2 Dashboard (real counts, not placeholders) + Screen 15 Reports with the four filters

**Integration checkpoint at H8 — everyone stops and we run this together:**

```
login as rep → create quote → add over-limit line → submit
  → login as manager → approve → confirm → see split → see invoice
```

If that chain runs end to end, we have a demo. If it doesn't, **the rest of the plan is cancelled**
until it does. Everything after this point is enhancement.

### H8 – H10 · Differentiators

- [ ] **steelix**: Screen 11 Customer Portal — separate layout, `portal_token`, narrow serialiser, counter-offer → **automatic re-approval**
- [ ] **steelix**: upsell panel with margin delta + promotion tags
- [ ] **anubhaw**: Screen 14 Deal Health — stalled / anomaly / slippage + Nudge & Escalate; proration on quantity change → credit note
- [ ] **sinjeki**: Firebase swap behind `AuthProvider`; export PDF/XLS on Reports

### H10 – H11 · Polish & hardening

- [ ] Re-run `seed_demo` on a **clean database** and walk all 8 verification steps
- [ ] Empty states and error toasts on every screen (a crash mid-demo costs more than a missing feature)
- [ ] Loading states on the builder (it's the screen judges will click fastest)
- [ ] README demo credentials verified by someone who didn't write them

### H11 – H12 · Demo prep

- [ ] Rehearse the 5-minute script **twice, timed**, on the actual demo machine
- [ ] Pre-seed a browser with two logged-in profiles (rep + manager) so role switching isn't 30 seconds of typing
- [ ] Screenshot fallbacks for every screen, in case the network dies
- [ ] Architecture diagram exported to a single page

---

## 4. What to cut, in order, when time runs out

Decide this **now**, cold, not at H10 when everyone's attached to their own work:

1. Export to PDF/XLS (screen 15) — a button that downloads a CSV is fine
2. Product variants UI (screen 17 middle panel) — seed them, show read-only
3. Firebase — the mock auth is a legitimate architectural choice; say so
4. Multi-currency — explicitly a bonus in the brief
5. Delivery slippage alerts — keep stalled + discount anomaly, they're the two that demo well
6. Plan-change proration — keep quantity-change proration, it's the same formula
7. Kanban drag-and-drop (screen 3) — clicking a card is enough

**Never cut, no matter what** — these are the graded core:

- Blended risk score → automatic approval routing
- Two-warehouse split with backorder
- One-time + recurring on the same order producing separate invoices
- Customer portal counter-offer → automatic re-approval
- The audit trail

---

## 5. Definition of done (per screen)

A screen is done when **all five** are true. "It renders" is not done.

1. It reads **real data from the API** — no hardcoded arrays, no mock JSON files
2. Its mutations persist and survive a refresh
3. It handles empty state (no quotations yet) and error state (API down) without a white screen
4. The business rule it demonstrates is in a **service or pure function**, not in the component
5. Someone who didn't build it can drive it from the README without asking questions

---

## 6. Risks and what we do about them

| Risk | Likelihood | Mitigation |
|---|---|---|
| Supabase connection flaky / pooler limits | Medium | `DATABASE_URL` empty → SQLite fallback already in `settings.py`. Test it **at H1**, not at H11. |
| Everyone edits `types/index.ts` at once | High | sinjeki owns it; additive changes only; announce in chat |
| Risk engine and approval UI disagree on shape | Medium | The engine returns a `RiskBreakdown` dataclass serialised straight to the API — screen 6 renders that object, no reshaping |
| Confirm flow (quote→split→invoice) not integrated until late | **High** | The H8 checkpoint exists exactly for this. It is non-negotiable. |
| Firebase eats two hours | Medium | It's cut #3. Mock auth is architecturally defensible and we say so in the demo. |
| Demo machine has no seeded data | Low but fatal | `seed_demo` is idempotent; run it as the first step of rehearsal |
| One person blocks on another's model | Medium | Pure functions (`risk.py`, `planner.py`, `proration.py`) take plain dicts — write and test them before the models exist |

---

## 7. What we'd build next with more time

The brief asks for this explicitly. Honest answers, in priority order:

1. **Celery + Redis for scheduled work.** Billing renewal, the deal-health sweep and backorder
   consolidation all run in-request today. They're naturally periodic jobs and belong on a beat
   schedule; the sweep is already written as an idempotent function, so this is wiring, not a rewrite.
2. **Optimistic locking on quotations.** A `version` column with a compare-and-swap on write. Two
   approvers acting simultaneously currently race; we return 409 on illegal transitions but don't
   detect concurrent edits to the same valid state.
3. **Real notifications.** Email/Slack on approval requests, nudges and portal counter-offers.
   The events all exist in `quotation_event`; there's just no transport.
4. **A proper pricing engine with time-bounded rules.** Price lists today have no validity window
   and no volume breaks. Real B2B pricing needs both.
5. **Learned upsell ranking.** Pairings are seeded co-purchase scores. With real order history this
   becomes a market-basket model, and `upsell_suggestion_log` is already collecting the training data.
6. **Multi-currency and multi-company.** FX rates on quotations, company-scoped querysets. Called
   out as a bonus in the brief; the schema was designed not to fight it (currency already lives on
   customer, price list and invoice).
7. **Approval delegation and SLAs.** Out-of-office reassignment, escalation when a step sits
   untouched past its SLA. `approval_step` already has the assignee and timestamps needed.
8. **Test coverage beyond the pure functions.** The four algorithms are unit-tested; the service
   layer and API are not. First target would be the state machine's guard table.

---

## 8. Working agreements

- **Push every 45 minutes.** Long-lived branches are how three people discover at H9 that they built
  three different `Quotation` shapes.
- **Ask in chat before editing someone else's app.** Ten seconds of asking beats forty minutes of
  untangling.
- **If you're stuck for 20 minutes, say so.** There are three of us; someone has probably solved it.
- **Backend first, then the screen.** A screen against a working endpoint takes 30 minutes. A screen
  against an imagined endpoint takes 30 minutes and then gets rewritten.
- **Demo data is a feature.** If a screen looks empty in the demo, it reads as broken regardless of
  how good the code is. Seed generously.
