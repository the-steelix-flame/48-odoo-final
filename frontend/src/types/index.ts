/**
 * The frontend ↔ backend contract.  Owner: sinjeki.
 *
 * These enums mirror `backend/apps/common/enums.py` EXACTLY. If you rename one
 * there, rename it here in the same commit — a mismatch fails silently and
 * costs twenty minutes to find.
 *
 * Additive changes only. If you need a new field, add it; don't restructure
 * someone else's type.
 */

// ---------------------------------------------------------------- enums
export type Role = "ADMIN" | "SALES_REP" | "SALES_MANAGER" | "FINANCE" | "CUSTOMER";
export type CustomerTier = "BRONZE" | "SILVER" | "GOLD";

export type QuotationStatus =
  | "DRAFT"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "SENT"
  | "UNDER_NEGOTIATION"
  | "CONFIRMED"
  | "REJECTED"
  | "CANCELLED";

export type LineType = "ONE_TIME" | "RECURRING";
export type RiskBand = "NONE" | "MEDIUM" | "HIGH";
export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED" | "RETURNED" | "SKIPPED";
export type InvoiceStatus = "DRAFT" | "OPEN" | "PARTIALLY_PAID" | "PAID" | "VOID";
export type InvoiceType = "ONE_TIME" | "RECURRING" | "PRORATION";
export type SubscriptionStatus = "ACTIVE" | "PAUSED" | "CANCELLED";
export type AlertType = "STALLED" | "DISCOUNT_ANOMALY" | "DELIVERY_SLIPPAGE";
export type AlertSeverity = "LOW" | "MEDIUM" | "HIGH";
export type FulfillmentStatus =
  | "SUGGESTED"
  | "ACCEPTED"
  | "OVERRIDDEN"
  | "PARTIALLY_SHIPPED"
  | "SHIPPED"
  | "BACKORDER";

export const INTERNAL_ROLES: Role[] = ["ADMIN", "SALES_REP", "SALES_MANAGER", "FINANCE"];

/** Kanban columns on screen 3, in order. */
export const PIPELINE_STAGES: { status: QuotationStatus; label: string }[] = [
  { status: "DRAFT", label: "Draft" },
  { status: "PENDING_APPROVAL", label: "Pending Approval" },
  { status: "APPROVED", label: "Approved" },
  { status: "UNDER_NEGOTIATION", label: "Negotiation" },
  { status: "CONFIRMED", label: "Confirmed" },
];

// ---------------------------------------------------------------- accounts
export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  sales_team_id?: number | null;
  sales_team_name?: string | null;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface Customer {
  id: number;
  name: string;
  tier: CustomerTier;
  currency: string;
  contact_email: string;
  owner_rep_id?: number | null;
  default_price_list_id?: number | null;
}

// ---------------------------------------------------------------- catalog
export interface Category {
  id: number;
  name: string;
  code: string;
}

export interface Product {
  id: number;
  name: string;
  sku: string;
  category_id: number;
  category_name: string;
  description: string;
  unit: string;
  base_price: string;
  tax_percent: string;
  is_subscription: boolean;
  recurring_plan_id?: number | null;
  is_promoted: boolean;
  is_active: boolean;
  variant_count: number;
  quantity_on_hand: number;
}

export interface ProductDetail extends Product {
  cost_price: string;
  margin_percent: string;
}

export interface UpsellSuggestion {
  product_id: number;
  product_name: string;
  unit_price: string;
  margin_delta: string;
  score: number;
  is_promoted: boolean;
  promo_label?: string | null;
}

// ---------------------------------------------------------------- governance
export interface TierCeiling {
  id: number;
  tier: CustomerTier;
  max_discount_percent: string;
}

export interface CategoryCeiling {
  id: number;
  category_id: number;
  category_name: string;
  max_discount_percent: string;
}

export interface ApprovalRule {
  id: number;
  name: string;
  band: RiskBand;
  min_score: string;
  max_score: string;
  required_roles: Role[];
  sequence: number;
  is_active: boolean;
}

export interface GovernanceConfig {
  tier_ceilings: TierCeiling[];
  category_ceilings: CategoryCeiling[];
  approval_rules: ApprovalRule[];
  risk_config: Record<string, string>;
}

// ---------------------------------------------------------------- quotations
export interface QuotationLine {
  id: number;
  product_id: number;
  variant_id?: number | null;
  line_type: LineType;
  description: string;
  category_name: string;
  quantity: string;
  unit_price: string;
  discount_percent: string;
  /** min(tier ceiling, category ceiling) — the limit THIS line is judged against. */
  allowed_discount_percent: string;
  /** max(0, given − allowed). Drives the `OVER (+8pt)` badge. */
  discount_excess_points: string;
  is_over_limit: boolean;
  tax_percent: string;
  line_subtotal: string;
  line_total: string;
  margin_amount: string;
}

export interface LineRisk {
  line_id: number | null;
  label: string;
  discount_percent: string;
  allowed_percent: string;
  excess_points: string;
  weight: string;
  is_over: boolean;
}

export interface RiskBreakdown {
  score: string;
  band: RiskBand;
  requires_approval: boolean;
  worst_line_excess: string;
  blended_excess: string;
  order_level_excess: string;
  effective_order_discount: string;
  /** Human sentence for screen 6's "Why This Quote Was Flagged". */
  explanation: string;
  lines: LineRisk[];
}

export interface QuotationEvent {
  id: number;
  event_type: string;
  actor_name: string;
  note: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface QuotationSummary {
  id: number;
  number: string;
  customer_id: number;
  customer_name: string;
  customer_tier: CustomerTier;
  owner_rep_id: number;
  owner_rep_name: string;
  status: QuotationStatus;
  currency: string;
  total: string;
  margin_percent: string;
  blended_risk_score: string;
  risk_band: RiskBand;
  requires_approval: boolean;
  idle_days: number;
  created_at: string;
  last_activity_at: string;
}

/**
 * Returned by EVERY quotation mutation, fully recomputed by the backend.
 * The frontend never calculates money or risk — it renders this.
 */
export interface QuotationDetail extends QuotationSummary {
  order_discount_percent: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  margin_amount: string;
  price_list_id?: number | null;
  lines: QuotationLine[];
  risk: RiskBreakdown;
  events: QuotationEvent[];
}

// ---------------------------------------------------------------- approvals
export interface ApprovalStep {
  id: number;
  sequence: number;
  role_required: Role;
  assignee_name?: string | null;
  status: ApprovalStatus;
  decision_note: string;
  acted_by_name?: string | null;
  acted_at?: string | null;
}

export interface ApprovalRow {
  id: number;
  quotation_id: number;
  quotation_number: string;
  customer_name: string;
  customer_tier: CustomerTier;
  risk_score: string;
  risk_band: RiskBand;
  status: ApprovalStatus;
  current_stage?: Role | null;
  assigned_to?: string | null;
  created_at: string;
}

export interface ApprovalDetail extends ApprovalRow {
  reason: string;
  steps: ApprovalStep[];
  risk: RiskBreakdown;
  audit_trail: QuotationEvent[];
}

// ---------------------------------------------------------------- fulfillment
export interface Warehouse {
  id: number;
  name: string;
  code: string;
  shipping_cost_weight: string;
  base_shipment_cost: string;
  is_active: boolean;
}

export interface StockRow {
  id: number;
  warehouse_id: number;
  warehouse_name: string;
  product_id: number;
  product_name: string;
  quantity_on_hand: number;
  quantity_reserved: number;
  available: number;
  needs_replenishment: boolean;
}

export interface OrderAwaiting {
  quotation_id: number;
  quotation_number: string;
  customer_name: string;
  status: string;
  warehouses: string;
  plan_id?: number | null;
}

export interface Allocation {
  id: number;
  quotation_line_id: number;
  line_description: string;
  warehouse_id: number;
  warehouse_name: string;
  quantity: number;
  is_backorder: boolean;
  promised_date?: string | null;
  shipped_at?: string | null;
}

export interface FulfillmentPlan {
  id: number;
  quotation_id: number;
  quotation_number: string;
  customer_name: string;
  status: FulfillmentStatus;
  estimated_shipments: number;
  estimated_cost: string;
  is_manual_override: boolean;
  /** True once a restock makes an open backorder fillable. */
  consolidation_available: boolean;
  allocations: Allocation[];
}

// ---------------------------------------------------------------- subscriptions
export interface RecurringPlanT {
  id: number;
  name: string;
  interval: string;
  proration_mode: string;
  cancellation_policy: string;
  refund_mode: string;
  bill_in_advance: boolean;
  is_active: boolean;
}

export interface SubscriptionRow {
  id: number;
  customer_id: number;
  customer_name: string;
  plan_id: number;
  plan_name: string;
  interval: string;
  status: SubscriptionStatus;
  quantity: string;
  unit_price: string;
  period_amount: string;
  next_bill_date?: string | null;
}

export interface SubscriptionEvent {
  id: number;
  event_type: string;
  effective_date: string;
  old_quantity?: string | null;
  new_quantity?: string | null;
  /** Signed: positive was invoiced, negative became a credit note. */
  proration_amount: string;
  invoice_id?: number | null;
  credit_note_id?: number | null;
  note: string;
  created_at: string;
}

export interface BillingDetail extends SubscriptionRow {
  quotation_id?: number | null;
  quotation_number?: string | null;
  current_period_start: string;
  current_period_end: string;
  one_time_lines: { description: string; quantity: string; line_total: string }[];
  upcoming_bills: { period_start: string; period_end: string; amount: string }[];
  events: SubscriptionEvent[];
}

// ---------------------------------------------------------------- billing
export interface InvoiceRow {
  id: number;
  number: string;
  customer_id: number;
  customer_name: string;
  invoice_type: InvoiceType;
  status: InvoiceStatus;
  issue_date: string;
  due_date: string;
  currency: string;
  total: string;
  amount_paid: string;
  amount_due: string;
}

export interface InvoiceDetail extends InvoiceRow {
  quotation_id?: number | null;
  quotation_number?: string | null;
  subscription_id?: number | null;
  period_start?: string | null;
  period_end?: string | null;
  subtotal: string;
  tax_total: string;
  lines: {
    id: number;
    description: string;
    quantity: string;
    unit_price: string;
    discount_percent: string;
    tax_percent: string;
    line_total: string;
  }[];
  payments: {
    id: number;
    amount: string;
    method: string;
    reference: string;
    paid_at: string;
    recorded_by_name?: string | null;
  }[];
  lifecycle: { label: string; done: boolean }[];
}

// ---------------------------------------------------------------- insights
export interface DashboardData {
  pending_approvals: number;
  open_quotations: number;
  at_risk_deals: number;
  recent_activity: { quotation_id: number; text: string; at: string }[];
}

export interface DealAlert {
  id: number;
  quotation_id: number;
  quotation_number: string;
  customer_name: string;
  alert_type: AlertType;
  severity: AlertSeverity;
  message: string;
  status: string;
  detected_at: string;
}

export interface DealHealth {
  stalled_count: number;
  anomaly_count: number;
  slippage_count: number;
  alerts: DealAlert[];
}

export interface ReportData {
  quotes_created: number;
  quotes_value: string;
  avg_approval_hours: number;
  top_upsold_product?: string | null;
  by_status: Record<string, unknown>[];
  by_rep: Record<string, unknown>[];
  by_category: Record<string, unknown>[];
}

// ---------------------------------------------------------------- portal
export interface PortalLine {
  id: number;
  description: string;
  quantity: string;
  unit_price: string;
  discount_percent: string;
  line_total: string;
  // NOTE: no cost, no margin, no risk. The portal serialiser never sends them.
}

export interface PortalMessage {
  id: number;
  quotation_line_id?: number | null;
  line_description?: string | null;
  author_type: "CUSTOMER" | "REP";
  body: string;
  created_at: string;
}

export interface PortalRequest {
  id: number;
  requested_discount_percent?: string | null;
  requested_delivery_date?: string | null;
  message: string;
  status: "SUBMITTED" | "ACCEPTED" | "REJECTED" | "COUNTERED";
  resolution_note: string;
  created_at: string;
}

export interface PortalQuotation {
  id: number;
  number: string;
  status: QuotationStatus;
  currency: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  total: string;
  valid_until?: string | null;
  company_name: string;
  lines: PortalLine[];
  messages: PortalMessage[];
  requests: PortalRequest[];
}
