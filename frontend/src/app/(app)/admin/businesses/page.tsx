"use client";

/**
 * Business Management.  Owner: the-steelix-flame.
 *
 * Admin registers a company you sell to; the system mints a portal login and
 * shows the password ONCE. There is deliberately no way to view it again —
 * the server only ever stores the hash. Losing it means resetting it.
 */

import { useState } from "react";

import { ApiError, patch, post } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  EmptyState,
  ErrorState,
  Field,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { dateTime } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Business, BusinessCredentials, CustomerTier, User } from "@/types";

const TIERS: CustomerTier[] = ["BRONZE", "SILVER", "GOLD"];

export default function BusinessManagementPage() {
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [tier, setTier] = useState<CustomerTier>("BRONZE");
  const [currency, setCurrency] = useState("USD");
  const [address, setAddress] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [ownerRepId, setOwnerRepId] = useState("");
  const [withLogin, setWithLogin] = useState(true);

  const [credentials, setCredentials] = useState<BusinessCredentials | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<Business[]>("/admin/businesses");
  const { data: reps } = useApi<User[]>("/auth/users");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const businesses = data ?? [];

  async function run(fn: () => Promise<BusinessCredentials | Business>, reveal: boolean) {
    setBusy(true);
    setActionError(null);
    setCopied(false);
    try {
      const result = await fn();
      if (reveal) setCredentials(result as BusinessCredentials);
      await reload();
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function createBusiness(event: React.FormEvent) {
    event.preventDefault();
    const ok = await run(
      () =>
        post<BusinessCredentials>("/admin/businesses", {
          name,
          contact_email: email,
          tier,
          currency,
          address,
          // Sent as null rather than "" so the server sees "no coordinate"
          // instead of a value it has to parse and reject.
          latitude: latitude.trim() || null,
          longitude: longitude.trim() || null,
          owner_rep_id: ownerRepId ? Number(ownerRepId) : null,
          create_portal_login: withLogin,
        }),
      withLogin,
    );
    if (ok) {
      setShowForm(false);
      setName("");
      setEmail("");
      setTier("BRONZE");
      setAddress("");
      setLatitude("");
      setLongitude("");
      setOwnerRepId("");
    }
  }

  const salesStaff = (reps ?? []).filter(
    (user) => user.role === "SALES_REP" || user.role === "SALES_MANAGER",
  );

  return (
    <>
      <PageHeader
        title="Business Management"
        subtitle="Companies you sell to, and the portal logins they use to negotiate."
        actions={
          <Button onClick={() => setShowForm((open) => !open)}>
            {showForm ? "Cancel" : "+ Add Business"}
          </Button>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      {/* ---------------------------------------- credentials, shown once */}
      {credentials && (
        <div className="mb-6 rounded-xl border border-emerald-700 bg-emerald-950/30 p-5">
          <h2 className="text-base font-semibold text-emerald-200">
            Credentials for {credentials.business.name}
          </h2>
          <p className="mt-1 text-sm text-emerald-300/80">{credentials.notice}</p>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-emerald-800 bg-black/30 px-3 py-2">
              <p className="text-xs uppercase tracking-wide text-emerald-400/70">Login email</p>
              <p className="mt-1 font-mono text-sm text-slate-100">
                {credentials.portal_login_email}
              </p>
            </div>
            <div className="rounded-lg border border-emerald-800 bg-black/30 px-3 py-2">
              <p className="text-xs uppercase tracking-wide text-emerald-400/70">Password</p>
              <p className="mt-1 font-mono text-sm text-slate-100">{credentials.password}</p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={async () => {
                await navigator.clipboard.writeText(
                  `DealFlow360 portal\nEmail: ${credentials.portal_login_email}\nPassword: ${credentials.password}`,
                );
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy credentials"}
            </Button>
            <Button variant="secondary" onClick={() => setCredentials(null)}>
              I&apos;ve shared these — dismiss
            </Button>
          </div>
        </div>
      )}

      {/* ---------------------------------------- create form */}
      {showForm && (
        <div className="mb-6">
          <Card title="Register a business">
            <form onSubmit={createBusiness}>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Field label="Business name">
                  <input
                    className={inputClass}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Northwind Traders"
                    required
                  />
                </Field>
                <Field
                  label="Contact email"
                  hint={withLogin ? "This becomes their portal login." : "Optional."}
                >
                  <input
                    type="email"
                    className={inputClass}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="buyer@northwind.test"
                    required={withLogin}
                  />
                </Field>
                <Field label="Tier" hint="Sets their discount ceiling on every quotation line.">
                  <select
                    className={inputClass}
                    value={tier}
                    onChange={(e) => setTier(e.target.value as CustomerTier)}
                  >
                    {TIERS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Currency">
                  <input
                    className={inputClass}
                    value={currency}
                    onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                    maxLength={3}
                  />
                </Field>
                <Field
                  label="Delivery address"
                  hint="Where their orders ship to. Used to pick the nearest warehouse."
                >
                  <input
                    className={inputClass}
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder="44 Harbour Street, Mumbai"
                  />
                </Field>
                <Field
                  label="Latitude"
                  hint="Optional — filled automatically from the address later."
                >
                  <input
                    className={inputClass}
                    value={latitude}
                    onChange={(e) => setLatitude(e.target.value)}
                    placeholder="19.0760"
                  />
                </Field>
                <Field label="Longitude" hint="Give both or neither.">
                  <input
                    className={inputClass}
                    value={longitude}
                    onChange={(e) => setLongitude(e.target.value)}
                    placeholder="72.8777"
                  />
                </Field>
                <Field label="Account manager">
                  <select
                    className={inputClass}
                    value={ownerRepId}
                    onChange={(e) => setOwnerRepId(e.target.value)}
                  >
                    <option value="">Unassigned</option>
                    {salesStaff.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.full_name || user.email}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Portal access">
                  <label className="flex items-center gap-2 pt-2 text-sm text-slate-300">
                    <input
                      type="checkbox"
                      checked={withLogin}
                      onChange={(e) => setWithLogin(e.target.checked)}
                    />
                    Generate portal credentials now
                  </label>
                </Field>
              </div>

              <div className="mt-5">
                <Button type="submit" disabled={busy}>
                  {busy ? "Creating…" : "Create business"}
                </Button>
              </div>
            </form>

            <div className="mt-4">
              <Note>
                The generated password is displayed once and stored only as a hash. When real email
                is wired up, this is where it gets sent to the business directly instead.
              </Note>
            </div>
          </Card>
        </div>
      )}

      {/* ---------------------------------------- list */}
      <Card>
        {businesses.length === 0 ? (
          <EmptyState
            title="No businesses registered"
            hint="Add one above to create a company and issue its portal login."
          />
        ) : (
          <Table
            columns={[
              "Business",
              "Tier",
              "Delivery address",
              "Account manager",
              "Portal login",
              "Access",
              "Last login",
              "Quotes",
              "Actions",
            ]}
          >
            {businesses.map((business) => (
              <Row key={business.id}>
                <Cell className="font-medium text-slate-100">
                  {business.name}
                  <span className="ml-2 text-xs text-slate-500">{business.currency}</span>
                </Cell>
                <Cell>
                  <Badge
                    tone={
                      business.tier === "GOLD"
                        ? "amber"
                        : business.tier === "SILVER"
                          ? "slate"
                          : "slate"
                    }
                  >
                    {business.tier}
                  </Badge>
                </Cell>
                <Cell className="max-w-[220px] text-slate-400">
                  {business.address || <span className="text-slate-500">Not set</span>}
                  {/* Says whether the planner could actually use this address.
                      An address with no point is not yet a location. */}
                  {business.address && !business.has_coordinates && (
                    <span className="mt-[2px] block text-[11px] text-[#D97706]">
                      Not located yet
                    </span>
                  )}
                </Cell>
                <Cell className="text-slate-400">{business.owner_rep_name ?? "—"}</Cell>
                <Cell className="font-mono text-xs text-slate-400">
                  {business.portal_login_email ?? "—"}
                </Cell>
                <Cell>
                  {!business.has_portal_login ? (
                    <Badge tone="slate">No login</Badge>
                  ) : business.portal_access_enabled ? (
                    <Badge tone="green">Active</Badge>
                  ) : (
                    <Badge tone="red">Suspended</Badge>
                  )}
                </Cell>
                <Cell className="text-slate-400">
                  {business.portal_last_login ? dateTime(business.portal_last_login) : "Never"}
                </Cell>
                <Cell>{business.quotation_count}</Cell>
                <Cell>
                  <div className="flex flex-wrap gap-1.5">
                    {!business.has_portal_login ? (
                      <Button
                        variant="secondary"
                        className="!px-2.5 !py-1 text-xs"
                        disabled={busy}
                        onClick={() =>
                          run(
                            () =>
                              post<BusinessCredentials>(
                                `/admin/businesses/${business.id}/portal-login`,
                              ),
                            true,
                          )
                        }
                      >
                        Issue login
                      </Button>
                    ) : (
                      <>
                        <Button
                          variant="secondary"
                          className="!px-2.5 !py-1 text-xs"
                          disabled={busy}
                          onClick={() =>
                            run(
                              () =>
                                post<BusinessCredentials>(
                                  `/admin/businesses/${business.id}/reset-password`,
                                ),
                              true,
                            )
                          }
                        >
                          Reset password
                        </Button>
                        <Button
                          variant={business.portal_access_enabled ? "danger" : "success"}
                          className="!px-2.5 !py-1 text-xs"
                          disabled={busy}
                          onClick={() =>
                            run(
                              () =>
                                post<Business>(`/admin/businesses/${business.id}/access`, {
                                  enabled: !business.portal_access_enabled,
                                }),
                              false,
                            )
                          }
                        >
                          {business.portal_access_enabled ? "Suspend" : "Restore"}
                        </Button>
                      </>
                    )}
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Suspending disables the login without deleting it, so the business&apos;s comments and
            counter-offers stay attached to the quotations they belong to. Revoking access must
            never rewrite the audit trail.
          </Note>
        </div>
      </Card>
    </>
  );
}
