"use client";

/**
 * The customer's half of the billing flow.  Owner: the-steelix-flame.
 *
 * One panel, three states, driven entirely by what the API sends:
 *   no bill      → the deal is confirmed but Finance hasn't signed it off yet
 *   bill unpaid  → "Your bill has been generated" + the way to pay it
 *   bill paid    → despatch status, and the invoice itself
 *
 * Nothing here decides when a bill exists. `PortalQuotation.bill` is null until
 * Finance or a Sales Manager accepts the final deal, so this panel cannot show
 * a bill early even if the status says CONFIRMED.
 */

import Link from "next/link";

import { Badge, Card, Cell, Row, Table } from "@/components/ui";
import { date, money } from "@/lib/format";
import type { PortalQuotation } from "@/types";

export function BillPanel({ quotation }: { quotation: PortalQuotation }) {
  const bill = quotation.bill ?? null;

  // Confirmed, but nobody internal has accepted the final deal yet. Saying so
  // beats silence — the customer has just agreed to something and would
  // otherwise be looking at a page with no next step on it.
  if (!bill) {
    if (quotation.status !== "CONFIRMED") return null;
    return (
      <Card title="Billing" className="mb-6">
        <p className="text-[13.5px] text-[#475569]">
          Your order is confirmed. Your bill will appear here as soon as our team has finalised
          it — there is nothing to pay in the meantime.
        </p>
      </Card>
    );
  }

  return (
    <>
      {bill.is_paid ? (
        <PaidBill quotation={quotation} />
      ) : (
        <OutstandingBill quotation={quotation} />
      )}
      <BillHistory quotation={quotation} />
    </>
  );
}

/**
 * Every invoice on this order.
 *
 * The panel above shows the ONE the customer is dealing with — what is due, or
 * their latest receipt. On an order that bills the goods once and a
 * subscription every period that hid the rest, so someone who had paid twice
 * could only ever see one of their own payments. Only rendered when there is
 * genuinely more than one.
 */
function BillHistory({ quotation }: { quotation: PortalQuotation }) {
  const history = quotation.bill_history ?? [];
  if (history.length < 2) return null;

  const currency = quotation.bill?.currency ?? quotation.currency;
  const paid = history.reduce((sum, row) => sum + Number(row.amount_paid), 0);

  return (
    <Card
      title="Your invoices"
      subtitle={`${history.length} invoices on this order · ${money(
        paid,
        currency,
      )} paid to date`}
      className="mb-6"
    >
      <Table columns={["Invoice", "Issued", "Covers", "Amount", "Status"]}>
        {history.map((row) => (
          <Row key={row.id}>
            <Cell className="font-medium text-[#0F172A]">{row.number}</Cell>
            <Cell className="text-[#64748B]">{date(row.issue_date)}</Cell>
            <Cell className="text-[#64748B]">
              {row.period_start && row.period_end
                ? `${date(row.period_start)} → ${date(row.period_end)}`
                : "One-off"}
            </Cell>
            <Cell>{money(row.total, currency)}</Cell>
            <Cell>
              {row.is_paid ? (
                <Badge tone="green">Paid</Badge>
              ) : (
                <Badge tone="amber">{money(row.amount_due, currency)} due</Badge>
              )}
            </Cell>
          </Row>
        ))}
      </Table>
    </Card>
  );
}

/** ------------------------------------------------------------- unpaid */
function OutstandingBill({ quotation }: { quotation: PortalQuotation }) {
  const bill = quotation.bill!;
  // Partial settlement isn't reachable from the portal, which always pays in
  // full — but an internally recorded part-payment would land here, and the
  // customer should be asked for the balance, not the whole total again.
  const partlyPaid = Number(bill.amount_paid) > 0;

  return (
    <div className="mb-6 overflow-hidden rounded-[12px] border border-[#BAE6FD] bg-[#F0F9FF]">
      <div className="p-[24px]">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="font-heading text-[18px] font-semibold tracking-[-0.01em] text-[#0C4A6E]">
              Your bill has been generated
            </h2>
            <p className="mt-[6px] text-[13.5px] text-[#0369A1]">
              {bill.number} · issued {date(bill.issue_date)} · due {date(bill.due_date)}
            </p>
            <p className="mt-[2px] text-[13px] text-[#0369A1]">
              Agreed with {bill.sales_rep} on quotation {quotation.number}.
            </p>
          </div>
          <div className="text-right">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-[#0369A1]">
              {partlyPaid ? "Balance due" : "Amount due"}
            </p>
            <p className="font-heading text-[30px] font-bold tracking-[-0.02em] text-[#0C4A6E]">
              {money(bill.amount_due, bill.currency)}
            </p>
            {partlyPaid && (
              <p className="text-[12px] text-[#0369A1]">
                {money(bill.amount_paid, bill.currency)} of{" "}
                {money(bill.total, bill.currency)} already received
              </p>
            )}
          </div>
        </div>

        <BillLines bill={bill} tone="sky" />

        <div className="mt-[20px] flex flex-wrap items-center gap-3">
          <Link
            href={`/portal/quotations/${quotation.id}/pay`}
            className="inline-flex items-center gap-[8px] rounded-[9px] bg-gradient-to-br from-[#0891B2] to-[#0E7490] px-[20px] py-[11px] text-[14px] font-semibold text-white shadow-[0_2px_6px_rgba(8,145,178,0.25)] transition hover:from-[#0E7490] hover:to-[#155E75]"
          >
            Make the payment
            <span aria-hidden>→</span>
          </Link>
          <span className="text-[12.5px] text-[#0369A1]">
            Your order is despatched once payment is received.
          </span>
        </div>
      </div>
    </div>
  );
}

/** --------------------------------------------------------------- paid */
function PaidBill({ quotation }: { quotation: PortalQuotation }) {
  const bill = quotation.bill!;

  return (
    <>
      <div className="mb-6 rounded-[12px] border border-[#A7F3D0] bg-[#ECFDF5] p-[20px]">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone="green">Payment received</Badge>
          <p className="text-[13.5px] text-[#065F46]">
            {/* The backend only fills this in once the bill is settled, so the
                fallback is defensive rather than expected. */}
            {quotation.shipping_status ?? "Your order is being prepared for despatch."}
          </p>
        </div>
        <p className="mt-[8px] text-[12.5px] text-[#047857]">
          We received {money(bill.amount_paid, bill.currency)} against {bill.number}. Your invoice
          is below.
        </p>
      </div>

      <Card
        title={`Invoice ${bill.number}`}
        subtitle={`Issued ${date(bill.issue_date)} · ${quotation.company_name}`}
        actions={<Badge tone="green">Paid in full</Badge>}
        className="mb-6"
      >
        <Table columns={["Item", "Qty", "Unit price", "Total"]}>
          {bill.lines.map((line, index) => (
            <Row key={index}>
              <Cell className="font-medium text-[#0F172A]">{line.description}</Cell>
              <Cell>{Number(line.quantity)}</Cell>
              <Cell>{money(line.unit_price, bill.currency)}</Cell>
              <Cell>{money(line.line_total, bill.currency)}</Cell>
            </Row>
          ))}
        </Table>

        <dl className="mt-4 space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-[#64748B]">Subtotal</dt>
            <dd className="text-[#334155]">{money(bill.subtotal, bill.currency)}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-[#64748B]">Tax</dt>
            <dd className="text-[#334155]">{money(bill.tax_total, bill.currency)}</dd>
          </div>
          <div className="flex justify-between border-t border-edge pt-2 text-base font-semibold">
            <dt className="text-[#475569]">Total</dt>
            <dd className="text-[#0F172A]">{money(bill.total, bill.currency)}</dd>
          </div>
          <div className="flex justify-between text-[#059669]">
            <dt>Paid</dt>
            <dd>− {money(bill.amount_paid, bill.currency)}</dd>
          </div>
          <div className="flex justify-between border-t border-edge pt-2 font-semibold">
            <dt className="text-[#475569]">Balance</dt>
            <dd className="text-[#0F172A]">{money(bill.amount_due, bill.currency)}</dd>
          </div>
        </dl>

        <p className="mt-4 text-[12.5px] text-[#64748B]">
          Account manager: {bill.sales_rep} · Quotation {quotation.number}
        </p>
      </Card>
    </>
  );
}

/** Shared line summary. Compact on purpose — the full invoice comes later. */
function BillLines({
  bill,
  tone,
}: {
  bill: NonNullable<PortalQuotation["bill"]>;
  tone: "sky";
}) {
  const label = tone === "sky" ? "text-[#0369A1]" : "text-[#64748B]";
  return (
    <dl className={`mt-[18px] space-y-[8px] border-t border-[#BAE6FD] pt-[14px] text-[13px]`}>
      {bill.lines.map((line, index) => (
        <div key={index} className="flex justify-between gap-3">
          <dt className={label}>
            {line.description}
            <span className="ml-1 opacity-70">× {Number(line.quantity)}</span>
          </dt>
          <dd className="shrink-0 text-[#0C4A6E]">{money(line.line_total, bill.currency)}</dd>
        </div>
      ))}
      <div className={`flex justify-between ${label}`}>
        <dt>Tax</dt>
        <dd>{money(bill.tax_total, bill.currency)}</dd>
      </div>
      <div className="flex justify-between border-t border-[#BAE6FD] pt-[8px] text-[14px] font-semibold text-[#0C4A6E]">
        <dt>Total</dt>
        <dd>{money(bill.total, bill.currency)}</dd>
      </div>
    </dl>
  );
}
