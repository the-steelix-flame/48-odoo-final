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
import type { GovernanceConfig, RiskBand } from "@/types";

const BAND_TONE: Record<RiskBand, string> = { NONE: "green", MEDIUM: "amber", HIGH: "red" };

export default function DiscountSettingsPage() {
  const { data, error, loading, reload } = useApi<GovernanceConfig>("/governance/config");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const valueFor = (key: string, fallback: string) => edits[key] ?? fallback;

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await Promise.all(
        Object.entries(edits).map(([key, value]) => {
          const [kind, id] = key.split(":");
          const path =
            kind === "tier" ? `/governance/tier-ceilings/${id}` : `/governance/category-ceilings/${id}`;
          return patch(path, { max_discount_percent: value });
        }),
      );
      setEdits({});
      setMessage("Saved. The next quotation is scored against these ceilings.");
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
          <Button onClick={save} disabled={saving || Object.keys(edits).length === 0}>
            {saving ? "Saving…" : "Save configuration"}
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
                <Cell className="font-medium text-slate-100">{ceiling.tier}</Cell>
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
                    <span className="text-xs text-slate-500">percent</span>
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
                <Cell className="font-medium text-slate-100">{ceiling.category_name}</Cell>
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
                    <span className="text-xs text-slate-500">percent</span>
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        </Card>
      </div>

      <div className="mt-6">
        <Card title="Approval Chains" subtitle="Which discount range needs whom">
          <Table columns={["Discount range", "Band", "Approval chain"]}>
            {data.approval_rules.map((rule) => (
              <Row key={rule.id}>
                <Cell className="text-slate-100">{rule.name}</Cell>
                <Cell>
                  <Badge tone={BAND_TONE[rule.band]}>{rule.band}</Badge>
                </Cell>
                <Cell>
                  {rule.required_roles.length === 0
                    ? "No approval needed"
                    : rule.required_roles
                        .map((role) => role.replace("_", " ").toLowerCase())
                        .join(" → ")}
                </Cell>
              </Row>
            ))}
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
              <div key={key} className="rounded-lg border border-edge bg-black/20 px-3 py-2">
                <p className="text-xs uppercase tracking-wide text-slate-500">
                  {key.replace(/_/g, " ")}
                </p>
                <p className="mt-1 text-slate-200">
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
