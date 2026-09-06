"use client";

/**
 * Warehouse Management.  Owner: the-steelix-flame.
 *
 * Warehouses could previously only be created by `seed_demo` or the Django
 * admin, so an operator could not add a depot at all — and a warehouse is what
 * the fulfillment splitter is allowed to consider, which makes defining one an
 * admin act rather than an operational one.
 *
 * Three fields were removed from this form (anubhaw0raj):
 *
 *   - Latitude / Longitude. Nothing reads them. `planner.py` never looks at a
 *     coordinate, so typing one changed nothing and implied it did.
 *   - Cost weight. The opposite problem: it is the planner's PRIMARY sort key
 *     and it multiplies the shipment cost, so it is far too load-bearing to be
 *     a free-text box. Someone typed 1000 into it, which sent Main Warehouse to
 *     last place in every split and priced its shipments at $42,000. New depots
 *     now take the service default of 1.0 and are ranked by real numbers.
 *
 * The columns still exist on the model and the splitter still uses the weight —
 * this only stops it being edited by hand.
 */

import Link from "next/link";
import { useState } from "react";

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
import { money } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Warehouse } from "@/types";

/** Matches the service defaults in `accounts/warehouses.py`. */
const BLANK = {
  name: "",
  code: "",
  address: "",
  base_shipment_cost: "30",
  lead_time_days: "3",
};

export default function WarehouseManagementPage() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...BLANK });
  /** id of the warehouse being edited, or null while creating a new one. */
  const [editingId, setEditingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<Warehouse[]>("/admin/warehouses");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const warehouses = data ?? [];
  const activeCount = warehouses.filter((w) => w.is_active).length;

  const set = (field: keyof typeof BLANK, value: string) =>
    setForm((current) => ({ ...current, [field]: value }));

  function openCreate() {
    setForm({ ...BLANK });
    setEditingId(null);
    setShowForm(true);
    setActionError(null);
  }

  function openEdit(warehouse: Warehouse) {
    setForm({
      name: warehouse.name,
      code: warehouse.code,
      address: warehouse.address ?? "",
      base_shipment_cost: warehouse.base_shipment_cost,
      lead_time_days: String(warehouse.lead_time_days),
    });
    setEditingId(warehouse.id);
    setShowForm(true);
    setActionError(null);
  }

  async function run(fn: () => Promise<unknown>, message: string) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await fn();
      await reload();
      setNotice(message);
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    // Coordinates and cost weight are deliberately absent: the PATCH only
    // touches keys it is sent, so omitting them leaves whatever the row already
    // has rather than blanking it.
    const payload = {
      name: form.name,
      code: form.code,
      address: form.address,
      base_shipment_cost: form.base_shipment_cost,
      lead_time_days: Number(form.lead_time_days),
    };
    const ok = await run(
      () =>
        editingId === null
          ? post<Warehouse>("/admin/warehouses", payload)
          : patch<Warehouse>(`/admin/warehouses/${editingId}`, payload),
      editingId === null ? `${form.name} created.` : `${form.name} updated.`,
    );
    if (ok) {
      setShowForm(false);
      setForm({ ...BLANK });
      setEditingId(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Warehouse Management"
        subtitle="Stock locations the fulfillment splitter is allowed to ship from."
        actions={
          <Button onClick={() => (showForm ? setShowForm(false) : openCreate())}>
            {showForm ? "Cancel" : "+ Add Warehouse"}
          </Button>
        }
      />

      {actionError && (
        <div className="mb-4">
          <ErrorState message={actionError} />
        </div>
      )}
      {notice && (
        <div className="mb-4">
          <Note>{notice}</Note>
        </div>
      )}

      {/* ---------------------------------------- create / edit */}
      {showForm && (
        <div className="mb-6">
          <Card title={editingId === null ? "New warehouse" : "Edit warehouse"}>
            <form onSubmit={save}>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <Field label="Name" hint="Shown on every allocation and plan.">
                  <input
                    className={inputClass}
                    value={form.name}
                    onChange={(e) => set("name", e.target.value)}
                    placeholder="Main Warehouse"
                    required
                  />
                </Field>
                <Field label="Code" hint="Short, unique. Upper-cased automatically.">
                  <input
                    className={inputClass}
                    value={form.code}
                    onChange={(e) => set("code", e.target.value.toUpperCase())}
                    placeholder="WH-MAIN"
                    required
                  />
                </Field>
                <Field label="Address" hint="Where the depot physically is.">
                  <input
                    className={inputClass}
                    value={form.address}
                    onChange={(e) => set("address", e.target.value)}
                    placeholder="12 Dock Road, Kolkata"
                  />
                </Field>
                <Field label="Base shipment cost" hint="Charged once per shipment from here.">
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={inputClass}
                    value={form.base_shipment_cost}
                    onChange={(e) => set("base_shipment_cost", e.target.value)}
                    required
                  />
                </Field>
                <Field
                  label="Lead time (days)"
                  hint="Drives the promised date the slippage alert measures against."
                >
                  <input
                    type="number"
                    min="0"
                    className={inputClass}
                    value={form.lead_time_days}
                    onChange={(e) => set("lead_time_days", e.target.value)}
                    required
                  />
                </Field>
              </div>

              <div className="mt-5">
                <Button type="submit" disabled={busy}>
                  {busy ? "Saving…" : editingId === null ? "Create warehouse" : "Save changes"}
                </Button>
              </div>
            </form>

            <div className="mt-4">
              <Note>
                Cost weight is set by the service, not typed here. It is the splitter&apos;s primary
                sort key and it multiplies the shipment cost, so a hand-typed value silently changes
                which depot every order ships from. New warehouses start at 1.0.
              </Note>
            </div>
          </Card>
        </div>
      )}

      {/* ---------------------------------------- list */}
      <Card>
        {warehouses.length === 0 ? (
          <EmptyState
            title="No warehouses configured"
            hint="Add one above. With none active, every order goes straight to backorder."
          />
        ) : (
          <Table
            columns={[
              "Warehouse",
              "Address",
              "Shipment cost",
              "Lead time",
              "Stock",
              "Status",
              "Actions",
            ]}
          >
            {warehouses.map((warehouse) => (
              <Row key={warehouse.id}>
                <Cell className="font-medium text-[#0F172A]">
                  <Link
                    href={`/admin/warehouses/${warehouse.id}`}
                    className="hover:text-[#0891B2] hover:underline"
                  >
                    {warehouse.name}
                  </Link>
                  <span className="ml-2 font-mono text-xs text-slate-500">{warehouse.code}</span>
                </Cell>
                <Cell className="max-w-[240px] text-[#64748B]">
                  {warehouse.address || <span className="text-slate-500">Not set</span>}
                </Cell>
                <Cell className="text-[#64748B]">{money(warehouse.base_shipment_cost)}</Cell>
                <Cell className="text-[#64748B]">{warehouse.lead_time_days}d</Cell>
                <Cell className="text-[#64748B]">
                  <Link
                    href={`/admin/warehouses/${warehouse.id}`}
                    className="hover:text-[#0891B2] hover:underline"
                  >
                    {warehouse.units_on_hand} units
                    <span className="block text-[11px] text-slate-500">
                      {warehouse.stock_line_count} product
                      {warehouse.stock_line_count === 1 ? "" : "s"} &rarr;
                    </span>
                  </Link>
                </Cell>
                <Cell>
                  <Badge tone={warehouse.is_active ? "green" : "slate"}>
                    {warehouse.is_active ? "Active" : "Retired"}
                  </Badge>
                </Cell>
                <Cell>
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" onClick={() => openEdit(warehouse)}>
                      Edit
                    </Button>
                    {warehouse.is_active ? (
                      <Button
                        variant="danger"
                        // The server refuses this for the last active warehouse;
                        // disabling it here means the admin never has to meet
                        // that error to learn the rule.
                        disabled={busy || activeCount <= 1}
                        onClick={() =>
                          void run(
                            () =>
                              post(`/admin/warehouses/${warehouse.id}/active`, {
                                enabled: false,
                              }),
                            `${warehouse.name} retired. Its stock and shipped allocations are untouched.`,
                          )
                        }
                      >
                        Retire
                      </Button>
                    ) : (
                      <Button
                        variant="success"
                        disabled={busy}
                        onClick={() =>
                          void run(
                            () =>
                              post(`/admin/warehouses/${warehouse.id}/active`, { enabled: true }),
                            `${warehouse.name} restored.`,
                          )
                        }
                      >
                        Restore
                      </Button>
                    )}
                  </div>
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Retiring never deletes. Stock rows and every shipped allocation point at the warehouse
            they came from, so removing one would either cascade away real inventory or leave the
            fulfillment history unable to say where an order shipped from. The last active warehouse
            cannot be retired — with none active, the splitter backorders every line of every order.
          </Note>
        </div>
      </Card>
    </>
  );
}
