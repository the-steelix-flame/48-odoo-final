"use client";

/** Screen 16 — Product Catalog.  Owner: sinjeki. */

import { useRouter } from "next/navigation";

import {
  Badge,
  Card,
  Cell,
  EmptyState,
  ErrorState,
  Loading,
  Note,
  PageHeader,
  Row,
  StatCard,
  Table,
} from "@/components/ui";
import { money, percent } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Category, Product } from "@/types";

export default function ProductsPage() {
  const router = useRouter();
  const { data: products, error, loading, reload } = useApi<Product[]>("/catalog/products");
  const { data: categories } = useApi<Category[]>("/catalog/categories");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;

  const list = products ?? [];
  const variantTotal = list.reduce((sum, p) => sum + p.variant_count, 0);

  return (
    <>
      <PageHeader
        title="Product catalog"
        subtitle="Every product, variant and price list in one place."
      />

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
