"use client";

/** The blue top bar from the mockup.  Owner: sinjeki. */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";
import type { Role } from "@/types";

type NavItem = { href: string; label: string; roles?: Role[] };

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/quotations", label: "Quotations" },
  { href: "/approvals", label: "Approvals" },
  { href: "/fulfillment", label: "Fulfillment" },
  { href: "/subscriptions", label: "Subscriptions" },
  { href: "/invoices", label: "Invoices" },
  { href: "/deal-health", label: "Deal Health" },
  { href: "/reports", label: "Reports" },
  { href: "/products", label: "Products" },
];

export function TopNav() {
  const pathname = usePathname();
  const { user, role, logout } = useAuth();

  const visible = NAV.filter((item) => !item.roles || (role && item.roles.includes(role)));

  return (
    <nav className="sticky top-0 z-20 border-b border-blue-400/30 bg-brand">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2 px-4 py-2.5">
        <Link href="/dashboard" className="mr-3 text-lg font-semibold text-white">
          DealFlow360
        </Link>

        <div className="flex flex-wrap gap-1.5">
          {visible.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-lg px-3 py-1.5 text-sm transition ${
                  active
                    ? "bg-black/70 font-medium text-white"
                    : "border border-white/40 text-white/90 hover:bg-white/15"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-3">
          <Link
            href="/settings/discounts"
            className="rounded-lg border border-white/40 px-3 py-1.5 text-sm text-white/90 hover:bg-white/15"
          >
            Back-end
          </Link>
          <span className="hidden text-xs text-white/80 sm:inline">
            {user?.full_name} · {role?.replace("_", " ").toLowerCase()}
          </span>
          <button
            onClick={logout}
            className="rounded-lg bg-black/30 px-3 py-1.5 text-sm text-white hover:bg-black/50"
          >
            Close Workspace
          </button>
        </div>
      </div>
    </nav>
  );
}
