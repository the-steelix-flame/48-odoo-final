"use client";

/**
 * User detail & analytics.  Owner: the-steelix-flame.
 *
 * Which sections appear depends on the role, because "how is this person
 * doing" means different things for a rep (are they discounting responsibly
 * and closing?) and an approver (are they the bottleneck?). The backend
 * decides which sections to send; this page just renders what arrives.
 */

import { use, useState } from "react";
import Link from "next/link";

import { ApiError, post } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  EmptyState,
  ErrorState,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { RISK_TONE, STATUS_TONE, date, dateTime, money, titleCase } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { AdminUserDetail, Role, UserCredentials } from "@/types";

const ROLE_TONE: Record<string, string> = {
  ADMIN: "red",
  SALES_MANAGER: "amber",
  FINANCE: "blue",
  SALES_REP: "green",
  CUSTOMER: "slate",
};

const ASSIGNABLE_ROLES: Role[] = ["SALES_REP", "SALES_MANAGER", "FINANCE", "ADMIN"];

const DECISION_TONE: Record<string, string> = {
  APPROVED: "green",
  REJECTED: "red",
  RETURNED: "amber",
  PENDING: "amber",
  SKIPPED: "slate",
};

export default function UserDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user: currentUser } = useAuth();

  const [credentials, setCredentials] = useState<UserCredentials | null>(null);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<AdminUserDetail>(`/admin/users/${id}`);

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const { user } = data;
  const isSelf = currentUser?.id === user.id;

  async function run(fn: () => Promise<unknown>, reveal: boolean) {
    setBusy(true);
    setActionError(null);
    setCopied(false);
    try {
      const result = await fn();
      if (reveal) setCredentials(result as UserCredentials);
      await reload();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={user.full_name || user.email}
        subtitle={`${user.email} · joined ${date(user.date_joined)}`}
        actions={
          <>
            <Badge tone={ROLE_TONE[user.role]}>{titleCase(user.role)}</Badge>
            <Badge tone={user.is_active ? "green" : "red"}>
              {user.is_active ? "Active" : "Disabled"}
            </Badge>
            <Link
              href="/admin/users"
              className="rounded-lg border border-edge px-4 py-2 text-sm text-slate-200 hover:bg-surface"
            >
              All users
            </Link>
          </>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      {credentials && (
        <div className="mb-6 rounded-xl border border-emerald-700 bg-emerald-950/30 p-5">
          <h2 className="text-base font-semibold text-emerald-200">New credentials</h2>
          <p className="mt-1 text-sm text-emerald-300/80">{credentials.notice}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-emerald-800 bg-black/30 px-3 py-2">
              <p className="text-xs uppercase tracking-wide text-emerald-400/70">Email</p>
              <p className="mt-1 font-mono text-sm text-slate-100">{credentials.email}</p>
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
                  `DealFlow360\nEmail: ${credentials.email}\nPassword: ${credentials.password}`,
                );
                setCopied(true);
              }}
            >
              {copied ? "Copied" : "Copy credentials"}
            </Button>
            <Button variant="secondary" onClick={() => setCredentials(null)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {/* ---------------------------------------- analytics */}
      {data.sections.length === 0 ? (
        <Card className="mb-6">
          <EmptyState
            title="No analytics for this role"
            hint="Admin accounts that neither sell nor approve have nothing to measure yet."
          />
        </Card>
      ) : (
        data.sections.map((section) => (
          <Card
            key={section.title}
            title={section.title}
            subtitle={`Trailing ${data.window_days} days`}
            className="mb-6"
          >
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
              {section.metrics.map((metric) => (
                <div
                  key={metric.label}
                  className="rounded-lg border border-edge bg-black/20 px-3 py-3"
                >
                  <p className="text-xs uppercase tracking-wide text-slate-500">
                    {metric.label}
                  </p>
                  <p className="mt-1.5 text-xl font-semibold text-slate-100">{metric.value}</p>
                  {metric.hint && (
                    <p className="mt-1 text-xs text-slate-500">{metric.hint}</p>
                  )}
                </div>
              ))}
            </div>
          </Card>
        ))
      )}

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          {data.recent_quotations.length > 0 && (
            <Card title="Recent quotations">
              <Table columns={["Quotation", "Customer", "Status", "Risk", "Total", "Created"]}>
                {data.recent_quotations.map((quotation) => (
                  <Row key={quotation.id}>
                    <Cell>
                      <Link
                        href={`/quotations/${quotation.id}`}
                        className="font-medium text-brand hover:underline"
                      >
                        {quotation.number}
                      </Link>
                    </Cell>
                    <Cell>{quotation.customer_name}</Cell>
                    <Cell>
                      <Badge tone={STATUS_TONE[quotation.status]}>
                        {titleCase(quotation.status)}
                      </Badge>
                    </Cell>
                    <Cell>
                      <Badge tone={RISK_TONE[quotation.risk_band]}>{quotation.risk_band}</Badge>
                    </Cell>
                    <Cell>{money(quotation.total)}</Cell>
                    <Cell className="text-slate-400">{date(quotation.created_at)}</Cell>
                  </Row>
                ))}
              </Table>
            </Card>
          )}

          {data.recent_decisions.length > 0 && (
            <Card title="Recent approval decisions">
              <Table columns={["Quotation", "Customer", "Decision", "Note", "When"]}>
                {data.recent_decisions.map((decision, index) => (
                  <Row key={index}>
                    <Cell>
                      <Link
                        href={`/quotations/${decision.quotation_id}`}
                        className="font-medium text-brand hover:underline"
                      >
                        {decision.quotation_number}
                      </Link>
                    </Cell>
                    <Cell>{decision.customer_name}</Cell>
                    <Cell>
                      <Badge tone={DECISION_TONE[decision.decision]}>
                        {titleCase(decision.decision)}
                      </Badge>
                    </Cell>
                    <Cell className="text-slate-400">{decision.note || "—"}</Cell>
                    <Cell className="text-slate-400">{dateTime(decision.acted_at)}</Cell>
                  </Row>
                ))}
              </Table>
            </Card>
          )}
        </div>

        {/* ---------------------------------------- account admin */}
        <div className="space-y-6">
          <Card title="Account">
            <dl className="space-y-2 text-sm">
              {[
                ["Email", user.email],
                ["Team", user.sales_team_name ?? "—"],
                ["Business", user.business_name ?? "—"],
                ["Joined", date(user.date_joined)],
                ["Last login", user.last_login ? dateTime(user.last_login) : "Never"],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3">
                  <dt className="text-slate-400">{label}</dt>
                  <dd className="text-right text-slate-200">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Manage">
            {user.role === "CUSTOMER" ? (
              <Note>
                This is a portal login. Manage its access and password from{" "}
                <Link href="/admin/businesses" className="text-brand hover:underline">
                  Business Management
                </Link>
                .
              </Note>
            ) : (
              <>
                <div className="mb-4">
                  <label className="mb-1.5 block text-xs font-medium text-slate-400">Role</label>
                  <select
                    className={inputClass}
                    value={user.role}
                    disabled={busy || isSelf}
                    onChange={(e) =>
                      run(
                        () => post(`/admin/users/${id}/role`, { role: e.target.value }),
                        false,
                      )
                    }
                  >
                    {ASSIGNABLE_ROLES.map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </select>
                  {isSelf && (
                    <p className="mt-1 text-xs text-slate-500">
                      You can&apos;t change your own role.
                    </p>
                  )}
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () => post<UserCredentials>(`/admin/users/${id}/reset-password`),
                        true,
                      )
                    }
                  >
                    Reset password
                  </Button>
                  <Button
                    variant={user.is_active ? "danger" : "success"}
                    disabled={busy || isSelf}
                    onClick={() =>
                      run(
                        () => post(`/admin/users/${id}/access`, { enabled: !user.is_active }),
                        false,
                      )
                    }
                  >
                    {user.is_active ? "Disable account" : "Enable account"}
                  </Button>
                </div>

                {isSelf && (
                  <p className="mt-3 text-xs text-slate-500">
                    You can&apos;t disable your own account.
                  </p>
                )}
              </>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
