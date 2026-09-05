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

### 2.1 🔴 BLOCKER — `POST /api/quotations/{id}/confirm` returns HTTP 500

**Owner: @the-steelix-flame (`apps/quotations/api.py`)**

```
TypeError: Object of type QuotationLine is not JSON serializable
```

`confirm_quotation` (`apps/quotations/api.py:155`) is the **only** state-changing endpoint in that
router without a `response=` schema. Every sibling declares `response=QuotationDetailOut`, which
routes the payload through Pydantic. Without it, Ninja falls back to raw `json.dumps`, and
`_detail()` (line 29) hands it live Django model instances — `lines=list(...)`, `events=list(...)`.

**This is worse than an ordinary 500.** The confirm *commits first*, then fails while serialising.
Confirmed on Q-1003: status went to `CONFIRMED`, fulfillment plan #2 was created and invoice
INV-1039 was issued — **and the caller still received a 500.** In a demo the rep clicks Confirm,
sees an error, clicks again, and gets `409 Cannot move a quotation from CONFIRMED to CONFIRMED`.
It looks like the system is broken when the data is actually correct.

This blocks the entire H8 integration checkpoint (`confirm → split → invoice`).

Suggested fix — declare a response schema:

```python
class ConfirmOut(Schema):
    confirmed: bool
    quotation: QuotationDetailOut
    fulfillment_plan_id: int | None = None
    subscription_ids: list[int] = []
    invoice_id: int | None = None
    reason: str | None = None

@router.post("/{quotation_id}/confirm", response=ConfirmOut)
```

Reproduce:
```bash
curl -X POST localhost:8000/api/quotations/<a DRAFT or APPROVED id>/confirm \
     -H "Authorization: Bearer <token>"
```

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
| 1 | Fix the `confirm` 500 — add a `response=` schema (§2.1) | @the-steelix-flame | 🔴 blocker |
| 2 | **Re-run `python manage.py migrate`** — new `fulfillment/0003` migration | everyone | 🔴 do now |
| 3 | Set East Depot `lead_time_days = 6` in `seed_demo` so the split visibly trades cost against speed | @sinjeki | 🟡 demo quality |
| 4 | Decide the risk-band mismatch vs the mockup (§2.6) | @the-steelix-flame | 🟡 |
| 5 | `DEBUG=False` + real `SECRET_KEY` before any deploy (§2.2) | whoever deploys | 🟡 pre-deploy |
| 6 | Agree whether `suggest_plan` should require `CONFIRMED` (§2.3) | @anubhaw0raj + team | 🟢 |
| 7 | Promote the fulfillment override modal to a shared `Modal` component | @sinjeki | 🟢 optional |

### Still unverified in my lane (highest remaining risk)

**Hybrid billing has not been proven end to end.** Q-1003 had no `RECURRING` lines, so no
subscription was created and the one-time/recurring split was never exercised. That is one of the
five "never cut" graded items in `IMPLEMENTATION.md` §4. It needs a quotation containing **both** a
one-time product and a subscription product, confirmed end to end, producing separate invoices.
**Blocked behind §2.1** — I cannot confirm an order over the API until `confirm` stops 500-ing.

Also not yet exercised: Record Payment (screen 13) and the cancellation credit note (screen 10).
Both are implemented; neither has been run.
