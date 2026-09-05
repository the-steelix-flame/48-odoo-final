"use client";

/**
 * Subscription Plan Management.  Owner: the-steelix-flame.
 *
 * A plan is the billing policy every recurring order inherits: renewal
 * cadence, what a mid-cycle change costs, and what cancelling refunds. Reps
 * pick a plan; only Admin decides what the plans mean.
 *
 * The plain-English reading of each plan comes from the server
 * (`policy_summary` / `policy_warnings`) rather than being rebuilt here. Two
 * copies of "what does END_OF_PERIOD + PRORATED actually do" is exactly how a
 * screen ends up confidently contradicting the code that bills the customer.
 */

import { Fragment, useState } from "react";

import { ApiError, patch, post } from "@/lib/api";
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
import { useApi } from "@/lib/useApi";
import type {
  AdminPlan,
  CancellationPolicy,
  ProrationMode,
  RecurringInterval,
  RefundMode,
} from "@/types";

/**
 * Each option carries what it does, not just its name. The admin picking
 * "FULL_PERIOD" at 2am should not have to open `proration.py` to find out that
 * it charges a whole period for a change made on the last day of one.
 */
const INTERVALS: { value: RecurringInterval; label: string; hint: string }[] = [
  { value: "WEEKLY", label: "Weekly", hint: "Renews every 7 days." },
  { value: "MONTHLY", label: "Monthly", hint: "Calendar months — Jan 31 renews Feb 28." },
  { value: "QUARTERLY", label: "Quarterly", hint: "Every 3 calendar months." },
  { value: "YEARLY", label: "Yearly", hint: "Every 12 calendar months." },
  {
    value: "BIENNIAL",
    label: "Every 2 years",
    hint: "Every 24 calendar months — multi-year care plans and SLAs.",
  },
];

const PRORATION_MODES: { value: ProrationMode; label: string; hint: string }[] = [
  { value: "DAILY", label: "Daily pro-rata", hint: "Charge only the unused days." },
  { value: "NONE", label: "No proration", hint: "Changes take effect next period, free." },
  { value: "FULL_PERIOD", label: "Charge full period", hint: "A whole period, any day." },
];

const CANCELLATION_POLICIES: { value: CancellationPolicy; label: string; hint: string }[] = [
  { value: "IMMEDIATE", label: "Immediate", hint: "Stops now; refund mode decides the credit." },
  { value: "END_OF_PERIOD", label: "End of period", hint: "Runs out the paid period." },
];

const REFUND_MODES: { value: RefundMode; label: string; hint: string }[] = [
  { value: "PRORATED", label: "Prorated refund", hint: "Credit note for the unused remainder." },
  { value: "NONE", label: "No refund", hint: "Keeps the whole period's money." },
];

type Draft = {
  name: string;
  interval: RecurringInterval;
  proration_mode: ProrationMode;
  cancellation_policy: CancellationPolicy;
  refund_mode: RefundMode;
  bill_in_advance: boolean;
  is_active: boolean;
  /** Create-only, and kept as strings so an empty box stays empty rather than
   *  silently becoming 0. Editing a plan never re-prices its product. */
  list_price?: string;
  cost_price?: string;
};

const BLANK: Draft = {
  name: "",
  interval: "MONTHLY",
  proration_mode: "DAILY",
  cancellation_policy: "IMMEDIATE",
  refund_mode: "PRORATED",
  bill_in_advance: true,
  is_active: true,
  list_price: "",
  cost_price: "",
};

const labelOf = <T extends string>(
  options: { value: T; label: string }[],
  value: T,
): string => options.find((option) => option.value === value)?.label ?? value;

export default function PlanManagementPage() {
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<Draft>(BLANK);
  /** The plan whose detail panel is open; also the one being edited. */
  const [openId, setOpenId] = useState<number | null>(null);
  const [edit, setEdit] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<AdminPlan[]>("/admin/plans");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const plans = data ?? [];

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      await reload();
      return true;
    } catch (err) {
      // The server refuses an interval change on a plan with live
      // subscriptions. That message explains what to do instead, so show it
      // verbatim rather than replacing it with "Update failed".
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function createPlan(event: React.FormEvent) {
    event.preventDefault();
    // The server wants numbers or null, not the empty strings an untouched
    // box holds. Cost is optional — it defaults to 40% of list server-side.
    const { list_price, cost_price, ...policy } = draft;
    const created = await run(() =>
      post<AdminPlan>("/admin/plans", {
        ...policy,
        list_price: list_price ? Number(list_price) : null,
        cost_price: cost_price ? Number(cost_price) : null,
      }),
    );
    if (created) {
      setShowForm(false);
      setDraft(BLANK);
    }
  }

  async function saveEdit(planId: number) {
    if (!edit) return;
    // Strip the create-only price fields; UpdatePlanIn rejects anything that
    // is not an editable policy field.
    const { list_price: _lp, cost_price: _cp, ...policy } = edit;
    const saved = await run(() => patch<AdminPlan>(`/admin/plans/${planId}`, policy));
    if (saved) setEdit(null);
  }

  function openPlan(plan: AdminPlan) {
    const next = openId === plan.id ? null : plan.id;
    setOpenId(next);
    setEdit(null);
    setActionError(null);
    if (next !== null) setShowForm(false);
  }

  /** Renders the four policy dropdowns for both the create and edit forms. */
  function policyFields(
    value: Draft,
    onChange: (patch: Partial<Draft>) => void,
    { intervalLocked = false }: { intervalLocked?: boolean } = {},
  ) {
    return (
      <>
        <Field
          label="Billing cadence"
          hint={
            intervalLocked
              ? "Locked — subscriptions are already billing on this cadence."
              : INTERVALS.find((i) => i.value === value.interval)?.hint
          }
        >
          <select
            className={inputClass}
            value={value.interval}
            disabled={intervalLocked}
            onChange={(e) => onChange({ interval: e.target.value as RecurringInterval })}
          >
            {INTERVALS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Mid-cycle changes"
          hint={PRORATION_MODES.find((m) => m.value === value.proration_mode)?.hint}
        >
          <select
            className={inputClass}
            value={value.proration_mode}
            onChange={(e) => onChange({ proration_mode: e.target.value as ProrationMode })}
          >
            {PRORATION_MODES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Cancellation"
          hint={
            CANCELLATION_POLICIES.find((c) => c.value === value.cancellation_policy)?.hint
          }
        >
          <select
            className={inputClass}
            value={value.cancellation_policy}
            onChange={(e) =>
              onChange({ cancellation_policy: e.target.value as CancellationPolicy })
            }
          >
            {CANCELLATION_POLICIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="Refund on cancellation"
          hint={
            value.cancellation_policy === "END_OF_PERIOD"
              ? "Not consulted — an end-of-period cancellation never refunds."
              : REFUND_MODES.find((r) => r.value === value.refund_mode)?.hint
          }
        >
          <select
            className={inputClass}
            value={value.refund_mode}
            onChange={(e) => onChange({ refund_mode: e.target.value as RefundMode })}
          >
            {REFUND_MODES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Invoicing" hint="When the period's invoice is raised.">
          <label className="flex items-center gap-2 pt-2 text-[13px] text-[#475569]">
            <input
              type="checkbox"
              checked={value.bill_in_advance}
              onChange={(e) => onChange({ bill_in_advance: e.target.checked })}
            />
            Bill in advance
          </label>
        </Field>

        <Field label="Availability" hint="Retired plans stay in reports but leave the pickers.">
          <label className="flex items-center gap-2 pt-2 text-[13px] text-[#475569]">
            <input
              type="checkbox"
              checked={value.is_active}
              onChange={(e) => onChange({ is_active: e.target.checked })}
            />
            Available to sales reps
          </label>
        </Field>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Subscription Plans"
        subtitle="The billing policy every recurring order inherits — cadence, proration, and what cancelling refunds."
        actions={
          <Button
            onClick={() => {
              setShowForm((open) => !open);
              setOpenId(null);
            }}
          >
            {showForm ? "Cancel" : "+ New plan"}
          </Button>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}

      {/* ---------------------------------------- create form */}
      {showForm && (
        <div className="mb-6">
          <Card title="Define a plan">
            <form onSubmit={createPlan}>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <Field
                  label="Plan name"
                  hint="Name it for the service, not the cadence — the cadence is the next field."
                >
                  <input
                    className={inputClass}
                    value={draft.name}
                    onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                    placeholder="Aftercare Service"
                    required
                  />
                </Field>
                <Field
                  label="List price"
                  hint="Per period. Creates the product reps add to a quote."
                >
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className={inputClass}
                    value={draft.list_price}
                    onChange={(e) => setDraft({ ...draft, list_price: e.target.value })}
                    placeholder="1400.00"
                    required
                  />
                </Field>
                <Field label="Cost price" hint="Drives margin. Defaults to 40% of list.">
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    className={inputClass}
                    value={draft.cost_price}
                    onChange={(e) => setDraft({ ...draft, cost_price: e.target.value })}
                    placeholder="520.00"
                  />
                </Field>
                {policyFields(draft, (change) => setDraft({ ...draft, ...change }))}
              </div>

              <div className="mt-5">
                <Button type="submit" disabled={busy}>
                  {busy ? "Creating…" : "Create plan"}
                </Button>
              </div>
            </form>

            <div className="mt-4">
              <Note>
                The cadence is the one choice that hardens. Once orders are billing on this plan
                its interval is frozen, because their billing windows were built from it — the
                other three policies stay editable and apply to future events only.
              </Note>
            </div>
          </Card>
        </div>
      )}

      {/* ---------------------------------------- list */}
      <Card>
        {plans.length === 0 ? (
          <EmptyState
            title="No subscription plans yet"
            hint="Define one above. A recurring product cannot be sold until it has a plan to bill against."
          />
        ) : (
          <Table
            columns={[
              "Plan",
              "Cadence",
              "Mid-cycle",
              "Cancellation",
              "In use",
              "Status",
              "Actions",
            ]}
          >
            {plans.map((plan) => {
              const open = openId === plan.id;
              return (
                <Fragment key={plan.id}>
                  <Row onClick={() => openPlan(plan)}>
                    <Cell className="font-medium text-[#0F172A]">
                      {plan.name}
                      {plan.policy_warnings.length > 0 && (
                        <span className="ml-2 text-[#D97706]" title={plan.policy_warnings[0]}>
                          ⚠
                        </span>
                      )}
                    </Cell>
                    <Cell>
                      {labelOf(INTERVALS, plan.interval)}
                      <span className="ml-2 text-[11.5px] text-[#94A3B8]">
                        {plan.bill_in_advance ? "in advance" : "in arrears"}
                      </span>
                    </Cell>
                    <Cell className="text-[#64748B]">
                      {labelOf(PRORATION_MODES, plan.proration_mode)}
                    </Cell>
                    <Cell className="text-[#64748B]">
                      {plan.cancellation_policy === "END_OF_PERIOD"
                        ? "End of period"
                        : labelOf(REFUND_MODES, plan.refund_mode)}
                    </Cell>
                    <Cell className="text-[#64748B]">
                      {/* Products and subscriptions are different kinds of use:
                          a product attached to the plan can still create new
                          subscriptions, so both matter before retiring it. */}
                      {plan.active_subscription_count} active
                      {plan.product_count > 0 && (
                        <span className="text-[#94A3B8]"> · {plan.product_count} product(s)</span>
                      )}
                    </Cell>
                    <Cell>
                      {plan.is_active ? (
                        <Badge tone="green">Available</Badge>
                      ) : (
                        <Badge tone="slate">Retired</Badge>
                      )}
                    </Cell>
                    <Cell>
                      <div className="flex flex-wrap gap-1.5">
                        <Button
                          variant="secondary"
                          className="!px-2.5 !py-1 text-xs"
                          onClick={() => openPlan(plan)}
                        >
                          {open ? "Close" : "Details"}
                        </Button>
                        <Button
                          variant={plan.is_active ? "danger" : "success"}
                          className="!px-2.5 !py-1 text-xs"
                          disabled={busy}
                          onClick={() =>
                            run(() =>
                              post<AdminPlan>(`/admin/plans/${plan.id}/active`, {
                                enabled: !plan.is_active,
                              }),
                            )
                          }
                        >
                          {plan.is_active ? "Retire" : "Restore"}
                        </Button>
                      </div>
                    </Cell>
                  </Row>

                  {open && (
                    <tr className="bg-[#F8FAFC]">
                      <td colSpan={7} className="p-[20px_16px]">
                        {/* Written by the server from the same fields
                            `subscriptions/services.py` bills against. */}
                        <h3 className="text-[13px] font-semibold text-[#0F172A]">
                          What this plan does
                        </h3>
                        <ul className="mt-2 space-y-1">
                          {plan.policy_summary.map((line) => (
                            <li key={line} className="text-[13px] text-[#475569]">
                              — {line}
                            </li>
                          ))}
                        </ul>

                        {plan.policy_warnings.map((warning) => (
                          <p
                            key={warning}
                            className="mt-3 rounded-[8px] border border-[#FEF3C7] bg-[#FFFBEB] p-[10px_12px] text-[12.5px] text-[#B45309]"
                          >
                            {warning}
                          </p>
                        ))}

                        <div className="mt-4">
                          {edit === null ? (
                            <Button
                              variant="secondary"
                              className="!px-2.5 !py-1 text-xs"
                              onClick={() =>
                                setEdit({
                                  name: plan.name,
                                  interval: plan.interval,
                                  proration_mode: plan.proration_mode,
                                  cancellation_policy: plan.cancellation_policy,
                                  refund_mode: plan.refund_mode,
                                  bill_in_advance: plan.bill_in_advance,
                                  is_active: plan.is_active,
                                })
                              }
                            >
                              Edit plan
                            </Button>
                          ) : (
                            <div>
                              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                                <Field label="Plan name">
                                  <input
                                    className={inputClass}
                                    value={edit.name}
                                    onChange={(e) => setEdit({ ...edit, name: e.target.value })}
                                  />
                                </Field>
                                {policyFields(
                                  edit,
                                  (change) => setEdit({ ...edit, ...change }),
                                  { intervalLocked: plan.interval_locked },
                                )}
                              </div>
                              <div className="mt-4 flex gap-2">
                                <Button disabled={busy} onClick={() => saveEdit(plan.id)}>
                                  {busy ? "Saving…" : "Save changes"}
                                </Button>
                                <Button variant="secondary" onClick={() => setEdit(null)}>
                                  Cancel
                                </Button>
                              </div>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Retiring a plan removes it from the pickers without touching the subscriptions already
            on it — they keep billing to the same rules, and their proration history keeps pointing
            at the plan that produced it. There is deliberately no delete.
          </Note>
        </div>
      </Card>
    </>
  );
}
