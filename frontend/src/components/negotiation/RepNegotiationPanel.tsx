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
  const [reply, setReply] = useState("");
  const [counter, setCounter] = useState("");
  const [counterNote, setCounterNote] = useState("");
  const [rejectNote, setRejectNote] = useState("");
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
  const awaitingUs = open?.status === "SUBMITTED";
  const awaitingThem = open?.status === "COUNTERED";

  async function run(fn: () => Promise<unknown>, refetchQuotation = false) {
    setBusy(true);
    setActionError(null);
    try {
      const result = await fn();
      setData(result as NegotiationView);
      if (refetchQuotation) onQuotationChanged();
      setReply("");
      setCounter("");
      setCounterNote("");
      setRejectNote("");
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
        awaitingUs ? (
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

            <div>
              <Field label="Or decline, with a reason">
                <input
                  className={inputClass}
                  value={rejectNote}
                  onChange={(e) => setRejectNote(e.target.value)}
                  placeholder="We can't go below list on services."
                />
              </Field>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant="success"
                  disabled={busy}
                  onClick={() =>
                    // Accepting already appends an ACCEPTED event carrying the
                    // agreed figure. Posting a "we've accepted" message on top
                    // would say the same thing twice in the thread.
                    run(
                      async () => {
                        await post(`/portal/internal/requests/${open!.id}/accept`);
                        return post(
                          `/portal/internal/quotations/${quotationId}/negotiation`,
                        );
                      },
                      true,
                    )
                  }
                >
                  Accept their {open?.requested_discount_percent
                    ? percent(open.requested_discount_percent, 0)
                    : "request"}
                </Button>
                <Button
                  variant="danger"
                  disabled={busy || !rejectNote.trim()}
                  onClick={() =>
                    run(() =>
                      post(`/portal/internal/requests/${open!.id}/reject`, {
                        note: rejectNote,
                      }).then(() =>
                        post(`/portal/internal/quotations/${quotationId}/negotiation`),
                      ),
                    )
                  }
                >
                  Decline
                </Button>
              </div>
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
            {data.customer_name} to accept it or come back with another number.
          </Note>
        </div>
      )}

      {/* ------------------------------------------- plain reply */}
      <div className="mt-5 border-t border-edge pt-4">
        <Field label="Reply" hint="For questions that aren't about price.">
          <textarea
            rows={2}
            className={inputClass}
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            placeholder="Type a message to the customer…"
          />
        </Field>
        <div className="mt-3">
          <Button
            variant="secondary"
            disabled={busy || !reply.trim()}
            onClick={() =>
              run(() =>
                post(`/portal/internal/quotations/${quotationId}/messages`, { body: reply }),
              )
            }
          >
            Send message
          </Button>
        </div>
      </div>
    </Card>
  );
}
