"""Deal health & anomaly detection.  Owner: anubhaw0raj.

`run_sweep()` is idempotent — it updates open alerts rather than creating
duplicates, so it's safe to call on every dashboard load and after every
quotation write. At seed-data scale it costs a few milliseconds; at real scale
it becomes a Celery beat and nothing else changes.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    QuotationEventType,
    QuotationStatus,
)
from apps.insights.models import AlertAction, DealAlert, DealHealthConfig, RepDiscountStat
from apps.quotations.models import Quotation

#: Quotations still in play — a confirmed or rejected deal cannot be "stalled".
ACTIVE_STATUSES = [
    QuotationStatus.DRAFT,
    QuotationStatus.PENDING_APPROVAL,
    QuotationStatus.SENT,
    QuotationStatus.UNDER_NEGOTIATION,
]
ANOMALY_WINDOW_DAYS = 90


@transaction.atomic
def run_sweep() -> dict:
    config = DealHealthConfig.get_solo()

    # Each sweep returns the quotations that qualify RIGHT NOW.
    live = {
        AlertType.STALLED: _sweep_stalled(config),
        AlertType.DISCOUNT_ANOMALY: _sweep_discount_anomalies(config),
        AlertType.DELIVERY_SLIPPAGE: _sweep_delivery_slippage(config),
    }
    for alert_type, quotation_ids in live.items():
        _resolve_cleared(alert_type, quotation_ids)

    # Count what is actually OPEN, not what this run happened to find. A deal
    # flagged yesterday that is still stalled today must keep counting, and one
    # whose condition has cleared must stop — otherwise the three stat cards
    # disagree with the alert table directly underneath them.
    open_alerts = DealAlert.objects.filter(status=AlertStatus.OPEN)
    return {
        "stalled": open_alerts.filter(alert_type=AlertType.STALLED).count(),
        "anomalies": open_alerts.filter(alert_type=AlertType.DISCOUNT_ANOMALY).count(),
        "slippage": open_alerts.filter(alert_type=AlertType.DELIVERY_SLIPPAGE).count(),
    }


def _resolve_cleared(alert_type: str, live_quotation_ids: set[int]) -> int:
    """Close alerts whose condition no longer holds.

    Nothing did this before. A quotation that went stalled and was then
    confirmed kept its STALLED alert open forever, so screen 14 listed a
    CONFIRMED deal as at-risk while the card above it correctly said zero.
    """
    return (
        DealAlert.objects.filter(
            alert_type=alert_type,
            status__in=[AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED],
        )
        .exclude(quotation_id__in=live_quotation_ids)
        .update(status=AlertStatus.RESOLVED, resolved_at=timezone.now())
    )


def _sweep_stalled(config: DealHealthConfig) -> set[int]:
    cutoff = timezone.now() - timedelta(days=config.stalled_days_threshold)
    flagged: set[int] = set()
    for quotation in Quotation.objects.filter(
        status__in=ACTIVE_STATUSES, last_activity_at__lt=cutoff
    ):
        idle = quotation.idle_days
        severity = (
            AlertSeverity.HIGH
            if idle >= config.stalled_days_threshold * 3
            else AlertSeverity.MEDIUM
            if idle >= config.stalled_days_threshold * 2
            else AlertSeverity.LOW
        )
        _upsert_alert(
            quotation, AlertType.STALLED, severity, f"Idle {idle} days"
        )
        flagged.add(quotation.id)
    return flagged


def _sweep_discount_anomalies(config: DealHealthConfig) -> set[int]:
    stats = _refresh_rep_stats()
    flagged: set[int] = set()
    for quotation in Quotation.objects.filter(status__in=ACTIVE_STATUSES).select_related(
        "owner_rep"
    ):
        stat = stats.get(quotation.owner_rep_id)
        # A rep with too little history has no baseline to be anomalous against.
        if stat is None or stat["count"] < config.anomaly_min_quotes:
            continue
        average = stat["average"]
        if average <= 0:
            continue
        effective = _effective_discount(quotation)
        if effective > average * Decimal(config.anomaly_multiplier):
            _upsert_alert(
                quotation,
                AlertType.DISCOUNT_ANOMALY,
                AlertSeverity.HIGH if effective > average * 3 else AlertSeverity.MEDIUM,
                f"Discount {effective:.0f}% vs avg {average:.0f}%",
            )
            flagged.add(quotation.id)
    return flagged


def _sweep_delivery_slippage(config: DealHealthConfig) -> set[int]:
    from apps.fulfillment.models import FulfillmentAllocation

    today = timezone.now().date()
    grace = timedelta(days=config.slippage_grace_days)
    flagged: set[int] = set()
    late = FulfillmentAllocation.objects.filter(
        shipped_at__isnull=True, promised_date__isnull=False, promised_date__lt=today - grace
    ).select_related("plan__quotation")

    for alloc in late:
        days_late = (today - alloc.promised_date).days
        _upsert_alert(
            alloc.plan.quotation,
            AlertType.DELIVERY_SLIPPAGE,
            AlertSeverity.HIGH if days_late > 7 else AlertSeverity.MEDIUM,
            f"Promise date passed by {days_late} days",
        )
        flagged.add(alloc.plan.quotation_id)
    return flagged


def _effective_discount(quotation: Quotation) -> Decimal:
    if not quotation.subtotal:
        return Decimal("0")
    return Decimal(quotation.discount_total) / Decimal(quotation.subtotal) * Decimal("100")


def _refresh_rep_stats() -> dict[int, dict]:
    """Trailing 90-day average discount per rep, cached in rep_discount_stat."""
    window_end = timezone.now().date()
    window_start = window_end - timedelta(days=ANOMALY_WINDOW_DAYS)

    totals: dict[int, list[Decimal]] = {}
    for quotation in Quotation.objects.filter(created_at__date__gte=window_start).exclude(
        subtotal=0
    ):
        totals.setdefault(quotation.owner_rep_id, []).append(_effective_discount(quotation))

    stats: dict[int, dict] = {}
    for rep_id, discounts in totals.items():
        average = (sum(discounts) / len(discounts)).quantize(Decimal("0.01"))
        stats[rep_id] = {"average": average, "count": len(discounts)}
        RepDiscountStat.objects.update_or_create(
            rep_id=rep_id,
            defaults={
                "avg_discount_percent": average,
                "quote_count": len(discounts),
                "window_start": window_start,
                "window_end": window_end,
            },
        )
    return stats


def _upsert_alert(quotation, alert_type: str, severity: str, message: str) -> DealAlert:
    """Update the open alert if there is one; never duplicate it."""
    existing = DealAlert.objects.filter(
        quotation=quotation, alert_type=alert_type, status=AlertStatus.OPEN
    ).first()
    if existing:
        if existing.message != message or existing.severity != severity:
            existing.message = message
            existing.severity = severity
            existing.save(update_fields=["message", "severity", "updated_at"])
        return existing
    return DealAlert.objects.create(
        quotation=quotation, alert_type=alert_type, severity=severity, message=message
    )


@transaction.atomic
def act_on_alert(alert: DealAlert, *, action_type: str, actor=None, note: str = "") -> AlertAction:
    """Nudge or Escalate.

    Both write to the deal's own audit trail as well as the alert, so the
    action shows up in the quotation's history rather than only in a dashboard.
    """
    from apps.quotations.services import record_event

    action = AlertAction.objects.create(
        alert=alert, action_type=action_type, actor=actor, note=note
    )
    record_event(
        alert.quotation,
        QuotationEventType.NUDGED
        if action_type == AlertAction.ActionType.NUDGE
        else QuotationEventType.ESCALATED,
        actor=actor,
        note=note or alert.message,
        alert_id=alert.id,
    )
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.save(update_fields=["status", "updated_at"])
    return action
