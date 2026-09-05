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

  const open = data.status === "SENT" || data.status === "UNDER_NEGOTIATION";

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
          <Badge tone={STATUS_TONE[data.status] ?? "slate"}>{titleCase(data.status)}</Badge>
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

      {data.requests.length > 0 && (
        <Card title="Your requests" className="mb-6">
          <Table columns={["Requested", "Discount", "Delivery", "Status", "Response"]}>
            {data.requests.map((request) => (
              <Row key={request.id}>
                <Cell className="text-[#64748B]">{dateTime(request.created_at)}</Cell>
                <Cell>
                  {request.requested_discount_percent
                    ? percent(request.requested_discount_percent, 0)
                    : "—"}
                </Cell>
                <Cell>{request.requested_delivery_date ?? "—"}</Cell>
                <Cell>
                  <Badge
                    tone={
                      request.status === "ACCEPTED"
                        ? "green"
                        : request.status === "REJECTED"
                          ? "red"
                          : "amber"
                    }
                  >
                    {titleCase(request.status)}
                  </Badge>
                </Cell>
                <Cell className="text-[#64748B]">{request.resolution_note || "—"}</Cell>
              </Row>
            ))}
          </Table>
        </Card>
      )}

      {data.messages.length > 0 && (
        <Card title="Conversation">
          <ul className="space-y-3">
            {data.messages.map((msg) => (
              <li
                key={msg.id}
                className={`rounded-lg border border-edge p-3 ${
                  msg.author_type === "CUSTOMER" ? "bg-[#F8FAFC]" : "bg-blue-950/20"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-[#64748B]">
                    {msg.author_type === "CUSTOMER" ? "You" : "Your account manager"}
                    {msg.line_description && ` · ${msg.line_description}`}
                  </span>
                  <span className="text-xs text-slate-500">{dateTime(msg.created_at)}</span>
                </div>
                <p className="mt-1.5 text-sm text-[#334155]">{msg.body}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
