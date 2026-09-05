"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

const ROUTE_MAP: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/quotations": "Quotations",
  "/approvals": "Approvals",
  "/fulfillment": "Fulfillment",
  "/subscriptions": "Subscriptions",
  "/invoices": "Invoices",
  "/deal-health": "Deal Health",
  "/reports": "Reports",
  "/products": "Products",
  "/settings/discounts": "Discount & approval rules",
};

export function Header() {
  const pathname = usePathname();
  const { user } = useAuth();
  
  const segments = pathname.split("/").filter(Boolean);
  const crumbs: { label: string; href?: string }[] = [];
  
  if (segments.length > 0) {
    const parentPath = `/${segments[0]}`;
    if (ROUTE_MAP[parentPath]) {
      crumbs.push({ label: ROUTE_MAP[parentPath], href: parentPath });
      if (segments.length > 1) {
        // Just hardcode a general detail label for now or use the ID
        const isDetail = segments.length > 1 && segments[0] !== "settings";
        if (isDetail) {
          crumbs.push({ label: segments[1] });
        }
      }
    } else {
      crumbs.push({ label: "DealFlow360" });
    }
  }

  const initials = user?.full_name ? user.full_name.split(" ").map(n => n[0]).join("").substring(0,2).toUpperCase() : "JR";
  const name = user?.full_name || "J. Rao";

  return (
    <header className="sticky top-0 z-10 flex h-[60px] shrink-0 items-center gap-4 border-b border-[#E2E8F0] bg-[rgba(248,250,252,0.86)] px-[26px] backdrop-blur-[8px]">
      <div className="flex min-w-0 items-center gap-2 text-[13px] text-[#475569]">
        {crumbs.map((crumb, idx) => (
          <span key={idx} className="flex items-center gap-2">
            {idx > 0 && <span className="text-[#A3AFBE]">/</span>}
            {crumb.href && idx < crumbs.length - 1 ? (
              <Link href={crumb.href} className="cursor-pointer transition-colors hover:text-[#0F172A]">
                {crumb.label}
              </Link>
            ) : (
              <span className="text-[#0F172A]">{crumb.label}</span>
            )}
          </span>
        ))}
      </div>
      <div className="flex-1"></div>
      <div className="flex items-center gap-[7px] rounded-[8px] border border-[#DFE5ED] bg-white p-[6px_11px] text-[12px] text-[#4B5A6B]">
        <span className="h-[7px] w-[7px] animate-dfPulse rounded-full bg-[#0891B2]"></span>
        Rules engine live
      </div>
      <div className="flex cursor-pointer items-center gap-[9px] rounded-full border border-[#E2E8F0] p-[5px_11px_5px_6px] transition-colors hover:border-[#0891B2]">
        <span className="flex h-[26px] w-[26px] items-center justify-center rounded-full bg-[#E2E8F0] font-mono text-[11.5px] text-[#334155]">
          {initials}
        </span>
        <span className="text-[13px] font-medium">{name}</span>
      </div>
    </header>
  );
}
