/** Display helpers.  Owner: sinjeki. */

import type { QuotationStatus, RiskBand } from "@/types";

/** Money arrives from the API as a decimal STRING — never parse it into a
 *  float for arithmetic, only for display. */
export function money(value: string | number | null | undefined, currency = "USD"): string {
  const amount = Number(value ?? 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function percent(value: string | number | null | undefined, digits = 1): string {
  return `${Number(value ?? 0).toFixed(digits)}%`;
}

export function date(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function titleCase(value: string): string {
  return value
    .split("_")
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(" ");
}

export const STATUS_TONE: Record<QuotationStatus, string> = {
  DRAFT: "slate",
  PENDING_APPROVAL: "amber",
  APPROVED: "green",
  SENT: "blue",
  UNDER_NEGOTIATION: "amber",
  CONFIRMED: "green",
  REJECTED: "red",
  CANCELLED: "slate",
};

export const RISK_TONE: Record<RiskBand, string> = {
  NONE: "green",
  MEDIUM: "amber",
  HIGH: "red",
};

/** What the risk band means in words, for tooltips and empty states. */
export const RISK_LABEL: Record<RiskBand, string> = {
  NONE: "No approval needed",
  MEDIUM: "Sales Manager approval",
  HIGH: "Sales Manager, then Finance",
};
