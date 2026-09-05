from django.db import models

from apps.common.enums import ApprovalStatus, RiskBand, Role
from apps.common.models import PERCENT, TimeStampedModel


class ApprovalRequest(TimeStampedModel):
    """One trip through the approval chain.

    A quotation can have several over its life — a portal counter-offer opens a
    NEW request rather than reopening the old one, so the history stays legible.
    """

    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="approval_requests"
    )
    risk_score = models.DecimalField(**PERCENT)
    risk_band = models.CharField(max_length=10, choices=RiskBand.choices)
    status = models.CharField(
        max_length=12, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    reason = models.TextField(blank=True, help_text="Why this quote was flagged")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval_request"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.quotation.number} [{self.risk_band}] {self.status}"

    @property
    def current_step(self):
        return self.steps.filter(status=ApprovalStatus.PENDING).order_by("sequence").first()


class ApprovalStep(TimeStampedModel):
    """Materialised when the request opens, from ApprovalRule.required_roles.

    Because steps are rows, screen 6's stepper is a plain read and
    "Finance only shown when required" is literally "there is no Finance row".
    """

    request = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE, related_name="steps"
    )
    sequence = models.IntegerField()
    role_required = models.CharField(max_length=20, choices=Role.choices)
    assignee = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="approval_steps"
    )
    status = models.CharField(
        max_length=12, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
    decision_note = models.TextField(blank=True)
    acted_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "approval_step"
        ordering = ["sequence"]
        unique_together = [("request", "sequence")]

    def __str__(self) -> str:
        return f"{self.sequence}. {self.role_required} — {self.status}"
