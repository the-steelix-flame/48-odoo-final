"use client";

/** Screen 8 — Fulfillment detail / warehouse split.  Owner: anubhaw0raj. */

import { use, useMemo, useState } from "react";

import { ApiError, post } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  EmptyState,
  ErrorState,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { date, money } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Allocation, FulfillmentPlan, Role, Warehouse } from "@/types";

/**
 * Mirrors `require_role(FINANCE)` on the backend; ADMIN is implicit there.
 * Accepting a split is not a read-only act — it moves stock into `reserved`,
 * making it unavailable to every other open deal — so it carries the same
 * guard as overriding one. The brief puts warehouse splits and backorder
 * decisions with the Finance / Operations user.
 */
const MAY_MANAGE_FULFILMENT: Role[] = ["FINANCE", "ADMIN"];
const NEEDS_FINANCE = "Only Finance or Admin can commit stock";

type DraftRow = {
  key: string;
  quotation_line_id: number;
  warehouse_id: number;
  quantity: number;
};

let seq = 0;
const nextKey = () => `row-${(seq += 1)}`;

/** Collapse allocations back into the order lines they came from. */
function orderLines(allocations: Allocation[]) {
  const byLine = new Map<number, { id: number; description: string; ordered: number }>();
  for (const a of allocations) {
    const found = byLine.get(a.quotation_line_id);
    if (found) found.ordered += a.quantity;
    else
      byLine.set(a.quotation_line_id, {
        id: a.quotation_line_id,
        description: a.line_description,
        ordered: a.quantity,
      });
  }
  return [...byLine.values()];
}

// ---------------------------------------------------------------- override modal
function OverrideModal({
  plan,
  warehouses,
  onCancel,
  onSaved,
}: {
  plan: FulfillmentPlan;
  warehouses: Warehouse[];
  onCancel: () => void;
  onSaved: (next: FulfillmentPlan) => void;
}) {
  const lines = useMemo(() => orderLines(plan.allocations), [plan.allocations]);
  const [rows, setRows] = useState<DraftRow[]>(() =>
    plan.allocations.map((a) => ({
      key: nextKey(),
      quotation_line_id: a.quotation_line_id,
      warehouse_id: a.warehouse_id,
      quantity: a.quantity,
    })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allocated = (lineId: number) =>
    rows
      .filter((r) => r.quotation_line_id === lineId)
      .reduce((sum, r) => sum + (r.quantity || 0), 0);

  // The backend turns anything unavailable into a backorder, but it does NOT
  // check that the whole ordered quantity was allocated. Dropping units here
  // would silently under-ship the order, so we refuse to submit a mismatch.
  const mismatched = lines.filter((l) => allocated(l.id) !== l.ordered);
  const nonPositive = rows.some((r) => !r.quantity || r.quantity <= 0);
  const blocked = rows.length === 0 || nonPositive || mismatched.length > 0;

  function update(key: string, patch: Partial<DraftRow>) {
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => [
      ...prev,
      {
        key: nextKey(),
        quotation_line_id: lines[0]?.id ?? 0,
        warehouse_id: warehouses[0]?.id ?? 0,
        quantity: 1,
      },
    ]);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const next = await post<FulfillmentPlan>(`/fulfillment/plans/${plan.id}/override`, {
        allocations: rows.map((r) => ({
          quotation_line_id: r.quotation_line_id,
          warehouse_id: r.warehouse_id,
          quantity: r.quantity,
        })),
      });
      onSaved(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the override");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 sm:p-8"
      role="dialog"
      aria-modal="true"
      aria-label="Manual override"
    >
      <div className="w-full max-w-3xl rounded-xl border border-edge bg-surface shadow-2xl">
        <div className="border-b border-edge px-5 py-4">
          <h2 className="text-base font-semibold text-slate-100">Manual override</h2>
          <p className="mt-1 text-xs text-slate-400">
            You decide who ships what. The override is recorded against your name — overrides are
            allowed, unrecorded overrides are not.
          </p>
        </div>

        <div className="space-y-4 px-5 py-4">
          {error && <ErrorState message={error} />}

          <div className="rounded-lg border border-edge bg-black/20 px-4 py-3">
            <p className="mb-2 text-xs uppercase tracking-wide text-slate-400">
              Ordered quantities
            </p>
            <ul className="space-y-1 text-sm">
              {lines.map((l) => {
                const got = allocated(l.id);
                const ok = got === l.ordered;
                return (
                  <li key={l.id} className="flex items-center justify-between gap-3">
                    <span className="text-slate-300">{l.description}</span>
                    <span className={ok ? "text-emerald-400" : "text-amber-400"}>
                      {got} / {l.ordered} allocated
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          <Table columns={["Line", "Warehouse", "Qty", ""]}>
            {rows.map((r) => (
              <Row key={r.key}>
                <Cell>
                  <select
                    className={inputClass}
                    value={r.quotation_line_id}
                    onChange={(e) => update(r.key, { quotation_line_id: Number(e.target.value) })}
                  >
                    {lines.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.description}
                      </option>
                    ))}
                  </select>
                </Cell>
                <Cell>
                  <select
                    className={inputClass}
                    value={r.warehouse_id}
                    onChange={(e) => update(r.key, { warehouse_id: Number(e.target.value) })}
                  >
                    {warehouses.map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}
                      </option>
                    ))}
                  </select>
                </Cell>
                <Cell>
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={r.quantity}
                    onChange={(e) => update(r.key, { quantity: Number(e.target.value) })}
                  />
                </Cell>
                <Cell>
                  <button
                    type="button"
                    onClick={() => setRows((prev) => prev.filter((x) => x.key !== r.key))}
                    className="text-xs text-slate-400 underline hover:text-red-400"
                  >
                    Remove
                  </button>
                </Cell>
              </Row>
            ))}
          </Table>

          <Button variant="secondary" onClick={addRow} className="!px-3 !py-1 text-xs">
            + Add allocation row
          </Button>

          {mismatched.length > 0 && (
            <Note>
              Every line must be fully allocated before this can be saved.{" "}
              {mismatched.map((l) => l.description).join(", ")}{" "}
              {mismatched.length === 1 ? "does" : "do"} not add up to the ordered quantity. Send
              units to a warehouse with no stock and they become a recorded backorder — dropping
              them records nothing.
            </Note>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-edge px-5 py-4">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={save} disabled={busy || blocked}>
            {busy ? "Saving…" : "Save override"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- page
export default function FulfillmentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { role } = useAuth();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [overriding, setOverriding] = useState(false);

  const { data, error, loading, reload, setData } = useApi<FulfillmentPlan>(
    `/fulfillment/plans/${id}`,
  );
  const { data: warehouses } = useApi<Warehouse[]>("/fulfillment/warehouses");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const backorders = data.allocations.filter((a) => a.is_backorder);
  const shipping = data.allocations.filter((a) => !a.is_backorder);
  const canAccept = data.status === "SUGGESTED" || data.status === "OVERRIDDEN";
  const mayManage = role !== null && MAY_MANAGE_FULFILMENT.includes(role);

  async function run(path: string, fallback: string) {
    setBusy(true);
    setActionError(null);
    try {
      setData(await post<FulfillmentPlan>(path));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`Fulfillment — ${data.quotation_number}`}
        subtitle={data.customer_name}
        actions={
          <>
            <Badge tone={data.status === "BACKORDER" ? "red" : "blue"}>
              {data.status.replace(/_/g, " ")}
            </Badge>
            {data.is_manual_override && <Badge tone="amber">Manually overridden</Badge>}
          </>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-edge bg-surface p-5">
          <p className="text-xs uppercase tracking-wide text-slate-400">Shipments</p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">{data.estimated_shipments}</p>
          <p className="mt-1 text-xs text-slate-500">Minimised first, then cost</p>
        </div>
        <div className="rounded-xl border border-edge bg-surface p-5">
          <p className="text-xs uppercase tracking-wide text-slate-400">Estimated cost</p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">{money(data.estimated_cost)}</p>
          <p className="mt-1 text-xs text-slate-500">Base cost × warehouse weight</p>
        </div>
        <div className="rounded-xl border border-edge bg-surface p-5">
          <p className="text-xs uppercase tracking-wide text-slate-400">Backordered lines</p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">{backorders.length}</p>
          <p className="mt-1 text-xs text-slate-500">
            {backorders.length === 0 ? "Fully covered by stock" : "Awaiting restock"}
          </p>
        </div>
      </div>

      <Card
        title="Recommended split"
        subtitle="Based on live stock at the moment this plan was computed"
        actions={
          canAccept ? (
            <>
              <span title={mayManage ? undefined : NEEDS_FINANCE}>
                <Button
                  onClick={() =>
                    run(`/fulfillment/plans/${id}/accept`, "Could not accept the split")
                  }
                  disabled={busy || !mayManage || data.allocations.length === 0}
                >
                  Accept Suggested Split
                </Button>
              </span>
              <span title={mayManage ? undefined : NEEDS_FINANCE}>
                <Button
                  variant="secondary"
                  onClick={() => setOverriding(true)}
                  disabled={busy || !mayManage || !warehouses?.length || data.allocations.length === 0}
                >
                  Manual Override
                </Button>
              </span>
            </>
          ) : null
        }
      >
        {data.allocations.length === 0 ? (
          <EmptyState
            title="Nothing on this order needs shipping"
            hint="Every line is a subscription or service, so there is no physical stock to allocate. Billing still runs on its own schedule."
          />
        ) : (
        <Table columns={["Warehouse", "Line", "Qty Fulfilled", "Promised", "Shipped", "Status"]}>
          {[...shipping, ...backorders].map((allocation) => (
            <Row key={allocation.id}>
              <Cell className="font-medium text-slate-100">{allocation.warehouse_name}</Cell>
              <Cell>{allocation.line_description}</Cell>
              <Cell>{allocation.quantity} units</Cell>
              <Cell className="text-slate-400">{date(allocation.promised_date)}</Cell>
              <Cell className="text-slate-400">{date(allocation.shipped_at)}</Cell>
              <Cell>
                {allocation.is_backorder ? (
                  <Badge tone="red">Backorder</Badge>
                ) : (
                  <Badge tone="green">Allocated</Badge>
                )}
              </Cell>
            </Row>
          ))}
        </Table>
        )}

        <div className="mt-4 space-y-2">
          {data.consolidation_available && (
            <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 px-4 py-3">
              <p className="text-sm text-emerald-300">
                Stock has arrived — the remaining backorder can now be filled.
              </p>
              <div className="mt-2">
                <span title={mayManage ? undefined : NEEDS_FINANCE}>
                  <Button
                    variant="success"
                    className="!px-3 !py-1 text-xs"
                    disabled={busy || !mayManage}
                    onClick={() =>
                      run(
                        `/fulfillment/plans/${id}/consolidate`,
                        "Could not consolidate the backorder",
                      )
                    }
                  >
                    Consolidate Remaining Backorder
                  </Button>
                </span>
              </div>
            </div>
          )}
          <Note>
            The planner tries a single warehouse first — that step is exact. Only when no one
            warehouse can cover the order does it fall back to a greedy multi-warehouse split, and
            anything still short becomes a backorder rather than silently vanishing.
          </Note>
        </div>
      </Card>

      {overriding && warehouses && (
        <OverrideModal
          plan={data}
          warehouses={warehouses}
          onCancel={() => setOverriding(false)}
          onSaved={(next) => {
            setData(next);
            setOverriding(false);
          }}
        />
      )}
    </>
  );
}
