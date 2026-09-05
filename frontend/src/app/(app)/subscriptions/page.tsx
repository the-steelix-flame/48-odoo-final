"use client";

/** Screen 9 — Subscriptions list.  Owner: anubhaw0raj. */

import { useRouter } from "next/navigation";

import {
  Badge,
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
import { date, money, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { RecurringPlanT, SubscriptionRow } from "@/types";

type Counts = { active: number; paused: number; cancelled: number };

const STATUS_TONE: Record<string, string> = {
  ACTIVE: "green",
  PAUSED: "amber",
  CANCELLED: "red",
};

export default function SubscriptionsPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<SubscriptionRow[]>("/subscriptions/");
  const { data: counts } = useApi<Counts>("/subscriptions/counts");
  const { data: plans } = useApi<RecurringPlanT[]>("/subscriptions/plans");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const rows = data ?? [];

  return (
    <>
      <PageHeader
        title="Subscriptions"
        subtitle="Every recurring plan across every customer, regardless of which order it came from."
      />

      <div className="mb-5 flex flex-wrap gap-2">
        <Badge tone="green">{counts?.active ?? 0} Active</Badge>
        <Badge tone="amber">{counts?.paused ?? 0} Paused</Badge>
        <Badge tone="red">{counts?.cancelled ?? 0} Cancelled</Badge>
      </div>

      <Card className="mb-6">
        {rows.length === 0 ? (
          <EmptyState
            title="No subscriptions yet"
            hint="Confirm an order containing a recurring product and it appears here."
          />
        ) : (
          <Table
            columns={["Customer", "Plan", "Cycle", "Qty", "Per period", "Next Bill", "Status"]}
          >
            {rows.map((row) => (
              <Row key={row.id} onClick={() => router.push(`/subscriptions/${row.id}`)}>
                <Cell className="font-heading font-medium text-[#0F172A]">{row.customer_name}</Cell>
                <Cell>{row.plan_name}</Cell>
                <Cell>{titleCase(row.interval)}</Cell>
                <Cell>{Number(row.quantity)}</Cell>
                <Cell>{money(row.period_amount)}</Cell>
                <Cell>{date(row.next_bill_date)}</Cell>
                <Cell>
                  <Badge tone={STATUS_TONE[row.status]}>{titleCase(row.status)}</Badge>
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        <div className="mt-4">
          <Note>
            Click a subscription row to open its billing detail and proration history.
          </Note>
        </div>
      </Card>

      <Card title="Recurring plans" subtitle="Configured by the admin (screen A5)">
        <Table
          columns={["Plan", "Interval", "Proration", "Cancellation", "Refund", "Billed"]}
        >
          {(plans ?? []).map((plan) => (
            <Row key={plan.id}>
              <Cell className="font-heading font-medium text-[#0F172A]">{plan.name}</Cell>
              <Cell>{titleCase(plan.interval)}</Cell>
              <Cell>{titleCase(plan.proration_mode)}</Cell>
              <Cell>{titleCase(plan.cancellation_policy)}</Cell>
              <Cell>{titleCase(plan.refund_mode)}</Cell>
              <Cell>{plan.bill_in_advance ? "In advance" : "In arrears"}</Cell>
            </Row>
          ))}
        </Table>
      </Card>
    </>
  );
}
