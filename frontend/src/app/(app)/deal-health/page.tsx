"use client";

/** Screen 14 — Deal health & anomaly dashboard.  Owner: anubhaw0raj. */

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
  StatCard,
  Table,
} from "@/components/ui";
import { dateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { DealHealth } from "@/types";

const SEVERITY_TONE: Record<string, string> = { LOW: "slate", MEDIUM: "amber", HIGH: "red" };

export default function DealHealthPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<DealHealth>("/insights/deal-health");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  async function act(alertId: number, actionType: "NUDGE" | "ESCALATE") {
    setBusy(true);
    setActionError(null);
    try {
      await post(`/insights/alerts/${alertId}/act`, { action_type: actionType, note: "" });
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not record that action");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Deal Health and Anomaly Dashboard"
        subtitle="Real-time flags for stalled deals and unusual discount patterns."
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <StatCard
          label="Stalled Deals"
          value={data.stalled_count}
          hint="Quotes idle past the configured threshold"
          tone={data.stalled_count > 0 ? "red" : "slate"}
        />
        <StatCard
          label="Discount Anomalies"
          value={data.anomaly_count}
          hint="Above the rep's own trailing average"
          tone={data.anomaly_count > 0 ? "red" : "slate"}
        />
        <StatCard
          label="Delivery Slippage"
          value={data.slippage_count}
          hint="Promise dates at risk"
          tone={data.slippage_count > 0 ? "red" : "slate"}
        />
      </div>

      <Card title="Open alerts">
        {data.alerts.length === 0 ? (
          <EmptyState
            title="Nothing at risk right now"
            hint="Alerts appear here as deals go quiet or discounts drift from a rep's norm."
          />
        ) : (
          <Table columns={["Deal", "Customer", "Issue", "Severity", "Flagged", "Action"]}>
            {data.alerts.map((alert) => (
              <Row key={alert.id}>
                <Cell>
                  <button
                    onClick={() => router.push(`/quotations/${alert.quotation_id}`)}
                    className="font-medium text-brand hover:underline"
                  >
                    {alert.quotation_number}
                  </button>
                </Cell>
                <Cell>{alert.customer_name}</Cell>
                <Cell>
                  <span className="text-slate-300">{alert.message}</span>
                  <span className="ml-2 text-xs text-slate-500">
                    {titleCase(alert.alert_type)}
                  </span>
                </Cell>
                <Cell>
                  <Badge tone={SEVERITY_TONE[alert.severity]}>{titleCase(alert.severity)}</Badge>
                </Cell>
                <Cell className="text-slate-400">{dateTime(alert.detected_at)}</Cell>
                <Cell>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      className="!px-3 !py-1 text-xs"
                      disabled={busy}
                      onClick={() => act(alert.id, "NUDGE")}
                    >
                      Nudge Rep
                    </Button>
                    <Button
                      variant="danger"
                      className="!px-3 !py-1 text-xs"
                      disabled={busy}
                      onClick={() => act(alert.id, "ESCALATE")}
                    >
                      Escalate
                    </Button>
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4 space-y-2">
          <Note>
            Anomaly detection is relative to the rep, not absolute. A 22% discount from someone who
            averages 8% is a signal; the same 22% from a rep who averages 20% is not.
          </Note>
          <Note>
            Nudging or escalating writes to the deal&apos;s own audit trail as well as the alert, so
            the action shows up in the quotation&apos;s history — not just on this dashboard.
          </Note>
        </div>
      </Card>
    </>
  );
}
