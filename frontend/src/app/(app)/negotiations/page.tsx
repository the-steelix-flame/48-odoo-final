"use client";

/**
 * Rep-side negotiation inbox.  Owner: sinjeki (screen listed as a TODO in
 * README §8 under the-steelix-flame's lane; built here so the counter-offer
 * loop is demonstrable from both ends).
 *
 * The portal lets a customer counter. Until now nothing on the internal side
 * ever showed those counters — `GET /portal/internal/requests` and its
 * accept/reject endpoints existed with no screen in front of them, so the
 * second half of the negotiation loop could only be demoed with curl.
 *
 * The headline behaviour is on accept: the counter is written through the
 * normal quotation service, which re-runs the risk engine, which may reopen
 * approval on its own. We surface that as `re_entered_approval` rather than
 * letting it happen invisibly — it is the single most interesting thing this
 * screen does.
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
import { dateTime, date as fmtDate, percent, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { InternalNegotiationRequest, NegotiationAcceptResult } from "@/types";

const STATUS_TONE: Record<string, string> = {
  SUBMITTED: "amber",
  ACCEPTED: "green",
  REJECTED: "red",
  COUNTERED: "blue",
};

export default function NegotiationInboxPage() {
  const router = useRouter();
  const [openOnly, setOpenOnly] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<NegotiationAcceptResult | null>(null);

  const { data, error, loading, reload } = useApi<InternalNegotiationRequest[]>(
    openOnly ? "/portal/internal/requests?status=SUBMITTED" : "/portal/internal/requests",
  );

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const rows = data ?? [];
  const open = rows.filter((row) => row.status === "SUBMITTED").length;

  async function accept(row: InternalNegotiationRequest) {
    setBusyId(row.id);
    setMessage(null);
    setOutcome(null);
    try {
      const result = await post<NegotiationAcceptResult>(
        `/portal/internal/requests/${row.id}/accept`,
      );
      setOutcome(result);
      setMessage(
        result.re_entered_approval
          ? `Accepted. ${row.quotation_number} re-entered approval automatically at ${result.risk_band} risk (score ${result.blended_risk_score}).`
          : `Accepted. ${row.quotation_number} stayed within every ceiling — no new approval needed.`,
      );
      await reload();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not accept the counter-offer");
    } finally {
      setBusyId(null);
    }
  }

  async function reject(row: InternalNegotiationRequest) {
    setBusyId(row.id);
    setMessage(null);
    setOutcome(null);
    try {
      await post(`/portal/internal/requests/${row.id}/reject`, { note });
      setMessage(`Rejected ${row.quotation_number}. The customer sees your reason in the portal.`);
      setRejecting(null);
      setNote("");
      await reload();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not reject the counter-offer");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Negotiation inbox"
        subtitle="Counter-offers customers raised from the portal, and what you do about them."
      />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <Badge tone="amber">{open} Awaiting you</Badge>
        <Badge tone="slate">{rows.length} Shown</Badge>
        <button
          onClick={() => setOpenOnly((value) => !value)}
          className="rounded-[8px] border border-[#E2E8F0] bg-white px-3 py-[5px] text-[12px] text-[#475569] transition hover:border-[#CBD5E1] hover:bg-[#F8FAFC]"
        >
          {openOnly ? "Show resolved too" : "Filter: awaiting me"}
        </button>
      </div>

      {message && (
        <div className="mb-4">
          <Note>{message}</Note>
        </div>
      )}

      {outcome?.re_entered_approval && (
        <div className="mb-4">
          <Card
            title="This quote is back in approval"
            subtitle="Accepting the counter re-scored the deal — the engine reopened approval, nobody had to remember to."
            actions={
              <Button variant="secondary" onClick={() => router.push("/approvals")}>
                Open approvals
              </Button>
            }
          >
            <div className="flex flex-wrap gap-3 text-[13px] text-[#334155]">
              <span>
                Band <Badge tone={outcome.risk_band === "HIGH" ? "red" : "amber"}>{outcome.risk_band}</Badge>
              </span>
              <span className="text-[#64748B]">Blended score {outcome.blended_risk_score}</span>
              <span className="text-[#64748B]">Status {titleCase(outcome.status)}</span>
            </div>
          </Card>
        </div>
      )}

      <Card>
        {rows.length === 0 ? (
          <EmptyState
            title={openOnly ? "No counter-offers waiting" : "No counter-offers yet"}
            hint={
              openOnly
                ? "Nothing needs your decision. Switch the filter to see resolved ones."
                : "When a customer counters from the portal, it lands here."
            }
          />
        ) : (
          <Table
            columns={["Quotation", "Customer", "Asked for", "Message", "Status", "Raised", "Decision"]}
          >
            {rows.map((row) => (
              <Row key={row.id}>
                <Cell className="font-heading font-medium text-[#0F172A]">
                  <Link
                    href={`/quotations/${row.quotation_id}`}
                    className="underline decoration-[#CBD5E1] underline-offset-2 hover:decoration-[#0891B2]"
                  >
                    {row.quotation_number}
                  </Link>
                </Cell>
                <Cell>{row.customer_name}</Cell>
                <Cell>
                  {row.requested_discount_percent != null && (
                    <span className="font-mono text-[12.5px] text-[#0F172A]">
                      {percent(row.requested_discount_percent)} discount
                    </span>
                  )}
                  {row.requested_delivery_date && (
                    <span className="block text-[12px] text-[#64748B]">
                      by {fmtDate(row.requested_delivery_date)}
                    </span>
                  )}
                  {row.requested_discount_percent == null && !row.requested_delivery_date && (
                    <span className="text-[#64748B]">—</span>
                  )}
                </Cell>
                <Cell className="max-w-[280px] text-[#475569]">
                  {row.message || <span className="text-[#94A3B8]">No message</span>}
                  {row.resolution_note && (
                    <span className="mt-[4px] block text-[12px] italic text-[#64748B]">
                      Your note: {row.resolution_note}
                    </span>
                  )}
                </Cell>
                <Cell>
                  <Badge tone={STATUS_TONE[row.status] ?? "slate"}>{titleCase(row.status)}</Badge>
                </Cell>
                <Cell className="text-[#64748B]">{dateTime(row.created_at)}</Cell>
                <Cell>
                  {row.status !== "SUBMITTED" ? (
                    <span className="text-[12px] text-[#94A3B8]">Resolved</span>
                  ) : rejecting === row.id ? (
                    <div className="w-[220px] space-y-2">
                      <Field label="Reason (the customer sees this)">
                        <input
                          className={inputClass}
                          value={note}
                          autoFocus
                          placeholder="Below our Gold floor"
                          onChange={(event) => setNote(event.target.value)}
                        />
                      </Field>
                      <div className="flex gap-2">
                        <Button
                          variant="danger"
                          disabled={busyId === row.id}
                          onClick={() => void reject(row)}
                        >
                          {busyId === row.id ? "Rejecting…" : "Confirm reject"}
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setRejecting(null);
                            setNote("");
                          }}
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button
                        variant="success"
                        disabled={busyId === row.id}
                        onClick={() => void accept(row)}
                      >
                        {busyId === row.id ? "Accepting…" : "Accept"}
                      </Button>
                      <Button variant="secondary" onClick={() => setRejecting(row.id)}>
                        Reject
                      </Button>
                    </div>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Accepting rewrites the discount through the normal quotation service, so the risk engine
            re-scores the deal and may reopen approval by itself. That is the point — the portal gets
            no special path around governance.
          </Note>
        </div>
      </Card>
    </>
  );
}
