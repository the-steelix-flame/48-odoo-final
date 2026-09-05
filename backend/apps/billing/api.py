"""Invoices & payments (screens 12, 13).  Owner: anubhaw0raj."""

from datetime import date, datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import internal_auth, require_role
from apps.billing import services
from apps.billing.models import Invoice
from apps.common.enums import InvoiceStatus, QuotationStatus, Role
from apps.common.errors import NotFound
from apps.quotations.models import Quotation

router = Router(auth=internal_auth)

#: Invoices and payments belong to Finance, with the Sales Manager able to see
#: the cash position of their team's deals. A Sales Rep sells; what has been
#: billed and collected afterwards is not theirs to see.
VIEW_ROLES = (Role.FINANCE, Role.SALES_MANAGER)


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
        # _detail-style endpoints hand Ninja a plain dict that already carries this
        # value; Ninja passes the RAW dict to the resolver, so attribute access
        # would raise AttributeError and the field would be dropped as "missing".
        if isinstance(obj, dict):
            return obj["customer_name"]
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
        if isinstance(obj, dict):
            return obj.get("recorded_by_name")
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
        if isinstance(obj, dict):
            return obj.get("quotation_number")
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
    """The order lifecycle, in the order it actually happens.

    Confirmed -> invoiced -> paid -> shipped. Shipped used to sit second, which
    read as though goods went out before anyone had been billed and left the
    step permanently grey between two green ones — the customer pays first, and
    despatch is what closes the deal out.
    """
    quotation = invoice.quotation
    shipped = False
    if quotation:
        plan = quotation.fulfillment_plans.first()
        # Every non-backordered line has left the warehouse. A plan with an
        # open backorder is deliberately not "shipped" yet.
        shipped = bool(
            plan
            and not plan.allocations.filter(
                shipped_at__isnull=True, is_backorder=False
            ).exists()
        )
    return [
        {"label": "Order Confirmed", "done": quotation is not None},
        {"label": "Invoiced", "done": True},
        {"label": "Paid", "done": invoice.status == InvoiceStatus.PAID},
        {"label": "Shipped", "done": shipped},
    ]


class DealBillingRowOut(Schema):
    """A confirmed deal and where it stands with billing.

    Drives the Finance worklist: raise the bill, wait for payment, then open
    the invoice. One row per deal so the three states read as one lifecycle
    rather than three unrelated screens.
    """

    quotation_id: int
    quotation_number: str
    customer_name: str
    #: Point 2 of the brief: whose deal this was.
    sales_rep: str
    #: The final closing amount agreed with the customer.
    closing_amount: Decimal
    currency: str
    confirmed_at: datetime
    billing_state: str  # AWAITING_BILL | PAYMENT_PENDING | PAID
    invoice_id: int | None = None
    invoice_number: str | None = None
    invoice_total: Decimal | None = None
    amount_due: Decimal | None = None


@router.get("/deals", response=list[DealBillingRowOut])
def list_deals_for_billing(request):
    """Every confirmed deal, with its billing state."""
    rows = []
    quotations = (
        Quotation.objects.filter(status=QuotationStatus.CONFIRMED)
        .select_related("customer", "owner_rep")
        .order_by("-last_activity_at")
    )
    for quotation in quotations:
        state, invoice = services.billing_state(quotation)
        rows.append(
            {
                "quotation_id": quotation.id,
                "quotation_number": quotation.number,
                "customer_name": quotation.customer.name,
                "sales_rep": quotation.owner_rep.full_name or quotation.owner_rep.email,
                "closing_amount": quotation.total,
                "currency": quotation.currency,
                "confirmed_at": quotation.last_activity_at,
                "billing_state": state,
                "invoice_id": invoice.id if invoice else None,
                "invoice_number": invoice.number if invoice else None,
                "invoice_total": invoice.total if invoice else None,
                "amount_due": invoice.amount_due if invoice else None,
            }
        )
    return rows


@router.post("/quotations/{quotation_id}/bill", response=InvoiceDetailOut)
def raise_bill(request, quotation_id: int):
    """Accept the final deal and raise its bill."""
    require_role(request, Role.FINANCE, Role.SALES_MANAGER)
    try:
        quotation = Quotation.objects.select_related("customer", "owner_rep").get(
            pk=quotation_id
        )
    except Quotation.DoesNotExist:
        raise NotFound("Quotation not found")
    invoice = services.raise_bill_for_quotation(quotation, actor=request.auth)
    return get_invoice(request, invoice.id)


@router.get("/invoices", response=list[InvoiceRowOut])
def list_invoices(request, status: str | None = None, customer_id: int | None = None):
    require_role(request, *VIEW_ROLES)
    qs = Invoice.objects.select_related("customer")
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    return list(qs)


@router.get("/invoices/counts")
def invoice_counts(request):
    require_role(request, *VIEW_ROLES)
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
    require_role(request, *VIEW_ROLES)
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
