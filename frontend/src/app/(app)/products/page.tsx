"use client";

/** Screen 16 — Product Catalog.  Owner: sinjeki. */

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, post } from "@/lib/api";
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
import { money, percent } from "@/lib/format";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/useApi";
import type { Category, Product } from "@/types";

/** Mirrors `ProductIn`. Prices are kept as strings so the inputs stay
 *  controlled and empty means empty, not 0. */
const BLANK = {
  name: "",
  sku: "",
  category_id: "",
  unit: "Each",
  base_price: "",
  cost_price: "",
  tax_percent: "0",
  is_subscription: false,
};

export default function ProductsPage() {
  const router = useRouter();
  const { role } = useAuth();
  const { data: products, error, loading, reload } = useApi<Product[]>("/catalog/products");
  const { data: categories } = useApi<Category[]>("/catalog/categories");

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ ...BLANK });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  // The backend restricts create to ADMIN, so don't offer it to anyone else.
  const canCreate = role === "ADMIN";
  const complete =
    form.name.trim() && form.sku.trim() && form.category_id && form.base_price && form.cost_price;

  async function create() {
    setSaving(true);
    setMessage(null);
    try {
      await post("/catalog/products", {
        name: form.name.trim(),
        sku: form.sku.trim(),
        category_id: Number(form.category_id),
        unit: form.unit,
        base_price: form.base_price,
        cost_price: form.cost_price,
        tax_percent: form.tax_percent || "0",
        is_subscription: form.is_subscription,
      });
      setForm({ ...BLANK });
      setCreating(false);
      setMessage(`Added ${form.name.trim()} to the catalog.`);
      await reload();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not create the product");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const list = products ?? [];
  const variantTotal = list.reduce((sum, p) => sum + p.variant_count, 0);

  return (
    <>
      <PageHeader
        title="Product catalog"
        subtitle="Every product, variant and price list in one place."
        actions={
          canCreate ? (
            <Button
              variant={creating ? "secondary" : "primary"}
              onClick={() => {
                setCreating((value) => !value);
                setMessage(null);
              }}
            >
              {creating ? "Cancel" : "New product"}
            </Button>
          ) : undefined
        }
      />

      {message && (
        <div className="mb-4">
          <Note>{message}</Note>
        </div>
      )}

      {creating && (
        <Card
          title="New product"
          subtitle="Its category decides which discount ceiling the risk engine applies to it"
          className="mb-6"
          actions={
            <Button onClick={create} disabled={saving || !complete}>
              {saving ? "Adding…" : "Add to catalog"}
            </Button>
          }
        >
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            <Field label="Product name">
              <input
                className={inputClass}
                value={form.name}
                placeholder="Laptop Pro 16"
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </Field>
            <Field label="SKU">
              <input
                className={inputClass}
                value={form.sku}
                placeholder="LP-16"
                onChange={(e) => setForm({ ...form, sku: e.target.value })}
              />
            </Field>
            <Field label="Category" hint="Sets the category discount ceiling">
              <select
                className={inputClass}
                value={form.category_id}
                onChange={(e) => setForm({ ...form, category_id: e.target.value })}
              >
                <option value="">Choose…</option>
                {(categories ?? []).map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Unit">
              <input
                className={inputClass}
                value={form.unit}
                onChange={(e) => setForm({ ...form, unit: e.target.value })}
              />
            </Field>
            <Field label="List price">
              <input
                type="number"
                className={inputClass}
                value={form.base_price}
                placeholder="1200.00"
                onChange={(e) => setForm({ ...form, base_price: e.target.value })}
              />
            </Field>
            <Field label="Cost price" hint="Drives the margin bar on the builder">
              <input
                type="number"
                className={inputClass}
                value={form.cost_price}
                placeholder="820.00"
                onChange={(e) => setForm({ ...form, cost_price: e.target.value })}
              />
            </Field>
            <Field label="Tax %">
              <input
                type="number"
                className={inputClass}
                value={form.tax_percent}
                onChange={(e) => setForm({ ...form, tax_percent: e.target.value })}
              />
            </Field>
            <Field label="Recurring" hint="Subscription products bill on a schedule">
              <label className="flex h-[38px] items-center gap-2 text-[13px] text-[#334155]">
                <input
                  type="checkbox"
                  checked={form.is_subscription}
                  onChange={(e) => setForm({ ...form, is_subscription: e.target.checked })}
                />
                Bills recurrently
              </label>
            </Field>
          </div>
        </Card>
      )}

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <StatCard label="Total Products" value={list.length} hint="Active in the catalog" />
        <StatCard
          label="Categories"
          value={categories?.length ?? 0}
          hint="Each carries its own discount ceiling"
        />
        <StatCard label="Variants" value={variantTotal} hint="SKUs across all products" />
      </div>

      <Card title="Products">
        {list.length === 0 ? (
          <EmptyState
            title="No products yet"
            hint="Run `python manage.py seed_demo` in the backend to load the demo catalog."
          />
        ) : (
          <Table
            columns={["Product name", "Category", "Variants", "Price", "Unit", "Tax", "Stock", "Status"]}
          >
            {list.map((product) => (
              <Row key={product.id} onClick={() => router.push(`/products/${product.id}`)}>
                <Cell className="font-heading font-medium text-[#0F172A]">
                  {product.name}
                  {product.is_promoted && (
                    <span className="ml-2">
                      <Badge tone="blue">Promoted</Badge>
                    </span>
                  )}
                </Cell>
                <Cell>{product.category_name}</Cell>
                <Cell>{product.variant_count || "—"}</Cell>
                <Cell>
                  {money(product.base_price)}
                  {product.is_subscription && (
                    <span className="text-[11px] text-[#64748B]">/period</span>
                  )}
                </Cell>
                <Cell>{product.unit}</Cell>
                <Cell>{percent(product.tax_percent, 0)}</Cell>
                <Cell>{product.is_subscription ? "—" : product.quantity_on_hand}</Cell>
                <Cell>
                  <Badge tone={product.is_active ? "green" : "slate"}>
                    {product.is_active ? "Active" : "Archived"}
                  </Badge>
                </Cell>
              </Row>
            ))}
          </Table>
        )}

        <div className="mt-4">
          <Note>
            Click a product row to open general info, variants and tier / currency price lists.
            Stock is derived from warehouse stock rows, never stored on the product — two sources
            of truth is how a fulfillment demo desyncs.
          </Note>
        </div>
      </Card>
    </>
  );
}
