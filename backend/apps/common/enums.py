"""Every enum in the system, in one place.

These strings are the API contract. `frontend/src/types/index.ts` mirrors them
exactly. If you rename one here, rename it there in the same commit or the demo
breaks in a way that takes twenty minutes to find.
"""

from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Admin"
    SALES_REP = "SALES_REP", "Sales Rep"
    SALES_MANAGER = "SALES_MANAGER", "Sales Manager"
    FINANCE = "FINANCE", "Finance / Operations"
    CUSTOMER = "CUSTOMER", "Customer"


#: Roles allowed into the internal workspace. Everything else goes to /portal.
INTERNAL_ROLES = (Role.ADMIN, Role.SALES_REP, Role.SALES_MANAGER, Role.FINANCE)


class CustomerTier(models.TextChoices):
    BRONZE = "BRONZE", "Bronze"
    SILVER = "SILVER", "Silver"
    GOLD = "GOLD", "Gold"


class QuotationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
    APPROVED = "APPROVED", "Approved"
    SENT = "SENT", "Sent"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION", "Under Negotiation"
    CONFIRMED = "CONFIRMED", "Confirmed"
    REJECTED = "REJECTED", "Rejected"
    CANCELLED = "CANCELLED", "Cancelled"


class LineType(models.TextChoices):
    ONE_TIME = "ONE_TIME", "One-time"
    RECURRING = "RECURRING", "Recurring"


class RiskBand(models.TextChoices):
    NONE = "NONE", "No approval needed"
    MEDIUM = "MEDIUM", "Sales Manager"
    HIGH = "HIGH", "Sales Manager then Finance"


class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    RETURNED = "RETURNED", "Returned for revision"
    SKIPPED = "SKIPPED", "Skipped"


class QuotationEventType(models.TextChoices):
    CREATED = "CREATED", "Created"
    LINE_ADDED = "LINE_ADDED", "Line added"
    LINE_UPDATED = "LINE_UPDATED", "Line updated"
    LINE_REMOVED = "LINE_REMOVED", "Line removed"
    DISCOUNT_CHANGED = "DISCOUNT_CHANGED", "Discount changed"
    UPSELL_ADDED = "UPSELL_ADDED", "Upsell added"
    DRAFT_SAVED = "DRAFT_SAVED", "Draft saved"
    SUBMITTED = "SUBMITTED", "Submitted for approval"
    AUTO_APPROVED = "AUTO_APPROVED", "Auto-approved (within limits)"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    RETURNED = "RETURNED", "Returned for revision"
    SENT_TO_CUSTOMER = "SENT_TO_CUSTOMER", "Sent to customer"
    NEGOTIATION_OPENED = "NEGOTIATION_OPENED", "Negotiation opened"
    COUNTER_RECEIVED = "COUNTER_RECEIVED", "Counter-offer received"
    COUNTER_ACCEPTED = "COUNTER_ACCEPTED", "Counter-offer accepted"
    CONFIRMED = "CONFIRMED", "Confirmed"
    NUDGED = "NUDGED", "Nudged"
    ESCALATED = "ESCALATED", "Escalated"


class StockMoveReason(models.TextChoices):
    RESERVE = "RESERVE", "Reserved for order"
    RELEASE = "RELEASE", "Reservation released"
    SHIP = "SHIP", "Shipped"
    RESTOCK = "RESTOCK", "Restocked"
    ADJUST = "ADJUST", "Manual adjustment"


class FulfillmentStatus(models.TextChoices):
    SUGGESTED = "SUGGESTED", "Split suggested"
    ACCEPTED = "ACCEPTED", "Split accepted"
    OVERRIDDEN = "OVERRIDDEN", "Manually overridden"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED", "Partially shipped"
    SHIPPED = "SHIPPED", "Shipped"
    BACKORDER = "BACKORDER", "Backorder"


class RecurringInterval(models.TextChoices):
    WEEKLY = "WEEKLY", "Weekly"
    MONTHLY = "MONTHLY", "Monthly"
    QUARTERLY = "QUARTERLY", "Quarterly"
    YEARLY = "YEARLY", "Yearly"


class ProrationMode(models.TextChoices):
    DAILY = "DAILY", "Daily pro-rata"
    NONE = "NONE", "No proration"
    FULL_PERIOD = "FULL_PERIOD", "Charge full period"


class CancellationPolicy(models.TextChoices):
    IMMEDIATE = "IMMEDIATE", "Immediate"
    END_OF_PERIOD = "END_OF_PERIOD", "End of current period"


class RefundMode(models.TextChoices):
    PRORATED = "PRORATED", "Prorated refund"
    NONE = "NONE", "No refund"


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    PAUSED = "PAUSED", "Paused"
    CANCELLED = "CANCELLED", "Cancelled"


class SubscriptionEventType(models.TextChoices):
    CREATED = "CREATED", "Created"
    QUANTITY_CHANGED = "QUANTITY_CHANGED", "Quantity changed"
    PLAN_CHANGED = "PLAN_CHANGED", "Plan changed"
    PAUSED = "PAUSED", "Paused"
    RESUMED = "RESUMED", "Resumed"
    CANCELLED = "CANCELLED", "Cancelled"
    RENEWED = "RENEWED", "Renewed"


class InvoiceType(models.TextChoices):
    ONE_TIME = "ONE_TIME", "One-time"
    RECURRING = "RECURRING", "Recurring"
    PRORATION = "PRORATION", "Proration"


class InvoiceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Unpaid"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
    PAID = "PAID", "Paid"
    VOID = "VOID", "Void"


class PaymentMethod(models.TextChoices):
    BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
    CARD = "CARD", "Card"
    CHEQUE = "CHEQUE", "Cheque"
    OTHER = "OTHER", "Other"


class NegotiationRequestStatus(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"
    COUNTERED = "COUNTERED", "Countered"


class AlertType(models.TextChoices):
    STALLED = "STALLED", "Stalled deal"
    DISCOUNT_ANOMALY = "DISCOUNT_ANOMALY", "Discount anomaly"
    DELIVERY_SLIPPAGE = "DELIVERY_SLIPPAGE", "Delivery slippage"


class AlertSeverity(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class AlertStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
    RESOLVED = "RESOLVED", "Resolved"
