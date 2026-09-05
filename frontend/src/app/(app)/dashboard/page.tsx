"use client";

/** Screen 2 — Sales Dashboard / Home.  Owner: sinjeki. */

import { useState } from "react";
import Link from "next/link";

import { Card, ErrorState, Loading, StatCard, Badge } from "@/components/ui";
import { dateTime, money } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import type { DashboardData } from "@/types";

/** Solid equivalents of STAGE_BAR, for the per-stage rows further down. */
const STAGE_TRACK: Record<string, string> = {
  DRAFT: "bg-[#64748B]",
  PENDING_APPROVAL: "bg-[#F59E0B]",
  APPROVED: "bg-[#10B981]",
  SENT: "bg-[#0891B2]",
  UNDER_NEGOTIATION: "bg-[#7C3AED]",
};

/** Stage colours for the pipeline bar, keyed on the real status values. */
const STAGE_BAR: Record<string, string> = {
  DRAFT: "bg-[#475569]",
  PENDING_APPROVAL: "bg-gradient-to-r from-[#D97706] to-[#FBBF24]",
  APPROVED: "bg-gradient-to-r from-[#10B981] to-[#34D399]",
  SENT: "bg-gradient-to-r from-[#0284C7] to-[#38BDF8]",
  UNDER_NEGOTIATION: "bg-gradient-to-r from-[#7C3AED] to-[#A78BFA]",
};

export default function DashboardPage() {
  const { user, role } = useAuth();
  const [scope, setScope] = useState<"company" | "mine">("company");
  const { data, error, loading, reload } = useApi<DashboardData>("/insights/dashboard");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  // "Mine" only exists for someone who actually owns deals, so the toggle is
  // hidden entirely for roles that never carry a quota rather than showing them
  // a row of zeros.
  const canScope = Boolean(data.mine);
  const summary = scope === "mine" && data.mine ? data.mine : data.company;
  const mineActive = canScope && scope === "mine";

  return (
    <div className="animate-dfIn space-y-6">
      <div className="relative overflow-hidden rounded-[16px] bg-gradient-to-br from-[#24354c] to-[#1a2638] p-[32px_40px] text-white shadow-md">
        <div className="absolute right-0 top-0 h-[250px] w-[500px] -translate-y-1/3 translate-x-1/3 rounded-full bg-[radial-gradient(circle,rgba(34,211,238,0.15)_0%,transparent_70%)] blur-[40px]"></div>
        
        <div className="relative z-10 flex flex-wrap items-end justify-between gap-6">
          <div>
            {/* An admin reaches this from a nav item labelled "Analytics", so
                landing on a personal greeting reads as the wrong page. Same
                screen, named for what it is to whoever opened it. */}
            <h1 className="font-heading text-[32px] font-bold tracking-[-0.03em]">
              {role === "ADMIN"
                ? "Platform Analytics"
                : `Welcome back, ${user?.full_name?.split(" ")[0] ?? "there"}`}
            </h1>
            <p className="mt-[6px] text-[15px] text-[#9CAABC]">
              {role === "ADMIN"
                ? "Platform-wide activity across every team."
                : "Here's what's happening with your deals today."}
            </p>
          </div>
          <div className="flex gap-[12px]">
            {(role === "SALES_REP" || role === "ADMIN") && (
            <Link
              href="/quotations?new=1"
              className="rounded-[8px] bg-gradient-to-br from-[#22D3EE] to-[#0891B2] px-[18px] py-[10px] text-[13.5px] font-semibold text-[#0F172A] shadow-[0_2px_10px_rgba(8,145,178,0.3)] transition hover:from-[#34D399] hover:to-[#059669] hover:text-white"
            >
              + New Quotation
            </Link>
            )}
            <Link
              href="/approvals"
              className="rounded-[8px] border border-[rgba(255,255,255,0.15)] bg-[rgba(255,255,255,0.05)] px-[18px] py-[10px] text-[13.5px] font-medium transition hover:bg-[rgba(255,255,255,0.1)]"
            >
              View Approvals
            </Link>
          </div>
        </div>

        {/* Every figure below is computed. This band previously read a
            hardcoded $4.2M with a 32/45/18/5 split; the real open pipeline is
            two orders of magnitude smaller, and the brief requires the numbers
            to come from application logic rather than being typed in. */}
        <div className="relative z-10 mt-[40px] grid grid-cols-1 gap-6 border-t border-[rgba(255,255,255,0.1)] pt-[24px] lg:grid-cols-4">
          <div>
            <div className="flex items-center gap-[8px]">
              <p className="font-mono text-[11.5px] font-medium tracking-[0.05em] text-[#9CAABC] uppercase">
                {mineActive ? "My Pipeline" : "Pipeline Total"}
              </p>
              {canScope && (
                <span className="flex overflow-hidden rounded-full border border-[rgba(255,255,255,0.18)]">
                  {(["company", "mine"] as const).map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setScope(option)}
                      className={`px-[8px] py-[2px] text-[10px] font-medium tracking-[0.03em] uppercase transition ${
                        scope === option
                          ? "bg-[#22D3EE] text-[#0F172A]"
                          : "text-[#9CAABC] hover:text-white"
                      }`}
                    >
                      {option === "company" ? "Company" : "Mine"}
                    </button>
                  ))}
                </span>
              )}
            </div>
            <p className="mt-[8px] font-heading text-[36px] font-bold tracking-[-0.02em] text-white">
              {money(summary.pipeline_total)}
            </p>
            {/* Pipeline is a forecast. These two are what has actually closed,
                kept separate so the headline is never mistaken for earnings. */}
            <div className="mt-[10px] flex flex-wrap gap-x-[18px] gap-y-[2px] font-mono text-[10.5px] tracking-[0.03em] uppercase">
              <span className="text-[#9CAABC]">
                Won <span className="text-[#34D399]">{money(summary.won_value)}</span>
              </span>
              <span className="text-[#9CAABC]">
                Expected margin{" "}
                <span className="text-[#34D399]">{money(summary.won_margin)}</span>
              </span>
              {!mineActive && (
                <span className="text-[#9CAABC]">
                  Collected <span className="text-[#38BDF8]">{money(data.collected)}</span>
                </span>
              )}
            </div>
          </div>
          <div className="lg:col-span-3">
            <div className="mb-[12px] flex flex-wrap items-center gap-x-[16px] gap-y-[4px] font-mono text-[11px] font-medium tracking-[0.03em] uppercase">
              {data.pipeline_by_stage.map((stage) => (
                <span key={stage.status} className="text-[#9CAABC]">
                  {stage.label} ({stage.percent}%)
                  <span className="ml-[4px] text-[#64748B]">{stage.count}</span>
                </span>
              ))}
            </div>
            <div className="flex h-[8px] w-full overflow-hidden rounded-full bg-[#0F172A]">
              {data.pipeline_by_stage.map((stage) => (
                <div
                  key={stage.status}
                  title={`${stage.label}: ${stage.count} deals, ${money(stage.value)}`}
                  className={`h-full ${STAGE_BAR[stage.status] ?? "bg-[#475569]"}`}
                  style={{ width: `${stage.percent}%` }}
                />
              ))}
            </div>
            <p className="mt-[8px] font-mono text-[10px] tracking-[0.03em] text-[#64748B] uppercase">
              Share of open pipeline by value
            </p>
          </div>
        </div>
      </div>

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

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="Pipeline by stage" subtitle="Deals currently moving through the system">
            {/* Was a hardcoded placeholder claiming 24 confirmed deals. Once the
                band above became real the two contradicted each other on the same
                screen, so this reads the same computed source. */}
            <div className="space-y-4">
              {data.pipeline_by_stage.map((stage) => (
                <div key={stage.status}>
                  <div className="mb-2 flex justify-between text-[13px] font-medium text-[#475569]">
                    <span>{stage.label}</span>
                    <span>
                      {stage.count} deal{stage.count === 1 ? "" : "s"}
                      <span className="ml-[8px] font-mono text-[11px] text-[#94A3B8]">
                        {money(stage.value)}
                      </span>
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-[#F1F5F9]">
                    <div
                      className={`h-full rounded-full ${STAGE_TRACK[stage.status] ?? "bg-[#64748B]"}`}
                      style={{ width: `${stage.percent}%` }}
                    />
                  </div>
                </div>
              ))}
              {data.pipeline_by_stage.every((stage) => stage.count === 0) && (
                <p className="py-[24px] text-center text-[13px] text-[#94A3B8]">
                  Nothing is open right now.
                </p>
              )}
            </div>
          </Card>
        </div>

        <Card title="Recent Activity" subtitle="Most recently touched quotations">
          {data.recent_activity.length === 0 ? (
            <p className="py-[40px] text-center text-[13px] text-[#64748B]">
              Nothing has happened yet. Create a quotation to get started.
            </p>
          ) : (
            <ul className="space-y-[16px]">
              {data.recent_activity.map((item, idx) => (
                <li key={`${item.quotation_id}-${item.at}`} className="flex gap-[12px]">
                  <div className="relative flex flex-col items-center">
                    <div className="h-[10px] w-[10px] rounded-full border-[2px] border-white bg-[#0891B2] shadow-[0_0_0_2px_#E2E8F0]"></div>
                    {idx !== data.recent_activity.length - 1 && (
                      <div className="absolute top-[10px] h-[calc(100%+6px)] w-[2px] bg-[#E2E8F0]"></div>
                    )}
                  </div>
                  <div className="-mt-[2px] pb-[4px]">
                    <Link
                      href={`/quotations/${item.quotation_id}`}
                      className="text-[13px] font-medium text-[#334155] hover:text-[#0891B2]"
                    >
                      {item.text}
                    </Link>
                    <p className="mt-[2px] text-[11px] text-[#94A3B8]">{dateTime(item.at)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
