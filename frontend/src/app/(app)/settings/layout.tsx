"use client";

/**
 * Settings guard.  Owner: the-steelix-flame.
 *
 * Closes a real gap: `/settings/discounts` was reachable by any internal role,
 * but its save endpoints require Admin or Sales Manager. A Sales Rep or
 * Finance user could open it, edit the ceilings, press Save and only then get
 * a 403. Now the page matches what the server will accept.
 */

import { RoleGuard } from "@/components/shell/RoleGuard";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <RoleGuard allow={["ADMIN", "SALES_MANAGER"]} title="Configuration">
      {children}
    </RoleGuard>
  );
}
