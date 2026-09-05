"use client";

/**
 * Route gate for the product catalogue.  Owner: anubhaw0raj.
 *
 * The sidebar hides this section from a Sales Rep, but hiding a link is not
 * access control — the URL still resolves if it is typed or shared. This
 * mirrors the `require_role` now enforced on the API, so the refusal is
 * explained rather than discovered as a wall of failed requests.
 */

import { RoleGuard } from "@/components/shell/RoleGuard";

export default function ProductsLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard allow={["FINANCE", "SALES_MANAGER", "ADMIN"]} title="Product catalogue">
      {children}
    </RoleGuard>
  );
}
