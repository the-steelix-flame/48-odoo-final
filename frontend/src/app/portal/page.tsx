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
        <p className="text-[13px] text-[#475569]">
          Open the quotation using the link your account manager sent you. It looks like{" "}
          <code className="rounded bg-[#F1F5F9] px-[6px] py-[2px] font-mono text-[12px] text-[#0F172A]">
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
