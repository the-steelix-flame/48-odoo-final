"use client";

/** Screen 13 — Invoice detail & payment.  Owner: anubhaw0raj. */

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
import { date, dateTime, money, percent, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { InvoiceDetail } from "@/types";

export default function InvoiceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("BANK_TRANSFER");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload, setData } = useApi<InvoiceDetail>(
    `/billing/invoices/${id}`,
  );

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const outstanding = Number(data.amount_due) > 0;

  async function recordPayment() {
    setBusy(true);
    setActionError(null);
    try {
      setData(
        await post<InvoiceDetail>(`/billing/invoices/${id}/payments`, {
          amount: amount || data!.amount_due,
          method,
          reference,
        }),
      );
      setAmount("");
      setReference("");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not record that payment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`Invoice ${data.number}`}
        subtitle={`${data.customer_name} · ${titleCase(data.invoice_type)}`}
        actions={
          <Badge
            tone={
              data.status === "PAID" ? "green" : data.status === "PARTIALLY_PAID" ? "amber" : "red"
            }
          >
            {titleCase(data.status)}
          </Badge>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      {/* Order Confirmed -> Shipped -> Invoiced -> Paid */}
      <Card className="mb-6">
        <ol className="flex flex-wrap items-center gap-3">
          {data.lifecycle.map((stage, index) => (
            <li key={stage.label} className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <span
                  className={`h-4 w-4 rounded-full ${
                    stage.done ? "bg-emerald-500" : "bg-slate-600"
                  }`}
                />
                <span
                  className={`text-sm ${stage.done ? "text-[#0F172A]" : "text-slate-500"}`}
                >
                  {stage.label}
                </span>
              </div>
              {index < data.lifecycle.length - 1 && (
                <span className="text-slate-600">&rarr;</span>
              )}
            </li>
          ))}
        </ol>
        <div className="mt-4">
          <Note>
            Partial invoicing stays reconciled with partial delivery — nothing is billed before it
            ships.
          </Note>
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <Card
            title="Invoice lines"
            subtitle={
              data.period_start
                ? `Billing period ${date(data.period_start)} → ${date(data.period_end)}`
                : undefined
            }
          >
            <Table columns={["Description", "Qty", "Unit Price", "Discount", "Tax", "Total"]}>
              {data.lines.map((line) => (
                <Row key={line.id}>
                  <Cell className="font-medium text-[#0F172A]">{line.description}</Cell>
                  <Cell>{Number(line.quantity)}</Cell>
                  <Cell>{money(line.unit_price, data.currency)}</Cell>
                  <Cell>{percent(line.discount_percent, 0)}</Cell>
                  <Cell>{percent(line.tax_percent, 0)}</Cell>
                  <Cell>{money(line.line_total, data.currency)}</Cell>
                </Row>
              ))}
            </Table>

            <dl className="mt-4 space-y-2 text-sm">
              {[
                ["Subtotal", money(data.subtotal, data.currency)],
                ["Tax", money(data.tax_total, data.currency)],
                ["Paid", `− ${money(data.amount_paid, data.currency)}`],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-[#64748B]">{label}</dt>
                  <dd className="text-[#334155]">{value}</dd>
                </div>
              ))}
              <div className="flex justify-between border-t border-edge pt-2 text-base font-semibold">
                <dt className="text-[#475569]">Amount due</dt>
                <dd className="text-[#0F172A]">{money(data.amount_due, data.currency)}</dd>
              </div>
            </dl>
          </Card>

          <Card title="Payments">
            {data.payments.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">Nothing recorded yet.</p>
            ) : (
              <Table columns={["Amount", "Method", "Reference", "When", "Recorded by"]}>
                {data.payments.map((payment) => (
                  <Row key={payment.id}>
                    <Cell className="font-medium text-[#0F172A]">
                      {money(payment.amount, data.currency)}
                    </Cell>
                    <Cell>{titleCase(payment.method)}</Cell>
                    <Cell className="text-[#64748B]">{payment.reference || "—"}</Cell>
                    <Cell className="text-[#64748B]">{dateTime(payment.paid_at)}</Cell>
                    <Cell className="text-[#64748B]">{payment.recorded_by_name ?? "—"}</Cell>
                  </Row>
                ))}
              </Table>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Record Payment">
            {!outstanding ? (
              <p className="text-sm text-emerald-700">
                This invoice is fully paid. Nothing outstanding.
              </p>
            ) : (
              <>
                <div className="space-y-4">
                  <Field
                    label="Amount"
                    hint={`Leave blank to settle the full ${money(data.amount_due, data.currency)}.`}
                  >
                    <input
                      type="number"
                      className={inputClass}
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      placeholder={String(data.amount_due)}
                    />
                  </Field>
                  <Field label="Method">
                    <select
                      className={inputClass}
                      value={method}
                      onChange={(e) => setMethod(e.target.value)}
                    >
                      <option value="BANK_TRANSFER">Bank transfer</option>
                      <option value="CARD">Card</option>
                      <option value="CHEQUE">Cheque</option>
                      <option value="OTHER">Other</option>
                    </select>
                  </Field>
                  <Field label="Reference">
                    <input
                      className={inputClass}
                      value={reference}
                      onChange={(e) => setReference(e.target.value)}
                      placeholder="Optional"
                    />
                  </Field>
                </div>
                <div className="mt-4">
                  <Button variant="success" onClick={recordPayment} disabled={busy}>
                    Record Payment
                  </Button>
                </div>
                <div className="mt-3">
                  <Note>
                    Part-paying moves the invoice to <em>Partially paid</em> rather than Paid —
                    multiple payments per invoice are supported.
                  </Note>
                </div>
              </>
            )}
          </Card>

          {data.quotation_id && (
            <Card title="Provenance">
              <Link
                href={`/quotations/${data.quotation_id}`}
                className="text-sm text-brand hover:underline"
              >
                Open originating quotation {data.quotation_number} →
              </Link>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
