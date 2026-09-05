"use client";

/**
 * Checkout.  Owner: the-steelix-flame.
 *
 * Settles the bill for one quotation. Card details are collected, validated for
 * shape, and deliberately never sent anywhere — the request to our own API
 * carries only a reference. Nothing here touches a card network.
 */

import { use, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, post } from "@/lib/api";
import { ErrorState, Loading } from "@/components/ui";
import { money } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { PortalQuotation } from "@/types";

/** 4-digit groups, so the field reads the way a card is printed. */
function formatCardNumber(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 16);
  return digits.replace(/(.{4})/g, "$1 ").trim();
}

function formatExpiry(raw: string): string {
  const digits = raw.replace(/\D/g, "").slice(0, 4);
  if (digits.length <= 2) return digits;
  return `${digits.slice(0, 2)}/${digits.slice(2)}`;
}

/** Month must be 01–12, and the expiry must not already have passed. */
function expiryIsValid(value: string): boolean {
  const [mm, yy] = value.split("/");
  if (!mm || !yy || mm.length !== 2 || yy.length !== 2) return false;
  const month = Number(mm);
  if (!Number.isInteger(month) || month < 1 || month > 12) return false;
  const now = new Date();
  const year = 2000 + Number(yy);
  const endOfMonth = new Date(year, month, 0, 23, 59, 59);
  return endOfMonth >= now;
}

export default function CheckoutPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();

  const [name, setName] = useState("");
  const [card, setCard] = useState("");
  const [expiry, setExpiry] = useState("");
  const [cvc, setCvc] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<PortalQuotation>(`/portal/quotations/${id}`);

  if (loading) return <Loading label="Loading your bill…" />;
  if (error) {
    return (
      <ErrorState
        message={
          error.status === 404
            ? "We couldn't find that quotation on your account."
            : error.message
        }
        onRetry={reload}
      />
    );
  }
  if (!data) return null;

  const bill = data.bill ?? null;

  // Three ways to arrive here with nothing to do. Each says which one it is,
  // rather than showing an empty form that would fail on submit.
  if (!bill) {
    return (
      <Standby
        heading="Nothing to pay yet"
        body="No bill has been raised against this order. We'll email you as soon as it is."
        onBack={() => router.push(`/portal/quotations/${id}`)}
      />
    );
  }
  if (bill.is_paid) {
    return (
      <Standby
        heading="This bill is already settled"
        body={`${bill.number} was paid in full. Nothing further is needed.`}
        onBack={() => router.push(`/portal/quotations/${id}`)}
      />
    );
  }

  const digits = card.replace(/\s/g, "");
  const cardOk = digits.length === 16;
  const expiryOk = expiryIsValid(expiry);
  const cvcOk = /^\d{3,4}$/.test(cvc);
  const nameOk = name.trim().length > 1;
  const ready = cardOk && expiryOk && cvcOk && nameOk;

  // What's incomplete, in the order the fields appear — so a click that can't
  // go through says why instead of the button just sitting there greyed out.
  // A customer who has already tabbed past a field has no other way to find
  // out it's the one holding things up.
  function whatsMissing(): string | null {
    const missing: string[] = [];
    if (!nameOk) missing.push("the name on the card");
    if (!cardOk) missing.push("a 16-digit card number");
    if (!expiryOk) missing.push("a valid expiry date");
    if (!cvcOk) missing.push("the security code");
    if (missing.length === 0) return null;
    return `Check ${missing.join(", ")} before paying.`;
  }

  async function pay(event: React.FormEvent) {
    event.preventDefault();
    if (!bill) return;
    const problem = whatsMissing();
    if (problem) {
      setFailure(problem);
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      // Only the last four travel, as a human-readable reference on the
      // payment record. The rest of the card never leaves this component.
      await post(`/portal/quotations/${id}/pay`, {
        reference: `Card ending ${digits.slice(-4)}`,
      });
      router.push(`/portal/quotations/${id}`);
    } catch (err) {
      setFailure(
        err instanceof ApiError
          ? err.message
          : "We couldn't complete that payment. No money has been taken.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[860px]">
      <div className="overflow-hidden rounded-[16px] border border-[#E2E8F0] bg-white shadow-sm">
        <div className="grid md:grid-cols-[1fr_1.1fr]">
          {/* ---------------------------------------------- what you're paying */}
          <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] p-[28px] md:border-b-0 md:border-r">
            <p className="font-mono text-[11px] font-medium uppercase tracking-[0.08em] text-[#64748B]">
              Amount due
            </p>
            <p className="mt-[6px] font-heading text-[34px] font-bold tracking-[-0.02em] text-[#0F172A]">
              {money(bill.amount_due, bill.currency)}
            </p>
            <p className="mt-[4px] text-[13px] text-[#64748B]">
              {bill.number} · {data.company_name}
            </p>

            <dl className="mt-[24px] space-y-[10px] border-t border-[#E2E8F0] pt-[18px] text-[13px]">
              {bill.lines.map((line, index) => (
                <div key={index} className="flex justify-between gap-3">
                  <dt className="text-[#475569]">
                    {line.description}
                    <span className="ml-1 text-[#94A3B8]">× {Number(line.quantity)}</span>
                  </dt>
                  <dd className="shrink-0 text-[#0F172A]">
                    {money(line.line_total, bill.currency)}
                  </dd>
                </div>
              ))}
              <div className="flex justify-between border-t border-[#E2E8F0] pt-[10px] text-[#64748B]">
                <dt>Tax</dt>
                <dd>{money(bill.tax_total, bill.currency)}</dd>
              </div>
              <div className="flex justify-between text-[15px] font-semibold text-[#0F172A]">
                <dt>Total</dt>
                <dd>{money(bill.total, bill.currency)}</dd>
              </div>
            </dl>

            <p className="mt-[20px] text-[12px] text-[#64748B]">
              Account manager: <span className="text-[#334155]">{bill.sales_rep}</span>
            </p>
          </div>

          {/* ---------------------------------------------- card details */}
          <div className="p-[28px]">
            <h1 className="font-heading text-[20px] font-semibold tracking-[-0.02em] text-[#0F172A]">
              Pay by card
            </h1>
            <p className="mt-[4px] text-[13px] text-[#64748B]">
              Enter the details of the card you'd like to use.
            </p>

            {failure && (
              <div className="mt-[16px] rounded-[10px] border border-[#FECACA] bg-[#FEF2F2] px-[14px] py-[10px] text-[13px] text-[#991B1B]">
                {failure}
              </div>
            )}

            <form onSubmit={pay} className="mt-[20px] space-y-[16px]">
              <label className="block">
                <span className="mb-[6px] block text-[12px] font-medium text-[#475569]">
                  Name on card
                </span>
                <input
                  className={FIELD}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="cc-name"
                  placeholder="A. Buyer"
                  required
                />
              </label>

              <label className="block">
                <span className="mb-[6px] block text-[12px] font-medium text-[#475569]">
                  Card number
                </span>
                <input
                  className={`${FIELD} font-mono tracking-[0.06em]`}
                  value={card}
                  onChange={(e) => setCard(formatCardNumber(e.target.value))}
                  inputMode="numeric"
                  autoComplete="cc-number"
                  placeholder="0000 0000 0000 0000"
                  required
                />
                {card.length > 0 && !cardOk && (
                  <span className="mt-[4px] block text-[11.5px] text-[#B45309]">
                    A card number is 16 digits.
                  </span>
                )}
              </label>

              <div className="grid grid-cols-2 gap-[14px]">
                <label className="block">
                  <span className="mb-[6px] block text-[12px] font-medium text-[#475569]">
                    Expiry
                  </span>
                  <input
                    className={`${FIELD} font-mono`}
                    value={expiry}
                    onChange={(e) => setExpiry(formatExpiry(e.target.value))}
                    inputMode="numeric"
                    autoComplete="cc-exp"
                    placeholder="MM/YY"
                    required
                  />
                  {expiry.length >= 5 && !expiryOk && (
                    <span className="mt-[4px] block text-[11.5px] text-[#B45309]">
                      Check the expiry date.
                    </span>
                  )}
                </label>
                <label className="block">
                  <span className="mb-[6px] block text-[12px] font-medium text-[#475569]">
                    Security code
                  </span>
                  <input
                    className={`${FIELD} font-mono`}
                    value={cvc}
                    onChange={(e) => setCvc(e.target.value.replace(/\D/g, "").slice(0, 4))}
                    inputMode="numeric"
                    autoComplete="cc-csc"
                    placeholder="123"
                    required
                  />
                </label>
              </div>

              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-[10px] bg-gradient-to-br from-[#22D3EE] to-[#0891B2] px-[18px] py-[13px] text-[14.5px] font-semibold text-[#062A33] transition hover:from-[#34D399] hover:to-[#059669] hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? "Processing…" : `Pay ${money(bill.amount_due, bill.currency)}`}
              </button>

              <button
                type="button"
                onClick={() => router.push(`/portal/quotations/${id}`)}
                className="w-full rounded-[10px] border border-[#E2E8F0] px-[18px] py-[11px] text-[13.5px] font-medium text-[#475569] transition hover:bg-[#F8FAFC]"
              >
                Cancel
              </button>
            </form>

            <p className="mt-[18px] text-center text-[11.5px] text-[#94A3B8]">
              Payments are encrypted in transit. Card details are not stored.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

const FIELD =
  "w-full rounded-[9px] border border-[#E2E8F0] bg-white px-[12px] py-[10px] text-[14px] text-[#0F172A] outline-none transition focus:border-[#22D3EE] focus:ring-2 focus:ring-[#CFFAFE]";

function Standby({
  heading,
  body,
  onBack,
}: {
  heading: string;
  body: string;
  onBack: () => void;
}) {
  return (
    <div className="mx-auto max-w-[520px] rounded-[16px] border border-[#E2E8F0] bg-white p-[32px] text-center shadow-sm">
      <h1 className="font-heading text-[20px] font-semibold text-[#0F172A]">{heading}</h1>
      <p className="mt-[8px] text-[13.5px] text-[#64748B]">{body}</p>
      <button
        onClick={onBack}
        className="mt-[20px] rounded-[10px] border border-[#E2E8F0] px-[18px] py-[10px] text-[13.5px] font-medium text-[#475569] transition hover:bg-[#F8FAFC]"
      >
        Back to your quotation
      </button>
    </div>
  );
}
