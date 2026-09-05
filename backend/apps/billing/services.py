"""Invoicing, payments and credit notes.  Owner: anubhaw0raj."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import CreditNote, Invoice, InvoiceLine, Payment
from apps.common.enums import InvoiceStatus, InvoiceType, LineType
from apps.common.errors import ValidationError
from apps.quotations.models import Quotation

ZERO = Decimal("0")
HUNDRED = Decimal("100")
DEFAULT_TERMS_DAYS = 30


def _next_number(model, prefix: str, start: int) -> str:
    last = model.objects.order_by("-id").values_list("number", flat=True).first()
    seq = int(last.split("-")[1]) + 1 if last and "-" in last else start
    return f"{prefix}-{seq}"


@transaction.atomic
def issue_one_time_invoice(quotation: Quotation, *, actor=None) -> Invoice | None:
    """Bill the ONE_TIME lines of a confirmed order.

    Returns None when the order is subscription-only — that's a legitimate
    outcome, not an error.
    """
    lines = list(quotation.lines.filter(line_type=LineType.ONE_TIME))
    if not lines:
        return None

    today = timezone.now().date()
    invoice = Invoice.objects.create(
        number=_next_number(Invoice, "INV", 1001),
        customer=quotation.customer,
        quotation=quotation,
        invoice_type=InvoiceType.ONE_TIME,
        status=InvoiceStatus.OPEN,
        issue_date=today,
        due_date=today + timedelta(days=DEFAULT_TERMS_DAYS),
        currency=quotation.currency,
    )
    subtotal = tax_total = ZERO
    for line in lines:
        net = Decimal(line.line_total)
        tax = (net * Decimal(line.tax_percent) / HUNDRED).quantize(Decimal("0.01"))
        InvoiceLine.objects.create(
            invoice=invoice,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=line.discount_percent,
            tax_percent=line.tax_percent,
            line_total=net,
            quotation_line=line,
        )
        subtotal += net
        tax_total += tax

    invoice.subtotal = subtotal
    invoice.tax_total = tax_total
    invoice.total = subtotal + tax_total
    invoice.save()
    return invoice


@transaction.atomic
def issue_recurring_invoice(subscription, period_start: date, period_end: date) -> Invoice:
    """Bill one subscription period. Called on activation and on renewal."""
    today = timezone.now().date()
    amount = (Decimal(subscription.quantity) * Decimal(subscription.unit_price)).quantize(
        Decimal("0.01")
    )
    tax = (amount * Decimal(subscription.product.tax_percent) / HUNDRED).quantize(Decimal("0.01"))

    invoice = Invoice.objects.create(
        number=_next_number(Invoice, "INV", 1001),
        customer=subscription.customer,
        quotation=subscription.quotation,
        subscription=subscription,
        invoice_type=InvoiceType.RECURRING,
        status=InvoiceStatus.OPEN,
        issue_date=today,
        due_date=today + timedelta(days=DEFAULT_TERMS_DAYS),
        period_start=period_start,
        period_end=period_end,
        currency=subscription.customer.currency,
        subtotal=amount,
        tax_total=tax,
        total=amount + tax,
    )
    InvoiceLine.objects.create(
        invoice=invoice,
        description=f"{subscription.plan.name} ({period_start} → {period_end})",
        quantity=subscription.quantity,
        unit_price=subscription.unit_price,
        tax_percent=subscription.product.tax_percent,
        line_total=amount,
        subscription=subscription,
    )
    return invoice


@transaction.atomic
def issue_proration_invoice(subscription, amount: Decimal, description: str) -> Invoice:
    """A mid-cycle upgrade, billed immediately."""
    today = timezone.now().date()
    amount = Decimal(amount).quantize(Decimal("0.01"))
    invoice = Invoice.objects.create(
        number=_next_number(Invoice, "INV", 1001),
        customer=subscription.customer,
        subscription=subscription,
        invoice_type=InvoiceType.PRORATION,
        status=InvoiceStatus.OPEN,
        issue_date=today,
        due_date=today + timedelta(days=DEFAULT_TERMS_DAYS),
        currency=subscription.customer.currency,
        subtotal=amount,
        total=amount,
    )
    InvoiceLine.objects.create(
        invoice=invoice,
        description=description,
        quantity=Decimal("1"),
        unit_price=amount,
        line_total=amount,
        subscription=subscription,
    )
    return invoice


@transaction.atomic
def issue_credit_note(customer, amount: Decimal, reason: str, invoice: Invoice | None = None):
    """A mid-cycle downgrade or cancellation refund."""
    return CreditNote.objects.create(
        number=_next_number(CreditNote, "CN", 501),
        customer=customer,
        invoice=invoice,
        amount=abs(Decimal(amount)).quantize(Decimal("0.01")),
        reason=reason,
    )


@transaction.atomic
def record_payment(
    invoice: Invoice,
    *,
    amount: Decimal,
    method: str,
    reference: str = "",
    actor=None,
) -> Invoice:
    """Record a payment and move the invoice status accordingly."""
    amount = Decimal(amount)
    if amount <= ZERO:
        raise ValidationError("Payment amount must be positive")
    if invoice.status == InvoiceStatus.VOID:
        raise ValidationError("Cannot pay a voided invoice")
    if amount > invoice.amount_due:
        raise ValidationError(
            f"Payment of {amount} exceeds the outstanding balance of {invoice.amount_due}"
        )

    Payment.objects.create(
        invoice=invoice,
        amount=amount,
        method=method,
        reference=reference,
        paid_at=timezone.now(),
        recorded_by=actor,
    )
    invoice.amount_paid += amount
    invoice.status = (
        InvoiceStatus.PAID if invoice.amount_paid >= invoice.total else InvoiceStatus.PARTIALLY_PAID
    )
    invoice.save(update_fields=["amount_paid", "status", "updated_at"])
    return invoice
