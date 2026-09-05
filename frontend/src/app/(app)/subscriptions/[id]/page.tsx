"use client";

/**
 * Screen 10 — Billing detail.  Owner: anubhaw0raj.
 *
 * The two tables on this screen come from genuinely different sources: the
 * one-time lines from the originating quotation, the recurring schedule from
 * the subscription. That separation is what hybrid billing means.
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
  Field,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { date, money, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { BillingDetail } from "@/types";

export default function BillingDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [quantity, setQuantity] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload, setData } = useApi<BillingDetail>(
    `/subscriptions/${id}`,
  );

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const active = data.status === "ACTIVE";

  async function act(path: string, body?: unknown) {
    setBusy(true);
    setActionError(null);
    try {
      setData(await post<BillingDetail>(path, body));
      setQuantity("");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not apply that change");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`${data.customer_name} — ${data.plan_name}`}
        subtitle={
          data.quotation_number
            ? `Originating order ${data.quotation_number}`
            : "Standalone subscription"
        }
        actions={
          <Badge tone={active ? "green" : data.status === "PAUSED" ? "amber" : "red"}>
            {titleCase(data.status)}
          </Badge>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <Card
            title="One-Time Lines"
            subtitle={
              data.quotation_number
                ? `From the originating order ${data.quotation_number}`
                : "None"
            }
          >
            {data.one_time_lines.length === 0 ? (
              <EmptyState title="This order had no one-time products" />
            ) : (
              <Table columns={["Product", "Qty", "Amount"]}>
                {data.one_time_lines.map((line, index) => (
                  <Row key={index}>
                    <Cell className="font-medium text-[#0F172A]">{line.description}</Cell>
                    <Cell>{Number(line.quantity)}</Cell>
                    <Cell>{money(line.line_total)}</Cell>
                  </Row>
                ))}
              </Table>
            )}
          </Card>

          <Card
            title="Recurring Lines"
            subtitle={`Current period ${date(data.current_period_start)} → ${date(data.current_period_end)}`}
          >
            <Table columns={["Plan", "Cycle", "Next Bill Date", "Amount"]}>
              <Row>
                <Cell className="font-medium text-[#0F172A]">{data.plan_name}</Cell>
                <Cell>{titleCase(data.interval)}</Cell>
                <Cell>{date(data.next_bill_date)}</Cell>
                <Cell>{money(data.period_amount)}</Cell>
              </Row>
            </Table>

            {data.upcoming_bills.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                  Upcoming schedule
                </p>
                <Table columns={["Period", "Amount"]}>
                  {data.upcoming_bills.map((bill, index) => (
                    <Row key={index}>
                      <Cell>
                        {date(bill.period_start)} → {date(bill.period_end)}
                      </Cell>
                      <Cell>{money(bill.amount)}</Cell>
                    </Row>
                  ))}
                </Table>
              </div>
            )}
          </Card>

          <Card title="Proration history" subtitle="Signed: positive was invoiced, negative credited">
            {data.events.length === 0 ? (
              <EmptyState title="No changes yet" />
            ) : (
              <Table columns={["Event", "Effective", "Change", "Proration", "Document"]}>
                {data.events.map((event) => (
                  <Row key={event.id}>
                    <Cell className="font-medium text-[#0F172A]">
                      {titleCase(event.event_type)}
                    </Cell>
                    <Cell className="text-[#64748B]">{date(event.effective_date)}</Cell>
                    <Cell>
                      {event.old_quantity != null && event.new_quantity != null
                        ? `${Number(event.old_quantity)} → ${Number(event.new_quantity)}`
                        : "—"}
                    </Cell>
                    <Cell
                      className={
                        Number(event.proration_amount) < 0
                          ? "text-emerald-600"
                          : Number(event.proration_amount) > 0
                            ? "text-amber-700"
                            : "text-slate-500"
                      }
                    >
                      {money(event.proration_amount)}
                    </Cell>
                    <Cell className="text-[#64748B]">
                      {event.invoice_id
                        ? `Invoice #${event.invoice_id}`
                        : event.credit_note_id
                          ? `Credit note #${event.credit_note_id}`
                          : "—"}
                    </Cell>
                  </Row>
                ))}
              </Table>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Modify Subscription">
            <Field
              label="New quantity"
              hint="Mid-cycle changes are prorated by day. An increase invoices; a decrease credits."
            >
              <input
                type="number"
                min="1"
                className={inputClass}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder={String(Number(data.quantity))}
                disabled={!active}
              />
            </Field>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                disabled={!active || busy || !quantity}
                onClick={() => act(`/subscriptions/${id}/quantity`, { quantity })}
              >
                Apply change
              </Button>
              <Button
                variant="danger"
                disabled={!active || busy}
                onClick={() => act(`/subscriptions/${id}/cancel`, {})}
              >
                Cancel Subscription
              </Button>
            </div>
            <div className="mt-4">
              <Note>
                Cancellation follows the plan&apos;s own policy: immediate with a prorated credit
                note, or at end of period with no refund.
              </Note>
            </div>
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
