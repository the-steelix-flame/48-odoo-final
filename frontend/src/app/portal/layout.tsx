"use client";

/**
 * The customer portal shell.  Owner: the-steelix-flame.
 *
 * A genuinely separate surface, not an internal screen with a different label:
 *   - its own route group and its own three-item nav
 *   - its own API namespace (/api/portal/*) with its own narrow serialiser
 *   - authorisation needs a portal token scoped to ONE quotation
 * This layout is the cosmetic half. The real boundary is server-side.
 */

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { NavigationProvider } from "@/lib/navigation";

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
  }, [user, loading, router]);

  if (loading || !user) return <Loading label="Checking your session…" />;

  return (
    <NavigationProvider>
    <div className="min-h-screen">
      <nav className="border-b border-blue-400/30 bg-brand">
        <div className="mx-auto flex max-w-5xl items-center gap-3 px-4 py-2.5">
          <Link href="/portal" className="mr-2 text-lg font-semibold text-white">
            DealFlow360
          </Link>
          {/* This was a dead <span>, so the only way back to the list was the
              browser's back button. "Messages" and "Profile" sat beside it as
              decoration for screens that don't exist — a nav item that does
              nothing is worse than one that isn't there. */}
          {[
            { href: "/portal", label: "My Quotations" },
            { href: "/portal/profile", label: "Profile" },
          ].map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                pathname === item.href
                  ? "bg-black/70 text-white"
                  : "border border-white/40 text-white/90 hover:bg-white/15"
              }`}
            >
              {item.label}
            </Link>
          ))}
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-xs text-white/80 sm:inline">{user.full_name}</span>
            <button
              onClick={logout}
              className="rounded-lg bg-black/30 px-3 py-1.5 text-sm text-white hover:bg-black/50"
            >
              Sign out
            </button>
          </div>
        </div>
      </nav>
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
    </NavigationProvider>
  );
}
