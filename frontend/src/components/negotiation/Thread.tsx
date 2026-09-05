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

const KIND_META: Record<
  TimelineEntry["kind"],
  { label: string; tone: string }
> = {
  MESSAGE: { label: "", tone: "slate" },
  COUNTER_REQUEST: { label: "Counter-offer", tone: "amber" },
  REP_COUNTER: { label: "Our counter-offer", tone: "blue" },
  ACCEPTED: { label: "Accepted", tone: "green" },
  REJECTED: { label: "Declined", tone: "red" },
};

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
        const meta = KIND_META[entry.kind];
        const who = mine
          ? "You"
          : viewpoint === "CUSTOMER"
            ? "Your account manager"
            : entry.author_name;

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

            {entry.body && (
              <p className="mt-2 whitespace-pre-wrap text-sm text-[#334155]">{entry.body}</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
