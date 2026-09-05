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
  const [lineComment, setLineComment] = useState<Record<number, string>>({});
  const [chat, setChat] = useState("");
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

  async function submitRequest() {
    setBusy(true);
    setActionError(null);
    try {
      const lineComments = Object.entries(lineComment)
        .filter(([, body]) => body.trim())
        .map(([lineId, body]) => ({ quotation_line_id: Number(lineId), body }));

      setData(
        await post<PortalQuotation>(`/portal/quotations/${id}/requests`, {
          requested_discount_percent: counterDiscount || null,
          requested_delivery_date: deliveryDate || null,
          message,
          line_comments: lineComments,
        }),
      );
      setCounterDiscount("");
      setDeliveryDate("");
      setMessage("");
      setLineComment({});
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not submit your request");
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
        <Card title="Request a change" className="mb-6">
          <p className="mb-4 text-sm text-[#64748B]">
            Ask a question on any line, or propose different terms. No email needed.
          </p>

          <div className="space-y-3">
            {data.lines.map((line) => (
              <div key={line.id} className="grid gap-2 sm:grid-cols-[200px_1fr] sm:items-center">
                <span className="text-sm text-[#475569]">{line.description}</span>
                <input
                  className={inputClass}
                  placeholder="Add a comment about this line…"
                  value={lineComment[line.id] ?? ""}
                  onChange={(e) =>
                    setLineComment({ ...lineComment, [line.id]: e.target.value })
                  }
                />
              </div>
            ))}
          </div>

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
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

          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={submitRequest} disabled={busy}>
              Submit Request
            </Button>
            <Button variant="success" onClick={confirmQuotation} disabled={busy}>
              Confirm Quotation
            </Button>
          </div>

          <div className="mt-4">
            <Note>
              If the final terms exceed our approval thresholds, the quotation automatically
              re-enters internal approval before it&apos;s accepted.
            </Note>
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

        {open && (
          <div className="mt-5 border-t border-edge pt-4">
            <Field label="Send a message" hint="For anything that isn't about price.">
              <textarea
                rows={2}
                className={inputClass}
                value={chat}
                onChange={(e) => setChat(e.target.value)}
                placeholder="Type a message…"
              />
            </Field>
            <div className="mt-3">
              <Button
                variant="secondary"
                disabled={busy || !chat.trim()}
                onClick={async () => {
                  setBusy(true);
                  setActionError(null);
                  try {
                    setData(
                      await post<PortalQuotation>(`/portal/quotations/${id}/messages`, {
                        body: chat,
                      }),
                    );
                    setChat("");
                  } catch (err) {
                    setActionError(err instanceof ApiError ? err.message : "Could not send");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Send message
              </Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
