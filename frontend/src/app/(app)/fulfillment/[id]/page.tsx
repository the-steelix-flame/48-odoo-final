"use client";

/** Screen 8 — Fulfillment detail / warehouse split.  Owner: anubhaw0raj. */

import { use, useState } from "react";

import { ApiError, post } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  ErrorState,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
} from "@/components/ui";
import { date, money } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { FulfillmentPlan } from "@/types";

export default function FulfillmentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload, setData } = useApi<FulfillmentPlan>(
    `/fulfillment/plans/${id}`,
  );

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const backorders = data.allocations.filter((a) => a.is_backorder);
  const shipping = data.allocations.filter((a) => !a.is_backorder);
  const canAccept = data.status === "SUGGESTED" || data.status === "OVERRIDDEN";

  async function accept() {
    setBusy(true);
    setActionError(null);
    try {
      setData(await post<FulfillmentPlan>(`/fulfillment/plans/${id}/accept`));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not accept the split");
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
          <p className="mt-2 text-2xl font-semibold text-slate-100">
            {data.estimated_shipments}
          </p>
          <p className="mt-1 text-xs text-slate-500">Minimised first, then cost</p>
        </div>
        <div className="rounded-xl border border-edge bg-surface p-5">
          <p className="text-xs uppercase tracking-wide text-slate-400">Estimated cost</p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">
            {money(data.estimated_cost)}
          </p>
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
              <Button onClick={accept} disabled={busy}>
                Accept Suggested Split
              </Button>
              {/* TODO(anubhaw0raj): the override modal posts
                  {allocations:[{quotation_line_id, warehouse_id, quantity}]}
                  to /fulfillment/plans/{id}/override. Backend is ready. */}
              <Button variant="secondary" disabled>
                Manual Override
              </Button>
            </>
          ) : null
        }
      >
        <Table
          columns={["Warehouse", "Line", "Qty Fulfilled", "Promised", "Shipped", "Status"]}
        >
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

        <div className="mt-4 space-y-2">
          {data.consolidation_available && (
            <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 px-4 py-3">
              <p className="text-sm text-emerald-300">
                Stock has arrived — the remaining backorder can now be filled.
              </p>
              <div className="mt-2">
                {/* TODO(anubhaw0raj): POST a consolidate endpoint that re-plans
                    only the backordered allocations. */}
                <Button variant="success" className="!px-3 !py-1 text-xs" disabled>
                  Consolidate Remaining Backorder
                </Button>
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
    </>
  );
}
