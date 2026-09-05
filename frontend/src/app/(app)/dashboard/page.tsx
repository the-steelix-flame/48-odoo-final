"use client";

/** Screen 2 — Sales Dashboard / Home.  Owner: sinjeki. */

import Link from "next/link";

import { Card, ErrorState, Loading, StatCard, Badge } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { useAuth } from "@/lib/auth";
import type { DashboardData } from "@/types";

export default function DashboardPage() {
  const { user, role } = useAuth();
  const { data, error, loading, reload } = useApi<DashboardData>("/insights/dashboard");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

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

        <div className="relative z-10 mt-[40px] grid grid-cols-4 gap-6 border-t border-[rgba(255,255,255,0.1)] pt-[24px]">
          <div>
            <p className="font-mono text-[11.5px] font-medium tracking-[0.05em] text-[#9CAABC] uppercase">Pipeline Total</p>
            <p className="mt-[8px] font-heading text-[36px] font-bold tracking-[-0.02em] text-white">
              $4.2M
            </p>
          </div>
          <div className="col-span-3">
            <div className="mb-[12px] flex items-center justify-between font-mono text-[11px] font-medium tracking-[0.03em] uppercase">
              <span className="text-[#34D399]">Confirmed (32%)</span>
              <span className="text-[#38BDF8]">Negotiation (45%)</span>
              <span className="text-[#FBBF24]">Approvals (18%)</span>
              <span className="text-[#9CAABC]">Drafts (5%)</span>
            </div>
            <div className="flex h-[8px] w-full overflow-hidden rounded-full bg-[#0F172A]">
              <div className="h-full bg-gradient-to-r from-[#10B981] to-[#34D399]" style={{ width: "32%" }}></div>
              <div className="h-full bg-gradient-to-r from-[#0284C7] to-[#38BDF8]" style={{ width: "45%" }}></div>
              <div className="h-full bg-gradient-to-r from-[#D97706] to-[#FBBF24]" style={{ width: "18%" }}></div>
              <div className="h-full bg-[#475569]" style={{ width: "5%" }}></div>
            </div>
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
            {/* Minimal visual placeholder since this isn't fully wired to data yet */}
            <div className="space-y-4">
               {[ 
                 { label: "Draft", val: 12, percent: 15, color: "bg-[#64748B]" },
                 { label: "Pending Approval", val: 3, percent: 18, color: "bg-[#F59E0B]" },
                 { label: "Under Negotiation", val: 8, percent: 45, color: "bg-[#0891B2]" },
                 { label: "Confirmed", val: 24, percent: 32, color: "bg-[#10B981]" }
               ].map(stage => (
                 <div key={stage.label}>
                   <div className="mb-2 flex justify-between text-[13px] font-medium text-[#475569]">
                     <span>{stage.label}</span>
                     <span>{stage.val} deals</span>
                   </div>
                   <div className="h-2 w-full overflow-hidden rounded-full bg-[#F1F5F9]">
                     <div className={`h-full rounded-full ${stage.color}`} style={{ width: `${stage.percent}%` }}></div>
                   </div>
                 </div>
               ))}
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
