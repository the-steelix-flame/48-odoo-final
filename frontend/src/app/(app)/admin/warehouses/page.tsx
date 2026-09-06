"use client";

/**
 * Warehouse Management.  Owner: the-steelix-flame.
 *
 * Warehouses could previously only be created by `seed_demo` or the Django
 * admin, so an operator could not add a depot at all — and a warehouse is what
 * the fulfillment splitter is allowed to consider, which makes defining one an
 * admin act rather than an operational one.
 *
 * Phase 1 of PLAN-distance-fulfillment.md. The coordinate fields are captured
 * here but nothing ranks by them yet: `planner.py` still sorts warehouses by
 * the static `shipping_cost_weight`, which is the same for every destination.
 */

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
  latitude: "",
  longitude: "",
  shipping_cost_weight: "1",
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
      latitude: warehouse.latitude ?? "",
      longitude: warehouse.longitude ?? "",
      shipping_cost_weight: warehouse.shipping_cost_weight,
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
    const payload = {
      name: form.name,
      code: form.code,
      address: form.address,
      // Empty means "no coordinate", not "parse this empty string". The server
      // takes both or neither and refuses half a pair.
      latitude: form.latitude.trim() || null,
      longitude: form.longitude.trim() || null,
      shipping_cost_weight: form.shipping_cost_weight,
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
                <Field
                  label="Address"
                  hint="Where the depot physically is. Used to measure the distance to a customer."
                >
                  <input
                    className={inputClass}
                    value={form.address}
                    onChange={(e) => set("address", e.target.value)}
                    placeholder="12 Dock Road, Kolkata"
                  />
                </Field>
                <Field
                  label="Latitude"
                  hint="Optional — filled automatically from the address later."
                >
                  <input
                    className={inputClass}
                    value={form.latitude}
                    onChange={(e) => set("latitude", e.target.value)}
                    placeholder="22.5726"
                  />
                </Field>
                <Field label="Longitude" hint="Give both or neither.">
                  <input
                    className={inputClass}
                    value={form.longitude}
                    onChange={(e) => set("longitude", e.target.value)}
                    placeholder="88.3639"
                  />
                </Field>
                <Field
                  label="Cost weight"
                  hint="Multiplier the splitter ranks by today. Main 1.0, remote 1.4."
                >
                  <input
                    type="number"
                    step="0.1"
                    min="0.1"
                    className={inputClass}
                    value={form.shipping_cost_weight}
                    onChange={(e) => set("shipping_cost_weight", e.target.value)}
                    required
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
                Coordinates are optional and nothing reads them yet — the splitter still ranks
                warehouses by cost weight, which is identical for every customer. Capturing them now
                is what lets distance-based allocation land without another migration.
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
              "Cost weight",
              "Shipment cost",
              "Lead time",
              "Stock",
              "Status",
              "Actions",
            ]}
          >
            {warehouses.map((warehouse) => (
              <Row key={warehouse.id}>
                <Cell className="font-medium text-slate-100">
                  {warehouse.name}
                  <span className="ml-2 font-mono text-xs text-slate-500">{warehouse.code}</span>
                </Cell>
                <Cell className="max-w-[240px] text-slate-400">
                  {warehouse.address || <span className="text-slate-500">Not set</span>}
                  {/* An address with no point is not yet a location — say so,
                      rather than letting it look ready for the planner. */}
                  {warehouse.address && !warehouse.has_coordinates && (
                    <span className="mt-[2px] block text-[11px] text-[#D97706]">
                      Not located yet
                    </span>
                  )}
                  {warehouse.has_coordinates && (
                    <span className="mt-[2px] block font-mono text-[11px] text-slate-500">
                      {warehouse.latitude}, {warehouse.longitude}
                    </span>
                  )}
                </Cell>
                <Cell className="font-mono text-slate-400">{warehouse.shipping_cost_weight}</Cell>
                <Cell className="text-slate-400">{money(warehouse.base_shipment_cost)}</Cell>
                <Cell className="text-slate-400">{warehouse.lead_time_days}d</Cell>
                <Cell className="text-slate-400">
                  {warehouse.units_on_hand} units
                  <span className="block text-[11px] text-slate-500">
                    {warehouse.stock_line_count} product
                    {warehouse.stock_line_count === 1 ? "" : "s"}
                  </span>
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
