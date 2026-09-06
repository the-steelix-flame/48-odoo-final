"use client";

/**
 * The negotiation thread.  Owner: the-steelix-flame.
 *
 * Rendered by BOTH the rep's quotation panel and the customer portal, from the
 * same `timeline` payload. One shared record of who said what — if the two
 * sides rendered different data structures they would eventually disagree, and
 * a negotiation both parties remember differently is worse than no record.
 *
 * `viewpoint` only changes labelling ("You" vs the other party's name), never
 * which entries are shown.
 */

import { Badge } from "@/components/ui";
import { date, dateTime, percent } from "@/lib/format";
import type { TimelineEntry } from "@/types";

const KIND_META: Record<string, { label: string; tone: string }> = {
  MESSAGE: { label: "", tone: "slate" },
  COUNTER_REQUEST: { label: "Counter-offer", tone: "amber" },
  REP_COUNTER: { label: "Our counter-offer", tone: "blue" },
  ACCEPTED: { label: "Accepted", tone: "green" },
  REJECTED: { label: "Declined", tone: "red" },
  SENT: { label: "Quotation sent", tone: "slate" },
  CONFIRMED: { label: "Confirmed", tone: "green" },
};

/** Keyed on a plain string and defaulted, so a kind added on the backend
 *  renders as a plain entry instead of crashing the whole thread. */
const UNKNOWN_KIND = { label: "", tone: "slate" };

/** Moves that mean haggling has happened, so a later send is a REVISED offer. */
const NEGOTIATION_KINDS = new Set(["COUNTER_REQUEST", "REP_COUNTER", "ACCEPTED"]);

export function NegotiationThread({
  entries,
  viewpoint,
  emptyHint,
}: {
  entries: TimelineEntry[];
  /** Whose side is reading — decides only how authors are labelled. */
  viewpoint: "REP" | "CUSTOMER";
  emptyHint?: string;
}) {
  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-edge py-10 text-center">
        <p className="text-sm text-[#64748B]">No messages yet</p>
        {emptyHint && <p className="mt-1 text-xs text-[#94A3B8]">{emptyHint}</p>}
      </div>
    );
  }

  return (
    <ol className="space-y-3">
      {entries.map((entry, index) => {
        const mine = entry.author_type === viewpoint;
        const who = mine
          ? "You"
          : viewpoint === "CUSTOMER"
            ? "Your account manager"
            : entry.author_name;

        /**
         * A send that follows any haggling is a REVISED offer, not the opening
         * one, and the two sides need to read it differently: internally it is
         * the outcome of the approval conversation, and to the customer it is
         * their account manager coming back to them. The stored body is one
         * neutral sentence written for nobody in particular, so both sides saw
         * the same "Quotation sent for your review" and neither learned that
         * the terms had actually changed.
         *
         * Derived here rather than stored, for the same reason `who` is: the
         * event log records what happened, and each audience is told about it
         * in its own words.
         */
        const isRevisedOffer =
          entry.kind === "SENT" &&
          entries.slice(0, index).some((earlier) => NEGOTIATION_KINDS.has(earlier.kind));

        const meta = isRevisedOffer
          ? { label: "Revised offer sent", tone: "blue" }
          : KIND_META[entry.kind] ?? UNKNOWN_KIND;

        const body = isRevisedOffer
          ? viewpoint === "REP"
            ? "Revised terms sent to the customer, following the internal review of this negotiation."
            : "Your account manager has come back with revised terms following your request. The updated figures are shown above."
          : entry.body;

        return (
          <li
            key={index}
            className={`rounded-lg border p-3 ${
              mine
                ? "border-edge bg-[#F8FAFC]"
                : "border-[#BAE6FD] bg-[#F0F9FF]"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-[#334155]">{who}</span>
                {meta.label && <Badge tone={meta.tone}>{meta.label}</Badge>}
                {entry.line_description && (
                  <span className="text-xs text-[#94A3B8]">
                    on {entry.line_description}
                  </span>
                )}
              </div>
              <span className="text-xs text-[#94A3B8]">{dateTime(entry.created_at)}</span>
            </div>

            {entry.discount_percent != null && (
              <p className="mt-2 text-sm text-[#0F172A]">
                {entry.kind === "COUNTER_REQUEST" && "Requested "}
                {entry.kind === "REP_COUNTER" && "Offered "}
                {entry.kind === "ACCEPTED" && "Agreed at "}
                <strong>{percent(entry.discount_percent, 0)}</strong>
                {entry.kind === "COUNTER_REQUEST" && " discount"}
              </p>
            )}

            {entry.delivery_date && (
              <p className="mt-1 text-xs text-[#64748B]">
                Requested delivery by {date(entry.delivery_date)}
              </p>
            )}

            {body && (
              <p className="mt-2 whitespace-pre-wrap text-sm text-[#334155]">{body}</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
