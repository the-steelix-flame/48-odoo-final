"use client";

/** Screen 7 — Fulfillment & stock list.  Owner: anubhaw0raj. */

import { useState } from "react";
import { useRouter } from "next/navigation";

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
} from "@/components/ui";
import { useApi } from "@/lib/useApi";
import type { OrderAwaiting, StockRow } from "@/types";

export default function FulfillmentPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data: stock, error, loading, reload } = useApi<StockRow[]>("/fulfillment/stock");
  const { data: orders, reload: reloadOrders } = useApi<OrderAwaiting[]>("/fulfillment/orders");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  async function openPlan(order: OrderAwaiting) {
    if (order.plan_id) {
      router.push(`/fulfillment/${order.plan_id}`);
      return;
    }
    // No plan yet — compute the suggested split now, then open it.
    setBusy(true);
    setActionError(null);
    try {
      const plan = await post<{ id: number }>(
        `/fulfillment/quotations/${order.quotation_id}/plan`,
      );
      await reloadOrders();
      router.push(`/fulfillment/${plan.id}`);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not plan this order");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Fulfillment and Stock"
        subtitle="Live stock per warehouse, plus every order that still needs fulfilling."
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <Card title="Stock by warehouse" className="mb-6">
        {(stock ?? []).length === 0 ? (
          <EmptyState title="No stock rows" hint="Seed the demo data to populate warehouses." />
        ) : (
          <Table
            columns={["Warehouse", "Product", "In Stock", "Reserved", "Available", "Replenish"]}
          >
            {(stock ?? []).map((row) => (
              <Row key={row.id}>
                <Cell className="font-heading font-medium text-[#0F172A]">{row.warehouse_name}</Cell>
                <Cell>{row.product_name}</Cell>
                <Cell>{row.quantity_on_hand}</Cell>
                <Cell>{row.quantity_reserved}</Cell>
                <Cell className="font-medium text-[#0F172A]">{row.available}</Cell>
                <Cell>
                  {row.needs_replenishment ? (
                    <Badge tone="amber">Below reorder point</Badge>
                  ) : (
                    <Badge tone="green">OK</Badge>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        <div className="mt-4">
          <Note>
            Available = in stock − reserved. It is computed, never stored — the split planner reads
            this column directly.
          </Note>
        </div>
      </Card>

      <Card title="Orders Awaiting Fulfillment">
        {(orders ?? []).length === 0 ? (
          <EmptyState
            title="Nothing to ship"
            hint="Confirm a quotation and it appears here with a suggested warehouse split."
          />
        ) : (
          <Table columns={["Order", "Customer", "Status", "Warehouses", ""]}>
            {(orders ?? []).map((order) => (
              <Row key={order.quotation_id}>
                <Cell className="font-heading font-medium text-[#0F172A]">{order.quotation_number}</Cell>
                <Cell>{order.customer_name}</Cell>
                <Cell>
                  <Badge
                    tone={
                      order.status === "BACKORDER"
                        ? "red"
                        : order.status === "ACCEPTED"
                          ? "green"
                          : "amber"
                    }
                  >
                    {order.status.replace(/_/g, " ")}
                  </Badge>
                </Cell>
                <Cell>{order.warehouses}</Cell>
                <Cell>
                  <Button
                    variant="secondary"
                    disabled={busy}
                    className="!px-3 !py-1 text-xs"
                    onClick={() => openPlan(order)}
                  >
                    {order.plan_id ? "Open split" : "Plan split"}
                  </Button>
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
