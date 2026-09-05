"use client";

/**
 * Screen 11 — Customer portal negotiation.  Owner: the-steelix-flame.
 *
 * Note what this screen CANNOT show: cost, margin, risk score, approval
 * history, internal notes. Not because they're filtered out here, but because
 * `PortalQuotationOut` never sends them. There is no code path from margin
 * data to this component.
 */

import { use, useState } from "react";
import Link from "next/link";

import { ApiError, post } from "@/lib/api";
import { NegotiationThread } from "@/components/negotiation/Thread";
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
import { dateTime, money, percent, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { PortalQuotation } from "@/types";

const STATUS_TONE: Record<string, string> = {
  SENT: "blue",
  UNDER_NEGOTIATION: "amber",
  CONFIRMED: "green",
  PENDING_APPROVAL: "amber",
  APPROVED: "green",
};

export default function PortalQuotationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [counterDiscount, setCounterDiscount] = useState("");
  const [deliveryDate, setDeliveryDate] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmNotice, setConfirmNotice] = useState<string | null>(null);

  const { data, error, loading, reload, setData } = useApi<PortalQuotation>(
    `/portal/quotations/${id}`,
  );

  if (loading) return <Loading />;
  if (error) {
    return (
      <ErrorState
        message={
          error.status === 404
            ? "We couldn't find that quotation on your account."
            : error.message
        }
        onRetry={reload}
      />
    );
  }
  if (!data) return null;

  const open =
    data.status === "SENT" ||
    data.status === "UNDER_NEGOTIATION" ||
    data.status === "APPROVED";
  // A countered request with a number on it is our offer, waiting on them.
  const counterOffer =
    data.open_request?.status === "COUNTERED" &&
    data.open_request.counter_discount_percent != null
      ? data.open_request
      : null;
  /** Their request is unanswered, so the server will refuse a confirmation. */
  const awaitingOurReply = data.open_request?.status === "SUBMITTED";

  async function submitRequest() {
    setBusy(true);
    setActionError(null);
    try {
      setData(
        await post<PortalQuotation>(`/portal/quotations/${id}/requests`, {
          requested_discount_percent: counterDiscount || null,
          requested_delivery_date: deliveryDate || null,
          message,
        }),
      );
      setCounterDiscount("");
      setDeliveryDate("");
      setMessage("");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not submit your request");
    } finally {
      setBusy(false);
    }
  }

  async function rejectQuotation() {
    setBusy(true);
    setActionError(null);
    setConfirmNotice(null);
    try {
      setData(
        await post<PortalQuotation>(`/portal/quotations/${id}/reject`, { note: message }),
      );
      setMessage("");
      setConfirmNotice("You've declined this quotation. Your account manager has been told.");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not decline");
    } finally {
      setBusy(false);
    }
  }

  async function confirmQuotation() {
    setBusy(true);
    setActionError(null);
    setConfirmNotice(null);
    try {
      const updated = await post<PortalQuotation>(`/portal/quotations/${id}/confirm`);
      setData(updated);
      setConfirmNotice(
        updated.status === "CONFIRMED"
          ? "Thank you — your order is confirmed and moving to fulfillment."
          : "Thanks. The final terms need one more internal approval; we'll be in touch shortly.",
      );
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not confirm");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`Quotation ${data.number}`}
        subtitle={`Prepared for ${data.company_name}`}
        actions={
          <>
            {/* Plain-language status from the backend. The internal names
                ("Pending Approval") leak process a customer shouldn't have to
                interpret. */}
            <Badge tone={data.action_required ? "amber" : STATUS_TONE[data.status] ?? "slate"}>
              {data.status_label}
            </Badge>
            <Link
              href="/portal"
              className="rounded-lg border border-edge px-4 py-2 text-sm text-slate-200 hover:bg-surface"
            >
              All quotations
            </Link>
          </>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}
      {confirmNotice && (
        <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {confirmNotice}
        </div>
      )}

      <Card title="Your quotation" className="mb-6">
        <Table columns={["Item", "Qty", "Unit Price", "Discount", "Total"]}>
          {data.lines.map((line) => (
            <Row key={line.id}>
              <Cell className="font-medium text-[#0F172A]">{line.description}</Cell>
              <Cell>{Number(line.quantity)}</Cell>
              <Cell>{money(line.unit_price, data.currency)}</Cell>
              <Cell>{percent(line.discount_percent, 0)}</Cell>
              <Cell>{money(line.line_total, data.currency)}</Cell>
            </Row>
          ))}
        </Table>

        <dl className="mt-4 space-y-2 text-sm">
          {[
            ["Subtotal", money(data.subtotal, data.currency)],
            ["Discount", `− ${money(data.discount_total, data.currency)}`],
            ["Tax", money(data.tax_total, data.currency)],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <dt className="text-[#64748B]">{label}</dt>
              <dd className="text-[#334155]">{value}</dd>
            </div>
          ))}
          <div className="flex justify-between border-t border-edge pt-2 text-base font-semibold">
            <dt className="text-[#475569]">Total</dt>
            <dd className="text-[#0F172A]">{money(data.total, data.currency)}</dd>
          </div>
        </dl>
      </Card>

      {open && (
        <Card title="Your decision" className="mb-6">
          <p className="mb-4 text-sm text-[#64748B]">
            Accept these terms, propose different ones, or decline. No email needed.
          </p>

          {/* The discount already on the table. It was only visible per line,
              so an order-level discount on top of them meant no single number
              on the page answered "what are we actually being given?". */}
          <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-[#BAE6FD] bg-[#F0F9FF] px-4 py-3">
            <span className="text-sm text-[#0369A1]">Discount currently offered</span>
            <span className="font-heading text-[22px] font-bold text-[#0C4A6E]">
              {percent(data.effective_discount_percent, 1)}
            </span>
            <span className="text-sm text-[#0369A1]">
              — {money(data.discount_total, data.currency)} off{" "}
              {money(data.subtotal, data.currency)}
            </span>
          </div>

          {/* The per-line comment boxes were removed. They restated the line
              table directly above them just to hang an input off each row, and
              a customer arguing a price argues about the order, not line 3 —
              the one "Message" field below carries that. The endpoint still
              accepts `line_comments`, so a rep-side annotation UI can use it
              without a backend change. */}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Counter Discount %">
              <input
                type="number"
                min="0"
                max="100"
                className={inputClass}
                value={counterDiscount}
                onChange={(e) => setCounterDiscount(e.target.value)}
                placeholder="e.g. 20"
              />
            </Field>
            <Field label="Requested Delivery Date">
              <input
                type="date"
                className={inputClass}
                value={deliveryDate}
                onChange={(e) => setDeliveryDate(e.target.value)}
              />
            </Field>
          </div>

          <div className="mt-4">
            <Field label="Message">
              <textarea
                rows={2}
                className={inputClass}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Anything else we should know?"
              />
            </Field>
          </div>

          {/* Three answers, and only the customer gets all three. Accepting
              and negotiating are blocked while a request of theirs is still
              unanswered — the server refuses both, and they used to find that
              out by clicking. Declining is never blocked: "no thank you" must
              always be available, or a deal they've already refused sits open
              pretending to be live. */}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <Button
              variant="success"
              onClick={confirmQuotation}
              disabled={busy || awaitingOurReply}
            >
              Accept
            </Button>
            <Button
              variant="secondary"
              onClick={submitRequest}
              disabled={busy || awaitingOurReply}
            >
              Negotiate
            </Button>
            <Button variant="danger" onClick={rejectQuotation} disabled={busy}>
              Reject
            </Button>
            {awaitingOurReply && (
              <span className="text-xs text-[#92400E]">
                Waiting on our reply to your request — you can accept or negotiate again once
                we&apos;ve responded.
              </span>
            )}
          </div>

          <div className="mt-4">
            <Note>
              If the final terms exceed our approval thresholds, the quotation automatically
              re-enters internal approval before it&apos;s accepted.
            </Note>
          </div>
        </Card>
      )}

      {/* Where the actions used to sit once there is nothing left to do. An
          empty space reads as a missing feature; a status reads as finished. */}
      {!open && (
        <Card className="mb-6">
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone={data.status === "CONFIRMED" ? "green" : "slate"}>
              {data.status_label}
            </Badge>
            <p className="text-sm text-[#475569]">
              {data.status === "CONFIRMED"
                ? "This quotation is confirmed and has moved to fulfillment. Nothing further is needed from you."
                : data.status === "PENDING_APPROVAL"
                  ? "Your terms are with our team for internal review. We'll be in touch as soon as it's cleared."
                  : "This quotation is closed. Contact your account manager if you'd like to reopen it."}
            </p>
          </div>
        </Card>
      )}

      {/* ---------------------------------------- our counter-offer */}
      {counterOffer && (
        <div className="mb-6 rounded-xl border border-[#BAE6FD] bg-[#F0F9FF] p-5">
          <h2 className="text-base font-semibold text-[#0C4A6E]">We&apos;ve made you an offer</h2>
          <p className="mt-1 text-sm text-[#0369A1]">
            You asked for {percent(counterOffer.requested_discount_percent, 0)}. We can offer{" "}
            <strong>{percent(counterOffer.counter_discount_percent, 0)}</strong>.
            {counterOffer.resolution_note && ` ${counterOffer.resolution_note}`}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              variant="success"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setActionError(null);
                try {
                  setData(
                    await post<PortalQuotation>(
                      `/portal/quotations/${id}/requests/${counterOffer.id}/accept`,
                    ),
                  );
                } catch (err) {
                  setActionError(err instanceof ApiError ? err.message : "Could not accept");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Accept {percent(counterOffer.counter_discount_percent, 0)}
            </Button>
            <span className="self-center text-xs text-[#64748B]">
              …or propose something different below.
            </span>
          </div>
        </div>
      )}

      <Card title="Conversation" className="mb-6">
        <NegotiationThread
          entries={data.timeline}
          viewpoint="CUSTOMER"
          emptyHint="Questions and counter-offers appear here."
        />

        {/* The free-text message box is gone from both sides. Every message
            that matters now rides along with a decision — the note on a
            counter-offer, the comment on a line — so a standalone chat channel
            was a second place to say things that nobody was obliged to read. */}
      </Card>
    </>
  );
}
