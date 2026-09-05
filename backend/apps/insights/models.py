from django.db import models

from apps.common.enums import AlertSeverity, AlertStatus, AlertType
from apps.common.models import PERCENT, TimeStampedModel


class DealHealthConfig(TimeStampedModel):
    """Singleton (pk=1). Thresholds are configurable, per the brief's
    "quotations inactive for more than a CONFIGURED number of days"."""

    stalled_days_threshold = models.IntegerField(default=7)
    #: Flag when a rep's discount exceeds this multiple of their own average.
    anomaly_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=2)
    #: Don't judge a rep on one quote.
    anomaly_min_quotes = models.IntegerField(default=3)
    slippage_grace_days = models.IntegerField(default=0)

    class Meta:
        db_table = "deal_health_config"

    @classmethod
    def get_solo(cls) -> "DealHealthConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RepDiscountStat(TimeStampedModel):
    """Cached trailing average per rep.

    Anomaly detection is RELATIVE to the rep: 22% from someone who averages 8%
    is a signal; the same 22% from an enterprise rep who averages 20% is not.
    That comparison is the only reason this table exists.
    """

    rep = models.OneToOneField(
        "accounts.User", on_delete=models.CASCADE, related_name="discount_stat"
    )
    avg_discount_percent = models.DecimalField(**PERCENT)
    quote_count = models.IntegerField(default=0)
    window_start = models.DateField()
    window_end = models.DateField()

    class Meta:
        db_table = "rep_discount_stat"


class DealAlert(TimeStampedModel):
    quotation = models.ForeignKey(
        "quotations.Quotation", on_delete=models.CASCADE, related_name="alerts"
    )
    alert_type = models.CharField(max_length=20, choices=AlertType.choices)
    severity = models.CharField(
        max_length=10, choices=AlertSeverity.choices, default=AlertSeverity.MEDIUM
    )
    message = models.CharField(max_length=250)
    status = models.CharField(
        max_length=14, choices=AlertStatus.choices, default=AlertStatus.OPEN
    )
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "deal_alert"
        ordering = ["-detected_at"]
        constraints = [
            # One OPEN alert per quotation per type. A re-run of the sweep
            # updates the existing row instead of spamming duplicates.
            models.UniqueConstraint(
                fields=["quotation", "alert_type"],
                condition=models.Q(status="OPEN"),
                name="unique_open_alert_per_quotation_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.quotation.number}: {self.message}"


class AlertAction(TimeStampedModel):
    class ActionType(models.TextChoices):
        NUDGE = "NUDGE", "Nudge rep"
        ESCALATE = "ESCALATE", "Escalate to manager"

    alert = models.ForeignKey(DealAlert, on_delete=models.CASCADE, related_name="actions")
    action_type = models.CharField(max_length=10, choices=ActionType.choices)
    actor = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=250, blank=True)

    class Meta:
        db_table = "alert_action"
