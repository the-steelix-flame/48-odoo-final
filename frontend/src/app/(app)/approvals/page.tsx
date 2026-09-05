"use client";

/** Screen 5 — Approvals list.  Owner: the-steelix-flame. */

import { useState } from "react";
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
import { RISK_TONE, dateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { ApprovalRow } from "@/types";

type Counts = { pending: number; returned: number; approved: number; rejected: number };

export default function ApprovalsPage() {
  const router = useRouter();
  const [pendingOnly, setPendingOnly] = useState(false);

  const { data, error, loading, reload } = useApi<ApprovalRow[]>(
    pendingOnly ? "/approvals/?status=PENDING" : "/approvals/",
  );
  const { data: counts } = useApi<Counts>("/approvals/counts");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const rows = data ?? [];

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Every quotation that needed, needs, or is going through discount approval."
      />

      <div className="mb-5 flex flex-wrap gap-2">
        <Badge tone="amber">{counts?.pending ?? 0} Pending</Badge>
        <Badge tone="red">{counts?.returned ?? 0} Returned</Badge>
        <Badge tone="green">{counts?.approved ?? 0} Approved</Badge>
        <button
          onClick={() => setPendingOnly((value) => !value)}
          className="rounded-lg border border-edge px-3 py-0.5 text-xs text-slate-300 hover:bg-white/5"
        >
          {pendingOnly ? "Show all" : "Filter: Pending only"}
        </button>
      </div>

      <Card>
        {rows.length === 0 ? (
          <EmptyState
            title="Nothing to approve"
            hint="Quotations that stay within every ceiling are auto-approved and never appear here."
          />
        ) : (
          <Table
            columns={["Quotation", "Customer", "Tier", "Blended Risk", "Stage", "Assigned To", "Status", "Raised"]}
          >
            {rows.map((row) => (
              <Row key={row.id} onClick={() => router.push(`/approvals/${row.id}`)}>
                <Cell className="font-medium text-slate-100">{row.quotation_number}</Cell>
                <Cell>{row.customer_name}</Cell>
                <Cell>{row.customer_tier}</Cell>
                <Cell>
                  <Badge tone={RISK_TONE[row.risk_band]}>
                    {row.risk_band} · {row.risk_score}
                  </Badge>
                </Cell>
                <Cell>
                  {row.chain.length === 0 ? (
                    <span className="text-slate-500">Auto-approved</span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-1">
                      {row.chain.map((role, index) => (
                        <span key={role} className="flex items-center gap-1">
                          {index > 0 && <span className="text-slate-600">&rarr;</span>}
                          <span
                            className={
                              index + 1 === row.current_step_number
                                ? "font-semibold text-amber-300"
                                : "text-slate-500"
                            }
                          >
                            {titleCase(role)}
                          </span>
                        </span>
                      ))}
                      {row.total_steps > 1 && row.current_step_number ? (
                        <span className="ml-1 text-xs text-slate-500">
                          ({row.current_step_number} of {row.total_steps})
                        </span>
                      ) : null}
                    </span>
                  )}
                </Cell>
                <Cell>{row.assigned_to ?? "—"}</Cell>
                <Cell>
                  <Badge
                    tone={
                      row.status === "APPROVED"
                        ? "green"
                        : row.status === "REJECTED"
                          ? "red"
                          : "amber"
                    }
                  >
                    {titleCase(row.status)}
                  </Badge>
                </Cell>
                <Cell className="text-slate-400">{dateTime(row.created_at)}</Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Click any row to open its full approval detail, risk breakdown and audit trail.
          </Note>
        </div>
      </Card>
    </>
  );
}
