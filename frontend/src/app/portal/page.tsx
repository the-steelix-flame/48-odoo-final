"use client";

/**
 * Portal landing.  Owner: the-steelix-flame.
 *
 * Customers reach a specific quotation by link. This page just points them at
 * the one they were sent — there is deliberately no "browse all quotations"
 * here, because a customer's access is scoped per quotation by token, not by
 * account.
 */

import { Card, Note, PageHeader } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function PortalHome() {
  const { user } = useAuth();

  return (
    <>
      <PageHeader
        title="Your quotations"
        subtitle={`Signed in as ${user?.email}`}
      />
      <Card>
        <p className="text-sm text-slate-300">
          Open the quotation using the link your account manager sent you. It looks like{" "}
          <code className="rounded bg-black/40 px-1.5 py-0.5 text-xs text-slate-200">
            /portal/quotations/&lt;id&gt;
          </code>
          .
        </p>
        <div className="mt-4">
          <Note>
            Access is granted per quotation, by token. A quotation you hold no token for returns
            &ldquo;not found&rdquo; — not &ldquo;forbidden&rdquo; — because whether someone else&apos;s
            quote exists isn&apos;t yours to learn either.
          </Note>
        </div>
      </Card>
    </>
  );
}
