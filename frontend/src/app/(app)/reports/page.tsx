"use client";

/** Screen 15 — Admin / reporting dashboard.  Owner: sinjeki. */

import { useState } from "react";

import {
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
  Button,
  inputClass,
} from "@/components/ui";
import { money, titleCase } from "@/lib/format";
import { useApi } from "@/lib/useApi";
import type { Category, QuotationStatus, ReportData, User } from "@/types";

const STATUSES: QuotationStatus[] = [
  "DRAFT",
  "PENDING_APPROVAL",
  "APPROVED",
  "SENT",
  "UNDER_NEGOTIATION",
  "CONFIRMED",
  "REJECTED",
];

export default function ReportsPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [repId, setRepId] = useState("");
  const [status, setStatus] = useState("");
  const [categoryId, setCategoryId] = useState("");

  const query = new URLSearchParams();
  if (dateFrom) query.set("date_from", dateFrom);
  if (dateTo) query.set("date_to", dateTo);
  if (repId) query.set("rep_id", repId);
  if (status) query.set("status", status);
  if (categoryId) query.set("category_id", categoryId);

  const { data, error, loading, reload } = useApi<ReportData>(
    `/insights/reports${query.toString() ? `?${query}` : ""}`,
  );
  const { data: reps } = useApi<User[]>("/auth/users");
  const { data: categories } = useApi<Category[]>("/catalog/categories");

  return (
    <>
      <PageHeader
        title="Reporting Dashboard"
        subtitle="Sales trends, approval bottlenecks and platform usage."
        actions={
          <>
            {/* TODO(sinjeki): server-side PDF/XLS export. A client-side CSV of
                the visible table is an acceptable fallback if time is short. */}
            <Button variant="secondary" disabled>
              Export PDF
            </Button>
            <Button variant="secondary" disabled>
              Export XLS
            </Button>
          </>
        }
      />

      <Card title="Filters" subtitle="Period · Sales rep · Approval status · Category" className="mb-6">
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
          <Field label="From">
            <input
              type="date"
              className={inputClass}
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
            />
          </Field>
          <Field label="To">
            <input
              type="date"
              className={inputClass}
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
            />
          </Field>
          <Field label="Sales rep">
            <select
              className={inputClass}
              value={repId}
              onChange={(e) => setRepId(e.target.value)}
            >
              <option value="">All reps</option>
              {(reps ?? [])
                .filter((user) => user.role !== "CUSTOMER")
                .map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.full_name || user.email}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Approval status">
            <select
              className={inputClass}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="">All statuses</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {titleCase(value)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Category">
            <select
              className={inputClass}
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
            >
              <option value="">All categories</option>
              {(categories ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Card>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={reload} />
      ) : !data ? null : (
        <>
          <div className="mb-6 grid gap-4 md:grid-cols-4">
            <StatCard label="Quotes Created" value={data.quotes_created} hint="Matching the filters" />
            <StatCard label="Pipeline Value" value={money(data.quotes_value)} />
            <StatCard
              label="Avg Approval Time"
              value={`${data.avg_approval_hours} h`}
              hint="Request opened → closed"
            />
            <StatCard
              label="Top Upsold Product"
              value={data.top_upsold_product ?? "—"}
              hint="From the upsell suggestion log"
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="By status">
              {data.by_status.length === 0 ? (
                <EmptyState title="No quotations match these filters" />
              ) : (
                <Table columns={["Status", "Count", "Value"]}>
                  {data.by_status.map((row, index) => (
                    <Row key={index}>
                      <Cell>{titleCase(String(row.status ?? "—"))}</Cell>
                      <Cell>{String(row.count ?? 0)}</Cell>
                      <Cell>{money(String(row.value ?? 0))}</Cell>
                    </Row>
                  ))}
                </Table>
              )}
            </Card>

            <Card title="By rep">
              {data.by_rep.length === 0 ? (
                <EmptyState title="No data" />
              ) : (
                <Table columns={["Rep", "Quotes", "Value"]}>
                  {data.by_rep.map((row, index) => (
                    <Row key={index}>
                      <Cell>{String(row["owner_rep__full_name"] ?? "Unassigned")}</Cell>
                      <Cell>{String(row.count ?? 0)}</Cell>
                      <Cell>{money(String(row.value ?? 0))}</Cell>
                    </Row>
                  ))}
                </Table>
              )}
            </Card>

            <Card title="By category" className="lg:col-span-2">
              {data.by_category.length === 0 ? (
                <EmptyState title="No data" />
              ) : (
                <Table columns={["Category", "Lines", "Value"]}>
                  {data.by_category.map((row, index) => (
                    <Row key={index}>
                      <Cell>
                        {String(row["lines__product__category__name"] ?? "Uncategorised")}
                      </Cell>
                      <Cell>{String(row.count ?? 0)}</Cell>
                      <Cell>{money(String(row.value ?? 0))}</Cell>
                    </Row>
                  ))}
                </Table>
              )}
            </Card>
          </div>

          <div className="mt-6">
            <Note>
              Every figure here is aggregated from the same tables the operational screens read —
              there is no separate reporting copy to drift out of date.
            </Note>
          </div>
        </>
      )}
    </>
  );
}
