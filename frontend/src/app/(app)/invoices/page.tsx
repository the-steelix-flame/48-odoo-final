"use client";

/** Screen 12 — Invoices list.  Owner: anubhaw0raj. */

import { useState } from "react";
import { useRouter } from "next/navigation";

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
} from "@/components/ui";
import { date, dateTime, money, titleCase } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { DealBillingRow, InvoiceRow } from "@/types";

/** Mirrors the server: only these two may accept a deal and raise its bill. */
const MAY_BILL = ["FINANCE", "SALES_MANAGER", "ADMIN"];

const STATUS_TONE: Record<string, string> = {
  DRAFT: "slate",
  OPEN: "red",
  PARTIALLY_PAID: "amber",
  PAID: "green",
  VOID: "slate",
};

export default function InvoicesPage() {
  const router = useRouter();
  const { role } = useAuth();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<InvoiceRow[]>("/billing/invoices");
  const { data: counts } = useApi<{ unpaid: number; paid: number }>("/billing/invoices/counts");
  const { data: deals, reload: reloadDeals } = useApi<DealBillingRow[]>("/billing/deals");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const rows = data ?? [];
  const dealRows = deals ?? [];
  const mayBill = role !== null && MAY_BILL.includes(role);

  async function raiseBill(deal: DealBillingRow) {
    setBusyId(deal.quotation_id);
    setActionError(null);
    setNotice(null);
    try {
      await post(`/billing/quotations/${deal.quotation_id}/bill`);
      setNotice(
        `Bill raised for ${deal.quotation_number}. ${deal.customer_name} can now pay it from their portal.`,
      );
      await Promise.all([reloadDeals(), reload()]);
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not raise the bill");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Invoices"
        subtitle="Every invoice generated from one-time and recurring orders."
      />

      <div className="mb-5 flex flex-wrap gap-2">
        <Badge tone="red">{counts?.unpaid ?? 0} Unpaid</Badge>
        <Badge tone="green">{counts?.paid ?? 0} Paid</Badge>
      </div>

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}
      {notice && (
        <div className="mb-4">
          <Note>{notice}</Note>
        </div>
      )}

      {/* Confirming is the customer agreeing to the terms; raising the bill is
          us agreeing to them. A deal sits here until Finance or a Sales Manager
          accepts it, which is why nothing is billed at confirmation time. */}
      <Card
        title="Confirmed deals"
        subtitle="Accept the final deal to raise its bill, then follow it through to payment."
        className="mb-6"
      >
        {dealRows.length === 0 ? (
          <EmptyState
            title="No confirmed deals"
            hint="A deal appears here once the customer has confirmed it in their portal."
          />
        ) : (
          <Table
            columns={["Deal", "Customer", "Sales rep", "Closing amount", "Confirmed", "Billing"]}
          >
            {dealRows.map((deal) => (
              <Row key={deal.quotation_id}>
                <Cell className="font-medium text-[#0F172A]">{deal.quotation_number}</Cell>
                <Cell>{deal.customer_name}</Cell>
                <Cell className="text-[#475569]">{deal.sales_rep}</Cell>
                <Cell className="font-medium text-[#0F172A]">
                  {money(deal.closing_amount, deal.currency)}
                </Cell>
                <Cell className="text-[#64748B]">{dateTime(deal.confirmed_at)}</Cell>
                <Cell>
                  {deal.billing_state === "AWAITING_BILL" ? (
                    mayBill ? (
                      <Button
                        disabled={busyId === deal.quotation_id}
                        onClick={() => void raiseBill(deal)}
                      >
                        {busyId === deal.quotation_id
                          ? "Raising…"
                          : "Accept deal & generate bill"}
                      </Button>
                    ) : (
                      // The server refuses this for other roles, so say so
                      // rather than offering a button that 403s.
                      <span className="text-[12px] text-[#94A3B8]">
                        Awaiting Finance sign-off
                      </span>
                    )
                  ) : deal.billing_state === "PAYMENT_PENDING" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="amber">Payment Pending</Badge>
                      <span className="text-[12px] text-[#64748B]">
                        {deal.invoice_number} · {money(deal.amount_due, deal.currency)} due
                      </span>
                    </div>
                  ) : (
                    <Button
                      variant="secondary"
                      onClick={() => router.push(`/invoices/${deal.invoice_id}`)}
                    >
                      View Invoice
                    </Button>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Card>

      <Card>
        {rows.length === 0 ? (
          <EmptyState
            title="No invoices yet"
            hint="Confirm an order and its one-time invoice plus any recurring schedule appear here."
          />
        ) : (
          <Table
            columns={["Invoice #", "Customer", "Type", "Amount", "Paid", "Due", "Due Date", "Status"]}
          >
            {rows.map((invoice) => (
              <Row key={invoice.id} onClick={() => router.push(`/invoices/${invoice.id}`)}>
                <Cell className="font-heading font-medium text-[#0F172A]">{invoice.number}</Cell>
                <Cell>{invoice.customer_name}</Cell>
                <Cell>
                  <Badge tone={invoice.invoice_type === "RECURRING" ? "blue" : "slate"}>
                    {titleCase(invoice.invoice_type)}
                  </Badge>
                </Cell>
                <Cell>{money(invoice.total, invoice.currency)}</Cell>
                <Cell className="text-[#64748B]">
                  {money(invoice.amount_paid, invoice.currency)}
                </Cell>
                <Cell>{money(invoice.amount_due, invoice.currency)}</Cell>
                <Cell className="text-[#64748B]">{date(invoice.due_date)}</Cell>
                <Cell>
                  <Badge tone={STATUS_TONE[invoice.status]}>{titleCase(invoice.status)}</Badge>
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        <div className="mt-4">
          <Note>
            Click an invoice row to open its full payment and delivery reconciliation detail. A
            single order produces separate one-time and recurring invoices — that&apos;s structural,
            not a filter.
          </Note>
        </div>
      </Card>
    </>
  );
}
