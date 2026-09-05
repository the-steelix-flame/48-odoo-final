# Plan — distance-based warehouse allocation

Owner: the-steelix-flame · Status: **Phase 1 implemented, Phases 2–4 not started**

## The problem in one paragraph

`fulfillment/planner.py` is a real algorithm, not a stub: it tries to find a single
warehouse that covers the whole order, else greedily takes the highest-coverage
warehouse, else backorders. What is fake is the number it ranks by —
`Warehouse.shipping_cost_weight`, a static constant (`Main = 1.0`, `remote = 1.4`)
that is identical no matter who the goods are going to. The suggestion is
therefore the same for a customer next door and one across the country.

Replacing that constant with a real distance from the business to each warehouse
is the whole feature. The planner's shape does not change.

---

## Phase 1 — the data and the admin surface ✅ built

No behaviour change. Nothing reads the new fields yet; this phase only makes it
possible for the later phases to be a small diff.

| Area | Change |
|---|---|
| `accounts.Customer` | `address`, `latitude`, `longitude`, `geocoded_at`. The model had **no address field at all**. |
| `fulfillment.Warehouse` | `latitude`, `longitude`, `geocoded_at`. `address` already existed as unused free text. |
| `accounts/warehouses.py` | **New** service — `create_warehouse`, `update_warehouse`, `set_active`, validation. Mirrors `plans.py`: warehouse is anubhaw0raj's model, the admin surface lives in this lane, no structural change to `fulfillment/`. |
| `accounts/admin_api.py` | `/admin/warehouses` CRUD + `/active`. Business schemas gain the address fields. |
| `/admin/warehouses` | **New** page — list, create, edit, retire/restore. |
| `/admin/businesses` | Delivery address on the create form and in the table. |

Coordinates are enterable by hand now and will be filled by the geocoder in
Phase 2. They are **nullable on purpose**: every existing customer and warehouse
row has none, and allocation must keep working for them.

### Field decisions

- `latitude`/`longitude` are `Decimal(9,6)` — ~11cm precision, enough for a depot,
  and exact, so two runs of the planner can never disagree by a float rounding.
- **Both or neither.** A row with a latitude and no longitude is refused; a
  half-located warehouse would silently rank as if it were at the equator.
- `geocoded_at` distinguishes "typed by a human" from "resolved from the address
  string", so Phase 2 can re-geocode stale rows without overwriting manual fixes.
- Retiring the **last active warehouse** is refused. `plan_split` returns
  "No active warehouses configured" and backorders the entire order, so the UI
  would let an admin break every future allocation in one click.

---

## Phase 2 — geocoding (not started)

Turn an address string into a point, **once, at write time**, and persist it.

`accounts/geocoding.py` — one function, `geocode(address) -> (lat, lng) | None`,
called from `create_business` / `update_business` / `create_warehouse` /
`update_warehouse` when the address changed and coordinates were not supplied by
hand.

- **Nominatim** (`nominatim.openstreetmap.org/search?format=json&q=…`), the same
  endpoint `aera` uses. Its policy caps callers at 1 request/second and forbids
  bulk geocoding — which is exactly why this is a write-time call on a single
  row, not a loop at allocation time.
- Requires a real `User-Agent`. Set it to the app name and a contact address.
- **Failure is not an error.** If the service is down or the address is not
  found, the row saves with null coordinates and the UI shows "not located —
  add coordinates by hand". Onboarding a business must never fail because
  OpenStreetMap is slow.
- `manage.py backfill_coordinates` for the rows that already exist, rate-limited
  to one call a second.

## Phase 3 — the planner reads distance (not started)

`planner.py` is documented as a **pure function** — no DB, no Django, no network.
That property is what makes it testable and what keeps allocation deterministic
and offline. Preserve it: the caller computes distance and passes it in.

- `common/geo.py` — `haversine_km(a, b)`, pure arithmetic, no dependency.
- `WarehouseStock` gains `distance_km: Decimal | None`.
- `services._warehouse_stock()` gains the destination and fills it in.

Then re-rank the three existing steps. **Do not replace them with nearest-first**:
the planner's stated objective #1 is fewest shipments, and pure nearest-first
breaks it — a nearest warehouse holding 1 of 10 units would split an order that
the second-nearest could ship whole.

| Step | Ranks by today | Ranks by after |
|---|---|---|
| 1 — one warehouse covers everything | lowest static weight | **nearest** such warehouse |
| 2 — greedy split | most coverage, cost breaks ties | most coverage, **distance** breaks ties |
| 3 — backorder parking | cheapest | **nearest** |

**The fallback is the feature's safety net.** When either side has no
coordinates, that warehouse ranks by `shipping_cost_weight` exactly as today, and
the plan's `notes` says so — "ranked by cost weight; no address on file for
Acme Corp". A partially-geocoded database must degrade to current behaviour,
never to a wrong answer stated confidently.

## Phase 4 — showing the reasoning (not started)

The suggestion is only trustworthy if it explains itself. On the fulfillment
plan screen: distance per allocation, and a note naming the rule that fired
("Main Warehouse is 12 km away and can cover the whole order — single shipment").

Optional, last: road distance via OSRM instead of straight-line, cached per
(warehouse, customer) pair. Straight-line already makes the ranking real;
road distance only makes it prettier, and `router.project-osrm.org` is a
no-guarantees demo server that must never sit in the allocation path.

---

## Notes for the others

**@anubhaw0raj** — Phase 1 adds two nullable columns to `Warehouse` and touches
nothing else in `fulfillment/`. `planner.py` and `services.py` are unchanged and
still pass. Phase 3 does change `plan_split`'s ranking; that one is worth
reviewing together before it lands.

**@sinjeki** — `Customer` gains four nullable fields. Additive only.
