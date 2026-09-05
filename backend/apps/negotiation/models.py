import uuid

from django.db import models

from apps.common.enums import NegotiationRequestStatus
from apps.common.models import PERCENT, TimeStampedModel, percent


class PortalToken(TimeStampedModel):
    """What makes the portal a genuinely separate surface.

    A portal request authorises against a token scoped to ONE quotation, not
    against an internal session. A customer holding a valid login but no token
    for quotation X cannot read X — and gets a 404, not a 403, because the
    existence of someone else's quote isn't theirs to learn either.
    """

    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    customer = models.ForeignKey(
        "accounts.Customer", on_delete=models.CASCADE, related_name="portal_tokens"
    )
    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="portal_tokens"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "portal_token"

    def __str__(self) -> str:
        return f"{self.quotation.number} → {self.customer.name}"

    @property
    def is_valid(self) -> bool:
        from django.utils import timezone

        return self.expires_at is None or self.expires_at > timezone.now()


class NegotiationThread(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    quotation = models.OneToOneField(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="negotiation_thread"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        db_table = "negotiation_thread"


class NegotiationMessage(TimeStampedModel):
    class AuthorType(models.TextChoices):
        CUSTOMER = "CUSTOMER", "Customer"
        REP = "REP", "Sales Rep"

    thread = models.ForeignKey(
        NegotiationThread, on_delete=models.CASCADE, related_name="messages"
    )
    #: null = an order-level comment rather than a line-level one.
    quotation_line = models.ForeignKey(
        "quotations.QuotationLine", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    author_type = models.CharField(max_length=10, choices=AuthorType.choices)
    author = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    body = models.TextField()

    class Meta:
        db_table = "negotiation_message"
        ordering = ["created_at"]


class NegotiationEvent(TimeStampedModel):
    """Append-only record of ONE move in a negotiation.

    The timeline used to be derived from the current state of each
    `NegotiationRequest`, which meant a row could only ever show its latest
    status: once a customer accepted our counter, the "we offered 12%" moment
    was overwritten by "accepted" and vanished from the history. A negotiation
    both sides remember differently is worse than no record at all.

    Nothing in here is ever updated or deleted. Every move — a message, an ask,
    our counter, the decision — is its own row, with who made it and when.
    Both the rep panel and the customer portal read this same table in order.
    """

    class Kind(models.TextChoices):
        MESSAGE = "MESSAGE", "Message"
        COUNTER_REQUEST = "COUNTER_REQUEST", "Customer counter-offer"
        REP_COUNTER = "REP_COUNTER", "Our counter-offer"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Declined"
        SENT = "SENT", "Quotation sent"
        CONFIRMED = "CONFIRMED", "Confirmed by customer"

    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="negotiation_events"
    )
    request = models.ForeignKey(
        "negotiation.NegotiationRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    author_type = models.CharField(max_length=10)  # CUSTOMER | REP | SYSTEM
    author = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    #: Snapshotted so the thread still reads correctly after a user is
    #: deactivated or renamed, and so a customer shows as their company rather
    #: than as "Acme Corp (portal)".
    author_name = models.CharField(max_length=150, blank=True)
    body = models.TextField(blank=True)
    discount_percent = models.DecimalField(**percent(default=None), null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    quotation_line = models.ForeignKey(
        "quotations.QuotationLine", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        db_table = "negotiation_event"
        # `id` breaks ties: two moves in the same transaction can share a
        # timestamp to the microsecond, and the thread must still read in the
        # order things actually happened.
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["quotation", "created_at"])]

    def __str__(self) -> str:
        return f"{self.quotation_id} {self.kind} by {self.author_name or 'system'}"


class NegotiationRequest(TimeStampedModel):
    """A counter-offer. Accepting one rewrites discounts through the normal
    quotation service, which re-runs the risk engine, which may reopen
    approval. The portal gets no special path — that's why re-approval is
    automatic rather than something we remembered to call."""

    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="negotiation_requests"
    )
    thread = models.ForeignKey(
        NegotiationThread, null=True, blank=True, on_delete=models.SET_NULL, related_name="requests"
    )
    requested_discount_percent = models.DecimalField(**PERCENT, null=True, blank=True)
    requested_delivery_date = models.DateField(null=True, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=12,
        choices=NegotiationRequestStatus.choices,
        default=NegotiationRequestStatus.SUBMITTED,
    )
    #: What the rep proposed back when they countered instead of accepting.
    #: Kept on the same row rather than opening a new request, so one round of
    #: haggling reads as one row: asked 20, offered 15, customer accepted.
    #: NOT `**PERCENT` — that carries `default=0`, which would make "no counter
    #: yet" indistinguishable from "we offered zero percent".
    counter_discount_percent = models.DecimalField(
        **percent(default=None), null=True, blank=True
    )
    resolved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        db_table = "negotiation_request"
        ordering = ["-created_at"]
