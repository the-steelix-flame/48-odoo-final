"use client";

/** Screen 3 — Quotations list / Kanban pipeline.  Owner: the-steelix-flame. */

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
  Field,
  Loading,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { RISK_TONE, STATUS_TONE, money, percent, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import { PIPELINE_STAGES } from "@/types";
import type { Customer, QuotationDetail, QuotationSummary } from "@/types";

export default function QuotationsPage() {
  const router = useRouter();
  const [view, setView] = useState<"kanban" | "table">("kanban");
  const [creating, setCreating] = useState(false);
  const [customerId, setCustomerId] = useState<string>("");
  const [createError, setCreateError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<QuotationSummary[]>("/quotations/");
  const { data: customers } = useApi<Customer[]>("/auth/customers");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const quotations = data ?? [];

  async function createQuotation() {
    if (!customerId) return;
    setCreateError(null);
    try {
      const created = await post<QuotationDetail>("/quotations/", {
        customer_id: Number(customerId),
      });
      router.push(`/quotations/${created.id}`);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not create the quotation");
    }
  }

  return (
    <>
      <PageHeader
        title="Quotations"
        subtitle="Every quotation in the system — click one to open its builder."
        actions={
          <>
            <Button onClick={() => setCreating((open) => !open)}>+ New Quotation</Button>
            <Button
              variant="secondary"
              onClick={() => setView(view === "kanban" ? "table" : "kanban")}
            >
              {view === "kanban" ? "Switch to Table View" : "Switch to Pipeline View"}
            </Button>
          </>
        }
      />

      {creating && (
        <div className="mb-6">
          <Card title="New quotation">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[260px] flex-1">
                <Field label="Customer" hint="Tier decides the discount ceiling on every line.">
                  <select
                    className={inputClass}
                    value={customerId}
                    onChange={(e) => setCustomerId(e.target.value)}
                  >
                    <option value="">Select a customer…</option>
                    {(customers ?? []).map((customer) => (
                      <option key={customer.id} value={customer.id}>
                        {customer.name} — {customer.tier}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <Button onClick={createQuotation} disabled={!customerId}>
                Create
              </Button>
            </div>
            {createError && <p className="mt-3 text-sm text-rose-300">{createError}</p>}
          </Card>
        </div>
      )}

      {quotations.length === 0 ? (
        <EmptyState
          title="No quotations yet"
          hint="Create one above, or run `python manage.py seed_demo` for the demo pipeline."
        />
      ) : view === "kanban" ? (
        <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-5">
          {PIPELINE_STAGES.map((stage) => {
            const cards = quotations.filter((q) => q.status === stage.status);
            return (
              <div
                key={stage.status}
                className="rounded-xl border border-edge bg-surface/60 p-3"
              >
                <div className="mb-3 flex items-center justify-between">
                  <h2 className="text-sm font-medium text-slate-200">{stage.label}</h2>
                  <span className="text-xs text-slate-500">{cards.length}</span>
                </div>
                <div className="space-y-2">
                  {cards.map((quotation) => (
                    <button
                      key={quotation.id}
                      onClick={() => router.push(`/quotations/${quotation.id}`)}
                      className="w-full rounded-lg border border-edge bg-black/30 p-3 text-left transition hover:border-slate-500"
                    >
                      <p className="text-sm font-medium text-slate-100">
                        {quotation.customer_name}
                      </p>
                      <p className="mt-0.5 text-xs text-slate-400">
                        {quotation.number} · {money(quotation.total, quotation.currency)}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Badge tone={RISK_TONE[quotation.risk_band]}>
                          {quotation.risk_band === "NONE" ? "No approval" : quotation.risk_band}
                        </Badge>
                        {quotation.idle_days >= 7 && (
                          <Badge tone="amber">Idle {quotation.idle_days}d</Badge>
                        )}
                      </div>
                    </button>
                  ))}
                  {cards.length === 0 && (
                    <p className="py-6 text-center text-xs text-slate-600">Empty</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <Card>
          <Table
            columns={["Quotation", "Customer", "Tier", "Owner", "Status", "Risk", "Margin", "Total"]}
          >
            {quotations.map((quotation) => (
              <Row key={quotation.id} onClick={() => router.push(`/quotations/${quotation.id}`)}>
                <Cell className="font-medium text-slate-100">{quotation.number}</Cell>
                <Cell>{quotation.customer_name}</Cell>
                <Cell>{quotation.customer_tier}</Cell>
                <Cell>{quotation.owner_rep_name}</Cell>
                <Cell>
                  <Badge tone={STATUS_TONE[quotation.status]}>
                    {titleCase(quotation.status)}
                  </Badge>
                </Cell>
                <Cell>
                  <Badge tone={RISK_TONE[quotation.risk_band]}>
                    {quotation.blended_risk_score}
                  </Badge>
                </Cell>
                <Cell>{percent(quotation.margin_percent)}</Cell>
                <Cell className="font-medium text-slate-100">
                  {money(quotation.total, quotation.currency)}
                </Cell>
              </Row>
            ))}
          </Table>
        </Card>
      )}
    </>
  );
}
