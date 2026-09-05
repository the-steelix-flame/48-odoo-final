"use client";

/** Screen 14 — Deal health & anomaly dashboard.  Owner: anubhaw0raj. */

import Link from "next/link";

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
  StatCard,
  Table,
} from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { dateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { DealHealth, QuotationStatus, Role } from "@/types";

const SEVERITY_TONE: Record<string, string> = { LOW: "slate", MEDIUM: "amber", HIGH: "red" };

/** Mirrors the approval chain: only these roles ever decide a flagged quote. */
const MAY_DECIDE: Role[] = ["SALES_MANAGER", "FINANCE", "ADMIN"];

/**
 * The four stages a deal passes through, as stored on `Quotation.status`.
 *
 * SENT and UNDER_NEGOTIATION both sit at the Approved stage — the quote has
 * cleared its approvals and is with the customer. They are not separate steps
 * on this track, but the label below still shows the real status so a manager
 * can tell "waiting on the customer" from "customer is arguing".
 */
const STAGES = ["Draft", "Pending", "Approved", "Confirmed"] as const;

function stageIndex(status: QuotationStatus): number {
  switch (status) {
    case "DRAFT":
      return 0;
    case "PENDING_APPROVAL":
      return 1;
    case "APPROVED":
    case "SENT":
    case "UNDER_NEGOTIATION":
      return 2;
    case "CONFIRMED":
      return 3;
    default:
      return -1; // REJECTED / CANCELLED never reach the track
  }
}

function StageTrack({ status }: { status: QuotationStatus }) {
  const active = stageIndex(status);

  // A dead deal has no progress to show; saying so beats a track of grey dots.
  if (active === -1) {
    return <Badge tone="red">{titleCase(status)}</Badge>;
  }

  return (
    <div className="flex items-center gap-[6px]" title={titleCase(status)}>
      <div className="flex items-center">
        {STAGES.map((stage, index) => (
          <div key={stage} className="flex items-center">
            {index > 0 && (
              <span
                className={`block h-[2px] w-[13px] ${
                  index <= active ? "bg-[#0891B2]" : "bg-[#E2E8F0]"
                }`}
              />
            )}
            {index < active ? (
              <span className="block h-[8px] w-[8px] rounded-full bg-[#0891B2]" />
            ) : index === active ? (
              // the live stage pulses, using the shell's own keyframe
              <span className="block h-[9px] w-[9px] animate-dfPulse rounded-full bg-[#0891B2] ring-[3px] ring-[#0891B2]/25" />
            ) : (
              <span className="block h-[8px] w-[8px] rounded-full bg-[#E2E8F0]" />
            )}
          </div>
        ))}
      </div>
      <span className="text-[11px] whitespace-nowrap text-[#64748B]">{titleCase(status)}</span>
    </div>
  );
}

export default function DealHealthPage() {
  const { role } = useAuth();
  const { data, error, loading, reload } = useApi<DealHealth>("/insights/deal-health");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const mayDecide = role !== null && MAY_DECIDE.includes(role);

  return (
    <>
      <PageHeader
        title="Deal Health and Anomaly Dashboard"
        subtitle="Real-time flags for stalled deals and unusual discount patterns."
      />

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
          <Table
            columns={["Deal", "Customer", "Issue", "Severity", "Stage", "Flagged", "Action"]}
          >
            {data.alerts.map((alert) => (
              <Row key={alert.id}>
                <Cell>
                  <Link
                    href={`/quotations/${alert.quotation_id}`}
                    className="font-heading font-medium text-[#0891B2] hover:underline"
                  >
                    {alert.quotation_number}
                  </Link>
                </Cell>
                <Cell>{alert.customer_name}</Cell>
                <Cell>
                  <span className="text-[#334155]">{alert.message}</span>
                  <span className="ml-[8px] text-[11px] text-[#64748B]">
                    {titleCase(alert.alert_type)}
                  </span>
                </Cell>
                <Cell>
                  <Badge tone={SEVERITY_TONE[alert.severity]}>{titleCase(alert.severity)}</Badge>
                </Cell>
                <Cell>
                  <StageTrack status={alert.quotation_status} />
                </Cell>
                <Cell className="text-[#64748B]">{dateTime(alert.detected_at)}</Cell>
                <Cell>
                  {alert.approval_request_id && mayDecide ? (
                    <Link
                      href={`/approvals/${alert.approval_request_id}`}
                      className="text-[12px] font-medium whitespace-nowrap text-[#0891B2] hover:underline"
                    >
                      Review approval &rarr;
                    </Link>
                  ) : alert.approval_request_id ? (
                    <span className="text-[11px] whitespace-nowrap text-[#64748B]">
                      Sales Manager / Finance decide
                    </span>
                  ) : (
                    <Link
                      href={`/quotations/${alert.quotation_id}`}
                      className="text-[12px] font-medium whitespace-nowrap text-[#0891B2] hover:underline"
                    >
                      Open quotation &rarr;
                    </Link>
                  )}
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
            The Stage column reads the quotation&apos;s own status, so this dashboard says not just
            that a deal is at risk but where it is stuck — waiting on an approver reads very
            differently from waiting on the customer.
          </Note>
          <Note>
            Only a Sales Manager or Finance can decide a flagged quote, so only they get the
            Review approval link. The same rule is enforced on the server.
          </Note>
        </div>
      </Card>
    </>
  );
}
