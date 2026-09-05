"use client";

/** Screen 12 — Invoices list.  Owner: anubhaw0raj. */

import { useRouter } from "next/navigation";

import {
  Badge,
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
import { date, money, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { InvoiceRow } from "@/types";

const STATUS_TONE: Record<string, string> = {
  DRAFT: "slate",
  OPEN: "red",
  PARTIALLY_PAID: "amber",
  PAID: "green",
  VOID: "slate",
};

export default function InvoicesPage() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi<InvoiceRow[]>("/billing/invoices");
  const { data: counts } = useApi<{ unpaid: number; paid: number }>("/billing/invoices/counts");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const rows = data ?? [];

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
                <Cell className="font-medium text-slate-100">{invoice.number}</Cell>
                <Cell>{invoice.customer_name}</Cell>
                <Cell>
                  <Badge tone={invoice.invoice_type === "RECURRING" ? "blue" : "slate"}>
                    {titleCase(invoice.invoice_type)}
                  </Badge>
                </Cell>
                <Cell>{money(invoice.total, invoice.currency)}</Cell>
                <Cell className="text-slate-400">
                  {money(invoice.amount_paid, invoice.currency)}
                </Cell>
                <Cell>{money(invoice.amount_due, invoice.currency)}</Cell>
                <Cell className="text-slate-400">{date(invoice.due_date)}</Cell>
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
