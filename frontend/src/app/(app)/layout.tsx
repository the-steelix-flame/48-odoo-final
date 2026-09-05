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

import { Sidebar } from "@/components/shell/Sidebar";
import { Header } from "@/components/shell/Header";
import { Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { NavigationProvider } from "@/lib/navigation";
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
    // NavigationProvider is mounted per authenticated shell, never at the root,
    // so the hop from /login is never counted as somewhere to go "back" to.
    <NavigationProvider>
      <div className="flex min-h-screen items-stretch">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col bg-[radial-gradient(1200px_600px_at_88%_-12%,#E3EEF2_0%,#F8FAFC_60%)]">
          <Header />
          <main className="flex-1 p-[30px_26px_60px]">
            {children}
          </main>
        </div>
      </div>
    </NavigationProvider>
  );
}
