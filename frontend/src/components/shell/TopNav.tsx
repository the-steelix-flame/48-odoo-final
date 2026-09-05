"use client";

/**
 * The blue top bar from the mockup.  Owner: sinjeki.
 *
 * the-steelix-flame: made the nav role-aware. Every role sees the operational
 * screens; Admin additionally sees the configuration screens inline, rather
 * than behind a hub page, because an admin lives in those screens and
 * shouldn't have to go through a landing page to reach them.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuth } from "@/lib/auth";
import type { Role } from "@/types";

type NavItem = {
  href: string;
  label: string;
  /** Omit to show to every internal role. */
  roles?: Role[];
  /** Per-role label override — the same screen can mean different things. */
  labelByRole?: Partial<Record<Role, string>>;
};

const NAV: NavItem[] = [
  // Operational screens — unchanged for everyone.
  {
    href: "/dashboard",
    label: "Dashboard",
    // For an admin this screen is a platform-wide read, not a personal
    // worklist, so it's named for what it does for them.
    labelByRole: { ADMIN: "Analytics" },
  },
  { href: "/quotations", label: "Quotations" },
  { href: "/approvals", label: "Approvals" },
  { href: "/fulfillment", label: "Fulfillment" },
  { href: "/subscriptions", label: "Subscriptions" },
  { href: "/invoices", label: "Invoices" },
  { href: "/deal-health", label: "Deal Health" },
  { href: "/reports", label: "Reports" },
  { href: "/products", label: "Products" },

  // Configuration screens. Admin gets all of them; Sales Manager gets the
  // discount config, because that's the one they can actually save.
  { href: "/admin/users", label: "User Management", roles: ["ADMIN"] },
  { href: "/admin/businesses", label: "Business Management", roles: ["ADMIN"] },
  {
    href: "/settings/discounts",
    label: "Discount Tiers & Approval Chains",
    roles: ["ADMIN", "SALES_MANAGER"],
  },
];

export function TopNav() {
  const pathname = usePathname();
  const { user, role, logout } = useAuth();

  const visible = NAV.filter((item) => !item.roles || (role && item.roles.includes(role)));

  // One divider, before the first role-restricted item, separating the
  // operational screens from the configuration ones. Derived rather than
  // hardcoded so it lands correctly for every role — a Sales Manager sees only
  // the discount config, and the divider still falls in the right place.
  const dividerIndex = visible.findIndex((item) => item.roles);

  return (
    <nav className="sticky top-0 z-20 border-b border-blue-400/30 bg-brand">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2 px-4 py-2.5">
        <Link href="/dashboard" className="mr-3 text-lg font-semibold text-white">
          DealFlow360
        </Link>

        <div className="flex flex-wrap items-center gap-1.5">
          {visible.map((item, index) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const label = (role && item.labelByRole?.[role]) || item.label;
            const showDivider = index === dividerIndex && index > 0;

            return (
              <span key={item.href} className="flex items-center gap-1.5">
                {showDivider && (
                  <span aria-hidden className="mx-1 h-5 w-px bg-white/30" />
                )}
                <Link
                  href={item.href}
                  className={`rounded-lg px-3 py-1.5 text-sm transition ${
                    active
                      ? "bg-black/70 font-medium text-white"
                      : "border border-white/40 text-white/90 hover:bg-white/15"
                  }`}
                >
                  {label}
                </Link>
              </span>
            );
          })}
        </div>

        <div className="ml-auto flex items-center gap-3">
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
