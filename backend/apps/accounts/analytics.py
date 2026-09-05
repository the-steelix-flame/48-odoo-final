"""Per-user analytics.  Owner: the-steelix-flame.

Powers the admin's user detail page. The numbers shown depend on the role,
because "how is this person doing" means completely different things for a rep
(are they discounting responsibly and closing?) and an approver (are they a
bottleneck?).

Every figure is aggregated from the operational tables the rest of the app
reads. There is no separate analytics copy to drift out of date.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import ApprovalStep
from apps.catalog.models import UpsellSuggestionLog
from apps.common.enums import AlertStatus, ApprovalStatus, QuotationStatus, Role
from apps.insights.models import DealAlert
from apps.quotations.models import Quotation

ZERO = Decimal("0")

#: Statuses that mean the deal is still in play.
OPEN_STATUSES = [
    QuotationStatus.DRAFT,
    QuotationStatus.PENDING_APPROVAL,
    QuotationStatus.APPROVED,
    QuotationStatus.SENT,
    QuotationStatus.UNDER_NEGOTIATION,
]


def user_analytics(user: User, *, window_days: int = 90) -> dict:
    """A role-appropriate view of one person's activity."""
    since = timezone.now() - timedelta(days=window_days)

    payload: dict = {
        "user_id": user.id,
        "window_days": window_days,
        "sections": [],
        "recent_quotations": [],
        "recent_decisions": [],
    }

    if user.role in (Role.SALES_REP, Role.SALES_MANAGER, Role.ADMIN):
        payload["sections"].extend(_selling_metrics(user, since))
        payload["recent_quotations"] = _recent_quotations(user)

    if user.role in (Role.SALES_MANAGER, Role.FINANCE, Role.ADMIN):
        payload["sections"].extend(_approver_metrics(user, since))
        payload["recent_decisions"] = _recent_decisions(user)

    if user.role == Role.CUSTOMER:
        payload["sections"].extend(_customer_metrics(user))
        payload["recent_quotations"] = _recent_customer_quotations(user)

    # `MetricOut.value` is typed `str`, and pydantic v2 does NOT coerce int to
    # str — it raises. Counts are naturally ints, so normalise once here rather
    # than relying on every call site to remember. Done centrally so adding a
    # new metric later can't reintroduce the 500.
    for section in payload["sections"]:
        for metric in section["metrics"]:
            metric["value"] = str(metric["value"])

    return payload


# ------------------------------------------------------------------ selling
def _selling_metrics(user: User, since) -> list[dict]:
    owned = Quotation.objects.filter(owner_rep=user)
    recent = owned.filter(created_at__gte=since)

    created = recent.count()
    confirmed = recent.filter(status=QuotationStatus.CONFIRMED)
    confirmed_count = confirmed.count()

    # Win rate is measured against DECIDED deals only. Counting still-open
    # quotations as losses would punish a rep for having a healthy pipeline.
    decided = recent.filter(
        status__in=[QuotationStatus.CONFIRMED, QuotationStatus.REJECTED, QuotationStatus.CANCELLED]
    ).count()
    win_rate = round(confirmed_count / decided * 100, 1) if decided else None

    avg_discount = _avg_effective_discount(recent)
    avg_risk = recent.aggregate(v=Avg("blended_risk_score"))["v"]
    open_value = owned.filter(status__in=OPEN_STATUSES).aggregate(v=Sum("total"))["v"] or ZERO
    needing_approval = owned.filter(status=QuotationStatus.PENDING_APPROVAL).count()
    alerts = DealAlert.objects.filter(
        quotation__owner_rep=user, status=AlertStatus.OPEN
    ).count()
    upsells = UpsellSuggestionLog.objects.filter(
        actor=user, action=UpsellSuggestionLog.Action.ADDED
    ).count()

    return [
        {
            "title": "Selling",
            "metrics": [
                {"label": "Quotations created", "value": created, "hint": f"last {90} days"},
                {"label": "Confirmed", "value": confirmed_count},
                {
                    "label": "Win rate",
                    "value": f"{win_rate}%" if win_rate is not None else "—",
                    "hint": "of decided deals" if win_rate is not None else "no decided deals yet",
                },
                {
                    "label": "Confirmed value",
                    "value": _money(confirmed.aggregate(v=Sum("total"))["v"]),
                },
                {"label": "Open pipeline", "value": _money(open_value)},
                {
                    "label": "Avg discount given",
                    "value": f"{avg_discount:.1f}%" if avg_discount is not None else "—",
                    "hint": "effective, across the order",
                },
                {
                    "label": "Avg risk score",
                    "value": f"{Decimal(avg_risk):.1f}" if avg_risk else "0.0",
                    "hint": "0 means every line within its ceiling",
                },
                {"label": "Awaiting approval", "value": needing_approval},
                {"label": "Open deal alerts", "value": alerts},
                {"label": "Upsells accepted", "value": upsells},
            ],
        }
    ]


def _avg_effective_discount(qs) -> float | None:
    """Discount as a share of subtotal, averaged over quotations with value."""
    rows = qs.exclude(subtotal=0).values_list("discount_total", "subtotal")
    ratios = [Decimal(d) / Decimal(s) * 100 for d, s in rows if s]
    return float(sum(ratios) / len(ratios)) if ratios else None


def _recent_quotations(user: User, limit: int = 10) -> list[dict]:
    return [
        {
            "id": q.id,
            "number": q.number,
            "customer_name": q.customer.name,
            "status": q.status,
            "risk_band": q.risk_band,
            "total": str(q.total),
            "created_at": q.created_at,
        }
        for q in Quotation.objects.filter(owner_rep=user)
        .select_related("customer")
        .order_by("-created_at")[:limit]
    ]


# ----------------------------------------------------------------- approving
def _approver_metrics(user: User, since) -> list[dict]:
    acted = ApprovalStep.objects.filter(acted_by=user, acted_at__gte=since)
    counts = acted.aggregate(
        approved=Count("id", filter=Q(status=ApprovalStatus.APPROVED)),
        rejected=Count("id", filter=Q(status=ApprovalStatus.REJECTED)),
        returned=Count("id", filter=Q(status=ApprovalStatus.RETURNED)),
    )
    total = sum(counts.values())

    # Time from the request opening to this person acting — the number that
    # says whether an approver is the bottleneck.
    durations = [
        (step.acted_at - step.request.created_at).total_seconds() / 3600
        for step in acted.select_related("request")
        if step.acted_at and step.request.created_at
    ]
    avg_hours = round(sum(durations) / len(durations), 1) if durations else None

    pending = ApprovalStep.objects.filter(
        status=ApprovalStatus.PENDING, role_required=user.role
    ).count()

    return [
        {
            "title": "Approvals",
            "metrics": [
                {"label": "Decisions made", "value": total, "hint": "last 90 days"},
                {"label": "Approved", "value": counts["approved"]},
                {"label": "Returned", "value": counts["returned"]},
                {"label": "Rejected", "value": counts["rejected"]},
                {
                    "label": "Avg decision time",
                    "value": f"{avg_hours} h" if avg_hours is not None else "—",
                    "hint": "from request raised to acted",
                },
                {
                    "label": "Waiting on this role",
                    "value": pending,
                    "hint": "steps currently pending",
                },
            ],
        }
    ]


def _recent_decisions(user: User, limit: int = 10) -> list[dict]:
    return [
        {
            "quotation_id": step.request.quotation_id,
            "quotation_number": step.request.quotation.number,
            "customer_name": step.request.quotation.customer.name,
            "decision": step.status,
            "note": step.decision_note,
            "acted_at": step.acted_at,
        }
        for step in ApprovalStep.objects.filter(acted_by=user, acted_at__isnull=False)
        .select_related("request__quotation__customer")
        .order_by("-acted_at")[:limit]
    ]


# ----------------------------------------------------------------- customer
def _customer_metrics(user: User) -> list[dict]:
    profile = getattr(user, "customer_profile", None)
    if profile is None:
        return [
            {
                "title": "Portal",
                "metrics": [
                    {
                        "label": "Business",
                        "value": "Not linked",
                        "hint": "This login has no business record — it cannot use the portal.",
                    }
                ],
            }
        ]

    quotations = Quotation.objects.filter(customer=profile)
    requests = profile.quotations.filter(negotiation_requests__isnull=False).distinct().count()

    return [
        {
            "title": "Portal activity",
            "metrics": [
                {"label": "Business", "value": profile.name, "hint": f"{profile.tier} tier"},
                {"label": "Quotations received", "value": quotations.count()},
                {
                    "label": "Confirmed",
                    "value": quotations.filter(status=QuotationStatus.CONFIRMED).count(),
                },
                {
                    "label": "Under negotiation",
                    "value": quotations.filter(status=QuotationStatus.UNDER_NEGOTIATION).count(),
                },
                {"label": "Quotes negotiated", "value": requests},
                {
                    "label": "Total value",
                    "value": _money(quotations.aggregate(v=Sum("total"))["v"]),
                },
            ],
        }
    ]


def _recent_customer_quotations(user: User, limit: int = 10) -> list[dict]:
    profile = getattr(user, "customer_profile", None)
    if profile is None:
        return []
    return [
        {
            "id": q.id,
            "number": q.number,
            "customer_name": profile.name,
            "status": q.status,
            "risk_band": q.risk_band,
            "total": str(q.total),
            "created_at": q.created_at,
        }
        for q in Quotation.objects.filter(customer=profile).order_by("-created_at")[:limit]
    ]


def _money(value) -> str:
    return f"{Decimal(value or 0):,.2f}"
