"use client";

/**
 * The internal workspace shell + role guard.  Owner: sinjeki.
 *
 * Half of the "the portal is a genuinely separate surface" claim lives here:
 * a CUSTOMER who reaches any /(app) route is bounced to /portal. The other
 * half is server-side, in the portal's token check — this guard is convenience,
 * not security.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { TopNav } from "@/components/shell/TopNav";
import { Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { INTERNAL_ROLES } from "@/types";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (!INTERNAL_ROLES.includes(user.role)) {
      router.replace("/portal");
    }
  }, [user, loading, router]);

  if (loading || !user || !INTERNAL_ROLES.includes(user.role)) {
    return <Loading label="Checking your session…" />;
  }

  return (
    <div className="min-h-screen">
      <TopNav />
      <main className="mx-auto max-w-[1600px] px-4 py-8">{children}</main>
    </div>
  );
}
