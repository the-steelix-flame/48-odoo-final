"""Invoices & payments (screens 12, 13).  Owner: anubhaw0raj."""

from datetime import date, datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import internal_auth, require_role
from apps.billing import services
from apps.billing.models import Invoice
from apps.common.enums import InvoiceStatus, Role
from apps.common.errors import NotFound

router = Router(auth=internal_auth)


class InvoiceRowOut(Schema):
    id: int
    number: str
    customer_id: int
    customer_name: str
    invoice_type: str
    status: str
    issue_date: date
    due_date: date
    currency: str
    total: Decimal
    amount_paid: Decimal
    amount_due: Decimal

    @staticmethod
    def resolve_customer_name(obj) -> str:
        return obj.customer.name


class InvoiceLineOut(Schema):
    id: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal
    tax_percent: Decimal
    line_total: Decimal


class PaymentOut(Schema):
    id: int
    amount: Decimal
    method: str
    reference: str
    paid_at: datetime
    recorded_by_name: str | None = None

    @staticmethod
    def resolve_recorded_by_name(obj) -> str | None:
        return (obj.recorded_by.full_name or obj.recorded_by.email) if obj.recorded_by_id else None


class InvoiceDetailOut(InvoiceRowOut):
    quotation_id: int | None = None
    quotation_number: str | None = None
    subscription_id: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    subtotal: Decimal
    tax_total: Decimal
    lines: list[InvoiceLineOut]
    payments: list[PaymentOut]
    #: Drives the Order Confirmed → Shipped → Invoiced → Paid stepper.
    lifecycle: list[dict]

    @staticmethod
    def resolve_quotation_number(obj) -> str | None:
        return obj.quotation.number if obj.quotation_id else None


class PaymentIn(Schema):
    amount: Decimal
    method: str = "BANK_TRANSFER"
    reference: str = ""


def _get(invoice_id: int) -> Invoice:
    try:
        return Invoice.objects.select_related("customer", "quotation").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        raise NotFound("Invoice not found")


def _lifecycle(invoice: Invoice) -> list[dict]:
    """Reconciliation state: nothing is billed before it ships."""
    quotation = invoice.quotation
    shipped = False
    if quotation:
        plan = quotation.fulfillment_plans.first()
        shipped = bool(
            plan and not plan.allocations.filter(shipped_at__isnull=True, is_backorder=False).exists()
        )
    return [
        {"label": "Order Confirmed", "done": quotation is not None},
        {"label": "Shipped", "done": shipped},
        {"label": "Invoiced", "done": True},
        {"label": "Paid", "done": invoice.status == InvoiceStatus.PAID},
    ]


@router.get("/invoices", response=list[InvoiceRowOut])
def list_invoices(request, status: str | None = None, customer_id: int | None = None):
    qs = Invoice.objects.select_related("customer")
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    return list(qs)


@router.get("/invoices/counts")
def invoice_counts(request):
    """The two chips at the top of screen 12."""
    qs = Invoice.objects.all()
    return {
        "unpaid": qs.filter(
            status__in=[InvoiceStatus.OPEN, InvoiceStatus.PARTIALLY_PAID]
        ).count(),
        "paid": qs.filter(status=InvoiceStatus.PAID).count(),
    }


@router.get("/invoices/{invoice_id}", response=InvoiceDetailOut)
def get_invoice(request, invoice_id: int):
    invoice = _get(invoice_id)
    data = {f: getattr(invoice, f) for f in (
        "id", "number", "customer_id", "invoice_type", "status", "issue_date", "due_date",
        "currency", "total", "amount_paid", "quotation_id", "subscription_id",
        "period_start", "period_end", "subtotal", "tax_total",
    )}
    data.update(
        customer_name=invoice.customer.name,
        amount_due=invoice.amount_due,
        quotation_number=invoice.quotation.number if invoice.quotation_id else None,
        lines=list(invoice.lines.all()),
        payments=list(invoice.payments.select_related("recorded_by")),
        lifecycle=_lifecycle(invoice),
    )
    return data


@router.post("/invoices/{invoice_id}/payments", response=InvoiceDetailOut)
def record_payment(request, invoice_id: int, payload: PaymentIn):
    """Record Payment — screen 13's green button."""
    require_role(request, Role.FINANCE, Role.SALES_MANAGER)
    services.record_payment(
        _get(invoice_id),
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        actor=request.auth,
    )
    return get_invoice(request, invoice_id)
