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
