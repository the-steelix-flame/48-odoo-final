"use client";

/**
 * Screen 18 — Discount tiers & approval chain setup.  Owner: sinjeki.
 *
 * This screen is the proof that the governance rules are DATA, not constants.
 * Editing a ceiling here changes how the next quotation is scored, with no
 * deploy — which is exactly what "implemented in application logic, not
 * hardcoded" is asking for. Demo it by lowering Services to 5% and watching a
 * previously-clean quote start asking for approval.
 */

import { useState } from "react";

import { ApiError, patch } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  Cell,
  ErrorState,
  Loading,
  Note,
  PageHeader,
  Row,
  Table,
  inputClass,
} from "@/components/ui";
import { percent } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { ApprovalRule, GovernanceConfig, RiskBand, Role } from "@/types";

const BAND_TONE: Record<RiskBand, string> = { NONE: "green", MEDIUM: "amber", HIGH: "red" };

/** The roles that can sit in an approval chain. A rep can't approve their own
 *  discount and a customer obviously can't, so neither is offered. */
const CHAIN_ROLES: Role[] = ["SALES_MANAGER", "FINANCE", "ADMIN"];

export default function DiscountSettingsPage() {
  const { data, error, loading, reload } = useApi<GovernanceConfig>("/governance/config");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [ruleEdits, setRuleEdits] = useState<Record<number, ApprovalRule>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const valueFor = (key: string, fallback: string) => edits[key] ?? fallback;
  /** The edited copy of a rule if it's been touched, otherwise the saved one. */
  const ruleFor = (rule: ApprovalRule) => ruleEdits[rule.id] ?? rule;
  const dirty = Object.keys(edits).length + Object.keys(ruleEdits).length;

  /** Toggle one role in a chain, keeping CHAIN_ROLES order so the arrow
   *  sequence a manager reads matches the order approvals actually run in. */
  function toggleRole(rule: ApprovalRule, role: Role) {
    const current = ruleFor(rule);
    const has = current.required_roles.includes(role);
    const next = has
      ? current.required_roles.filter((item) => item !== role)
      : CHAIN_ROLES.filter((item) => item === role || current.required_roles.includes(item));
    setRuleEdits({ ...ruleEdits, [rule.id]: { ...current, required_roles: next } });
  }

  function toggleActive(rule: ApprovalRule) {
    const current = ruleFor(rule);
    setRuleEdits({ ...ruleEdits, [rule.id]: { ...current, is_active: !current.is_active } });
  }

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await Promise.all([
        ...Object.entries(edits).map(([key, value]) => {
          const [kind, id] = key.split(":");
          const path =
            kind === "tier" ? `/governance/tier-ceilings/${id}` : `/governance/category-ceilings/${id}`;
          return patch(path, { max_discount_percent: value });
        }),
        // ApprovalRuleIn is a full replacement, not a partial — send every
        // field back or the omitted ones get clobbered with defaults.
        ...Object.values(ruleEdits).map((rule) =>
          patch(`/governance/approval-rules/${rule.id}`, {
            name: rule.name,
            band: rule.band,
            min_score: rule.min_score,
            max_score: rule.max_score,
            required_roles: rule.required_roles,
            sequence: rule.sequence,
            is_active: rule.is_active,
          }),
        ),
      ]);
      setEdits({});
      setRuleEdits({});
      setMessage("Saved. The next quotation is scored and routed against these rules.");
      await reload();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Discount tiers and approval chains"
        subtitle="The governance rules the risk engine reads on every quotation."
        actions={
          <Button onClick={save} disabled={saving || dirty === 0}>
            {saving ? "Saving…" : dirty === 0 ? "Save configuration" : `Save ${dirty} change${dirty === 1 ? "" : "s"}`}
          </Button>
        }
      />

      {message && (
        <div className="mb-4">
          <Note>{message}</Note>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Tier Discount Ceilings" subtitle="The customer's maximum, by tier">
          <Table columns={["Tier", "Max Discount"]}>
            {data.tier_ceilings.map((ceiling) => (
              <Row key={ceiling.id}>
                <Cell className="font-heading font-medium text-[#0F172A]">{ceiling.tier}</Cell>
                <Cell>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      className={`${inputClass} w-24`}
                      value={valueFor(`tier:${ceiling.id}`, ceiling.max_discount_percent)}
                      onChange={(e) =>
                        setEdits({ ...edits, [`tier:${ceiling.id}`]: e.target.value })
                      }
                    />
                    <span className="text-[11px] text-[#64748B]">percent</span>
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        </Card>

        <Card
          title="Category Discount Ceilings"
          subtitle="Some categories allow more discretion than others"
        >
          <Table columns={["Category", "Max Discount"]}>
            {data.category_ceilings.map((ceiling) => (
              <Row key={ceiling.id}>
                <Cell className="font-heading font-medium text-[#0F172A]">{ceiling.category_name}</Cell>
                <Cell>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      className={`${inputClass} w-24`}
                      value={valueFor(`category:${ceiling.id}`, ceiling.max_discount_percent)}
                      onChange={(e) =>
                        setEdits({ ...edits, [`category:${ceiling.id}`]: e.target.value })
                      }
                    />
                    <span className="text-[11px] text-[#64748B]">percent</span>
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        </Card>
      </div>

      <div className="mt-6">
        <Card
          title="Approval Chains"
          subtitle="Which discount range needs whom — click a role to add or remove it from the chain"
        >
          <Table columns={["Discount range", "Band", "Approval chain", "Active"]}>
            {data.approval_rules.map((saved) => {
              const rule = ruleFor(saved);
              const changed = ruleEdits[saved.id] !== undefined;
              return (
                <Row key={saved.id}>
                  <Cell className="text-[#0F172A]">
                    {rule.name}
                    {changed && (
                      <span className="ml-2 text-[11px] font-medium text-[#0891B2]">edited</span>
                    )}
                  </Cell>
                  <Cell>
                    <Badge tone={BAND_TONE[rule.band]}>{rule.band}</Badge>
                  </Cell>
                  <Cell>
                    <div className="flex flex-wrap items-center gap-[6px]">
                      {CHAIN_ROLES.map((role) => {
                        const on = rule.required_roles.includes(role);
                        const step = rule.required_roles.indexOf(role) + 1;
                        return (
                          <button
                            key={role}
                            type="button"
                            onClick={() => toggleRole(saved, role)}
                            title={on ? `Step ${step} — click to remove` : "Click to add to the chain"}
                            className={`rounded-full px-[10px] py-[4px] text-[11.5px] font-medium transition ${
                              on
                                ? "border border-[#A5F3FC] bg-[#E0F2FE] text-[#0369A1]"
                                : "border border-[#E2E8F0] bg-white text-[#94A3B8] hover:border-[#CBD5E1] hover:text-[#64748B]"
                            }`}
                          >
                            {on && <span className="mr-1 font-mono text-[10px]">{step}</span>}
                            {role.replace("_", " ").toLowerCase()}
                          </button>
                        );
                      })}
                      {rule.required_roles.length === 0 && (
                        <span className="text-[12px] text-[#64748B]">No approval needed</span>
                      )}
                    </div>
                  </Cell>
                  <Cell>
                    <button
                      type="button"
                      onClick={() => toggleActive(saved)}
                      className={`rounded-full px-[10px] py-[4px] text-[11.5px] font-medium transition ${
                        rule.is_active
                          ? "border border-[#BBF7D0] bg-[#ECFDF5] text-[#059669]"
                          : "border border-[#E2E8F0] bg-[#F8FAFC] text-[#94A3B8]"
                      }`}
                    >
                      {rule.is_active ? "Active" : "Off"}
                    </button>
                  </Cell>
                </Row>
              );
            })}
          </Table>

          <div className="mt-4 space-y-2">
            <Note>
              When a quote mixes categories with different ceilings, the system computes a blended
              risk score and routes to the highest required level. Every line is checked against
              the stricter of its tier ceiling and its category ceiling.
            </Note>
            <Note>
              All approvals, rejections and edits are logged with user, timestamp and reason.
            </Note>
          </div>
        </Card>
      </div>

      <div className="mt-6">
        <Card title="Risk score weights" subtitle="Tuning the score is a config change, not a deploy">
          <div className="grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {Object.entries(data.risk_config).map(([key, value]) => (
              <div key={key} className="rounded-[8px] border border-[#E2E8F0] bg-[#F8FAFC] px-[12px] py-[8px]">
                <p className="text-[11px] font-medium uppercase tracking-[0.05em] text-[#64748B]">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="mt-[4px] text-[#0F172A] font-medium">
                  {key.startsWith("weight") ? value : percent(value, 0)}
                </p>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
