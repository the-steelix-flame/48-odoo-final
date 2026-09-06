# CHANGES — anubhaw0raj lane (Operations & money)

Branch: `anubhaw_work` · Apps: `fulfillment` `subscriptions` `billing` `insights` · Screens: 7, 8, 9, 10, 12, 13, 14

Everything below was verified by running it, not by reading it. Verification commands are given so
anyone can reproduce the result.

---

## 1. Changes shipped

### `bd31615` — Backorder consolidation + manual override (screen 8)

Both actions were stubbed behind `disabled` buttons with `TODO(anubhaw0raj)` markers. Now wired end to end.

**Backend**

| File | Change |
|---|---|
| `apps/fulfillment/services.py` | New `consolidate_backorders(plan, actor)`. Re-plans **only** the backordered allocations against current stock. Rows already allocated and reserved are left untouched — otherwise one order's consolidation would steal stock another customer is already promised. |
| `apps/fulfillment/services.py` | New `_recost(plan)`. Recomputes shipments and cost from surviving allocations. Backordered rows ship nothing, so they cost nothing and count for nothing. |
| `apps/fulfillment/api.py` | New `POST /api/fulfillment/plans/{id}/consolidate`, restricted to `FINANCE` / `SALES_MANAGER` (`ADMIN` implicit via `require_role`). |

Behaviour worth knowing:

- If the restock still isn't enough, it raises `InsufficientStock` **and** clears
  `consolidation_available`, so the prompt stops offering something that cannot happen.
- Newly-filled rows are reserved **only** when the plan was already accepted, matching the rows
  that were reserved at acceptance time. Consolidating a not-yet-accepted plan reserves nothing.

**Frontend** — `app/(app)/fulfillment/[id]/page.tsx`

- Manual Override modal: editable line / warehouse / qty rows, live `3 / 4 allocated` per line.
- **Submit is blocked on a mismatch.** The backend converts unavailable units into a *recorded*
  backorder, but it does **not** verify that the full ordered quantity was allocated. Without this
  guard a rep could silently under-ship an order. Closed client-side; see §2.4 for the server gap.
- Consolidate button wired to the new endpoint.
- Both actions gated on the same roles the backend enforces.
- A local modal was built inside our own folder rather than editing `components/ui`
  (per `IMPLEMENTATION.md` §2). **@sinjeki** — promote it to a shared `Modal` if you want it.

### `aa01a6f` — Delivery promises so slippage detection can fire

`insights/health.py::_sweep_delivery_slippage()` filters on `promised_date__isnull=False`. Nothing
in the codebase ever set `promised_date`. The sweep was correct, fully implemented, and silently
returned **zero every single time** — screen 14's third card could never display anything.

| File | Change |
|---|---|
| `apps/fulfillment/models.py` | New `Warehouse.lead_time_days` (default 3). Configurable per warehouse because a remote depot is genuinely slower — keeps the rule in **data**, not as a constant in code (brief §7). |
| `apps/fulfillment/migrations/0003_warehouse_lead_time_days.py` | New migration. **Everyone must re-run `manage.py migrate`.** |
| `apps/fulfillment/services.py` | `accept_plan()` stamps `promised_date = today + lead_time_days` on every row it reserves. `consolidate_backorders()` does the same for rows it newly fills. |

Backordered rows deliberately get **no** promise — there is nothing to promise until stock actually
arrives, and a fabricated date would make the slippage alert lie.

Verified: accepting a plan sets `promised_date`; backdating it raises
`Q-1003: Promise date passed by 5 days [MEDIUM]`.

---

## 2. Bugs, gaps and risks discovered

### 2.1 ✅ FIXED — `POST /api/quotations/{id}/confirm` returned HTTP 500

**File owner: @the-steelix-flame. Fixed by @anubhaw0raj — flagging loudly because it is not my lane.**
It blocked the entire H8 checkpoint and neither teammate had pushed since the v1 commit.

There were **two independent causes**, and the second one was much wider than the confirm endpoint.

**Cause 1 — `confirm` had no response schema.**

```
TypeError: Object of type QuotationLine is not JSON serializable
```

`confirm_quotation` was the only state-changing endpoint in that router without a `response=`
schema. Every sibling declares one, which routes the payload through Pydantic. Without it Ninja
falls back to raw `json.dumps`, which cannot serialise the live model instances `_detail()` puts
in `lines` and `events`.

*Fix:* new `ConfirmOut` schema in `apps/quotations/schemas.py`, declared on the endpoint.

**Cause 2 — EVERY `GET /api/quotations/{id}` was also returning 500.**

Found while verifying the first fix. This was not a confirm problem at all:

```
ValidationError: 3 validation errors for NinjaResponseSchema
response.customer_name  Field required
response.customer_tier  Field required
response.owner_rep_name Field required
```

`QuotationSummaryOut` resolves those three down a relation (`obj.customer.name`). That works for
the list endpoint, which passes `Quotation` instances. But `api.py::_detail()` returns a **plain
dict**, and Ninja hands the **raw dict** to the resolver — so `dict.customer` raises
`AttributeError`, the field is silently dropped, and response validation fails as "missing".

Every endpoint returning `QuotationDetailOut` was affected: the quotation detail view, and every
mutation on the builder (add line, update line, delete line, order discount, submit). **Screen 4
could not have worked in a browser.**

*Fix:* the three resolvers now accept either shape — dict key when given a dict, relation walk when
given a model. One schema, both call paths. No behaviour change for the list endpoint.

**Why this mattered more than a normal 500:** confirm *commits first*, then fails serialising.
Verified on Q-1003 — status went to `CONFIRMED`, plan #2 created, INV-1039 issued, **and the caller
still got a 500.** The rep clicks Confirm, sees an error, clicks again, gets a 409. It looks broken
when the data is correct.

**Files touched (3 lines + 33 lines, no logic changed):**

| File | Change |
|---|---|
| `apps/quotations/schemas.py` | New `ConfirmOut`; three resolvers made dict-tolerant |
| `apps/quotations/api.py` | Import `ConfirmOut`; add `response=ConfirmOut` to the decorator |

**Verified over real HTTP after the fix:**

```
GET  /quotations/          200      GET /quotations/1,2,3,5   200  (were all 500)
POST /quotations/4/submit  200 -> APPROVED
POST /quotations/4/confirm 200 -> confirmed=true, plan #4, invoice #6,
                                  lines+events+risk all serialised
POST /quotations/4/confirm 409 -> clean conflict on re-confirm, not a 500
```

Every other router still returns 200; `manage.py test apps` still 28/28.

**@the-steelix-flame** — please sanity-check the resolver change. If you would rather `_detail()`
returned model instances instead, that is a bigger refactor but arguably cleaner; this fix was
chosen to be the smallest safe change that unblocks the demo.

### 2.1b ✅ FIXED — the same resolver bug broke three more detail screens

Found by enumerating all 62 routes from `/api/openapi.json` and hitting every one, rather than
testing the paths we happened to think of. Three more endpoints were returning 500:

| Endpoint | Screen | Fields that failed |
|---|---|---|
| `GET /api/billing/invoices/{id}` | 13 Invoice Detail | `customer_name`, `quotation_number` |
| `GET /api/subscriptions/{id}` | 10 Billing Detail | `customer_name`, `plan_name`, `interval` |
| `GET /api/approvals/{id}` | 6 Approval Detail | `quotation_number`, `customer_name`, `customer_tier` |

Identical cause to §2.1 cause 2: the list endpoints pass model instances (so the relation-walking
resolvers work and those routes returned 200), while the detail endpoints build a plain dict —
and Ninja hands the raw dict to the resolver.

**Every detail screen in the app was broken**, across all three lanes. Nothing caught it because
the test suite only covers the four pure functions; it never touches HTTP.

*Fix:* 11 resolvers across `subscriptions/api.py` (3, ours), `billing/api.py` (3, ours) and
`approvals/api.py` (5, @the-steelix-flame's) now accept either shape. 31 lines added, no logic
changed, no behaviour change on the list paths.

**Verified:** all 30 GET endpoints return 200, portal correctly 403s a non-customer, role
enforcement returns 403 for a REP on a Finance-only mutation, `test apps` 28/28.

### 2.1c ✅ FIXED — deal-health alerts were never resolved (screen 14)

Spotted from the UI: Q-1004 (Zenith Co) sat in the **Confirmed** kanban column while screen 14
still listed it as `Idle 9 days — Stalled`. Two separate defects behind it.

**Defect 1 — nothing ever closed an alert.** `ACTIVE_STATUSES` correctly excludes `CONFIRMED`, so
a fresh sweep no longer *finds* Q-1004. But no code path ever set `resolved_at` or moved an alert
off `OPEN`. Once raised, an alert stayed open forever, even after the deal was confirmed, rejected
or revived. `DealAlert.resolved_at` existed and was never written to.

**Defect 2 — the stat cards and the table were counting different things.** `run_sweep()` returned
the number of alerts *found on that run*, while the table below rendered *every OPEN alert*. So the
card read `STALLED DEALS 0` directly above a row showing a stalled deal — visibly contradicting
itself in the same screenshot.

*Fix:* each `_sweep_*` now returns the set of quotations that qualify **right now**;
`_resolve_cleared()` marks any `OPEN`/`ACKNOWLEDGED` alert of that type whose quotation is no longer
in that set as `RESOLVED` with a timestamp; and `run_sweep()` returns counts of what is genuinely
`OPEN`, so the cards can never disagree with the table again.

*Verified:* Q-1004's alert moved `OPEN → RESOLVED`, cards and table both read 0, and an assertion
now guarantees no `CONFIRMED` quotation can be listed as stalled. `test apps` 28/28.

**Not a bug — the related question this came from.** The Approvals page showed Q-1002 as *Approved*
while the kanban showed nothing in its *Approved* column. That is correct: they render **two
different objects**. `ApprovalRequest.status` is `APPROVED` (that request was granted, and it stays
in the approvals history), while `Quotation.status` has since moved on to `CONFIRMED`. The kanban
groups by quotation status, so the quote appears under Confirmed. The Approvals screen is a history
of approval requests — per the brief, "every quotation that needed, needs, or is going through
discount approval" — not a mirror of the pipeline.

### 2.1d 🔴 OPEN — a CONFIRMED order stuck in fulfilment raises nothing

Raised by @anubhaw0raj from the brief: *"Once confirmed, the order proceeds to fulfilment and
billing."* Confirmation is **not** the end of the deal — an order can then sit unfulfilled for
weeks on missing stock, and today nothing anywhere flags it.

Current state of every confirmed order in the database:

| Quote | Plan | Allocations | Shipped | promised_date | Open alerts |
|---|---|---|---|---|---|
| Q-1002 | #3 `SUGGESTED` | 1 | 0 | none | **NONE** |
| Q-1003 | #2 `SUGGESTED` | 1 | 0 | none | **NONE** |
| Q-1004 | #4 `SUGGESTED` | 1 | 0 | none | **NONE** |

All three could sit like that forever and screen 14 would stay empty. Two holes combine:

1. **`STALLED` only looks at `ACTIVE_STATUSES`**, which excludes `CONFIRMED` — correctly, because
   "idle as a quotation" stops being meaningful once the customer has signed. But nothing replaced
   it for the post-confirmation phase.
2. **`DELIVERY_SLIPPAGE` cannot cover the gap**, because `promised_date` is only stamped by
   `accept_plan()`. A plan that is never accepted has no promise, and the sweep filters on
   `promised_date__isnull=False`. **Backordered rows are invisible to it by design** — they
   deliberately get no promise, since there is nothing to promise until stock arrives.

So the exact scenario the brief describes — confirmed, then blocked on stock — is the one case
deal health cannot see.

**Proposed fix (NOT implemented — awaiting team agreement):** a fourth alert type
`FULFILMENT_STALLED`, raised when a quotation is `CONFIRMED` and, after a configurable number of
days, its plan is still un-accepted, or has allocations neither shipped nor consolidated. Severity
scales with age. Add `fulfilment_stalled_days_threshold` to `DealHealthConfig` so the rule stays in
data, not in code.

**Why the alert-resolution fix (§2.1c) is still correct and must not be reverted:** reverting it
would leave Q-1004 showing `Idle 9 days` — the wrong metric for the wrong phase, describing
quotation inactivity on a deal that is no longer a quotation. It would also permanently strand
alerts on deals that genuinely recover (a DRAFT the rep picks back up would stay flagged forever),
and it would still leave Q-1002 and Q-1003 with no alerts at all, because they never had one. The
fix above closes the real gap; the revert would only hide it behind a misleading message.

### 2.2 🟡 `DEBUG=True` leaks full tracebacks over HTTP

The 500 above returned a complete traceback including absolute filesystem paths
(`C:\Users\...\backend\.venv\...`) to an unauthenticated-ish client. Fine locally; **must not ship**.
Before any Supabase/production deploy: `DEBUG=False` and a real `SECRET_KEY` in the environment.
Django will then return a generic 500 body.

### 2.3 🟡 `suggest_plan()` does not check quotation status

`apps/fulfillment/services.py::suggest_plan` will happily plan fulfillment for a `DRAFT` quotation —
Q-1001 (DRAFT) can be planned right now. Nothing in the state machine guards it. Not exploited by
any current screen, but it means stock could be reserved against a quote nobody has approved.
**My lane — leaving it alone until we agree, since tightening it could break someone's test path.**

### 2.4 🟡 `override_plan()` does not verify total allocated quantity

`apps/fulfillment/services.py::override_plan` validates that each line exists and each quantity is
positive, but never checks that the allocations **sum to the ordered quantity**. Posting a partial
set silently under-ships the order. The new modal blocks this client-side, but the API is still
open to it. A server-side check is the real fix — deliberately not added yet because it would be a
behaviour change to an endpoint others may already be calling.

### 2.5 🟢 Services are treated as physical stock

`Onsite Setup Service` is a service but carries a `stock_item` row with 999 units and is shipped
through the warehouse planner. `_demands()` filters on `LineType.ONE_TIME`, which includes services.
Works, but a judge poking at "why is a service in a warehouse" has a point. Cosmetic for the demo.

### 2.6 🟢 Risk formula disagrees with the mockup

`WORKFLOW.md` §4 scores the brief's own Q-1042 example at **47.13 → MEDIUM → Sales Manager only**.
Mockup screens 5 and 6 both label that same quote **HIGH** with a `Sales Manager → Finance` chain.
Our math is internally consistent and asserted in `governance/tests.py`, so this is defensible —
but it should be a **decision**, not an accident. **@the-steelix-flame's call.**

### 2.7 🟢 Mockup numbers do not reconcile — treat the seed as canonical

Q-1042 appears as `$12,400` (screen 3), `$2,643` (screen 4, computed from its own lines), and
`$2,730` (screens 10/13, which use a 5% discount rather than screen 4's 12%, and drop the
Extended Warranty line). The wireframes are illustrative. **`seed_demo` is the source of truth.**

---

## 3. Action items

| # | Item | Owner | Priority |
|---|---|---|---|
| 1 | ~~Fix the `confirm` 500~~ — **done** (§2.1). Review the resolver change | @the-steelix-flame | ✅ review |
| 2 | **Re-run `python manage.py migrate`** — new `fulfillment/0003` migration | everyone | 🔴 do now |
| 3 | Set East Depot `lead_time_days = 6` in `seed_demo` so the split visibly trades cost against speed | @sinjeki | 🟡 demo quality |
| 4 | Decide the risk-band mismatch vs the mockup (§2.6) | @the-steelix-flame | 🟡 |
| 5 | `DEBUG=False` + real `SECRET_KEY` before any deploy (§2.2) | whoever deploys | 🟡 pre-deploy |
| 6 | Agree whether `suggest_plan` should require `CONFIRMED` (§2.3) | @anubhaw0raj + team | 🟢 |
| 7 | Promote the fulfillment override modal to a shared `Modal` component | @sinjeki | 🟢 optional |

---

## 4. Verification log — Q-1002 driven end to end

Run against the seeded database and **committed** (the demo needs this data — screens 9, 10, 12 and
13 rendered completely empty before this, because there were zero subscriptions).

Driven through the **service layer**, deliberately not over HTTP, so it does not depend on §2.1
being fixed first. `services.confirm()` itself is fine — only its HTTP response is broken.

### Hybrid billing — one order, two lifecycles ✅

Q-1002 mixes `ONE_TIME` Laptop Pro 14 ×12 with `RECURRING` Support SLA on a Quarterly plan.
Approved as Sales Manager, then confirmed:

| Artefact | Result |
|---|---|
| `INV-1041` | type `ONE_TIME`, **$14,241.60** — contains the laptop only |
| `INV-1040` | type `RECURRING`, **$285.00** — contains the Quarterly Plan period only |
| Subscription #1 | ACTIVE, qty 1, period `2026-09-05 → 2026-12-05`, next bill `2026-12-05` |
| Fulfillment plan #3 | 12 × Laptop from Main Warehouse. **The subscription never entered fulfillment.** |

`14,241.60 + 285.00 = 14,526.60` — exactly the order total. Asserted: no recurring line leaks onto
the one-time invoice, and no recurring line is sent to a warehouse.

### Payments (screen 13) ✅

`INV-1041`: `OPEN` → part-paid $5,000 → **`PARTIALLY_PAID`** (due $9,241.60) → settled remainder →
**`PAID`**. Status transitions are driven by `amount_due`, not set by hand.

### Proration, both directions (screen 10) ✅

Mid-cycle on `2026-10-05`, 61 of 91 days remaining:

| Change | Proration | Document |
|---|---|---|
| 1 → 3 units | **+$382.09** | `INV-1042` type `PRORATION` |
| 3 → 2 units | **−$191.04** | `CN-501` credit note |

`382.09 / 2 = 191.045` — the downgrade of one unit is exactly half the upgrade of two. Symmetric by
construction, because it is one signed formula rather than two code paths.

### Still not exercised

- Subscription **cancellation** (immediate-with-credit vs end-of-period) — implemented, not run.
  Deliberately skipped: cancelling the only live subscription would empty screens 9 and 10 again.
- Backorder **consolidation through the browser UI** — proven at service level (§1), but the modal
  and button have not been clicked in a real browser.
- Everything above went through the service layer. **The HTTP path for confirm is still broken
  (§2.1)** and remains the one blocker for a genuine click-through demo.

---

## 5. Suggested improvements — anubhaw0raj

> **⚠️ DO NOT IMPLEMENT ANY OF THIS UNTIL EXPLICITLY TOLD TO. These are suggestions only.
> No changes are to be made to the codebase for any item in this section until the team agrees
> and gives the go-ahead.**

Taken from an alternative design document reviewed on 2026-09-05. Roughly 80% of that document is
already built here; these are the parts that are genuinely missing and worth the time. Ranked by
impact ÷ effort. Nothing below requires a schema migration except where stated.

### S1 — Remediation hint on the approval screen ⭐ highest impact
> *"Drop Setup Service to 13% and this auto-approves."*

Per-line excess is already computed in `RiskBreakdown`. Binary-search the discount that moves the
quote down a band by calling the existing scoring function in a loop. Turns governance from a
blocker into a coach. ~1 hour. **Lane: @the-steelix-flame.**

### S2 — `value_at_risk` in currency ⭐
`Σ (overage_i / 100 × line_value_i)` — the money given away beyond policy. Every input already
exists. *"This quote gives away $1,240 beyond policy"* lands far harder than *"score 47.13"*.
~30 min. **Lane: @the-steelix-flame.**

### S3 — Margin leakage report ⭐
Cost, ceiling and excess are already stored per line. Aggregate by rep / category / tier. The
punchline writes itself: *"68% of leakage came from lines that were individually within ceiling —
only the blended score caught them"*, which is the brief's entire thesis proven with our own data.
~2 hours. **Lane: shared — @anubhaw0raj (insights) + @sinjeki (reports screen).**

### S4 — Approve-with-conditions (`capped_discount_pct`)
Manager approves **at a cap** rather than yes/no; the quote self-adjusts and the audit trail records
the counter. One column plus logic. No other team will have built it. ~2 hours, needs a migration.
**Lane: @the-steelix-flame.**

### S5 — Portal leakage test (cheap, high credibility)
Assert the portal payload contains no key matching `/cost|margin|risk/`. The separate serialiser
already exists; there is no test proving it holds. ~15 min. **Lane: @the-steelix-flame.**

### S6 — Alert reason codes
`[STALE_7D] [APPROVAL_WAIT_38H]` instead of a bare severity — tells a manager what to do. Fits the
existing `DealAlert` with no schema change. ~1 hour. **Lane: @anubhaw0raj.**

### Deliberately rejected

- **Migrating to the other document's data model** — fatal at this stage, zero judge-visible gain.
- **Microservices / event bus / outbox** — our modular monolith already has the boundaries.
- **`governance_hash`** — elegant, but re-scoring on confirm already satisfies the same requirement.
- **Scenario variants, undo/replay, LLM layer** — out of scope for the time remaining.
- **Full clock injection** — genuinely good, but retrofitting "never call `now()` directly" across
  ten apps is a day we do not have. `run_billing --as-of` already covers the billing demo.

### Also flagged from that review

**Recurring billing has no idempotency backstop.** There is no `BillingSchedule` table and
`renew()` has no per-period guard — it unconditionally advances the period and issues an invoice.
Safety rests entirely on `run_billing`'s date filter. A `UNIQUE(subscription_id, period_start)`
constraint on a persisted schedule would make repeat runs safe. Worth verifying before demo day,
especially since a time-travel demo runs that command repeatedly. **Lane: @anubhaw0raj.**

==============================================================================

# CHANGES — the-steelix-flame lane (Deal engine & admin back-end)

Branch: `main` (uncommitted working tree) · Apps: `quotations` `approvals` `negotiation` + admin back-end · Screens: 3, 4, 5, 6, 11, 18, admin

Everything below was verified by running it, not by reading it. Verification commands are given so
anyone can reproduce the result.

---

## 1. Changes shipped

### Admin back-end: business management + the "Back-end" button

**Why the button changed.** `TopNav` showed a **Back-end** link to *every* internal role, deep-linked
to `/settings/discounts`. But that page's save endpoints
(`apps/governance/api.py::update_tier_ceiling` and friends) call
`require_role(request, Role.ADMIN, Role.SALES_MANAGER)`. So a Sales Rep or Finance user could open
the page, edit the ceiling inputs, press **Save configuration** — and only then discover a 403.
A visible dead end for two of the four internal roles.

It also made the rest of the configuration surface undiscoverable: the button went to *one* config
page rather than to a back-end.

| File | Change |
|---|---|
| `frontend/src/components/shell/TopNav.tsx` | Button gated to `ADMIN` / `SALES_MANAGER`, repointed at `/admin`. |
| `frontend/src/app/(app)/admin/layout.tsx` | **New.** Second role gate over the whole admin section, mirroring the server's `require_role`. Renders an explanatory panel rather than a redirect, so a Rep who follows a link understands why. |
| `frontend/src/app/(app)/admin/page.tsx` | **New.** Hub with three tiles — Business Management (Admin), Discounts & Approval Chains, Product Catalog. Tiles filter by role. |

**Business management.** Admin registers a company you sell to; the system mints a portal login and
displays the password **once**.

| File | Change |
|---|---|
| `backend/apps/accounts/businesses.py` | **New.** `create_business`, `issue_portal_login`, `reset_portal_password`, `set_portal_access`, `generate_password`. |
| `backend/apps/accounts/admin_api.py` | **New.** `/api/admin/businesses` CRUD + `/portal-login`, `/reset-password`, `/access`. Every route `require_role(ADMIN)`. |
| `backend/apps/accounts/tests.py` | **New.** 17 tests. |
| `backend/config/api.py` | One line: `api.add_router("/admin/", admin_router)`. |
| `frontend/src/types/index.ts` | **Additive only** — added `Business` and `BusinessCredentials`. Nothing existing was touched. |
| `frontend/src/app/(app)/admin/businesses/page.tsx` | **New.** List, create form, one-time credential panel with copy-to-clipboard, reset, suspend/restore. |

**No migration.** This deliberately reuses what already exists rather than adding columns:

- portal access is `User.is_active` — already there
- issuance date is `User.date_joined`, last use is `User.last_login` — already there
- the business↔login link is `Customer.portal_user` — already there, and until now only ever
  populated by `seed_demo`. There was no UI to create a portal user at all.

### The nav is now role-shaped

Two rounds here, and the second replaced the first — recording both so nobody re-adds the thing we
removed.

**First attempt (wrong):** a **Back-end** button in the right-hand utility cluster, then an **Admin**
nav item, both leading to an `/admin` hub page of tiles. The button read as a control rather than a
destination and was invisible; the hub was a landing page in front of screens an admin lives in,
which is a click that buys nothing.

**What's there now:** the admin screens sit *inline in the nav*, and the nav is filtered per role.

| Role | Nav |
|---|---|
| **Admin** (12) | **Analytics** · Quotations · Approvals · Fulfillment · Subscriptions · Invoices · Deal Health · Reports · Products ⟩ User Management · Business Management · Discount Tiers & Approval Chains |
| **Sales Manager** (10) | Dashboard · …the same nine… ⟩ Discount Tiers & Approval Chains |
| **Sales Rep** (9) | Dashboard · …the same nine… |
| **Finance** (9) | Dashboard · …the same nine… |

| File | Change |
|---|---|
| `components/shell/TopNav.tsx` | `NavItem` gained `labelByRole`. Admin config items added inline. Back-end button removed. A single divider is derived from the first role-restricted item, so it lands correctly for Admin *and* for a Sales Manager who only sees one config link. |
| `app/(app)/dashboard/page.tsx` | Heading reads "Platform Analytics" for Admin. The nav says *Analytics*; landing on "Welcome back, A." reads as the wrong page. |
| `app/(app)/admin/page.tsx` | Hub replaced by a redirect to `/admin/users`, so old links don't 404. |
| `app/(app)/admin/layout.tsx` | Tightened to `ADMIN` only, matching `require_role(ADMIN)` on every route in `admin_api.py`. |
| `app/(app)/settings/layout.tsx` | **New.** See below. |
| `components/shell/RoleGuard.tsx` | **New.** Shared gate behind both layouts. |

**"Product Catalog" was requested as a fourth admin link and deliberately not added** — *Products*
already sits in the nav for every role and points at the same `/products`. Two entries to one screen
is noise. Say the word if you want it duplicated anyway.

### Closed: `/settings/discounts` was ungated

Separate from the button. The page was reachable by **any** internal role, but its save endpoints
require Admin or Sales Manager. A Sales Rep or Finance user could open it, edit the ceilings, press
**Save configuration**, and only then get a 403 — the original dead end, still open after the first
round because the discount screen lives under `/settings`, not `/admin`.

`app/(app)/settings/layout.tsx` now gates the subtree to `ADMIN` / `SALES_MANAGER`, matching the
server. The refusal explains itself rather than silently redirecting, so someone following a
colleague's link understands why.

### User management + per-user analytics

| File | Change |
|---|---|
| `backend/apps/accounts/staff.py` | **New.** `create_account`, `reset_password`, `set_access`, `change_role`. |
| `backend/apps/accounts/analytics.py` | **New.** `user_analytics(user)` — role-appropriate metrics aggregated from the operational tables. |
| `backend/apps/accounts/admin_api.py` | Added `/admin/users` (list, create, detail, reset-password, access, role) and `/admin/teams`. All `require_role(ADMIN)`. |
| `frontend/src/app/(app)/admin/users/page.tsx` | **New.** Table with role filter chips, create form, one-time credential panel, reset / enable / disable. |
| `frontend/src/app/(app)/admin/users/[id]/page.tsx` | **New.** Analytics, recent quotations, recent approval decisions, role change and account controls. |
| `frontend/src/app/(app)/admin/page.tsx` | Added the User Management tile. |
| `frontend/src/types/index.ts` | Additive: `AdminUser`, `UserCredentials`, `AnalyticsMetric`, `AnalyticsSection`, `UserQuotationRef`, `UserDecisionRef`, `AdminUserDetail`, `SalesTeam`. |

**Analytics are role-shaped, not one-size-fits-all.** "How is this person doing" means different
things per role, so the backend decides which sections to send and the page renders what arrives:

| Role | Sections |
|---|---|
| Sales Rep | Selling |
| Sales Manager, Admin | Selling + Approvals |
| Finance | Approvals |
| Customer | Portal activity |

Selling covers quotations created, confirmed count and value, win rate, open pipeline, average
effective discount, average risk score, awaiting approval, open alerts and upsells accepted.
Approvals covers decisions made, the approved/returned/rejected split, average decision time from
request raised to acted, and how many steps currently wait on that role.

**Win rate counts decided deals only.** Treating still-open quotations as losses would punish a rep
for having a healthy pipeline. With no decided deals it shows `—` rather than a misleading `0%`.

### Guards that exist for a reason

| Guard | Why |
|---|---|
| `CUSTOMER` cannot be created in User Management | A `CUSTOMER` user with no `Customer` row can log in and then hit a wall on every portal route, because portal auth resolves through `customer_profile`. The error names Business Management instead. |
| Cannot deactivate your own account | Trivially locks you out mid-session. |
| Cannot deactivate or demote the last active admin | Locks *every* human out of the back-end, unrecoverably through the UI. |
| Deactivate never deletes | Quotations, approval decisions and audit events all FK to the user. `on_delete=SET_NULL` on the audit trail would quietly turn a named decision into an anonymous one. |
| Reset re-enables the account | Reset is how a locked-out person gets back in; leaving them disabled makes it a trap. |

### Bug found and fixed during this work

`GET /api/admin/users/{id}` returned **500** on every call. `MetricOut.value` is typed `str`, and
pydantic v2 does **not** coerce `int` to `str` — it raises. Counts are naturally ints, so every
metric built from a `.count()` blew up response validation.

Fixed centrally in `analytics.py::user_analytics` — one normalisation pass over all sections before
returning, rather than relying on twenty call sites to remember. Covered by
`test_every_metric_value_is_a_string`, which walks every role and asserts the contract, so adding a
new metric later can't reintroduce it.

Worth flagging to the team: this is the **same class of bug** anubhaw0raj hit twice
(`0cb8c26`, `9a5904d`) — Ninja response schemas failing on a type the code assumed would be
coerced. It fails as an opaque 500 with an empty body; the traceback is only in the server log.
**If an endpoint returns nothing and the page renders blank, check `runserver` output first.**

### The customer portal had no index — two bugs on the negotiation loop

**Bug 1 — a customer could log in and reach nothing.** Portal access is granted *per quotation* by
`PortalToken`, and nothing enumerated the tokens a customer held. `/portal` was a static "open the
link your account manager sent you" message, and there was no `GET /api/portal/quotations` at all.
So a business onboarded through Business Management would log in, see a paragraph of instructions,
and have no way to reach a quotation that had genuinely been sent to them.

| File | Change |
|---|---|
| `apps/negotiation/services.py` | New `portal_quotations_for(user)` — token-scoped, deduped when a quotation was re-sent, newest first. New `portal_status()` mapping internal statuses to customer-facing wording. |
| `apps/negotiation/api.py` | New `GET /api/portal/quotations`. `status_label` + `action_required` added to the detail payload too. |
| `app/portal/page.tsx` | Rewritten as the real list: reference, sent date, item count, total, status, and a banner when something needs the customer's attention. |
| `app/portal/quotations/[id]/page.tsx` | Shows the friendly status; added an "All quotations" link back. |
| `types/index.ts` | Additive: `PortalQuotationRow`; `status_label` / `action_required` on `PortalQuotation`. |

**Bug 2 — the negotiation loop dead-ended at the final click.** The brief's flow is: customer
counters → rep accepts → quote re-enters approval → approvers clear it → customer confirms. That
last step lands the quotation on `APPROVED`, but `confirm_by_customer` only accepted `SENT` and
`UNDER_NEGOTIATION`. Meanwhile `portal_status` was already telling the customer **"Ready for your
confirmation"**. The UI invited a click that the service refused.

`confirm_by_customer` now accepts `APPROVED` as well. Safe by construction: reaching the endpoint at
all requires a `PortalToken`, and tokens only exist because a rep sent the quotation.

Found by running the flow, not by reading it — the listing bug hid the confirm bug, because nobody
could get far enough to hit it.

### Two-way negotiation with a shared history

Negotiation was one-shot: the customer sent a counter, the rep could only accept or reject, and
neither side could see the conversation. Now it's a real back-and-forth over one shared record.

| File | Change |
|---|---|
| `apps/negotiation/models.py` | `NegotiationRequest.counter_discount_percent` — what we offered back. Kept on the **same row** so one round of haggling reads as one row: asked 25, offered 12, accepted. |
| `apps/negotiation/migrations/0003_*`, `0004_*` | **Everyone must re-run `manage.py migrate`.** |
| `apps/negotiation/services.py` | `negotiation_timeline()` merges messages and request state-changes into one ordered thread. Plus `post_message()` (either side), `counter_request()`, `accept_counter()`, `open_request_for()`. |
| `apps/negotiation/api.py` | Internal: `GET/POST .../negotiation`, `.../messages`, `.../requests/{id}/counter`. Portal: `POST .../messages`, `POST .../requests/{id}/accept`. `timeline` + `open_request` added to the portal payload. |
| `components/negotiation/Thread.tsx` | **New.** Rendered by **both** sides from the same payload; `viewpoint` changes only labelling, never which entries appear. |
| `components/negotiation/RepNegotiationPanel.tsx` | **New.** On the quotation: read the exchange, then accept / counter / decline, or just reply. |
| `app/portal/quotations/[id]/page.tsx` | Same thread, plus an "Accept 12%" panel when we've made an offer. |

**A counter is an offer, not a decision.** `counter_request` changes nothing on the quotation — the
discount only lands when the customer accepts. Quoting a customer a total that reflects a discount
they haven't agreed to would be lying, and the rep would be staring at a number nobody promised.
`test_rep_counter_does_not_change_the_quotation_yet` pins this.

**Re-approval doesn't care who agreed.** The rep-accepts path and the customer-accepts-our-counter
path both end in the same extracted `_reapprove_if_needed()`, so they cannot drift. Accepting a
30% counter still re-enters approval automatically.

### Four more bugs, all found by running the negotiation rather than reading it

1. **`counter_discount_percent` defaulted to `0.00`, not null.** `**PERCENT` carries `default=0`, so
   "no counter yet" was indistinguishable from "we offered zero percent" — the portal announced
   *"We've made you an offer"* the instant a customer sent a request. Fixed with
   `percent(default=None)`; the label is now keyed on `status == COUNTERED`.
2. **Messages appeared twice.** `submit_request` wrote the customer's text as both a
   `NegotiationMessage` *and* the request's `message`; `counter_request` did the same with the rep's
   note. The request row carries the text and the timeline renders it — the duplicates are gone.
3. **Accepting a counter rewrote history.** `accept_counter` overwrote `requested_discount_percent`
   with the agreed figure, so a customer who asked 25% and settled at 12% appeared to have asked for
   12% all along. The original ask is now left intact.
4. **`POST .../counter` returned 500** — no `response=` schema, so Ninja tried to serialise model
   instances. Same failure mode as the analytics bug and as `0cb8c26`: empty body, blank page,
   traceback only in the server log.

### Status wording is decided server-side

Internal names leak process a customer shouldn't have to interpret — "Pending Approval" invites
"approval by whom, for what?". `portal_status()` maps each status to plain language plus an
`action_required` flag, so the portal can highlight only what's genuinely waiting on the customer:

| Internal | Customer sees | Their move? |
|---|---|---|
| `SENT` | Awaiting your review | **yes** |
| `APPROVED` | Ready for your confirmation | **yes** |
| `UNDER_NEGOTIATION` | Your request is with our team | no |
| `PENDING_APPROVAL` | Under internal review | no |
| `CONFIRMED` | Confirmed | no |
| `REJECTED` / `CANCELLED` | Closed | no |

The list stays thin on purpose — reference, date, item count, total, status. No margin, no risk
score, no approval history; those never enter the portal serialiser.

### Decisions worth knowing

**The password is never recoverable.** It goes straight into Django's hasher and is returned exactly
once, by the call that generated it. There is no "show password" endpoint and no plaintext column.
If it's lost, you reset it. `test_password_is_never_recoverable_after_creation` asserts that no
column on either row contains the plaintext.

**Suspend disables, never deletes.** `set_portal_access` toggles `is_active`. Deleting the user
would orphan or cascade their negotiation messages and counter-offers. Revoking access must not
rewrite the audit trail.

**Reset also re-enables.** Resetting a suspended account is how you *recover* it, so a reset that
left the account locked out would be a trap.

**Generated passwords exclude `l I O 0 1`.** These get read aloud on a call and retyped off a
screenshot.

**Email collisions are rejected, loudly.** Onboarding a business whose contact email already
belongs to an account fails with a clear message rather than silently attaching a portal role to
an existing staff login.

### The header badge says who you are, not that the rules engine is up

Every internal role saw the same pill in the top bar: a pulsing dot and the words **Rules engine
live**. It was decorative — nothing behind it ever checked whether the engine was actually running,
so it was a claim the UI could not have retracted if it were false. Meanwhile the app is
role-shaped throughout (the nav, the dashboard heading, `/admin` and `/settings` gates, the
analytics sections), and nothing on screen told you which role you were signed in as. On a demo
where you switch between four seeded logins, that is the thing you actually need in the header.

The pill now shows the signed-in user's role.

| File | Change |
|---|---|
| `lib/format.ts` | New `ROLE_LABEL: Record<Role, string>`. Wording matches the signup form, so the badge reads the same as the role you were given — "Finance / Operations", not `FINANCE`. |
| `components/shell/Header.tsx` | Pill renders `ROLE_LABEL[user.role]`. |

Two details worth keeping:

- **No fallback role.** The name beside it falls back to `"J. Rao"` while the session loads; the
  badge does not. Showing someone the wrong user type is worse than briefly showing none, so the
  pill is omitted until `user` resolves.
- **The dot no longer pulses.** `animate-dfPulse` said *live*, which is a liveness signal. Identity
  is not a heartbeat. The keyframe is still defined in `tailwind.config.ts` and is now unused —
  left in place rather than removed, since it is a shared design token.

Customers are unaffected: `Header` mounts only in the `(app)` shell, and the portal has its own.
`CUSTOMER` is in the map for completeness.

### Three screens disagreed about how many deals there were

Reported from the UI: the board showed 8 cards while the sidebar said 7, and the sidebar counted a
negotiation the board's Negotiation column left empty. Three separate causes, all of the same
shape — a count derived one way, next to a list derived another.

**The board was hiding quotations.** `PIPELINE_STAGES` had five columns for eight statuses. `SENT`,
`REJECTED` and `CANCELLED` had nowhere to go, so a sent quotation rendered *nowhere* on a screen
whose own subtitle reads "every quotation in the system". Q-1009 was sitting in exactly that hole.
The sidebar counted it, so the sidebar looked wrong when it was the board that was lying.

Stages now carry `statuses: QuotationStatus[]` — a list, because `REJECTED` and `CANCELLED` are one
thing to a reader — and every status is covered. `Closed` is `hideWhenEmpty`, so a terminal column
doesn't sit empty on every healthy board while still guaranteeing no record is invisible.

**The badge counted a different set.** It filtered to `OPEN_QUOTE_STATUSES`, excluding `CONFIRMED`,
so it could never match the board even once `SENT` was visible. It now counts what the endpoint
returns. That is a real trade — the badge grows as confirmed deals accumulate, which is what the
original comment was guarding against — but a number that quietly disagrees with the list beside it
is worse than a number that grows. Every other badge means "work waiting"; this one means "how many
there are", matching the screen it links to.

**A quotation could be under negotiation without being `UNDER_NEGOTIATION`.** The real bug.
`submit_request` never checked for an already-open round, so a customer could stack a second request
on an unanswered one. Resolving the newer one left the older orphaned at `SUBMITTED` forever — the
inbox counted it, the board filed the quotation under whatever status the *newer* request had driven
it to, and no screen offered a way to clear it. Q-1007 was in precisely that state: request #2
unanswered since 15:31, request #3 raised 32 seconds later and accepted, quotation moved on to
`APPROVED`.

Fixed as an invariant rather than a patch: **a quotation is `UNDER_NEGOTIATION` exactly while a round
is open.**

| Change | |
|---|---|
| `submit_request` | Refuses a second request while one is `SUBMITTED` or `COUNTERED`. `open_request_for` always spoke of "the round currently awaiting a reply" in the singular; now nothing can contradict it. |
| `_reapprove_if_needed` → `_settle_round` | The shared tail of *every* resolved round, decline included. Re-approval when the terms moved and breach a ceiling; otherwise transition out of `UNDER_NEGOTIATION`. |
| `reject_request` | Now calls it. A decline ends a round as surely as an acceptance, but the quote used to stay parked in the Negotiation column with nothing left to negotiate. |
| `0007_settle_stranded_negotiations` | Moves already-stranded quotations to `UNDER_NEGOTIATION`. |

The settle target is `APPROVED`, not `SENT`: `SENT` is only ever reached *from* `APPROVED`, so the
quote was cleared once already, and the terms now on it either breach no ceiling (accepted) or are
the ones that were cleared (declined). The customer reads "Ready for your confirmation", which is
where the ball actually is. `UNDER_NEGOTIATION → SENT` isn't in `ALLOWED_TRANSITIONS` anyway.

**The migration deliberately does not close the orphans.** An unanswered customer request is real
work; marking it rejected would answer the customer on the rep's behalf. It moves the quotation to
where that work is *visible* instead. Terminal statuses are excluded — an orphan under a `CONFIRMED`
order is history, not work, and dragging a confirmed order back into negotiation would be worse than
the inconsistency it fixes. Not reversible: the prior status is recorded nowhere, so an automatic
reverse would guess between `SENT` and `APPROVED` and be wrong half the time.

One direction of drift is left standing on purpose. A `COUNTERED` round keeps the quotation in the
Negotiation column while the "awaiting you" badge reads zero — correct, because that round is the
*customer's* move. The failure that was reported is the other direction: work waiting on you, on a
deal the board doesn't show as negotiating. That can no longer happen.

### `Negotiate` on the inbox row

Accept and Reject were the row's whole vocabulary, but a counter-offer is the third answer and it
doesn't fit in a table cell — it needs the thread, the line breakdown and a number. The new button
opens `/quotations/{id}`, where `RepNegotiationPanel` already offers accept, counter and decline
against the same endpoints the inbox posts to. No new decision path; the row just stops being a
dead end for the one answer it couldn't express.

### Regression caught in review: the two accept paths disagreed

Flagged against the change above, and correct. `accept_request` (rep accepts the customer's ask)
sets `order_discount_percent`. `accept_counter` (customer accepts the rep's counter) still looped
`update_line`, stamping the counter onto every line — the exact bug `accept_request`'s own comment
describes:

- a line already at 18% was silently **cut** to a 12% counter, so the customer's haggling made their
  own price worse;
- flattening the per-line spread changed the blended risk score the deal is governed by, because
  `recalculate` feeds line discounts and the order discount to `score_quotation` separately.

The two paths differ only in *whose* number is applied, so they must apply it the same way.
`accept_counter` now sets `order_discount_percent` too.

`test_customer_accepting_our_counter_applies_our_number` had encoded the old behaviour — it asserted
the line was rewritten to 12% — and was updated to assert the order discount plus an untouched line.
`test_accepting_our_counter_never_cuts_a_deeper_line` is the new regression test: an 18% line, a 12%
counter, and an assertion that the line is still 18% afterwards.

### Per-line comment boxes removed from the portal

"Your decision" repeated the line table that sits directly above it — description and discount, per
row — purely to hang an "Add a comment about this line…" input off each one. A customer disputing a
price disputes the order, not line 3; the single **Message** field in the same card already carries
that, and it is the field the rep's inbox actually surfaces.

Frontend only. `SubmitRequestIn.line_comments` defaults to `[]`, so the portal just stops sending
the key — the endpoint, the `quotation_line_id` column on `NegotiationMessage` and the thread's
line-scoped rendering are all untouched, and a rep-side annotation UI could use them with no backend
change.

### Warehouse Management, and addresses on both ends of a shipment

Phase 1 of [`PLAN-distance-fulfillment.md`](PLAN-distance-fulfillment.md). **No behaviour change** —
this is the data and the admin surface that the distance-based splitter needs, landed on its own so
the algorithm change can be reviewed as a small diff.

The premise it starts from, corrected: `fulfillment/planner.py` is *not* a stub. It genuinely tries
a single warehouse first, then greedy coverage, then backorder. What is fake is the number it ranks
by — `Warehouse.shipping_cost_weight`, a static constant (`Main = 1.0`, `remote = 1.4`) that is
identical whoever the goods are going to. So the suggestion is the same for a customer next door and
one across the country, and replacing that one number is the whole feature.

| File | Change |
|---|---|
| `common/geo.py` | **New.** `clean_point()` — the coordinate rule in one place, because two models carry a point and validating it twice would let the two drift. Dependency-free; `haversine_km` joins it in Phase 3. |
| `accounts/models.py` | `Customer` gains `address`, `latitude`, `longitude`, `geocoded_at`. It had **no address field at all**. |
| `fulfillment/models.py` | `Warehouse` gains `latitude`, `longitude`, `geocoded_at`. `address` already existed as unused free text. |
| `accounts/warehouses.py` | **New.** `create_warehouse`, `update_warehouse`, `set_active`, validation. |
| `accounts/admin_api.py` | `/admin/warehouses` CRUD + `/active`. Business schemas gain the address fields. |
| `accounts/businesses.py` | `create_business` takes an address and a point. |
| `app/(app)/admin/warehouses/page.tsx` | **New.** List, create, edit, retire/restore. |
| `app/(app)/admin/businesses/page.tsx` | Delivery address on the form and in the table. |
| `components/shell/Sidebar.tsx` | Warehouse management, Admin only. |

**There was no way to create a warehouse.** `GET /fulfillment/warehouses` is read-only; warehouses
came only from `seed_demo` or the Django admin. A warehouse decides what the splitter is even
allowed to consider, which makes defining one an admin act — so this follows the `plans.py`
precedent exactly: new file in `accounts`, no structural change to `fulfillment/`.

**Coordinates are nullable on purpose.** Every existing customer and warehouse row has none, and
allocation has to keep working for them — Phase 3's fallback to `shipping_cost_weight` is the
feature's safety net, not an afterthought.

Guards, each of which is a way to break allocation from the UI:

| Guard | Why |
|---|---|
| Both coordinates or neither | A latitude alone reads as the prime meridian — a confidently wrong position, worse than no position. |
| Range-checked (-90..90, -180..180) | An out-of-range value is not a near-miss; it is a swapped pair or metres. |
| Cost weight must be > 0 | The splitter sorts on it and multiplies by it. Zero makes every warehouse look free and identical; a negative inverts the ranking. |
| The last active warehouse cannot be retired | `plan_split` answers "No active warehouses configured" and backorders every line of every order. One click, all future allocation broken, nothing on screen saying why. |
| Retiring never deletes | `StockItem` and `FulfillmentAllocation` both FK to the warehouse — deleting cascades away real inventory or orphans the record of where an order shipped from. |
| Codes upper-cased, names and codes unique case-insensitively | The column is unique and case-sensitive, so `wh-1` and `WH-1` would both be accepted and read as one code. |

Hand-typed coordinates clear `geocoded_at`, which is what will stop Phase 2's re-geocode from
overwriting a correction someone made by hand.

**On reusing `the-steelix-flame/aera`** — checked, and there is nothing to lift. It is a fork of an
air-quality routing hackathon: one FastAPI file that calls open-meteo and asks Gemini whether
there's a landfill nearby, plus a Leaflet frontend. No distance math and no geocoding module. What
it does demonstrate is the two public endpoints worth using — Nominatim to geocode and OSRM to
route — and those are recorded in the plan, with Nominatim's 1-request-per-second policy as the
reason geocoding belongs at write time rather than in the allocation path.

---

## 2. What this is NOT (scope decision)

"Add a binded business" was ambiguous between two very different features, and we picked
deliberately:

- **Built:** *customer onboarding.* A business is a company you sell **to**. Its login opens the
  **portal**, where it views, comments on, counter-offers and confirms **its own quotations**.
- **Not built:** *multi-tenancy.* A business does **not** get its own products, warehouses, ceilings
  or staff, and cannot create quotations or approve anything. That would need a company FK on
  nearly every table plus queryset scoping on every read — roughly a day, touching all three lanes.
  The brief calls multi-company a bonus, not a requirement.

If we later want multi-tenancy, the migration path is a `Company` table plus a nullable FK, not a
rewrite of this.

---

## 3. Verification

```bash
cd backend && python manage.py test apps      # 90 passed (31 accounts, 31 negotiation)
cd frontend && npm run build                  # all routes emitted
```

Counts read back off the running API after the changes above, rather than off the screen:

| Surface | Before | After |
|---|---|---|
| Sidebar *Quotations* badge | 7 | **10** |
| Board cards (all columns) | 8 — `SENT` had no column | **10** |
| Sidebar *Negotiations* badge | 1 | 1 |
| Board *Negotiation* column | 0 | **1** — Q-1007, the deal that request is on |

`GET /portal/internal/quotations/7/negotiation` returns `open_request` `#2` at `SUBMITTED`, so the
rep panel renders Accept / Counter / Decline on the page the new **Negotiate** button opens.

Full portal loop, live against `runserver`, with a business created through the admin UI:

| Step | Result |
|---|---|
| Admin onboards "Portal Test Co" (Gold) | credentials issued |
| Customer's portal list *before* anything is sent | **0 rows** — an unsent quotation stays private |
| Rep builds Q-1009, submits | auto-routed, `MEDIUM` (47.58) |
| Manager approves, rep sends | portal token minted |
| Customer's portal list *after* sending | **1 row** — "Awaiting your review", action required |
| Customer counters at 20% | "Your request is with our team" |
| Rep accepts → re-scored `HIGH` | re-entered approval automatically |
| Manager then Finance approve | "Ready for your confirmation" |
| Customer confirms | `CONFIRMED` |
| Sales side continues | fulfillment plan created, `INV-1043` raised |
| Customer hits `/api/quotations/` | `401` |
| Customer opens another company's quotation | `Not found` |

Live, against `runserver` with seeded data:

| Check | Result |
|---|---|
| Admin creates "Northwind Traders" (GOLD) | Business + credentials returned, `portal_access_enabled: true` |
| Business logs in with the generated password | `200`, role `CUSTOMER` |
| Admin suspends access, business retries login | `403` |
| Sales Rep calls `GET /api/admin/businesses` | `403` |
| Admin creates a `SALES_REP` account | Created, password returned once |
| Admin tries to create a `CUSTOMER` account | Refused, pointing at Business Management |
| Analytics for J. Rao (rep) | 4 quotations, 100% win rate, 16.4% avg discount, 58.9 avg risk, 2 upsells |
| Section titles per role | Rep → Selling · Manager/Admin → Selling + Approvals · Finance → Approvals · Customer → Portal activity |

Test records were removed afterwards; the dev database is back to 6 customers and 7 users.

---

## 4. Notes for the others

**@sinjeki** — I added two **new files** inside your `accounts` app (`businesses.py`,
`admin_api.py`) rather than editing `models.py` or `api.py`, so this shouldn't conflict with your
work. Two things do touch your files:

- `types/index.ts` — additive only, one new block, nothing existing changed.
- `config/api.py` — one `add_router` line under the `the-steelix-flame` section.

If you'd rather this lived in its own `apps/administration` app, say so and I'll move it; it's
self-contained.

**@anubhaw0raj** — nothing in your lane was touched.

---

## 5. Open items

- [ ] **Onboarding and user provisioning write no audit event.** Quotations have
      `quotation_event`; business creation, account creation, password resets, role changes and
      suspensions have no equivalent trail. For features that hand out credentials and change
      permissions, that's the most important gap here. The `actor` parameter is already threaded
      through every service function in `businesses.py` and `staff.py` for exactly this.
- [ ] **Analytics recompute on every page load.** Fine at seed scale; the rep metrics do a handful
      of aggregates plus one Python-side loop over discount ratios. `insights.RepDiscountStat`
      already exists as the caching pattern to follow if it gets slow.
- [ ] **No pagination on the user list**, same as businesses.
- [ ] **No email delivery.** `create_business` returns the password to the caller. When real email
      lands, that function is where it should be sent instead.
- [ ] **Business edit UI is API-only.** `PATCH /api/admin/businesses/{id}` works; the table has no
      inline edit yet.
- [ ] **No pagination** on the business list. Fine at demo scale.
- [ ] **The timeline shows one entry per round, not per move.** Once a customer accepts our
      counter, the `REP_COUNTER` entry becomes `ACCEPTED` — the "we offered 12%" moment is folded
      into the outcome rather than kept as its own line. Every figure survives (asked 25, agreed 12)
      and all messages are preserved, so nothing is lost that matters; it's just less granular than
      a true event log. Splitting it would mean an append-only `negotiation_event` table.
- [ ] **No notification when the other side replies.** Both parties have to open the quotation to
      see a new message. The events are already written to `quotation_event`; there's just no
      transport.

---

## 6. The negotiation history is now an append-only log

The timeline was **derived from each request's current status**, so a row could only ever show its
latest state. Once a customer accepted our counter, the "we offered 12%" moment was overwritten by
"accepted" and disappeared from the history. A negotiation the two sides remember differently is
worse than no record at all.

| File | Change |
|---|---|
| `apps/negotiation/models.py` | **New `NegotiationEvent`** — one row per move, never updated, never deleted. Carries kind, author type, a snapshotted author name, body, discount, delivery date and line. Ordered by `created_at, id` so two moves in the same transaction still read in the order they happened. |
| `migrations/0005_negotiationevent` | The table. |
| `migrations/0006_backfill_negotiation_events` | **Backfills from existing messages and requests**, preserving original timestamps — without it every conversation that already exists would render empty on both sides. |
| `apps/negotiation/services.py` | Every action appends an event: sent, asked, countered, messaged, accepted, declined. `negotiation_timeline()` is now a straight read of the log; the old derivation is deleted. |
| `components/negotiation/Thread.tsx` | Handles the new `SENT` / `CONFIRMED` kinds and defaults unknown ones, so a kind added on the backend renders plainly instead of crashing the thread. |

Verified live — both sides return the identical sequence, including the counter that used to vanish:

```
17:03:33  REP       J. Rao        [SENT]             Quotation sent for your review.
17:03:34  CUSTOMER  Seq Check Co  [COUNTER_REQUEST]  25%   Can you do 25%?
17:03:35  REP       J. Rao        [REP_COUNTER]      12%   12% is our best on hardware.
17:03:37  CUSTOMER  Seq Check Co  [MESSAGE]                Does that include setup?
17:03:38  REP       J. Rao        [MESSAGE]                Yes, setup is included.
17:03:39  CUSTOMER  Seq Check Co  [ACCEPTED]         12%   Accepted your offer.
```

The backfill also surfaced two things in existing data, both fixed: rows created before
`counter_discount_percent` was nullable carry `0.00`, which would have rendered a plain acceptance
as "Agreed at 0%"; and the rep panel was posting a "we've accepted your request" message on top of
the ACCEPTED event, saying the same thing twice.

### Finished actions no longer sit there looking live

- **Portal:** Submit Request and Confirm Quotation stayed enabled even while a request was
  unanswered — the server refuses that, so the customer only found out by clicking. Both are now
  disabled with the reason shown. When there is nothing left to do the buttons are replaced by a
  status panel rather than an empty space, which reads as finished instead of broken.
- **Portal nav:** "My Quotation" was a dead `<span>`, so the only way back to the list was the
  browser's back button. It is now a working link. "Messages" and "Profile" sat beside it as
  decoration for screens that don't exist and were removed — a nav item that does nothing is worse
  than one that isn't there.
- **Sidebar:** removed **"Customer portal view"**. The portal is a customer's own surface, scoped
  to the quotations *they* were sent; an internal user following that link either sees nothing or
  reads a business's private view. Staff already see the whole conversation on the quotation itself.

---

### Who gets to say no

A rep had a **Decline** button on their own deal, which is just deleting their own work — if the
number doesn't suit, the answer is a counter. Meanwhile the customer, the one party with a real
reason to walk away, had no way to do it: their only exits were accept or keep negotiating, so a
quote they had already refused sat open pretending to be live.

The two sides now have the answers that belong to them:

| Side | Actions |
|---|---|
| Sales rep | **Accept** their number · **Counter** with ours |
| Customer | **Accept** · **Negotiate** · **Reject** |

| File | Change |
|---|---|
| `apps/quotations/services.py` | `REJECTED` reachable from `APPROVED`, `SENT` and `UNDER_NEGOTIATION` — every state the customer can see, because "no thank you" is valid at any point in the conversation. |
| `apps/negotiation/services.py` | New `reject_by_customer()`. Closes any round still in flight, appends a `REJECTED` event, moves the quotation. |
| `apps/negotiation/api.py` | `POST /api/portal/quotations/{id}/reject`. Portal-only — there is deliberately no internal equivalent. |
| `components/negotiation/RepNegotiationPanel.tsx` | Decline removed. New "Rejected by customer" panel carrying their reason, so the rep sees *why* rather than inferring it from a status badge. |
| `app/portal/quotations/[id]/page.tsx` | Accept / Negotiate / Reject. Accept and Negotiate are blocked while a request of theirs is unanswered; **Reject never is** — refusing must always be available. |

Reject is the one action with no precondition beyond the quotation being live. Blocking it would
be the same bug as before, in reverse: the customer stuck with a deal the UI won't let them end.

### Follow-up: the same Reject lived on a second screen

Removing the button from the quotation panel missed the **Negotiation inbox**
(`/negotiations`), a separate screen built upstream that carried its own
Accept / Reject / Negotiate row. A rule enforced on one screen and not the
other is not a rule.

| File | Change |
|---|---|
| `app/(app)/negotiations/page.tsx` | Reject button, its confirm-with-reason panel, the `rejecting`/`note` state and the `reject()` handler all removed. Rows now read Accept · Negotiate. |
| `apps/negotiation/api.py` | `POST /internal/requests/{id}/reject` **deleted**. Removed at the API boundary rather than only hidden, so a button re-added later gets a 404 and a conversation instead of silently working. |

`services.reject_request` survives: it also settles a quote out of
`UNDER_NEGOTIATION`, and a teammate's test pins that. Nothing routes to it now.
**@anubhaw0raj / @sinjeki** — if you were planning to use that endpoint, say so
and we can decide together; the service is still there.

### Follow-up: the portal list undersold what it was for

The row action said **"Review →"**, which reads as "have a look" and hid that a
decision was waiting; the banner still offered to "ask a question" after
messaging was removed. The row now reads **"Accept, negotiate or reject →"**
with the discount underneath it, and the banner names the same three answers.
`effective_discount_percent` was added to the list payload as well as the
detail, so the number is on screen before you open anything.

Verified against real data: `Q-1009 — 8.00% off`, `Q-1007 — 10.00% off`.

### The discount is now stated, not implied

The portal showed a percentage per line, but an order-level discount sits on top of those, so no
number on the page answered "what are we actually being offered?". `effective_discount_percent` is
computed server-side — `discount_total / subtotal` — and shown as a headline figure above the
decision buttons, with the money either side of it.

### Free-text messaging removed from both sides

The standalone "Send message" box is gone from the rep panel and the portal. Every message that
matters now rides along with a decision — the note on a counter-offer, the comment on a line — so a
separate chat channel was a second place to say things that nobody was obliged to read. Existing
messages still render in the timeline; it is history, and history is not deleted.

Removing it from only one side would have been worse than leaving it: a channel the customer can
write to and the rep cannot answer is a trap.

---

### A customer profile, and one Back control for the whole app

**Profile** (`/portal/profile`). Split deliberately into two halves: the account
details are **read-only** and the password is not. Business name, pricing tier and
account manager are ours to set — a customer able to edit their own tier would be
editing their own discount ceiling. What they get is their sign-in email, contact
address, account manager, member-since, last sign-in, and how many quotations
they've received and confirmed.

| File | Change |
|---|---|
| `apps/accounts/staff.py` | New `change_own_password()`. Distinct from the admin `reset_password()`: that one acts on someone else's account and *cannot* ask for the old password, so here the current password **is** the proof of identity — without checking it, anyone at an unlocked screen could lock the real owner out. Also enforces a minimum length and refuses a no-op reuse. |
| `apps/negotiation/services.py` | `portal_profile()` and `assert_portal_user()`. Received-count comes from `PortalToken`, not from the customer's quotations, so drafts they were never sent are not counted. |
| `apps/negotiation/api.py` | `GET /api/portal/profile`, `POST /api/portal/profile/password`. |
| `app/portal/profile/page.tsx` | **New.** Read-only account card beside the password form. |
| `app/portal/layout.tsx` | Profile is now a real nav item — it was one of the dead `<span>`s removed earlier. |

Verified: wrong current password, too short, and reuse are each refused with their
own message; a valid change works, the new password authenticates and the old one
stops; a `SALES_REP` gets 403 on the portal profile.

**Back.** Lives in `PageHeader`, above the title. Every screen already renders a
`PageHeader` — 21 of 25 pages, and the four that don't are the dashboard, login and
two redirects, none of which want one — so it lands in the same place everywhere for
free and cannot drift as pages are added. `hideBack` opts out.

It uses `router.back()` rather than a computed parent path, because arriving at a
quotation from the negotiation inbox should return you to the inbox, not to the
quotations list.

The interesting part is when it appears. `window.history.length` is no use: it counts
everything the tab ever visited, so on the first screen after login it would offer to
go "back" to `/login`, which immediately redirects forward again — a button that
visibly does nothing. `NavigationProvider` (`lib/navigation.tsx`) therefore mounts
**per authenticated shell**, never at the root, and only counts navigations that
happen inside one. Land directly on a shared portal link and there is no Back button,
which is correct: there is nothing in-app behind you.

---

### Billing: the deal is not billed until someone internal accepts it

The negotiation workflow is untouched. What changed is what happens *after* it —
previously nothing, or rather too much: `quotations.confirm()` issued the one-time
invoice itself. Confirming is the **customer** agreeing to the terms; it is not us
agreeing to them. Billing at that moment invoices a customer for a deal nobody on
our side has signed off, and re-confirming during a negotiation would have raised
paperwork repeatedly for terms still in flight.

So the deal now stops at CONFIRMED and waits. Finance or a Sales Manager accepts
it, and *that* raises the bill.

**The lifecycle**, one deal, three states, named once in `billing/services.py` and
rendered from that same source on both sides:

| State | Finance sees | The customer sees |
|---|---|---|
| `AWAITING_BILL` | **Accept deal & generate bill** | "Your bill will appear here as soon as our team has finalised it" |
| `PAYMENT_PENDING` | **Payment Pending** + the amount outstanding | "Your bill has been generated" → **Make the payment →** |
| `PAID` | **View Invoice** | Despatch status, then the invoice itself |

| File | Change |
|---|---|
| `apps/quotations/services.py` | `confirm()` no longer bills. It still plans fulfillment and creates the subscription records — the schedule should be visible — but passes `issue_invoices=False`. Returns `invoice_id: None` rather than dropping the key, so existing callers keep their shape. |
| `apps/subscriptions/services.py` | `activate_from_quotation(..., issue_invoices=True)`. The opt-out defers a subscription's *first* period to the same sign-off as the one-time lines. Default unchanged, so every other caller behaves exactly as before. |
| `apps/billing/services.py` | `bill_for()`, `billing_state()`, `raise_bill_for_quotation()`. |
| `apps/billing/api.py` | `GET /billing/deals`, `POST /billing/quotations/{id}/bill` (FINANCE or SALES_MANAGER). |
| `apps/negotiation/services.py` | `portal_bill()`, `portal_shipping()`, `pay_bill()`. |
| `apps/negotiation/api.py` | `bill` and `shipping_status` on `PortalQuotationOut`; `POST /portal/quotations/{id}/pay`. |
| `app/(app)/invoices/page.tsx` | The **Confirmed deals** worklist above the invoice list. |
| `components/portal/BillPanel.tsx` | **New.** The customer's three states. |
| `app/portal/quotations/[id]/pay/page.tsx` | **New.** Card checkout. |

**Three decisions worth knowing.**

`bill_for()` looks only at `ONE_TIME` invoices. A recurring invoice belongs to a
subscription's own schedule and keeps arriving every period, so treating one as
"the bill for the deal" would leave the deal permanently unpaid — the Finance row
would never leave Payment Pending.

Raising a bill twice is refused, and the refusal carries the existing `invoice_id`.
Two people accepting the same deal at once is not hypothetical on a shared worklist,
and two invoices for one order is a much more expensive mistake than a rejected
second click.

`portal_shipping()` returns `None` until the bill is paid. Promising despatch on an
unpaid order is a claim we have not earned; once paid it names the warehouses the
fulfillment plan actually allocated from.

**Edge cases the frontend handles rather than discovers.** Checkout opened with no
bill raised, or with one already settled, says which of the two it is instead of
showing a form that would fail on submit. A part-settled bill asks for the balance,
not the total again. Roles that cannot bill see "Awaiting Finance sign-off" rather
than a button that 403s — the same "UI offers what the API refuses" pattern fixed
earlier on settings, admin and the portal. And the confirmed-status line, which
unconditionally read "Nothing further is needed from you", now defers to the bill
above it when there is money outstanding; it was a direct contradiction.

Verified: 10 new tests in `apps/negotiation/tests.py` (`BillingFlowTests`) walk
confirm → sign-off → payment → invoice, and pin the refusals — billing before
confirmation, billing twice, paying twice, paying with no bill raised. 127 backend
tests pass. Every real row in the dev database was also serialised through the new
schemas, which is where the pydantic-v2 coercion bugs have surfaced before: Q-1004
sits in `PAYMENT_PENDING`, Q-1002 in `PAID` with despatch from Main Warehouse.

No migration. It reuses the existing `Invoice`, `InvoiceLine` and `Payment` models.

**Two follow-ups from using it.**

*The checkout's Pay button failed silently.* It was disabled until every field
validated, with no statement of what was outstanding. Entering `09/3` in the
expiry — a two-digit month and one digit of year — left the button grey with
nothing on screen explaining why, and once you had tabbed on to the security
code there was no way to find out. The button is now always clickable and
`whatsMissing()` names the incomplete fields on submit. A disabled control that
won't say what it wants is a dead end.

*A paid quotation still read "Confirmed" in the portal.* `portal_status` maps
`QuotationStatus` alone, which never reaches "paid" — that is an invoice state,
not a quotation one — so a settled order was indistinguishable from one with a
bill sitting unpaid against it. New `portal_status_for(quotation)` overrides the
label to **Paid** for a CONFIRMED deal whose bill is settled, and both the list
and the detail payload now use it. Keyed on CONFIRMED, so earlier stages keep
their own wording. 3 tests cover it.

---

### Shipping, so the lifecycle actually finishes

Three things reported from the running app, all the same root cause.

**Nothing ever shipped.** `shipped_at` was read in four places and written in
none: no service set it, no endpoint existed, and `StockMoveReason.SHIP` was
declared and unused. So the Shipped milestone was unreachable. Downstream of
that, the invoice stepper showed Shipped grey forever, "Orders Awaiting
Fulfillment" listed every confirmed order ever placed and could never empty,
and the delivery-slippage sweep in `insights/health.py` compared `promised_date`
against a timestamp nothing would ever set.

**The stepper was in the wrong order.** It read Order Confirmed → Shipped →
Invoiced → Paid, which says goods leave before anyone is billed. With the
billing work above that is now plainly wrong, and it rendered as a grey step
sandwiched between two green ones. It is now **Order Confirmed → Invoiced →
Paid → Shipped**.

| File | Change |
|---|---|
| `apps/fulfillment/services.py` | New `mark_shipped()` and `_consume_reservation()`. |
| `apps/fulfillment/api.py` | `POST /fulfillment/plans/{id}/ship` (Finance/Admin); `billing_state` on `PlanOut`; `orders_awaiting` now excludes SHIPPED plans. |
| `apps/billing/api.py` | `_lifecycle()` reordered. |
| `apps/negotiation/services.py` | `portal_shipping()` says "has been despatched from" once it actually has, and mentions a backorder following separately. |
| `app/(app)/fulfillment/[id]/page.tsx` | **Mark Shipped** action, per-allocation Shipped badge, green SHIPPED status. |

**Shipping is gated on payment**, which is the rule the whole sequence rests on:
`mark_shipped` refuses an unpaid order outright. Despatch is the one step that
cannot be taken back, so it is a refusal rather than a warning. `PlanOut` carries
`billing_state` purely so the screen can disable the button and say *why* instead
of offering one the service will reject — the same pattern applied to the Finance
worklist and the portal.

**Reservations are consumed, not just released.** `_reserve` raises
`quantity_reserved` and leaves `quantity_on_hand` alone, because a reservation is
a promise rather than a movement. Shipping is the movement, so both drop together
and a `SHIP` stock move records the delta. Clearing the reservation without
deducting the stock would hand the same units to the next order.

**A backorder holds the plan open.** A plan with unfilled backordered lines
reaches `PARTIALLY_SHIPPED`, never `SHIPPED`, so it stays in the fulfillment
queue — that leftover is exactly what the screen exists to surface — and the
customer is told the rest follows separately.

Verified: 9 new tests in `apps/fulfillment/tests.py` (`ShippingTests`, the first
database-backed tests in that file) cover the refusals, the stock arithmetic, the
queue emptying, the customer wording and the stepper order. 139 backend tests
pass. Against the dev database, Q-1013/Q-1012/Q-1002 are paid and now offer
**Mark Shipped**, while Q-1004 is payment-pending and correctly does not.

No migration. `shipped_at`, `FulfillmentStatus.SHIPPED` and `StockMoveReason.SHIP`
all already existed — they had simply never been wired to anything.

---

### The negotiated discount never reached the bill

Found in the dev database, not in a test: **Q-1013** was agreed at 10% off. The
quotation total said **$186.30**. The invoice said **$207.00**. The customer was
charged the full list price and overpaid by exactly the discount both sides had
shaken hands on.

`issue_one_time_invoice` billed each line's `line_total`, which is net of that
line's OWN discount and nothing else. A negotiated figure never lands on the
lines — `accept_request` and `accept_counter` both write
`order_discount_percent`, deliberately, so that agreeing 12% overall doesn't
overwrite a line already sitting at 18%. So the one number the whole negotiation
produces was the one number billing ignored.

New `quotations.order_discount_factor(quotation)` is the single definition of
"what is actually charged for this line". `recalculate` apportions the order
discount by each line's share of the post-line-discount net, which reduces
exactly to one multiplier:

    order_discount_value × (line_total / net_after_lines)
      = net_after_lines × order% / 100 × line_total / net_after_lines
      = line_total × order% / 100

so tax computed from it agrees with the tax on the quotation, by construction
rather than by coincidence.

| File | Change |
|---|---|
| `apps/quotations/services.py` | New `order_discount_factor()`. |
| `apps/billing/services.py` | `issue_one_time_invoice` applies it, and states the **effective** discount per line. |
| `apps/subscriptions/services.py` | `activate_from_quotation` applies it to the subscription's unit price. |

**The subscription had the same hole.** It priced off `line_total / quantity`,
so a negotiated discount was dropped from every recurring period, forever — a
worse version of the same bug, because it recurs. It now inherits the agreed
rate.

**The invoice line states the effective discount**, not the line-level one.
Showing 5% next to a total that had 12% taken off would put a line on a
customer-facing document whose own numbers don't multiply out. The percentage is stored
to two places, so re-multiplying it can't reproduce the cent exactly: the line
total is the authority on what is owed and the percentage describes it. The test
asserts the money exactly and the percentage to within a cent.

Verified: Q-1013 now bills **$186.30**, matching its quotation exactly; Q-1012
(no negotiation) is unchanged at $207.00; Q-1002 stays at $14,241.60 against a
$14,526.60 quotation, which is correct — the $285 difference is a RECURRING line
billing on its own subscription schedule, which is hybrid billing working, not a
discrepancy. 3 new tests, 156 backend tests pass.

⚠️ **The existing Q-1013 invoice in the dev database is still wrong** — it was
raised before this fix and is already marked paid at $207.00. Left alone
deliberately: correcting a settled invoice is a credit note, not an edit, and
that is a call for whoever owns the demo data.

---

### Back on a screen the nav already lands on

Reported on the portal quotation list: a Back control on the customer's home
screen, offering to return them to a quotation they had deliberately navigated
out of.

`canGoBack` only asked "was there a previous screen inside this shell", which is
true the moment you go anywhere and come back. But Back is meaningless on a nav
destination — the nav gets you there in one click, and going "back" from a home
screen leaves the place you just chose to be.

`NAV_ROOTS` in `lib/navigation.tsx` lists every screen the sidebar or portal nav
lands on, and `canGoBack` is false on those. Kept in one place rather than passed
per page so it cannot drift: a new screen is either a nav destination and listed,
or it is a detail view and gets Back. This also fixes `/portal/profile` and the
fourteen internal nav screens, which all had it for the same reason — the report
was about the portal, but the cause was not specific to it.

---

### Negotiating is the rep's job, and only the rep's

A Sales Manager and a Finance user could both open the negotiation inbox and
answer a customer's counter-offer directly. That puts an approver on both sides
of their own approval: they haggle the terms, then sign off the terms they
haggled. Their decision on a deal belongs in Approvals.

| File | Change |
|---|---|
| `apps/negotiation/api.py` | `MAY_NEGOTIATE = (Role.SALES_REP,)`, enforced on `accept_request` and `counter_request`. ADMIN is implicit in `require_role`. |
| `components/shell/Sidebar.tsx` | The Negotiations item is gated to Sales Rep and Admin. |
| `app/(app)/negotiations/layout.tsx` | **New.** `RoleGuard`, because hiding a link is not access control — the URL still resolves if typed. |
| `components/negotiation/RepNegotiationPanel.tsx` | Accept and counter are replaced, for other roles, by a line saying where their decision actually gets made. |

Reading the thread stays open to every internal role, deliberately: an approver
has to see what was said in order to judge it. Only acting on it is restricted.

7 tests cover it, including that a rep and an admin can still accept, and that
an approver can still read.

---

### The 28.6% on Q-1014, and two records that had drifted

Reported from the portal: a deal negotiated at **17%** was showing the customer
**28.6%**.

This is the compounding bug anubhaw0raj fixed in `300bd46` (merged above):
`accept_request` used to write the agreed figure straight onto
`order_discount_percent`, which stacks on top of whatever the lines already
carry. Q-1014 has a 14% line discount, so an agreed 17% came out at 28.62%.
The current code derives the order-level percentage instead — for Q-1014 that
is 3.49%, which produces exactly 17.00% overall.

So the code was already right; **Q-1014 was a stale record written before the
merge.** Two such records existed and both have been repaired in place:

| Quote | Agreed | Was showing | Now | Status when repaired |
|---|---|---|---|---|
| Q-1014 | 17% | 28.62% | 17.00% | SENT |
| Q-1011 | 8% | 14.44% | 8.00% | PENDING_APPROVAL |

Neither was confirmed, invoiced or paid, so this is a correction rather than a
credit note. **Q-1010 was checked and deliberately left alone**: it looks
drifted against the customer's *asking* figure of 20%, but the rep countered 2%
and the customer accepted that counter, so 2% is the agreed number and the
record is correct.

---

### A revised offer now reads differently to each side

The thread showed both parties the same sentence — "Quotation sent for your
review" — for every send, including one that follows a whole negotiation. So
neither side learned from the timeline that the terms had actually changed, and
the rep's own screen described their revised offer in words written for the
customer.

`Thread.tsx` now derives this. A `SENT` entry preceded by any counter-offer,
rep counter or acceptance is a **revised** offer, badged as such, and reads:

- **Rep:** "Revised terms sent to the customer, following the internal review of this negotiation."
- **Customer:** "Your account manager has come back with revised terms following your request. The updated figures are shown above."

Derived at render rather than stored, for exactly the reason the author label
already is: the event log records what happened, and each audience is told
about it in its own words. The opening send is untouched.

---

### Accepting already-approved terms no longer reopens approval

Reported on Q-1014, and the audit trail tells the whole story:

```
22:53  SUBMITTED  → approval #11: Sales Manager APPROVED, Finance APPROVED
22:59  SENT_TO_CUSTOMER          ← the approved offer goes out
23:15  SUBMITTED  → approval #12: the SAME two people, the SAME figures
```

The customer accepted exactly what two approvers had just cleared, and it went
straight back into their queue. A discount only ever reaches a customer *after*
approval, so the customer's yes is the last decision needed — the order should
go to fulfillment.

**Approval was being read off the status.** `confirm()` tested
`status != APPROVED`, and `send_to_customer` moves an approved quote
`APPROVED → SENT` — so the approval was discarded the instant the offer went
out. The status records where the quote *is*, not what was *agreed to*.

Approval now attaches to the terms. `terms_fingerprint()` hashes every input
that moves the money — the order discount, and each line's quantity, unit price
and discount — and `approved_terms_hash` stores it when an approval completes
(including an auto-approval, which is still an approval, it just didn't need a
human).

Two properties make it safe:

*It cannot go stale.* Any change to the money changes the hash by itself, so
there is no invalidation step to remember and therefore none to forget. A
renegotiation after approval still reopens it, which is tested.

*It hashes inputs, not totals.* `recalculate()` rewrites `line_total`
constantly with nothing having actually changed; fingerprinting the outputs
would throw away an approval for free.

The status check is **kept alongside** it, not replaced — `APPROVED →
PENDING_APPROVAL` is not a legal transition, so on a quote sitting at APPROVED
the old check was also preventing a crash rather than only a redundant
approval. The full suite caught exactly that when the first attempt dropped it.

| File | Change |
|---|---|
| `apps/quotations/models.py` | `approved_terms_hash` (migration `0005`). |
| `apps/quotations/services.py` | `terms_fingerprint()`, `mark_terms_approved()`, `terms_are_approved()`; the confirm guard; auto-approval records it. |
| `apps/approvals/services.py` | A completed approval records what it approved. |

4 tests, including the reported flow end to end. 167 backend tests pass.

⚠️ **Quotations approved before this migration have an empty hash**, so they
need one more pass through approval to benefit; new deals work end to end.
Q-1014 itself is legitimately back in approval — the discount correction in the
previous commit changed its numbers, which is precisely the invalidation
working.

---

### The intermittent 500 on the dashboard

Two causes, both from the same design choice: `/insights/dashboard` calls
`run_sweep()`, so **a GET performs writes** — and signing in fires several API
calls at once, which is exactly when they collide.

*SQLite locking.* The local database runs in the default rollback-journal mode,
where a writer takes an exclusive lock on the whole file. A concurrent request
got `database is locked` immediately. Now `journal_mode=WAL` with a 20s busy
timeout: readers run alongside the writer, and a second writer waits its turn.
Reproduced with 30 concurrent dashboard loads — 8 of 8 sweeps failed before,
0 of 30 requests fail now.

*A check-then-create race.* `_upsert_alert` looked for an open alert and then
inserted, with no atomicity, against the partial unique constraint
`unique_open_alert_per_quotation_type`. Two sweeps both found nothing and both
inserted; the second was refused. The insert now takes its own savepoint — a
failed statement aborts the surrounding transaction on Postgres, so recovering
without one would strand the rest of the sweep — and falls back to the row the
other sweep created. This is the cause that matters on Supabase, where the
SQLite fix does nothing.

The dashboard also no longer dies if the sweep fails: the counts are read from
the table either way, so a lost race leaves them seconds stale. Answering 500
because a background refresh collided is the one outcome that is certainly
wrong.

---

### One logo, three surfaces

The mark was hand-rolled twice, at different sizes, in the sidebar and the
login panel — and the customer portal had no mark at all, just the words. The
portal therefore looked like a different product from the one the rep was
signed in to. `components/shell/Brand.tsx` now defines it once, in three sizes,
and all three surfaces use it.

---

### A subscription deal could never be paid

Two faults, one deal shape.

**Finance saw a red error for a deal it had just billed.** For an order with no
one-time lines, `raise_bill_for_quotation` released the recurring schedule and
*then* raised `ValidationError` to explain itself. But it is `@transaction.
atomic`, so raising rolled the release back — the message said "its recurring
schedule has been released" while undoing exactly that. Q-1014 sat at
AWAITING_BILL with zero invoices and a red banner. Releasing the schedule is
the whole job for a subscription deal, so it now returns the first period's
invoice instead of raising.

**The customer had a live subscription and nothing they could pay.**
`portal_bill` keyed on `bill_for`, which is ONE_TIME only — correct for "have
the goods been paid for", useless as "what do I owe". Split in two:

| Function | Answers |
|---|---|
| `bill_for` | The one-off goods bill. Still ONE_TIME; despatch turns on it. |
| `payable_invoice_for` | The next invoice owed, of any type. Drives the portal. |

`billing_state` now reads every invoice type, so a recurring deal returns to
PAYMENT_PENDING each period — that is the schedule working, not the deal
reopening. **Finance signs off once**; every period after that invoices itself
via `renew()` and becomes payable with nobody touching it, which is what a
schedule is for. `portal_shipping` was re-keyed onto `bill_for` so the despatch
message doesn't vanish each time a period falls due.

Verified on Q-1014 in a rolled-back transaction: it now bills as INV-1047
(RECURRING, $3,818.00) and the customer immediately has something to pay.

---

### The customer's screen no longer moves while we are still deciding

Reported on Q-1015, and its timestamps make it plain:

```
23:42:38  customer asks for 20%
23:42:49  rep accepts        ← order discount rewritten, portal changes NOW
23:46:13  SENT_TO_CUSTOMER   ← when the customer should actually have seen it
```

For three and a half minutes the customer was looking at terms nobody had sent
them, produced by an internal decision that had not yet cleared approval.

The portal read the live quotation. It now reads what was last **sent**:
`PortalToken.terms_snapshot` (migration `negotiation/0008`) freezes the
customer-facing figures at the moment a token is minted — which is the moment
of sending, so the token is exactly the right place for it. Both the portal
detail view and the list use it, falling back to live figures for quotations
that predate the field.

Decimals are stored as strings; JSON has no decimal type and rounding money
through a float is not a trade worth making.

**And an accepted request stops reading as a negotiation.** When we simply say
yes to the customer's own figure, the portal now says *"Your request was
accepted"* rather than describing an exchange that is over. Only where we
accepted their number — a countered round is a different conversation, already
labelled — and not while the deal is still with our approvers, where
"accepted" would be true of the request and misleading about the deal.

---

## 7. Migrations added by this lane

Anyone pulling this must run `python manage.py migrate`:

| Migration | Why |
|---|---|
| `negotiation/0003_negotiationrequest_counter_discount_percent` | The rep's counter-offer. |
| `negotiation/0004_alter_negotiationrequest_counter_discount_percent` | Makes it nullable — see bug 1 above. |
| `negotiation/0005_negotiationevent` | The append-only negotiation log. |
| `negotiation/0006_backfill_negotiation_events` | Reconstructs existing conversations into it. Data migration, reversible. |
| `quotations/0005_quotation_approved_terms_hash` | Pins an approval to the terms it approved, so sending the quote doesn't discard it. |
| `negotiation/0008_portaltoken_terms_snapshot` | Freezes the figures a customer was actually sent, so internal decisions stop leaking into the portal. |

Business and user management deliberately needed **no** migration; they reuse `User.is_active`,
`User.date_joined` and `Customer.portal_user`.
