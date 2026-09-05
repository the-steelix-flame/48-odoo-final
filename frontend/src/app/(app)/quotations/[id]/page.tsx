"use client";

/**
 * Screen 4 — Quotation builder.  Owner: the-steelix-flame.
 *
 * The key behaviour: every mutation returns the FULL recomputed quotation, and
 * this component just renders it. The `OVER (+8pt)` badge, the margin bar and
 * the risk score all come from the backend, so they can never disagree with
 * what the approval screen will later say. Nothing here computes money.
 */

import { use, useState } from "react";
import type { KeyboardEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, del, patch, post } from "@/lib/api";
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
import { RISK_TONE, STATUS_TONE, dateTime, money, percent, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Product, QuotationDetail, UpsellSuggestion } from "@/types";

/**
 * Enter commits the value by blurring the field, which fires the same onBlur
 * handler a click-away would. One code path, so typing 17 and pressing Enter
 * cannot produce a different result from typing 17 and clicking elsewhere.
 */
function commitOnEnter(event: KeyboardEvent<HTMLInputElement>) {
  if (event.key === "Enter") {
    event.preventDefault();
    event.currentTarget.blur();
  }
}

export default function QuotationBuilderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [addProductId, setAddProductId] = useState("");

  const { data, error, loading, reload, setData } = useApi<QuotationDetail>(`/quotations/${id}`);
  const { data: products } = useApi<Product[]>("/catalog/products");
  const { data: upsells, reload: reloadUpsells } = useApi<UpsellSuggestion[]>(
    `/quotations/${id}/upsell`,
  );

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const editable = ["DRAFT", "UNDER_NEGOTIATION", "REJECTED"].includes(data.status);

  /** Every mutation replaces local state with the backend's recomputed truth. */
  async function run(fn: () => Promise<QuotationDetail>) {
    setBusy(true);
    setActionError(null);
    try {
      setData(await fn());
      await reloadUpsells();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const addLine = (productId: number, fromUpsell = false) =>
    run(() =>
      post<QuotationDetail>(`/quotations/${id}/lines`, {
        product_id: productId,
        quantity: "1",
        discount_percent: "0",
        from_upsell: fromUpsell,
      }),
    );

  const updateLine = (lineId: number, body: Record<string, string>) =>
    run(() => patch<QuotationDetail>(`/quotations/${id}/lines/${lineId}`, body));

  const removeLine = (lineId: number) =>
    run(() => del<QuotationDetail>(`/quotations/${id}/lines/${lineId}`));

  /**
   * Quantity and discount inputs commit on blur or Enter, so a value the user
   * is still sitting in has not been sent yet. Blurring first makes that PATCH
   * fire before we act, otherwise clicking straight from a half-typed discount
   * to Submit would route the quote on the previous number.
   */
  function flushPendingEdit() {
    const active = document.activeElement as HTMLElement | null;
    if (active && typeof active.blur === "function") active.blur();
  }

  async function saveDraft() {
    flushPendingEdit();
    setBusy(true);
    setActionError(null);
    try {
      setData(await post<QuotationDetail>(`/quotations/${id}/save-draft`));
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not save the draft");
    } finally {
      setBusy(false);
    }
  }

  async function submitForApproval() {
    flushPendingEdit();
    setBusy(true);
    setActionError(null);
    try {
      const updated = await post<QuotationDetail>(`/quotations/${id}/submit`);
      setData(updated);
      if (!updated.requires_approval) {
        setActionError(null);
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Could not submit");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={`Quotation ${data.number}`}
        subtitle={`${data.customer_name} · ${data.customer_tier} tier · owned by ${data.owner_rep_name}`}
        actions={
          <>
            <Badge tone={STATUS_TONE[data.status]}>{titleCase(data.status)}</Badge>
            <Badge tone={RISK_TONE[data.risk_band]}>
              Risk {data.blended_risk_score} · {data.risk_band}
            </Badge>
          </>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[2fr_1fr]">
        {/* -------------------------------------------------- cart */}
        <div className="space-y-6">
          <Card
            title="Order lines"
            subtitle="Discount is checked against each line's own limit, live."
            actions={
              editable ? (
                <div className="flex gap-2">
                  <select
                    className={`${inputClass} w-56`}
                    value={addProductId}
                    onChange={(e) => setAddProductId(e.target.value)}
                  >
                    <option value="">Add a product…</option>
                    {(products ?? []).map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name} ({product.category_name})
                      </option>
                    ))}
                  </select>
                  <Button
                    disabled={!addProductId || busy}
                    onClick={() => {
                      void addLine(Number(addProductId));
                      setAddProductId("");
                    }}
                  >
                    Add
                  </Button>
                </div>
              ) : null
            }
          >
            {data.lines.length === 0 ? (
              <EmptyState title="No lines yet" hint="Add a product to start building this quote." />
            ) : (
              <Table
                columns={["Product", "Type", "Qty", "Price", "Discount", "Limit", "Status", "Total", ""]}
              >
                {data.lines.map((line) => (
                  <Row key={line.id}>
                    <Cell className="font-medium text-slate-100">
                      {line.description}
                      <span className="ml-2 text-xs text-slate-500">{line.category_name}</span>
                    </Cell>
                    <Cell>
                      <Badge tone={line.line_type === "RECURRING" ? "blue" : "slate"}>
                        {line.line_type === "RECURRING" ? "Recurring" : "One-time"}
                      </Badge>
                    </Cell>
                    <Cell>
                      <input
                        type="number"
                        min="1"
                        disabled={!editable || busy}
                        className={`${inputClass} w-20`}
                        defaultValue={Number(line.quantity)}
                        onKeyDown={commitOnEnter}
                        onBlur={(e) =>
                          Number(e.target.value) !== Number(line.quantity) &&
                          updateLine(line.id, { quantity: e.target.value })
                        }
                      />
                    </Cell>
                    <Cell>{money(line.unit_price, data.currency)}</Cell>
                    <Cell>
                      <input
                        type="number"
                        min="0"
                        max="100"
                        disabled={!editable || busy}
                        className={`${inputClass} w-20`}
                        defaultValue={Number(line.discount_percent)}
                        onKeyDown={commitOnEnter}
                        onBlur={(e) =>
                          Number(e.target.value) !== Number(line.discount_percent) &&
                          updateLine(line.id, { discount_percent: e.target.value })
                        }
                      />
                    </Cell>
                    <Cell className="text-slate-400">
                      {percent(line.allowed_discount_percent, 0)}
                    </Cell>
                    <Cell>
                      {line.is_over_limit ? (
                        <Badge tone="red">
                          OVER (+{Number(line.discount_excess_points).toFixed(0)}pt)
                        </Badge>
                      ) : (
                        <Badge tone="green">OK</Badge>
                      )}
                    </Cell>
                    <Cell className="font-medium text-slate-100">
                      {money(line.line_total, data.currency)}
                    </Cell>
                    <Cell>
                      {editable && (
                        <button
                          onClick={() => removeLine(line.id)}
                          disabled={busy}
                          className="text-xs text-rose-400 hover:text-rose-300"
                        >
                          Remove
                        </button>
                      )}
                    </Cell>
                  </Row>
                ))}
              </Table>
            )}

            <div className="mt-4">
              <Note>
                Each line is judged against the stricter of the customer tier ceiling and its own
                category ceiling — which is why an 18% Services line is flagged on a Gold customer
                even though 15% &ldquo;sounds fine&rdquo;.
              </Note>
            </div>
          </Card>

          {/* ------------------------------------------- audit trail */}
          <Card title="Audit trail" subtitle="Every edit, approval and negotiation, logged">
            {data.events.length === 0 ? (
              <EmptyState title="Nothing logged yet" />
            ) : (
              <Table columns={["User", "Action", "When", "Note"]}>
                {[...data.events].reverse().map((event) => (
                  <Row key={event.id}>
                    <Cell>{event.actor_name}</Cell>
                    <Cell>{titleCase(event.event_type)}</Cell>
                    <Cell className="text-slate-400">{dateTime(event.created_at)}</Cell>
                    <Cell className="text-slate-400">{event.note || "—"}</Cell>
                  </Row>
                ))}
              </Table>
            )}
          </Card>
        </div>

        {/* -------------------------------------------------- sidebar */}
        <div className="space-y-6">
          <Card title="Totals">
            <dl className="space-y-2 text-sm">
              {[
                ["Subtotal", money(data.subtotal, data.currency)],
                ["Discount", `− ${money(data.discount_total, data.currency)}`],
                ["Tax", money(data.tax_total, data.currency)],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between">
                  <dt className="text-slate-400">{label}</dt>
                  <dd className="text-slate-200">{value}</dd>
                </div>
              ))}
              <div className="flex justify-between border-t border-edge pt-2 text-base font-semibold">
                <dt className="text-slate-300">Total</dt>
                <dd className="text-slate-100">{money(data.total, data.currency)}</dd>
              </div>
            </dl>

            <div className="mt-4">
              <p className="mb-1.5 flex justify-between text-xs">
                <span className="text-slate-400">Live margin</span>
                <span className="text-slate-200">
                  {percent(data.margin_percent)} · {money(data.margin_amount, data.currency)}
                </span>
              </p>
              <div className="h-2 overflow-hidden rounded-full bg-black/40">
                <div
                  className={`h-full transition-all ${
                    Number(data.margin_percent) < 15
                      ? "bg-rose-500"
                      : Number(data.margin_percent) < 30
                        ? "bg-amber-500"
                        : "bg-emerald-500"
                  }`}
                  style={{
                    width: `${Math.max(0, Math.min(100, Number(data.margin_percent)))}%`,
                  }}
                />
              </div>
            </div>

            {editable && (
              <div className="mt-4">
                <Field label="Order-level discount %" hint="Applied on top of line discounts.">
                  <input
                    type="number"
                    className={inputClass}
                    defaultValue={Number(data.order_discount_percent)}
                    onKeyDown={commitOnEnter}
                    onBlur={(e) =>
                      Number(e.target.value) !== Number(data.order_discount_percent) &&
                      run(() =>
                        patch<QuotationDetail>(`/quotations/${id}/order-discount`, {
                          order_discount_percent: e.target.value,
                        }),
                      )
                    }
                  />
                </Field>
              </div>
            )}
          </Card>

          {/* ------------------------------------------- risk */}
          <Card title="Approval routing" subtitle="Computed, not requested">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm text-slate-400">Blended risk score</span>
              <Badge tone={RISK_TONE[data.risk_band]}>{data.risk.score}</Badge>
            </div>
            <p className="text-sm text-slate-300">{data.risk.explanation}</p>
            <dl className="mt-3 space-y-1 text-xs text-slate-500">
              <div className="flex justify-between">
                <dt>Worst line excess</dt>
                <dd>{data.risk.worst_line_excess} pt</dd>
              </div>
              <div className="flex justify-between">
                <dt>Blended excess</dt>
                <dd>{data.risk.blended_excess} pt</dd>
              </div>
              <div className="flex justify-between">
                <dt>Order-level excess</dt>
                <dd>{data.risk.order_level_excess} pt</dd>
              </div>
            </dl>

            {editable && (
              <div className="mt-4">
                <div className="flex flex-wrap gap-2">
                  <Button onClick={submitForApproval} disabled={busy || data.lines.length === 0}>
                    {data.requires_approval ? "Submit for Approval" : "Submit (auto-approves)"}
                  </Button>
                  <Button variant="secondary" onClick={saveDraft} disabled={busy}>
                    Save as Draft
                  </Button>
                </div>
                {savedAt && (
                  <p className="mt-2 text-xs text-emerald-400">
                    Draft saved at {savedAt} — logged on the audit trail below.
                  </p>
                )}
              </div>
            )}

            {data.status === "PENDING_APPROVAL" && (
              <div className="mt-4">
                <Link href="/approvals" className="text-sm text-brand hover:underline">
                  Track approval →
                </Link>
              </div>
            )}

            {data.status === "APPROVED" && (
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await post(`/portal/internal/quotations/${id}/send`);
                      await reload();
                    } catch (err) {
                      setActionError(err instanceof ApiError ? err.message : "Failed");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Send to Customer
                </Button>
              </div>
            )}

            {data.status === "SENT" && (
              <div className="mt-4">
                <Note>
                  Sent to the customer. Only the customer can confirm it, from their own portal —
                  confirming here would skip their sign-off and start fulfilment on terms they had
                  not yet accepted.
                </Note>
              </div>
            )}
          </Card>

          {/* ------------------------------------------- upsell (B5) */}
          <Card
            title="Upsell & Cross-Sell"
            subtitle="Ranked by co-purchase, floored by margin"
          >
            {!upsells || upsells.length === 0 ? (
              <EmptyState
                title="No suggestions"
                hint="Add a product to the cart to see what pairs with it."
              />
            ) : (
              <ul className="space-y-2">
                {upsells.map((suggestion) => (
                  <li
                    key={suggestion.product_id}
                    className="rounded-lg border border-edge bg-black/20 p-3"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-slate-100">
                          {suggestion.product_name}
                        </p>
                        <p className="mt-0.5 text-xs text-emerald-400">
                          Margin +{money(suggestion.margin_delta)}
                        </p>
                      </div>
                      {suggestion.is_promoted && <Badge tone="blue">Promo</Badge>}
                    </div>
                    {editable && (
                      <div className="mt-2 flex gap-2">
                        <Button
                          disabled={busy}
                          onClick={() => addLine(suggestion.product_id, true)}
                          className="!px-3 !py-1 text-xs"
                        >
                          Add to Quote
                        </Button>
                        <Button
                          variant="secondary"
                          disabled={busy}
                          className="!px-3 !py-1 text-xs"
                          onClick={async () => {
                            await post(
                              `/quotations/${id}/upsell/${suggestion.product_id}/dismiss`,
                            );
                            await reloadUpsells();
                          }}
                        >
                          Dismiss
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3">
              <Note>
                Adding a suggestion goes through the same service as any other line, so the margin
                indicator above updates immediately and can&apos;t drift.
              </Note>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
