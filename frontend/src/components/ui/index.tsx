"use client";

/**
 * Shared UI primitives.  Owner: sinjeki.
 *
 * Deliberately tiny — enough to make eighteen screens look like one product,
 * not a component library. If you need something that isn't here, build it in
 * your own folder first and tell sinjeki to promote it. Don't block.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { useNavigation } from "@/lib/navigation";

// ------------------------------------------------------------------ Button
type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "success" | "warning" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
};

const BUTTON_VARIANTS: Record<string, string> = {
  primary: "bg-gradient-to-br from-[#0891B2] to-[#0E7490] text-white shadow-[0_2px_4px_rgba(8,145,178,0.15)] hover:from-[#0E7490] hover:to-[#155E75]",
  secondary: "bg-white text-[#475569] border border-[#E2E8F0] shadow-sm hover:border-[#CBD5E1] hover:bg-[#F8FAFC]",
  success: "bg-gradient-to-br from-[#10B981] to-[#059669] text-white shadow-[0_2px_4px_rgba(16,185,129,0.15)] hover:from-[#059669] hover:to-[#047857]",
  warning: "bg-gradient-to-br from-[#F59E0B] to-[#D97706] text-white shadow-[0_2px_4px_rgba(245,158,11,0.15)] hover:from-[#D97706] hover:to-[#B45309]",
  danger: "bg-gradient-to-br from-[#EF4444] to-[#DC2626] text-white shadow-[0_2px_4px_rgba(239,68,68,0.15)] hover:from-[#DC2626] hover:to-[#B91C1C]",
};

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  type = "button",
  className = "",
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-[8px] px-4 py-[9px] text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${BUTTON_VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Badge
const BADGE_TONES: Record<string, string> = {
  slate: "bg-[#F1F5F9] text-[#475569]",
  blue: "bg-[#E0F2FE] text-[#0369A1]",
  green: "bg-[#ECFDF5] text-[#059669]",
  amber: "bg-[#FFFBEB] text-[#D97706] border border-[#FEF3C7]",
  red: "bg-[#FEF2F2] text-[#DC2626]",
};

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-[8px] py-[3px] text-[11px] font-semibold tracking-wide uppercase ${BADGE_TONES[tone] ?? BADGE_TONES.slate}`}
    >
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ Card
export function Card({
  title,
  subtitle,
  children,
  actions,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-[12px] border border-[#E2E8F0] bg-white p-[24px] shadow-sm transition hover:border-[#CBD5E1] hover:shadow-[0_4px_20px_-8px_rgba(0,0,0,0.08)] ${className}`}
    >
      {(title || actions) && (
        <header className="mb-[20px] flex items-start justify-between gap-4">
          <div>
            {title && <h2 className="font-heading text-[16px] font-semibold tracking-[-0.01em] text-[#0F172A]">{title}</h2>}
            {subtitle && <p className="mt-[4px] text-[13px] text-[#64748B]">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 gap-[10px]">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  hint,
  href,
  tone = "slate",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  href?: string;
  tone?: string;
}) {
  const body = (
    <div className="group relative overflow-hidden rounded-[12px] border border-[#E2E8F0] bg-white p-[20px] shadow-sm transition hover:-translate-y-[2px] hover:border-[#0891B2] hover:shadow-[0_8px_24px_-12px_rgba(8,145,178,0.3)]">
      <div className={`absolute left-0 top-0 h-[3px] w-full ${tone === 'red' ? 'bg-[#EF4444]' : tone === 'green' ? 'bg-[#10B981]' : tone === 'amber' ? 'bg-[#F59E0B]' : 'bg-[#0891B2]'}`}></div>
      <p className="font-mono text-[11px] font-medium tracking-[0.04em] text-[#64748B] uppercase">{label}</p>
      <p className="mt-[12px] font-heading text-[28px] font-semibold tracking-[-0.02em] text-[#0F172A]">{value}</p>
      {hint && <p className="mt-[6px] text-[12px] text-[#64748B]">{hint}</p>}
      {tone !== "slate" && (
        <div className="mt-[12px]">
          <Badge tone={tone}>{tone === "red" ? "Needs attention" : tone === "amber" ? "Warning" : "Healthy"}</Badge>
        </div>
      )}
    </div>
  );
  return href ? <Link href={href} className="block">{body}</Link> : body;
}

// ------------------------------------------------------------------ Table
export function Table({
  columns,
  children,
}: {
  columns: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      {/* 640px was fixed regardless of column count. The 9-column quotation
          builder got ~39px of content per column, which collapsed the Qty and
          Discount inputs and wrapped product names onto two lines. Scale with
          the columns instead and let the wrapper scroll. */}
      <table
        className="w-full text-left text-[13px]"
        style={{ minWidth: Math.max(640, columns.length * 112) }}
      >
        <thead className="border-b border-[#E2E8F0] bg-[#F8FAFC]">
          <tr>
            {columns.map((column) => (
              <th key={column} className="p-[12px_16px] font-mono text-[11px] font-medium tracking-[0.02em] text-[#64748B] uppercase">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F1F5F9]">{children}</tbody>
      </table>
    </div>
  );
}

export function Row({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick?: () => void;
}) {
  // The hover strip is drawn with an inset box-shadow rather than an extra
  // <td>. A spacer cell counts as a real column, so every clickable table
  // rendered one more cell than it had headers and the whole row sat shifted
  // one column right of its own heading.
  return (
    <tr
      onClick={onClick}
      className={`text-[#334155] transition-colors ${
        onClick
          ? "cursor-pointer hover:bg-[#F8FAFC] hover:shadow-[inset_2px_0_0_0_#0891B2]"
          : ""
      }`}
    >
      {children}
    </tr>
  );
}

export function Cell({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`p-[14px_16px] ${className}`}>{children}</td>;
}

// ------------------------------------------------------------------ Field
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="mb-[6px] block text-[12.5px] font-medium text-[#475569]">{label}</span>
      {children}
      {hint && <span className="mt-[6px] block text-[11.5px] text-[#64748B]">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-[8px] border border-[#CBD5E1] bg-white p-[9px_12px] text-[13px] text-[#0F172A] shadow-[inset_0_1px_2px_rgba(0,0,0,0.03)] outline-none transition-colors placeholder:text-[#94A3B8] focus:border-[#0891B2] focus:ring-1 focus:ring-[#0891B2]";

// ------------------------------------------------------------------ States
export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="py-12 text-center text-[13px] text-[#64748B]">{label}</p>;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-[12px] border border-dashed border-[#CBD5E1] bg-[#F8FAFC] py-[48px] text-center">
      <p className="text-[14px] font-medium text-[#475569]">{title}</p>
      {hint && <p className="mt-[4px] text-[13px] text-[#64748B]">{hint}</p>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-[12px] border border-[#FECACA] bg-[#FEF2F2] p-[20px] text-center">
      <p className="text-[13px] text-[#DC2626]">{message}</p>
      {onRetry && (
        <div className="mt-[12px]">
          <Button variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-[8px] border border-[#FDE68A] bg-[#FEF9C3] p-[12px_16px] text-[12.5px] leading-relaxed text-[#92400E]">
      {children}
    </p>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
  /** Opt out on screens where going back makes no sense. */
  hideBack = false,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  hideBack?: boolean;
}) {
  // the-steelix-flame: Back lives here, above the title, rather than being
  // placed by each page. Every screen already renders a PageHeader, so it
  // lands in exactly the same spot everywhere for free — and it cannot drift
  // as pages are added. It appears only once there is somewhere in-app to go
  // back to; see lib/navigation.tsx for why history.length won't do.
  const { canGoBack, goBack } = useNavigation();

  return (
    <header className="mb-[24px] animate-dfIn">
      {canGoBack && !hideBack && (
        <button
          onClick={goBack}
          className="group -ml-[6px] mb-[10px] inline-flex items-center gap-[6px] rounded-[7px] px-[6px] py-[3px] text-[13px] font-medium text-[#64748B] transition hover:bg-[#F1F5F9] hover:text-[#0F172A]"
        >
          <span
            aria-hidden
            className="text-[15px] leading-none transition-transform group-hover:-translate-x-[2px]"
          >
            ←
          </span>
          Back
        </button>
      )}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-heading text-[28px] font-bold tracking-[-0.03em] text-[#0F172A]">{title}</h1>
          {subtitle && <p className="mt-[4px] text-[14px] text-[#64748B]">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-[10px]">{actions}</div>}
      </div>
    </header>
  );
}
