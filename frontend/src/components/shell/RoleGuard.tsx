"use client";

/**
 * Route-level role gate.  Owner: the-steelix-flame.
 *
 * `(app)/layout.tsx` only checks that you're internal staff. Several screens
 * need a narrower gate than that, and they were previously ungated — a Sales
 * Rep could open `/settings/discounts`, edit the ceilings and only discover on
 * save that the endpoint requires Admin or Sales Manager.
 *
 * This mirrors the server's `require_role`. The server is what actually
 * enforces access; this exists so nobody is shown a door they can't walk
 * through, and so the refusal explains itself instead of silently redirecting.
 */

import Link from "next/link";

import { Card, Loading, PageHeader } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/types";

export function RoleGuard({
  allow,
  title = "Restricted",
  children,
}: {
  allow: Role[];
  title?: string;
  children: React.ReactNode;
}) {
  const { role, loading } = useAuth();

  if (loading) return <Loading label="Checking your access…" />;

  if (!role || !allow.includes(role)) {
    const allowed = allow.map((r) => r.replace("_", " ").toLowerCase()).join(" or ");
    return (
      <>
        <PageHeader title={title} />
        <Card>
          <p className="text-sm text-slate-300">
            This area is available to {allowed} accounts. You&apos;re signed in as{" "}
            <strong>{role?.replace("_", " ").toLowerCase()}</strong>.
          </p>
          <p className="mt-3 text-sm">
            <Link href="/dashboard" className="text-brand hover:underline">
              Back to the dashboard →
            </Link>
          </p>
        </Card>
      </>
    );
  }

  return <>{children}</>;
}
