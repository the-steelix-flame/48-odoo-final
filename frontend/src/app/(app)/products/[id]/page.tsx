"use client";

/** Screen 17 — Product & pricelist detail.  Owner: sinjeki. */

import { use } from "react";

import {
  Badge,
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
import { money, percent } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { GovernanceConfig, ProductDetail } from "@/types";

interface PriceListT {
  id: number;
  name: string;
  tier: string | null;
  currency: string;
  is_active: boolean;
}

export default function ProductDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading, reload } = useApi<ProductDetail>(`/catalog/products/${id}`);
  const { data: priceLists } = useApi<PriceListT[]>("/catalog/price-lists");
  const { data: governance } = useApi<GovernanceConfig>("/governance/config");

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error.message} onRetry={reload} />;
  if (!data) return null;

  const categoryCeiling = governance?.category_ceilings.find(
    (c) => c.category_id === data.category_id,
  );

  return (
    <>
      <PageHeader
        title="Product and pricelist"
        subtitle={`${data.name} · ${data.sku}`}
        actions={<Badge tone={data.is_active ? "green" : "slate"}>{data.is_active ? "Active" : "Archived"}</Badge>}
      />

      <Card title="General Info" className="mb-6">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Field label="Product name">
            <input className={inputClass} defaultValue={data.name} readOnly />
          </Field>
          <Field label="Category">
            <input className={inputClass} defaultValue={data.category_name} readOnly />
          </Field>
          <Field label="Price">
            <input className={inputClass} defaultValue={money(data.base_price)} readOnly />
          </Field>
          <Field label="Unit">
            <input className={inputClass} defaultValue={data.unit} readOnly />
          </Field>
          <Field label="Tax %">
            <input className={inputClass} defaultValue={percent(data.tax_percent, 0)} readOnly />
          </Field>
          <Field label="Quantity on hand" hint="Derived from warehouse stock rows.">
            <input
              className={inputClass}
              defaultValue={data.is_subscription ? "n/a (subscription)" : data.quantity_on_hand}
              readOnly
            />
          </Field>
          <Field label="Subscription">
            <input
              className={inputClass}
              defaultValue={data.is_subscription ? "Yes" : "No"}
              readOnly
            />
          </Field>
          {data.is_subscription && (
            <Field label="Recurring plan">
              <input className={inputClass} defaultValue={`Plan #${data.recurring_plan_id}`} readOnly />
            </Field>
          )}
          <Field label="Margin" hint="Internal only — never sent to the customer portal.">
            <input
              className={inputClass}
              defaultValue={`${percent(data.margin_percent)} (cost ${money(data.cost_price)})`}
              readOnly
            />
          </Field>
        </div>
        <div className="mt-4">
          <Field label="Description">
            <textarea className={inputClass} rows={2} defaultValue={data.description} readOnly />
          </Field>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          title="Product Variants"
          subtitle="Attribute → values → extra price"
        >
          {/* TODO(sinjeki): wire /catalog/products/{id}/variants once the
              variant endpoints land. Seeded variants exist on Laptop Pro 14. */}
          {data.variant_count === 0 ? (
            <EmptyState title="No variants on this product" />
          ) : (
            <Table columns={["Attribute", "Values", "Extra price"]}>
              <Row>
                <Cell>Color</Cell>
                <Cell>Blue, Black</Cell>
                <Cell>+{money(0)}</Cell>
              </Row>
              <Row>
                <Cell>RAM</Cell>
                <Cell>4GB, 8GB</Cell>
                <Cell>+{money(30)}</Cell>
              </Row>
              <Row>
                <Cell>Manufacturer</Cell>
                <Cell>Dell, HP</Cell>
                <Cell>+{money(10)} / +{money(30)}</Cell>
              </Row>
            </Table>
          )}
        </Card>

        <Card title="Pricelists" subtitle="Tier and currency specific rules">
          <Table columns={["Tier", "Currency", "Price rule"]}>
            {(priceLists ?? []).map((list) => (
              <Row key={list.id}>
                <Cell>{list.tier ?? "All tiers"}</Cell>
                <Cell>{list.currency}</Cell>
                <Cell>{list.tier === "GOLD" ? "Price minus 10 percent base" : "Price, no adjustment"}</Cell>
              </Row>
            ))}
          </Table>

          <div className="mt-4 space-y-2">
            {categoryCeiling && (
              <Note>
                Lines of this product are capped at{" "}
                <strong>{percent(categoryCeiling.max_discount_percent, 0)}</strong> by the{" "}
                {data.category_name} category ceiling, or the customer&apos;s tier ceiling —
                whichever is stricter.
              </Note>
            )}
            {data.is_subscription && (
              <Note>
                Recurring orders with this product are invoiced at the beginning of the period.
              </Note>
            )}
          </div>
        </Card>
      </div>
    </>
  );
}
