"use client";

/**
 * Customer profile.  Owner: the-steelix-flame.
 *
 * Two halves, and the split is deliberate. The account details are read-only:
 * the business name, tier and account manager are ours to set, and a customer
 * able to edit their own tier would be editing their own discount ceiling.
 * The password is the one thing that is genuinely theirs.
 */

import { useState } from "react";

import { ApiError, post } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  Loading,
  Note,
  PageHeader,
  inputClass,
} from "@/components/ui";
import { date, dateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { PortalProfile } from "@/types";

const MIN_PASSWORD_LENGTH = 8;

export default function PortalProfilePage() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<PortalProfile>("/portal/profile");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  // Checked here purely so the user hears about a typo before a round trip;
  // the server enforces all three rules regardless.
  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < MIN_PASSWORD_LENGTH;
  const canSubmit =
    current.length > 0 && next.length >= MIN_PASSWORD_LENGTH && next === confirm;

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await post("/portal/profile/password", {
        current_password: current,
        new_password: next,
      });
      setCurrent("");
      setNext("");
      setConfirm("");
      setNotice("Your password has been changed. Use the new one next time you sign in.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not change your password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Your profile"
        subtitle={data.company_name}
        actions={<Badge tone="blue">{data.tier} tier</Badge>}
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}
      {notice && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Account" subtitle="Managed by your account manager">
          <dl className="space-y-3 text-sm">
            {[
              ["Business", data.company_name],
              ["Pricing tier", `${data.tier} — sets the discount you're eligible for`],
              ["Currency", data.currency],
              ["Sign-in email", data.login_email],
              ["Contact email", data.contact_email || "—"],
              ["Account manager", data.account_manager ?? "Not assigned"],
              ["Member since", date(data.member_since)],
              ["Last sign-in", data.last_login ? dateTime(data.last_login) : "This is your first"],
            ].map(([label, value]) => (
              <div key={label} className="flex flex-wrap justify-between gap-3">
                <dt className="text-[#64748B]">{label}</dt>
                <dd className="text-right font-medium text-[#0F172A]">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-edge bg-[#F8FAFC] px-4 py-3">
              <p className="text-xs uppercase tracking-wide text-[#64748B]">
                Quotations received
              </p>
              <p className="mt-1 font-heading text-[22px] font-bold text-[#0F172A]">
                {data.quotations_received}
              </p>
            </div>
            <div className="rounded-lg border border-edge bg-[#F8FAFC] px-4 py-3">
              <p className="text-xs uppercase tracking-wide text-[#64748B]">Confirmed</p>
              <p className="mt-1 font-heading text-[22px] font-bold text-[#0F172A]">
                {data.quotations_confirmed}
              </p>
            </div>
          </div>

          <div className="mt-4">
            <Note>
              Your business details and pricing tier are set by your account manager. Ask them if
              anything here needs changing.
            </Note>
          </div>
        </Card>

        <Card title="Change password" subtitle="The one thing only you control">
          <form onSubmit={changePassword} className="space-y-4">
            <Field
              label="Current password"
              hint="Proves it's you — without it, anyone at your desk could lock you out."
            >
              <input
                type="password"
                autoComplete="current-password"
                className={inputClass}
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </Field>
            <Field label="New password" hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}>
              <input
                type="password"
                autoComplete="new-password"
                className={inputClass}
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
              />
            </Field>
            <Field label="Confirm new password">
              <input
                type="password"
                autoComplete="new-password"
                className={inputClass}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
              />
            </Field>

            {tooShort && (
              <p className="text-xs text-[#B45309]">
                That&apos;s {next.length} characters — {MIN_PASSWORD_LENGTH} is the minimum.
              </p>
            )}
            {mismatch && (
              <p className="text-xs text-[#B91C1C]">Those two don&apos;t match.</p>
            )}

            <Button type="submit" disabled={busy || !canSubmit}>
              {busy ? "Changing…" : "Change password"}
            </Button>
          </form>

          <div className="mt-4">
            <Note>
              If you&apos;ve forgotten the current one, your account manager can issue a fresh
              password — it&apos;s stored scrambled, so nobody here can read it back to you.
            </Note>
          </div>
        </Card>
      </div>
    </>
  );
}
