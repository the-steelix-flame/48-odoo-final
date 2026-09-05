"use client";

/** The left sidebar from the refinement design. */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type {
  DealHealth,
  InternalNegotiationRequest,
  OrderAwaiting,
  QuotationSummary,
  Role,
} from "@/types";

type NavItem = {
  href: string;
  label: string;
  badge?: number;
  roles?: Role[];
  /** Per-role label override — the same screen can mean different things. */
  labelByRole?: Partial<Record<Role, string>>;
};

/** Statuses that still want a human. A CONFIRMED quote is finished work, so
 *  counting it would make the badge grow forever and mean nothing. */
const OPEN_QUOTE_STATUSES = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "SENT", "UNDER_NEGOTIATION"];

export function Sidebar() {
  const pathname = usePathname();
  const { role, logout } = useAuth();

  // Badges were hardcoded ("12", "3", "4"…), so the sidebar confidently
  // contradicted the very page it linked to — Approvals read 3 above a screen
  // showing none pending. Every badge is now derived from the same endpoint
  // the destination screen uses, so they cannot disagree.
  const { data: quotations } = useApi<QuotationSummary[]>("/quotations/");
  const { data: approvals } = useApi<{ pending: number }>("/approvals/counts");
  const { data: negotiations } = useApi<InternalNegotiationRequest[]>(
    "/portal/internal/requests?status=SUBMITTED",
  );
  const { data: orders } = useApi<OrderAwaiting[]>("/fulfillment/orders");
  const { data: invoices } = useApi<{ unpaid: number }>("/billing/invoices/counts");
  const { data: health } = useApi<DealHealth>("/insights/deal-health");

  const openQuotes = (quotations ?? []).filter((q) =>
    OPEN_QUOTE_STATUSES.includes(q.status),
  ).length;

  const NAV: NavItem[] = [
    {
      href: "/dashboard",
      label: "Dashboard",
      // For an admin this screen is a platform-wide read, not a personal
      // worklist, so it's named for what it does for them.
      labelByRole: { ADMIN: "Analytics" },
    },
    { href: "/quotations", label: "Quotations", badge: openQuotes },
    { href: "/approvals", label: "Approvals", badge: approvals?.pending },
    { href: "/negotiations", label: "Negotiations", badge: negotiations?.length },
    { href: "/fulfillment", label: "Fulfillment", badge: orders?.length },
    { href: "/subscriptions", label: "Subscriptions" },
    { href: "/invoices", label: "Invoices", badge: invoices?.unpaid },
    { href: "/deal-health", label: "Deal Health", badge: health?.alerts.length },
    { href: "/reports", label: "Reports" },
    { href: "/products", label: "Products" },
  ];

  /**
   * Configuration screens, pinned below the operational ones. Gated to the
   * roles that can actually save them — the discount rules link used to show
   * for everyone while its save endpoints require Admin or Sales Manager, so a
   * Rep could edit the ceilings and only meet the 403 on save.
   */
  const CONFIG_NAV: NavItem[] = [
    { href: "/admin/users", label: "User management", roles: ["ADMIN"] },
    { href: "/admin/businesses", label: "Business management", roles: ["ADMIN"] },
    {
      href: "/settings/discounts",
      label: "Discount & approval rules",
      roles: ["ADMIN", "SALES_MANAGER"],
    },
  ];

  const canSee = (item: NavItem) => !item.roles || (role && item.roles.includes(role));
  const visible = NAV.filter(canSee);
  const visibleConfig = CONFIG_NAV.filter(canSee);

  return (
    <aside className="sticky top-0 flex h-screen w-[240px] shrink-0 flex-col gap-1 overflow-auto border-r border-[#1b2a3c] bg-gradient-to-b from-[#24354c] to-[#2c4459] p-[18px_14px]">
      <Link href="/dashboard" className="mb-[12px] flex items-center gap-[10px] p-[6px_8px_18px]">
        <div className="relative flex h-[28px] w-[28px] shrink-0 items-center justify-center rounded-[9px] bg-gradient-to-br from-[#22D3EE] via-[#0891B2] to-[#0E7490] shadow-[inset_0_0_0_1px_rgba(255,255,255,0.34),0_8px_18px_-10px_rgba(8,145,178,0.9)]">
          <div className="h-[12px] w-[12px] rotate-45 rounded-[2px] bg-[#F8FAFC]"></div>
          <div className="absolute bottom-[4px] right-[4px] h-[5px] w-[5px] rounded-full bg-[#0F172A]"></div>
        </div>
        <span className="font-heading text-[16px] font-semibold tracking-[-0.02em] text-[#F8FAFC]">
          DealFlow<span className="text-[#22D3EE]">360</span>
        </span>
      </Link>

      {visible.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`group flex items-center gap-[9px] rounded-[10px] p-[10px_11px] text-[13.5px] transition hover:bg-white/10 hover:text-[#F8FAFC] ${
              active
                ? "bg-gradient-to-r from-[rgba(34,211,238,0.22)] to-[rgba(20,184,166,0.05)] font-semibold text-[#F0FCFF] shadow-[0_0_20px_-8px_rgba(34,211,238,0.7)]"
                : "bg-transparent font-medium text-[#B7C4D4]"
            }`}
            style={
              active
                ? { borderLeft: "2px solid #22D3EE" }
                : { borderLeft: "2px solid transparent" }
            }
          >
            <span
              className={`h-[5px] w-[5px] rounded-full ${
                active ? "bg-[#22D3EE] shadow-[0_0_8px_#22D3EE]" : "bg-[#6b7d92]"
              }`}
            ></span>
            <span className="flex-1">
              {(role && item.labelByRole?.[role]) || item.label}
            </span>
            {/* `{0 && …}` renders a literal 0, and "nothing waiting" is better
                said with no badge at all than with a grey zero. */}
            {item.badge !== undefined && item.badge > 0 ? (
              <span className="rounded-[6px] border border-[rgba(34,211,238,0.3)] bg-[rgba(34,211,238,0.2)] p-[2px_6px] font-mono text-[10.5px] text-[#B7EDF7]">
                {item.badge}
              </span>
            ) : null}
          </Link>
        );
      })}

      <div className="mt-auto flex flex-col gap-1 border-t border-white/15 pt-4">
        {visibleConfig.map((item) => {
          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-[9px] rounded-[10px] p-[10px_11px] text-[13.5px] transition hover:bg-white/10 hover:text-[#F8FAFC] ${
                active
                  ? "bg-gradient-to-r from-[rgba(34,211,238,0.22)] to-[rgba(20,184,166,0.05)] font-semibold text-[#F0FCFF] shadow-[0_0_20px_-8px_rgba(34,211,238,0.7)] border-l-2 border-[#22D3EE]"
                  : "bg-transparent font-medium text-[#B7C4D4] border-l-2 border-transparent"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
        <Link
          href="/portal"
          className="flex items-center gap-[9px] rounded-[9px] p-[9px_10px] text-[13.5px] font-medium text-[#B7C4D4] transition hover:bg-white/10 hover:text-[#F8FAFC]"
        >
          Customer portal view
        </Link>
        <button
          onClick={logout}
          className="flex items-center gap-[9px] rounded-[9px] p-[9px_10px] text-left text-[13.5px] font-medium text-[#9CAABC] transition hover:text-red-600"
        >
          Log out
        </button>
      </div>
    </aside>
  );
}
