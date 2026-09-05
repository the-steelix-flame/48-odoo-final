"use client";

/**
 * Portal home — the customer's quotation list.  Owner: the-steelix-flame.
 *
 * This page used to be a static "open the link your account manager sent you"
 * message, with no list behind it. Since portal access is granted per
 * quotation by token, and nothing enumerated those tokens, a customer who
 * logged in genuinely could not reach anything they'd been sent.
 *
 * Kept deliberately thin: reference, date, a plain-language status, and the
 * total. No margin, no risk score, no approval history — those never leave
 * the internal serialiser.
 */

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
import { date, money } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { PortalQuotationRow } from "@/types";

function toneFor(row: PortalQuotationRow): string {
  if (row.action_required) return "amber";
  if (row.status === "CONFIRMED") return "green";
  if (row.status === "REJECTED" || row.status === "CANCELLED") return "slate";
  return "blue";
}

export default function PortalHome() {
  const router = useRouter();
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi<PortalQuotationRow[]>("/portal/quotations");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const rows = data ?? [];
  const awaiting = rows.filter((row) => row.action_required);

  return (
    <>
      <PageHeader
        title="Your quotations"
        subtitle={`Signed in as ${user?.email}`}
      />

      {awaiting.length > 0 && (
        <div className="mb-6 rounded-xl border border-amber-700 bg-amber-950/30 p-4">
          <p className="text-sm text-amber-200">
            {awaiting.length === 1
              ? "One quotation is waiting for you."
              : `${awaiting.length} quotations are waiting for you.`}{" "}
            Open it to review the terms, ask a question, propose a different discount, or confirm.
          </p>
        </div>
      )}

      <Card>
        {/* This replaced a static "open the link your account manager sent you"
            message. Access is per-quotation by token and nothing enumerated
            those tokens, so a customer who logged in could reach nothing at
            all. Colours follow the light canvas restyle from origin/main. */}
        {rows.length === 0 ? (
          <EmptyState
            title="Nothing here yet"
            hint="Quotations appear here as soon as your account manager sends them."
          />
        ) : (
          <Table columns={["Quotation", "Sent", "Items", "Total", "Status", ""]}>
            {rows.map((row) => (
              <Row key={row.id} onClick={() => router.push(`/portal/quotations/${row.id}`)}>
                <Cell className="font-medium text-[#0F172A]">{row.number}</Cell>
                <Cell className="text-[#64748B]">{date(row.sent_at)}</Cell>
                <Cell className="text-[#64748B]">
                  {row.line_count} {row.line_count === 1 ? "item" : "items"}
                </Cell>
                <Cell className="font-medium text-[#0F172A]">
                  {money(row.total, row.currency)}
                </Cell>
                <Cell>
                  <Badge tone={toneFor(row)}>{row.status_label}</Badge>
                </Cell>
                <Cell className="text-right text-xs font-medium text-[#0891B2]">
                  {row.action_required ? "Review →" : "View →"}
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            You only see quotations that have been sent to you. Anything your account manager is
            still preparing stays private until they share it.
          </Note>
        </div>
      </Card>
    </>
  );
}
