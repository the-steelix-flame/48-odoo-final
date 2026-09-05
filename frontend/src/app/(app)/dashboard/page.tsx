"use client";

/** Screen 2 — Sales Dashboard / Home.  Owner: sinjeki. */

import Link from "next/link";

import { Card, ErrorState, Loading, PageHeader, StatCard } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import type { DashboardData } from "@/types";

export default function DashboardPage() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<DashboardData>("/insights/dashboard");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  return (
    <>
      <PageHeader
        title={`Welcome back, ${user?.full_name?.split(" ")[0] ?? "there"}`}
        subtitle="Central hub — every module links out from here."
        actions={
          <>
            <Link
              href="/quotations?new=1"
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
            >
              + New Quotation
            </Link>
            <Link
              href="/approvals"
              className="rounded-lg border border-edge px-4 py-2 text-sm text-slate-200 hover:bg-surface"
            >
              View Approvals
            </Link>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <StatCard
          label="Pending Approvals"
          value={data.pending_approvals}
          hint={`${data.pending_approvals} quotation${data.pending_approvals === 1 ? "" : "s"} waiting`}
          href="/approvals"
        />
        <StatCard
          label="Open Quotations"
          value={data.open_quotations}
          hint="Active deals in the pipeline"
          href="/quotations"
        />
        <StatCard
          label="At-Risk Deals"
          value={data.at_risk_deals}
          hint="Flagged by Deal Health"
          href="/deal-health"
          tone={data.at_risk_deals > 0 ? "red" : "slate"}
        />
      </div>

      <div className="mt-6">
        <Card title="Recent Activity" subtitle="Most recently touched quotations">
          {data.recent_activity.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">
              Nothing has happened yet. Create a quotation to get started.
            </p>
          ) : (
            <ul className="divide-y divide-edge">
              {data.recent_activity.map((item) => (
                <li key={`${item.quotation_id}-${item.at}`}>
                  <Link
                    href={`/quotations/${item.quotation_id}`}
                    className="flex items-center justify-between gap-4 py-3 text-sm hover:text-white"
                  >
                    <span className="text-slate-300">{item.text}</span>
                    <span className="shrink-0 text-xs text-slate-500">{dateTime(item.at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
