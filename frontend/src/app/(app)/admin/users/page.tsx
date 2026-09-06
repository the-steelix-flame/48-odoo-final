"use client";

/**
 * User Management.  Owner: the-steelix-flame.
 *
 * Admin creates staff accounts and hands the credentials over. Same one-time
 * password reveal as Business Management — the server only ever keeps a hash.
 *
 * Customer logins are NOT created here. They come from Business Management,
 * which also creates the business record the portal depends on.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, post } from "@/lib/api";
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
import { dateTime, titleCase } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { AdminUser, Role, SalesTeam, UserCredentials } from "@/types";

const CREATABLE_ROLES: { value: Role; label: string }[] = [
  { value: "SALES_REP", label: "Sales Rep" },
  { value: "SALES_MANAGER", label: "Sales Manager" },
  { value: "FINANCE", label: "Finance / Operations" },
  { value: "ADMIN", label: "Admin" },
];

const ROLE_TONE: Record<string, string> = {
  ADMIN: "red",
  SALES_MANAGER: "amber",
  FINANCE: "blue",
  SALES_REP: "green",
  CUSTOMER: "slate",
};

export default function UserManagementPage() {
  const router = useRouter();
  const { user: currentUser } = useAuth();

  const [showForm, setShowForm] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("SALES_REP");
  const [teamId, setTeamId] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  const [credentials, setCredentials] = useState<UserCredentials | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<AdminUser[]>(
    `/admin/users${roleFilter ? `?role=${roleFilter}` : ""}`,
  );
  const { data: teams } = useApi<SalesTeam[]>("/admin/teams");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const users = data ?? [];

  async function run(fn: () => Promise<unknown>, reveal: boolean) {
    setBusy(true);
    setActionError(null);
    setCopied(false);
    try {
      const result = await fn();
      if (reveal) setCredentials(result as UserCredentials);
      await reload();
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    const ok = await run(
      () =>
        post<UserCredentials>("/admin/users", {
          email,
          full_name: fullName,
          role,
          sales_team_id: teamId ? Number(teamId) : null,
        }),
      true,
    );
    if (ok) {
      setShowForm(false);
      setEmail("");
      setFullName("");
      setRole("SALES_REP");
      setTeamId("");
    }
  }

  return (
    <>
      <PageHeader
        title="User Management"
        subtitle="Staff accounts, their credentials, and what each person is doing."
        actions={
          <Button onClick={() => setShowForm((open) => !open)}>
            {showForm ? "Cancel" : "+ Add User"}
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
        <div className="mb-6 rounded-xl border border-[#A7F3D0] bg-[#ECFDF5] p-5">
          <h2 className="text-base font-semibold text-[#065F46]">
            Credentials for {credentials.user.full_name}
          </h2>
          <p className="mt-1 text-sm text-[#047857]">{credentials.notice}</p>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-[#A7F3D0] bg-white px-3 py-2">
              <p className="text-xs uppercase tracking-wide text-[#047857]">Email</p>
              <p className="mt-1 font-mono text-sm text-[#0F172A]">{credentials.email}</p>
            </div>
            <div className="rounded-lg border border-[#A7F3D0] bg-white px-3 py-2">
              <p className="text-xs uppercase tracking-wide text-[#047857]">Password</p>
              <p className="mt-1 font-mono text-sm text-[#0F172A]">{credentials.password}</p>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={async () => {
                await navigator.clipboard.writeText(
                  `DealFlow360\nEmail: ${credentials.email}\nPassword: ${credentials.password}`,
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
          <Card title="Create a user account">
            <form onSubmit={createUser}>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <Field label="Full name">
                  <input
                    className={inputClass}
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="J. Rao"
                    required
                  />
                </Field>
                <Field label="Email" hint="This is their login.">
                  <input
                    type="email"
                    className={inputClass}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="rep@dealflow360.test"
                    required
                  />
                </Field>
                <Field label="Role" hint="Decides what they can do, not who they are.">
                  <select
                    className={inputClass}
                    value={role}
                    onChange={(e) => setRole(e.target.value as Role)}
                  >
                    {CREATABLE_ROLES.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Sales team" hint="Used for approval routing and reporting.">
                  <select
                    className={inputClass}
                    value={teamId}
                    onChange={(e) => setTeamId(e.target.value)}
                  >
                    <option value="">None</option>
                    {(teams ?? []).map((team) => (
                      <option key={team.id} value={team.id}>
                        {team.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              <div className="mt-5">
                <Button type="submit" disabled={busy}>
                  {busy ? "Creating…" : "Create user"}
                </Button>
              </div>
            </form>

            <div className="mt-4">
              <Note>
                Customer logins aren&apos;t created here — they come from{" "}
                <Link href="/admin/businesses" className="text-brand hover:underline">
                  Business Management
                </Link>
                , which also creates the business record the portal needs.
              </Note>
            </div>
          </Card>
        </div>
      )}

      {/* ---------------------------------------- filter + list */}
      <div className="mb-4 flex flex-wrap gap-2">
        <button
          onClick={() => setRoleFilter("")}
          className={`rounded-lg border px-3 py-1 text-xs transition ${
            roleFilter === ""
              ? "border-brand bg-brand/20 text-white"
              : "border-edge text-slate-300 hover:bg-white/5"
          }`}
        >
          All ({users.length})
        </button>
        {["ADMIN", "SALES_MANAGER", "SALES_REP", "FINANCE", "CUSTOMER"].map((value) => (
          <button
            key={value}
            onClick={() => setRoleFilter(value)}
            className={`rounded-lg border px-3 py-1 text-xs transition ${
              roleFilter === value
                ? "border-brand bg-brand/20 text-white"
                : "border-edge text-slate-300 hover:bg-white/5"
            }`}
          >
            {titleCase(value)}
          </button>
        ))}
      </div>

      <Card>
        {users.length === 0 ? (
          <EmptyState title="No users match this filter" />
        ) : (
          <Table
            columns={[
              "Name",
              "Email",
              "Role",
              "Team / Business",
              "Status",
              "Quotes",
              "Decisions",
              "Last login",
              "Actions",
            ]}
          >
            {users.map((user) => (
              <Row key={user.id}>
                <Cell>
                  <button
                    onClick={() => router.push(`/admin/users/${user.id}`)}
                    className="font-medium text-brand hover:underline"
                  >
                    {user.full_name || "—"}
                  </button>
                  {currentUser?.id === user.id && (
                    <span className="ml-2 text-xs text-slate-500">(you)</span>
                  )}
                </Cell>
                <Cell className="font-mono text-xs text-slate-400">{user.email}</Cell>
                <Cell>
                  <Badge tone={ROLE_TONE[user.role]}>{titleCase(user.role)}</Badge>
                </Cell>
                <Cell className="text-slate-400">
                  {user.business_name ?? user.sales_team_name ?? "—"}
                </Cell>
                <Cell>
                  <Badge tone={user.is_active ? "green" : "red"}>
                    {user.is_active ? "Active" : "Disabled"}
                  </Badge>
                </Cell>
                <Cell>{user.quotations_owned}</Cell>
                <Cell>{user.approvals_made}</Cell>
                <Cell className="text-slate-400">
                  {user.last_login ? dateTime(user.last_login) : "Never"}
                </Cell>
                <Cell>
                  <div className="flex flex-wrap gap-1.5">
                    <Button
                      variant="secondary"
                      className="!px-2.5 !py-1 text-xs"
                      disabled={busy}
                      onClick={() =>
                        run(
                          () => post<UserCredentials>(`/admin/users/${user.id}/reset-password`),
                          true,
                        )
                      }
                    >
                      Reset
                    </Button>
                    <Button
                      variant={user.is_active ? "danger" : "success"}
                      className="!px-2.5 !py-1 text-xs"
                      disabled={busy || currentUser?.id === user.id}
                      onClick={() =>
                        run(
                          () =>
                            post(`/admin/users/${user.id}/access`, { enabled: !user.is_active }),
                          false,
                        )
                      }
                    >
                      {user.is_active ? "Disable" : "Enable"}
                    </Button>
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Disabling keeps the account and everything attached to it. Quotations, approval
            decisions and audit events all point at this row — deleting it would turn a named
            decision into an anonymous one. Click any name for that person&apos;s analytics.
          </Note>
        </div>
      </Card>
    </>
  );
}
