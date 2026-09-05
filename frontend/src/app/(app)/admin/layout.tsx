"use client";

/**
 * Admin-only subtree.  Owner: the-steelix-flame.
 *
 * User and Business Management are Admin-only on the server
 * (`require_role(request, Role.ADMIN)` on every route in `admin_api.py`), so
 * the gate here matches exactly. Discount config is NOT under this subtree —
 * it lives at /settings/discounts, which Sales Managers can also use.
 */

import { RoleGuard } from "@/components/shell/RoleGuard";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard allow={["ADMIN"]} title="Administration">
      {children}
    </RoleGuard>
  );
}
