"use client";

/**
 * The rep's negotiation panel.  Owner: the-steelix-flame.
 *
 * Shown on the quotation once a conversation exists. Lets the rep read the
 * whole exchange and answer it three ways: accept the customer's number,
 * counter with our own, or decline — plus plain replies for questions that
 * aren't about price.
 */

import { useState } from "react";

import { ApiError, post } from "@/lib/api";
import { NegotiationThread } from "@/components/negotiation/Thread";
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  Loading,
  Note,
  inputClass,
} from "@/components/ui";
import { percent } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { NegotiationView } from "@/types";

export function RepNegotiationPanel({
  quotationId,
  onQuotationChanged,
}: {
  quotationId: number | string;
  /** Accepting a counter rewrites the lines, so the parent must refetch. */
  onQuotationChanged: () => void;
}) {
  const [counter, setCounter] = useState("");
  const [counterNote, setCounterNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload, setData } = useApi<NegotiationView>(
    `/portal/internal/quotations/${quotationId}/negotiation`,
  );

  if (loading) return <Loading label="Loading the conversation…" />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  // Nothing has been sent to the customer yet — no panel to show.
  if (!data.has_thread && data.requests.length === 0) return null;

  const open = data.open_request;
  const rejectedByCustomer = data.status === "REJECTED";
  // Nothing to answer once the customer has walked away.
  const awaitingUs = open?.status === "SUBMITTED" && !rejectedByCustomer;
  const awaitingThem = open?.status === "COUNTERED" && !rejectedByCustomer;
  const lastRejection = [...data.timeline]
    .reverse()
    .find((entry) => entry.kind === "REJECTED" && entry.author_type === "CUSTOMER");

  async function run(fn: () => Promise<unknown>, refetchQuotation = false) {
    setBusy(true);
    setActionError(null);
    try {
      const result = await fn();
      setData(result as NegotiationView);
      if (refetchQuotation) onQuotationChanged();
      setCounter("");
      setCounterNote("");
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      title="Negotiation"
      subtitle={`With ${data.customer_name}`}
      actions={
        rejectedByCustomer ? (
          <Badge tone="red">Rejected by customer</Badge>
        ) : awaitingUs ? (
          <Badge tone="amber">Awaiting your reply</Badge>
        ) : awaitingThem ? (
          <Badge tone="blue">Awaiting customer</Badge>
        ) : (
          <Badge tone="slate">No open request</Badge>
        )
      }
    >
      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      <NegotiationThread
        entries={data.timeline}
        viewpoint="REP"
        emptyHint="Messages from the customer portal appear here."
      />

      {/* ------------------------------------------- their open request */}
      {awaitingUs && (
        <div className="mt-5 rounded-lg border border-[#FDE68A] bg-[#FFFBEB] p-4">
          <p className="text-sm text-[#92400E]">
            {open?.requested_discount_percent
              ? `${data.customer_name} is asking for ${percent(open.requested_discount_percent, 0)} across the order.`
              : `${data.customer_name} has sent a request.`}
          </p>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <Field
                label="Counter with a different discount %"
                hint="Nothing changes on the quotation until they accept it."
              >
                <input
                  type="number"
                  min="0"
                  max="100"
                  className={inputClass}
                  value={counter}
                  onChange={(e) => setCounter(e.target.value)}
                  placeholder="e.g. 12"
                />
              </Field>
              <div className="mt-2">
                <input
                  className={inputClass}
                  value={counterNote}
                  onChange={(e) => setCounterNote(e.target.value)}
                  placeholder="Add a note with your counter (optional)"
                />
              </div>
              <div className="mt-3">
                <Button
                  variant="warning"
                  disabled={busy || !counter}
                  onClick={() =>
                    run(() =>
                      post(`/portal/internal/requests/${open!.id}/counter`, {
                        counter_discount_percent: counter,
                        note: counterNote,
                      }),
                    )
                  }
                >
                  Send counter-offer
                </Button>
              </div>
            </div>

            {/* There is deliberately no Decline here. A seller rejecting their
                own deal is just deleting their own work — if the number doesn't
                suit, the answer is a counter. Walking away is the customer's
                call, and only they get that button. */}
            <div className="flex flex-col justify-end">
              <Button
                variant="success"
                disabled={busy}
                onClick={() =>
                  // One call. This used to accept and then POST to
                  // `/internal/quotations/{id}/negotiation` to refresh — a
                  // GET-only route, which answered 405. The accept had already
                  // gone through by then, so the deal moved while the screen
                  // showed an error. The accept endpoint now returns the
                  // conversation itself.
                  run(
                    () => post(`/portal/internal/requests/${open!.id}/accept`),
                    true,
                  )
                }
              >
                Accept their {open?.requested_discount_percent
                  ? percent(open.requested_discount_percent, 0)
                  : "request"}
              </Button>
              <p className="mt-2 text-xs text-[#64748B]">
                Or counter with your own number on the left.
              </p>
            </div>
          </div>

          <div className="mt-4">
            <Note>
              Accepting applies the discount to every line and re-scores the quotation — if the new
              terms breach a ceiling it re-enters approval automatically.
            </Note>
          </div>
        </div>
      )}

      {awaitingThem && (
        <div className="mt-5">
          <Note>
            You offered {percent(open?.counter_discount_percent, 0)}. Waiting for{" "}
            {data.customer_name} to accept it, come back with another number, or decline.
          </Note>
        </div>
      )}

      {/* The customer walked away. Without this the panel just went quiet and
          the rep had to infer it from the quotation status badge. */}
      {rejectedByCustomer && (
        <div className="mt-5 rounded-lg border border-[#FECACA] bg-[#FEF2F2] p-4">
          <p className="text-sm font-medium text-[#991B1B]">
            {data.customer_name} declined this quotation.
          </p>
          {lastRejection?.body && (
            <p className="mt-1 text-sm text-[#B91C1C]">
              &ldquo;{lastRejection.body}&rdquo;
            </p>
          )}
          <p className="mt-2 text-xs text-[#B91C1C]">
            The conversation is closed. Revise the quote and send it again if you want another go.
          </p>
        </div>
      )}
    </Card>
  );
}
