"""Invoicing, payments and credit notes.  Owner: anubhaw0raj."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import CreditNote, Invoice, InvoiceLine, Payment
from apps.common.enums import InvoiceStatus, InvoiceType, LineType
from apps.common.errors import ValidationError
from apps.quotations import services as quotation_services
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
    # The negotiated discount lands on `order_discount_percent`, not on the
    # lines, so billing `line_total` straight charges the pre-negotiation price.
    # A deal closed at 10% off was invoiced at full list and the customer
    # overpaid by exactly the discount they had agreed.
    factor = quotation_services.order_discount_factor(quotation)

    subtotal = tax_total = ZERO
    for line in lines:
        gross = Decimal(line.line_subtotal)
        net = (Decimal(line.line_total) * factor).quantize(Decimal("0.01"))
        tax = (net * Decimal(line.tax_percent) / HUNDRED).quantize(Decimal("0.01"))
        # One discount per invoice line: everything actually taken off, so that
        # unit price × quantity × (1 − discount) equals the line total. Carrying
        # only the line-level figure would leave the arithmetic on a document
        # the customer reads visibly not adding up.
        effective_discount = (
            ((gross - net) / gross * HUNDRED).quantize(Decimal("0.01")) if gross else ZERO
        )
        InvoiceLine.objects.create(
            invoice=invoice,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount_percent=effective_discount,
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


#: A confirmed deal moves through these three, in order.
BILLING_AWAITING = "AWAITING_BILL"
BILLING_PAYMENT_PENDING = "PAYMENT_PENDING"
BILLING_PAID = "PAID"


def bill_for(quotation) -> Invoice | None:
    """The bill raised against this deal, if Finance has raised one.

    ONE_TIME only. A recurring invoice belongs to a subscription's own
    schedule and keeps arriving every period, so treating one as "the bill for
    the deal" would leave the deal permanently unpaid.
    """
    return (
        Invoice.objects.filter(quotation=quotation, invoice_type=InvoiceType.ONE_TIME)
        .order_by("id")
        .first()
    )


def billing_state(quotation) -> tuple[str, Invoice | None]:
    """Where a confirmed deal stands: awaiting a bill, awaiting payment, paid."""
    invoice = bill_for(quotation)
    if invoice is None:
        return BILLING_AWAITING, None
    if invoice.status == InvoiceStatus.PAID:
        return BILLING_PAID, invoice
    return BILLING_PAYMENT_PENDING, invoice


@transaction.atomic
def raise_bill_for_quotation(quotation, *, actor=None) -> Invoice:
    """Finance or a Sales Manager signs the deal off, and the bill goes out.

    Confirmation is the customer agreeing to the terms; this is us agreeing to
    them. Billing before that point means invoicing for a deal nobody internal
    has accepted, which is why `quotations.confirm()` deliberately leaves the
    money alone.
    """
    from apps.common.enums import QuotationStatus

    if quotation.status != QuotationStatus.CONFIRMED:
        raise ValidationError(
            "Only a confirmed deal can be billed — this one is "
            f"{quotation.get_status_display().lower()}."
        )

    existing = bill_for(quotation)
    if existing is not None:
        # Idempotent on purpose: a double click, or two people accepting the
        # same deal at once, must not raise two bills for one order.
        raise ValidationError(
            f"{quotation.number} has already been billed as {existing.number}.",
            invoice_id=existing.id,
        )

    invoice = issue_one_time_invoice(quotation, actor=actor)

    # The recurring lines were deferred at confirm time for the same reason;
    # release their first period now that the deal is signed off.
    for subscription in quotation.subscriptions.select_related("plan", "product"):
        if not subscription.plan.bill_in_advance:
            continue
        if subscription.invoices.exists():
            continue
        issue_recurring_invoice(
            subscription,
            subscription.current_period_start,
            subscription.current_period_end,
        )

    if invoice is None:
        # Subscription-only order: there are no one-time lines to bill, so the
        # recurring schedule above is the whole of it. Surfaced rather than
        # returning None, so the caller never has to guess.
        raise ValidationError(
            f"{quotation.number} has no one-time lines to bill. Its recurring "
            "schedule has been released and will invoice each period."
        )
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
