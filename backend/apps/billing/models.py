from django.db import models

from apps.common.enums import InvoiceStatus, InvoiceType, PaymentMethod
from apps.common.models import MONEY, PERCENT, QUANTITY, TimeStampedModel


class Invoice(TimeStampedModel):
    """A one-time order and its subscription produce DIFFERENT invoice rows.

    That separation is the whole point of hybrid billing, so it's structural
    rather than a filter on one big table.
    """

    number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="invoices"
    )
    quotation = models.ForeignKey(
        "quotations.Quotation", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoices",
    )
    subscription = models.ForeignKey(
        "subscriptions.Subscription", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="invoices",
    )
    invoice_type = models.CharField(
        max_length=12, choices=InvoiceType.choices, default=InvoiceType.ONE_TIME
    )
    status = models.CharField(
        max_length=16, choices=InvoiceStatus.choices, default=InvoiceStatus.OPEN
    )
    issue_date = models.DateField()
    due_date = models.DateField()
    #: Only meaningful for RECURRING invoices.
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    currency = models.CharField(max_length=3, default="USD")
    subtotal = models.DecimalField(**MONEY)
    tax_total = models.DecimalField(**MONEY)
    total = models.DecimalField(**MONEY)
    amount_paid = models.DecimalField(**MONEY)

    class Meta:
        db_table = "invoice"
        ordering = ["-issue_date", "-id"]

    def __str__(self) -> str:
        return f"{self.number} — {self.customer.name} ({self.status})"

    @property
    def amount_due(self):
        return self.total - self.amount_paid


class InvoiceLine(TimeStampedModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(**QUANTITY)
    unit_price = models.DecimalField(**MONEY)
    discount_percent = models.DecimalField(**PERCENT)
    tax_percent = models.DecimalField(**PERCENT)
    line_total = models.DecimalField(**MONEY)
    quotation_line = models.ForeignKey(
        "quotations.QuotationLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    subscription = models.ForeignKey(
        "subscriptions.Subscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "invoice_line"


class Payment(TimeStampedModel):
    """Several payments per invoice, so PARTIALLY_PAID is real, not decorative."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(**MONEY)
    method = models.CharField(
        max_length=16, choices=PaymentMethod.choices, default=PaymentMethod.BANK_TRANSFER
    )
    reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField()
    recorded_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "payment"
        ordering = ["-paid_at"]


class CreditNote(TimeStampedModel):
    class Status(models.TextChoices):
        ISSUED = "ISSUED", "Issued"
        APPLIED = "APPLIED", "Applied"
        VOID = "VOID", "Void"

    number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.PROTECT, related_name="credit_notes"
    )
    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name="credit_notes"
    )
    amount = models.DecimalField(**MONEY)
    reason = models.CharField(max_length=250, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ISSUED)

    class Meta:
        db_table = "credit_note"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.number} — {self.amount}"
