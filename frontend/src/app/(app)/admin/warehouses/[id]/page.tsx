"use client";

/**
 * Warehouse detail — what this depot stocks.  Owner: anubhaw0raj.
 *
 * Warehouse Management listed depots and the catalogue listed products, and
 * nothing joined the two. Stock is per (warehouse, product), so a product with
 * no row at a warehouse is not "zero stock" there — it is invisible to the
 * splitter entirely. That meant the catalogue could grow without any of it
 * becoming shippable, and the only fix was the Django admin.
 *
 * This screen is that join: every product the warehouse holds, what is on hand,
 * what is already promised to accepted plans, and the reorder trigger — all
 * editable in place, plus a picker to start stocking something new.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { useParams } from "next/navigation";

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
  StatCard,
  Table,
  inputClass,
} from "@/components/ui";
import { money } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Product, Warehouse } from "@/types";

/**
 * `/fulfillment/warehouses/{id}/stock`. Declared here rather than in
 * `types/index.ts` because that file is shared — a local type keeps this
 * feature out of everyone else's merge.
 */
interface StockRowFull {
  id: number;
  warehouse_id: number;
  warehouse_name: string;
  product_id: number;
  product_name: string;
  product_sku: string;
  category_name: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  available: number;
  needs_replenishment: boolean;
  reorder_point: number;
  reorder_quantity: number;
}

const BLANK_ADD = { product_id: "", quantity: "0", reorder_point: "0", reorder_quantity: "0" };

export default function WarehouseDetailPage() {
  const params = useParams<{ id: string }>();
  const warehouseId = Number(params.id);

  const warehouses = useApi<Warehouse[]>("/admin/warehouses");
  const stock = useApi<StockRowFull[]>(`/fulfillment/warehouses/${warehouseId}/stock`);
  const products = useApi<Product[]>("/catalog/products");

  const [adding, setAdding] = useState(false);
  const [addForm, setAddForm] = useState({ ...BLANK_ADD });
  /** id of the stock row open for editing, or null. */
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({
    quantity_on_hand: "",
    reorder_point: "",
    reorder_quantity: "",
  });
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const rows = useMemo(() => stock.data ?? [], [stock.data]);

  /**
   * Only products this warehouse does not already stock, and never a
   * subscription — those are billed, not shipped, and the server refuses them.
   * Filtering here means the picker cannot offer a choice that would fail.
   */
  const stockable = useMemo(() => {
    const held = new Set(rows.map((r) => r.product_id));
    return (products.data ?? [])
      .filter((p) => !p.is_subscription && !held.has(p.id))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [products.data, rows]);

  const warehouse = (warehouses.data ?? []).find((w) => w.id === warehouseId);

  if (warehouses.loading || stock.loading) return <Loading />;
  if (stock.error)
    return <ErrorState message={stock.error.message} onRetry={() => void stock.reload()} />;
  if (!warehouse) return <ErrorState message="That warehouse does not exist." />;

  const unitsOnHand = rows.reduce((sum, r) => sum + r.quantity_on_hand, 0);
  const unitsAvailable = rows.reduce((sum, r) => sum + r.available, 0);
  const lowCount = rows.filter((r) => r.needs_replenishment).length;

  async function run(fn: () => Promise<unknown>, message: string) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      await fn();
      await stock.reload();
      await warehouses.reload();
      setNotice(message);
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "Something went wrong");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function addProduct(event: React.FormEvent) {
    event.preventDefault();
    if (!addForm.product_id) return;
    const name = stockable.find((p) => p.id === Number(addForm.product_id))?.name ?? "Product";
    const ok = await run(
      () =>
        post(`/fulfillment/warehouses/${warehouseId}/stock`, {
          product_id: Number(addForm.product_id),
          quantity: Number(addForm.quantity || 0),
          reorder_point: Number(addForm.reorder_point || 0),
          reorder_quantity: Number(addForm.reorder_quantity || 0),
        }),
      `${name} is now stocked at ${warehouse?.name}.`,
    );
    if (ok) {
      setAddForm({ ...BLANK_ADD });
      setAdding(false);
    }
  }

  function openEdit(row: StockRowFull) {
    setEditForm({
      quantity_on_hand: String(row.quantity_on_hand),
      reorder_point: String(row.reorder_point),
      reorder_quantity: String(row.reorder_quantity),
    });
    setEditingId(row.id);
    setActionError(null);
  }

  async function saveEdit(row: StockRowFull) {
    const ok = await run(
      () =>
        patch(`/fulfillment/stock/${row.id}`, {
          quantity_on_hand: Number(editForm.quantity_on_hand),
          reorder_point: Number(editForm.reorder_point),
          reorder_quantity: Number(editForm.reorder_quantity),
        }),
      `${row.product_name} updated.`,
    );
    if (ok) setEditingId(null);
  }

  return (
    <>
      <PageHeader
        title={warehouse.name}
        subtitle={`${warehouse.code} · ${warehouse.address || "no address set"} · ${money(
          warehouse.base_shipment_cost,
        )} per shipment · ${warehouse.lead_time_days}d lead time`}
        actions={
          <div className="flex gap-2">
            <Link
              href="/admin/warehouses"
              className="rounded-lg border border-edge px-4 py-2 text-sm text-[#334155] hover:bg-surface"
            >
              All warehouses
            </Link>
            <Button
              onClick={() => {
                setAdding((open) => !open);
                setActionError(null);
              }}
              disabled={stockable.length === 0 && !adding}
            >
              {adding ? "Cancel" : "+ Add product"}
            </Button>
          </div>
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

      <div className="mb-6 grid gap-4 md:grid-cols-4">
        <StatCard label="Products" value={rows.length} hint="Distinct SKUs held here" />
        <StatCard label="Units on hand" value={unitsOnHand} hint="Counted, before reservations" />
        <StatCard
          label="Available"
          value={unitsAvailable}
          hint="On hand minus what is promised"
        />
        <StatCard
          label="At or below reorder"
          value={lowCount}
          hint="Available has reached the trigger"
          tone={lowCount > 0 ? "red" : "slate"}
        />
      </div>

      {/* ---------------------------------------- add a product */}
      {adding && (
        <div className="mb-6">
          <Card title="Stock a new product here">
            <form onSubmit={addProduct}>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <Field label="Product" hint="Only products this depot does not already hold.">
                  <select
                    className={inputClass}
                    value={addForm.product_id}
                    onChange={(e) =>
                      setAddForm((f) => ({ ...f, product_id: e.target.value }))
                    }
                    required
                  >
                    <option value="">Choose a product…</option>
                    {stockable.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.category_name}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Opening quantity" hint="Written to the ledger as a restock.">
                  <input
                    type="number"
                    min="0"
                    className={inputClass}
                    value={addForm.quantity}
                    onChange={(e) => setAddForm((f) => ({ ...f, quantity: e.target.value }))}
                    required
                  />
                </Field>
                <Field label="Reorder point" hint="Flag the row when available drops to this.">
                  <input
                    type="number"
                    min="0"
                    className={inputClass}
                    value={addForm.reorder_point}
                    onChange={(e) => setAddForm((f) => ({ ...f, reorder_point: e.target.value }))}
                    required
                  />
                </Field>
                <Field label="Reorder quantity" hint="How much to bring in when it does.">
                  <input
                    type="number"
                    min="0"
                    className={inputClass}
                    value={addForm.reorder_quantity}
                    onChange={(e) =>
                      setAddForm((f) => ({ ...f, reorder_quantity: e.target.value }))
                    }
                    required
                  />
                </Field>
              </div>
              <div className="mt-5">
                <Button type="submit" disabled={busy || !addForm.product_id}>
                  {busy ? "Saving…" : "Add to this warehouse"}
                </Button>
              </div>
            </form>
            <div className="mt-4">
              <Note>
                Subscriptions are not offered: they are billed on a schedule, never boxed, so they
                hold no stock anywhere. The server refuses them too.
              </Note>
            </div>
          </Card>
        </div>
      )}

      {/* ---------------------------------------- what it stocks */}
      <Card title="Products stocked here">
        {rows.length === 0 ? (
          <EmptyState
            title="This warehouse holds nothing yet"
            hint="Until it stocks something, the splitter can never choose it — add a product above."
          />
        ) : (
          <Table
            columns={[
              "Product",
              "Category",
              "On hand",
              "Reserved",
              "Available",
              "Reorder at",
              "Reorder qty",
              "Status",
              "Actions",
            ]}
          >
            {rows.map((row) =>
              editingId === row.id ? (
                <Row key={row.id}>
                  <Cell className="font-medium text-[#0F172A]">
                    {row.product_name}
                    <span className="ml-2 font-mono text-xs text-slate-500">{row.product_sku}</span>
                  </Cell>
                  <Cell className="text-[#64748B]">{row.category_name}</Cell>
                  <Cell>
                    <input
                      type="number"
                      min={row.quantity_reserved}
                      className={`${inputClass} w-[90px]`}
                      value={editForm.quantity_on_hand}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, quantity_on_hand: e.target.value }))
                      }
                    />
                  </Cell>
                  {/* Reserved is never editable: those units are already promised
                      to accepted plans, and the reservation ledger owns them. */}
                  <Cell className="text-[#64748B]">{row.quantity_reserved}</Cell>
                  <Cell className="text-[#64748B]">
                    {Number(editForm.quantity_on_hand || 0) - row.quantity_reserved}
                  </Cell>
                  <Cell>
                    <input
                      type="number"
                      min="0"
                      className={`${inputClass} w-[80px]`}
                      value={editForm.reorder_point}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, reorder_point: e.target.value }))
                      }
                    />
                  </Cell>
                  <Cell>
                    <input
                      type="number"
                      min="0"
                      className={`${inputClass} w-[80px]`}
                      value={editForm.reorder_quantity}
                      onChange={(e) =>
                        setEditForm((f) => ({ ...f, reorder_quantity: e.target.value }))
                      }
                    />
                  </Cell>
                  <Cell>—</Cell>
                  <Cell>
                    <div className="flex flex-wrap gap-2">
                      <Button disabled={busy} onClick={() => void saveEdit(row)}>
                        {busy ? "Saving…" : "Save"}
                      </Button>
                      <Button variant="secondary" onClick={() => setEditingId(null)}>
                        Cancel
                      </Button>
                    </div>
                  </Cell>
                </Row>
              ) : (
                <Row key={row.id}>
                  <Cell className="font-medium text-[#0F172A]">
                    <Link
                      href={`/products/${row.product_id}`}
                      className="hover:text-[#0891B2] hover:underline"
                    >
                      {row.product_name}
                    </Link>
                    <span className="ml-2 font-mono text-xs text-slate-500">{row.product_sku}</span>
                  </Cell>
                  <Cell className="text-[#64748B]">{row.category_name}</Cell>
                  <Cell className="text-[#334155]">{row.quantity_on_hand}</Cell>
                  <Cell className="text-[#64748B]">{row.quantity_reserved}</Cell>
                  <Cell className="font-medium text-[#0F172A]">{row.available}</Cell>
                  <Cell className="text-[#64748B]">{row.reorder_point}</Cell>
                  <Cell className="text-[#64748B]">{row.reorder_quantity}</Cell>
                  <Cell>
                    {row.needs_replenishment ? (
                      <Badge tone="red">Reorder</Badge>
                    ) : (
                      <Badge tone="green">In stock</Badge>
                    )}
                  </Cell>
                  <Cell>
                    <Button variant="secondary" onClick={() => openEdit(row)}>
                      Edit
                    </Button>
                  </Cell>
                </Row>
              ),
            )}
          </Table>
        )}

        <div className="mt-4 space-y-2">
          <Note>
            Changing on hand writes a signed adjustment to the stock ledger rather than overwriting
            the number, so the level can always be explained by its own history. It cannot be cut
            below the reserved column — those units are already promised to accepted plans, and
            allowing it would let the splitter commit the same stock twice.
          </Note>
          <Note>
            A product with no row here is not zero stock at this depot — it is invisible to the
            splitter here, and will never be allocated from it.
          </Note>
        </div>
      </Card>
    </>
  );
}
