"use client";

/**
 * Route gate for the negotiation inbox.  Owner: the-steelix-flame.
 *
 * Negotiating is the rep's job, and only the rep's. A Sales Manager or Finance
 * user governs the deal — they approve or refuse the terms the rep brings them
 * — so haggling directly with the customer would put them on both sides of
 * their own approval.
 *
 * The sidebar already hides this, but hiding a link is not access control: the
 * URL still resolves if it is typed or shared. This mirrors the `require_role`
 * on the accept and counter endpoints.
 */

import { RoleGuard } from "@/components/shell/RoleGuard";

export default function NegotiationsLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard allow={["SALES_REP", "ADMIN"]} title="Negotiation inbox">
      {children}
    </RoleGuard>
  );
}
