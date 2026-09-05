"use client";

/**
 * Screen 6 — Approval detail.  Owner: the-steelix-flame.
 *
 * "Why This Quote Was Flagged" is rendered straight from the risk engine's own
 * dataclass — no reshaping, so the reason shown here is literally the reason
 * the router used.
 */

import { use, useState } from "react";
import Link from "next/link";

import { ApiError, post } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  ErrorState,
  Field,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { RISK_TONE, dateTime, percent, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { ApprovalDetail } from "@/types";

const STEP_TONE: Record<string, string> = {
  PENDING: "amber",
  APPROVED: "green",
  REJECTED: "red",
  RETURNED: "amber",
  SKIPPED: "slate",
};

export default function ApprovalDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { user, role } = useAuth();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload, setData } = useApi<ApprovalDetail>(`/approvals/${id}`);

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  async function decide(decision: "APPROVED" | "REJECTED" | "RETURNED") {
    if (decision !== "APPROVED" && !note.trim()) {
      setActionError("A reason is required when rejecting or returning a quotation.");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      setData(await post<ApprovalDetail>(`/approvals/${id}/decide`, { decision, note }));
      setNote("");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not record that decision");
    } finally {
      setBusy(false);
    }
  }

  const isOpen = data.status === "PENDING";

  // The decision panel used to render for anyone who could open the page. A
  // Sales Rep saw Approve/Reject, and an approver who had already signed off
  // still saw them on the step that had moved past them — both only failed on
  // the server, after the click, as "This step requires role X".
  const currentStep = data.steps.find((step) => step.status === "PENDING") ?? null;
  const myName = user ? user.full_name || user.email : null;
  const myStep =
    data.steps.find((step) => step.acted_by_name && myName && step.acted_by_name === myName) ??
    null;
  /** Mirrors `act()`: the caller must hold the CURRENT step's role. ADMIN may act on any step. */
  const canDecide =
    isOpen && currentStep !== null && role !== null &&
    (role === currentStep.role_required || role === "ADMIN");
  /** Is this role ever an approver on this chain at all? A Sales Rep never is. */
  const isApprover = role !== null && (role === "ADMIN" || data.chain.includes(role));

  return (
    <>
      <PageHeader
        title={`Approval — ${data.quotation_number}`}
        subtitle={data.customer_name}
        actions={
          <>
            <Badge tone={RISK_TONE[data.risk_band]}>Blended Risk: {data.risk_band}</Badge>
            <Badge tone="blue">Customer Tier: {data.customer_tier}</Badge>
            <Link
              href={`/quotations/${data.quotation_id}`}
              className="rounded-lg border border-edge px-4 py-2 text-sm text-[#334155] hover:bg-surface"
            >
              Open quotation
            </Link>
          </>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <Card title="Why This Quote Was Flagged">
            <Table columns={["Line", "Discount Given", "Limit Allowed", "Weight", "Over By"]}>
              {data.risk.lines.map((line, index) => (
                <Row key={line.line_id ?? index}>
                  <Cell className="font-medium text-[#0F172A]">{line.label}</Cell>
                  <Cell>{percent(line.discount_percent, 0)}</Cell>
                  <Cell>{percent(line.allowed_percent, 0)}</Cell>
                  <Cell className="text-[#64748B]">
                    {(Number(line.weight) * 100).toFixed(0)}% of order
                  </Cell>
                  <Cell>
                    {line.is_over ? (
                      <Badge tone="red">{Number(line.excess_points).toFixed(0)} pt OVER</Badge>
                    ) : (
                      <Badge tone="green">0 pt · OK</Badge>
                    )}
                  </Cell>
                </Row>
              ))}
            </Table>

            <div className="mt-4">
              <Note>{data.risk.explanation}</Note>
            </div>

            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-4">
              {[
                ["Score", data.risk.score],
                ["Worst line", `${data.risk.worst_line_excess} pt`],
                ["Blended", `${data.risk.blended_excess} pt`],
                ["Order-level", `${data.risk.order_level_excess} pt`],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-edge bg-[#F8FAFC] px-3 py-2">
                  <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
                  <dd className="mt-0.5 text-[#334155]">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card title="Audit trail" subtitle="User, action, timestamp and reason">
            <Table columns={["User", "Action", "Date", "Note"]}>
              {data.audit_trail.map((event) => (
                <Row key={event.id}>
                  <Cell>{event.actor_name}</Cell>
                  <Cell>{titleCase(event.event_type)}</Cell>
                  <Cell className="text-[#64748B]">{dateTime(event.created_at)}</Cell>
                  <Cell className="text-[#64748B]">{event.note || "—"}</Cell>
                </Row>
              ))}
            </Table>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Approval chain" subtitle="Finance only appears when the band requires it">
            <ol className="space-y-3">
              {data.steps.map((step) => (
                <li key={step.id} className="flex items-start gap-3">
                  <span
                    className={`mt-1 h-3 w-3 shrink-0 rounded-full ${
                      step.status === "APPROVED"
                        ? "bg-emerald-500"
                        : step.status === "PENDING"
                          ? "bg-brand"
                          : step.status === "REJECTED"
                            ? "bg-rose-500"
                            : "bg-slate-600"
                    }`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-[#0F172A]">
                      {step.sequence}. {titleCase(step.role_required)}
                    </p>
                    <p className="text-xs text-slate-500">
                      {step.assignee_name ?? "Unassigned"}
                      {step.acted_at && ` · ${dateTime(step.acted_at)}`}
                    </p>
                    {step.decision_note && (
                      <p className="mt-1 text-xs text-[#64748B]">&ldquo;{step.decision_note}&rdquo;</p>
                    )}
                  </div>
                  <Badge tone={STEP_TONE[step.status]}>{titleCase(step.status)}</Badge>
                </li>
              ))}
            </ol>
          </Card>

          {isOpen && !canDecide ? (
            <Card title={isApprover ? "Waiting on someone else" : "Not authorised"}>
              {myStep ? (
                <p className="text-sm text-[#475569]">
                  You already <strong>{titleCase(myStep.status)}</strong> this on{" "}
                  {dateTime(myStep.acted_at)}. It has moved to{" "}
                  <strong>{titleCase(currentStep!.role_required)}</strong> and there is nothing
                  further for you to do here.
                </p>
              ) : isApprover ? (
                <p className="text-sm text-[#475569]">
                  This request is with <strong>{titleCase(currentStep!.role_required)}</strong>
                  {currentStep!.assignee_name ? ` (${currentStep!.assignee_name})` : ""}. Steps are
                  decided in order, so you cannot act ahead of them.
                </p>
              ) : (
                <p className="text-sm text-[#475569]">
                  You do not have permission to decide this approval. Discount approvals are
                  decided by <strong>Sales Manager</strong> and <strong>Finance</strong> only — a
                  Sales Rep can see why a quote was flagged, but cannot approve their own discount.
                </p>
              )}
              <div className="mt-3">
                <Note>
                  The same rule is enforced on the server, so hiding these buttons changes what you
                  see, not what you are allowed to do.
                </Note>
              </div>
            </Card>
          ) : isOpen ? (
            <Card title="Your decision">
              <Field
                label="Reason"
                hint="Required when rejecting or returning. Stored on the audit trail."
              >
                <textarea
                  rows={3}
                  className={inputClass}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="e.g. Margin justified by the three-year commitment."
                />
              </Field>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="success" disabled={busy} onClick={() => decide("APPROVED")}>
                  Approve
                </Button>
                <Button variant="warning" disabled={busy} onClick={() => decide("RETURNED")}>
                  Return for Revision
                </Button>
                <Button variant="danger" disabled={busy} onClick={() => decide("REJECTED")}>
                  Reject
                </Button>
              </div>
            </Card>
          ) : (
            <Card title="Closed">
              <p className="text-sm text-[#475569]">
                This request was <strong>{titleCase(data.status)}</strong>. A later change to the
                quotation opens a new request rather than reopening this one, so the history stays
                readable.
              </p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
