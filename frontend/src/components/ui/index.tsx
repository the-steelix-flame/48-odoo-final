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
  primary: "bg-brand text-white hover:bg-blue-500",
  secondary: "bg-transparent text-slate-200 border border-edge hover:bg-surface",
  success: "bg-emerald-600 text-white hover:bg-emerald-500",
  warning: "bg-amber-600 text-white hover:bg-amber-500",
  danger: "bg-rose-600 text-white hover:bg-rose-500",
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
      className={`rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${BUTTON_VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Badge
const BADGE_TONES: Record<string, string> = {
  slate: "bg-slate-700/40 text-slate-300 border-slate-600",
  blue: "bg-blue-500/15 text-blue-300 border-blue-700",
  green: "bg-emerald-500/15 text-emerald-300 border-emerald-700",
  amber: "bg-amber-500/15 text-amber-300 border-amber-700",
  red: "bg-rose-500/15 text-rose-300 border-rose-700",
};

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${BADGE_TONES[tone] ?? BADGE_TONES.slate}`}
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
      className={`rounded-xl border border-edge bg-surface p-5 ${className}`}
    >
      {(title || actions) && (
        <header className="mb-4 flex items-start justify-between gap-4">
          <div>
            {title && <h2 className="text-base font-semibold text-slate-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
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
    <div className="rounded-xl border border-edge bg-surface p-5 transition hover:border-slate-600">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-100">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {tone !== "slate" && (
        <div className="mt-3">
          <Badge tone={tone}>{tone === "red" ? "Needs attention" : "Healthy"}</Badge>
        </div>
      )}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
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
    // Wide tables scroll inside their own container; the page body never
    // scrolls horizontally.
    <div className="overflow-x-auto rounded-lg border border-edge">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="bg-black/30 text-xs uppercase tracking-wide text-slate-400">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-4 py-3 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-edge">{children}</tbody>
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
  return (
    <tr
      onClick={onClick}
      className={`text-slate-300 ${onClick ? "cursor-pointer hover:bg-white/5" : ""}`}
    >
      {children}
    </tr>
  );
}

export function Cell({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`px-4 py-3 ${className}`}>{children}</td>;
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
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-lg border border-edge bg-black/30 px-3 py-2 text-sm text-slate-100 outline-none focus:border-brand";

// ------------------------------------------------------------------ States
/** Every screen must handle these three. A white box reads as broken. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="py-12 text-center text-sm text-slate-500">{label}</p>;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-edge py-12 text-center">
      <p className="text-sm text-slate-400">{title}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-rose-800 bg-rose-950/30 p-5 text-center">
      <p className="text-sm text-rose-300">{message}</p>
      {onRetry && (
        <div className="mt-3">
          <Button variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

/** The yellow explainer strip used throughout the mockup. */
export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-amber-900/60 bg-amber-950/30 px-4 py-3 text-xs text-amber-200/80">
      {children}
    </p>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </header>
  );
}
