"""Dashboard, deal health & reporting (screens 2, 14, 15).
Owners: sinjeki (2, 15) · anubhaw0raj (14).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Sum
from django.utils import timezone
from ninja import Router, Schema

from apps.accounts.auth import internal_auth
from apps.billing.models import Invoice
from apps.catalog.models import UpsellSuggestionLog
from apps.common.enums import (
    AlertStatus,
    ApprovalStatus,
    InvoiceStatus,
    QuotationStatus,
    Role,
)
from apps.common.errors import NotFound
from apps.insights.health import act_on_alert, run_sweep
from apps.insights.models import AlertAction, DealAlert
from apps.quotations.models import Quotation

router = Router(auth=internal_auth)


class MoneySummaryOut(Schema):
    """The same four figures, computed for the company or for one rep."""

    #: Value of deals still in flight. NOT earnings - nothing here is won yet.
    pipeline_total: Decimal
    #: Value of quotations that reached CONFIRMED. Won, but not necessarily paid.
    won_value: Decimal
    #: Margin on those confirmed deals - what the company actually makes.
    won_margin: Decimal
    quotation_count: int


class PipelineStageOut(Schema):
    status: str
    label: str
    count: int
    value: Decimal
    percent: float


class DashboardOut(Schema):
    """Screen 2's three cards plus the activity feed."""

    pending_approvals: int
    open_quotations: int
    at_risk_deals: int
    recent_activity: list[dict]
    #: The hero band used to be hardcoded to $4.2M with 32/45/18/5 split. These
    #: are the real figures; the brief requires the numbers to be computed, and
    #: a fabricated headline is the first thing a reviewer would check.
    company: MoneySummaryOut
    pipeline_by_stage: list[PipelineStageOut]
    #: Cash actually received, across every invoice.
    collected: Decimal
    #: The same summary scoped to the viewer, when they own any quotations.
    #: Null for roles that never own deals, so the UI can hide the toggle.
    mine: MoneySummaryOut | None = None


class AlertOut(Schema):
    id: int
    quotation_id: int
    quotation_number: str
    customer_name: str
    alert_type: str
    severity: str
    message: str
    status: str
    detected_at: datetime
    #: Where the deal actually is. Screen 14 listed at-risk deals with no
    #: indication of what stage they were stuck at, so "idle 9 days" gave no
    #: clue whether it was waiting on a rep, an approver, or the customer.
    quotation_status: str
    #: The approval request to open, when one exists. Lets a manager jump
    #: straight to the decision instead of hunting for it in the approvals list.
    approval_request_id: int | None = None
    risk_band: str

    @staticmethod
    def resolve_quotation_number(obj) -> str:
        return obj.quotation.number

    @staticmethod
    def resolve_customer_name(obj) -> str:
        return obj.quotation.customer.name

    @staticmethod
    def resolve_quotation_status(obj) -> str:
        return obj.quotation.status

    @staticmethod
    def resolve_risk_band(obj) -> str:
        return obj.quotation.risk_band

    @staticmethod
    def resolve_approval_request_id(obj) -> int | None:
        """Prefer the request still awaiting a decision; fall back to the latest."""
        from apps.approvals.models import ApprovalRequest
        from apps.common.enums import ApprovalStatus

        requests = ApprovalRequest.objects.filter(quotation_id=obj.quotation_id)
        pending = requests.filter(status=ApprovalStatus.PENDING).order_by("-created_at").first()
        chosen = pending or requests.order_by("-created_at").first()
        return chosen.id if chosen else None


class DealHealthOut(Schema):
    stalled_count: int
    anomaly_count: int
    slippage_count: int
    alerts: list[AlertOut]


class AlertActionIn(Schema):
    action_type: str  # NUDGE | ESCALATE
    note: str = ""


class ReportOut(Schema):
    """Screen 15's tiles plus the breakdowns behind them."""

    quotes_created: int
    quotes_value: Decimal
    avg_approval_hours: float
    top_upsold_product: str | None = None
    by_status: list[dict]
    by_rep: list[dict]
    by_category: list[dict]


@router.get("/dashboard", response=DashboardOut)
def dashboard(request):
    from apps.approvals.models import ApprovalRequest

    run_sweep()  # keep the at-risk count honest on every load

    open_statuses = [
        QuotationStatus.DRAFT,
        QuotationStatus.PENDING_APPROVAL,
        QuotationStatus.APPROVED,
        QuotationStatus.SENT,
        QuotationStatus.UNDER_NEGOTIATION,
    ]
    recent = (
        Quotation.objects.select_related("customer")
        .order_by("-last_activity_at")[:5]
    )
    return {
        "pending_approvals": ApprovalRequest.objects.filter(
            status=ApprovalStatus.PENDING
        ).count(),
        "open_quotations": Quotation.objects.filter(status__in=open_statuses).count(),
        "at_risk_deals": DealAlert.objects.filter(status=AlertStatus.OPEN).count(),
        "company": _money_summary(Quotation.objects.all(), open_statuses),
        "pipeline_by_stage": _pipeline_by_stage(open_statuses),
        "collected": Invoice.objects.aggregate(t=Sum("amount_paid"))["t"] or Decimal("0"),
        "mine": _mine(request.auth, open_statuses),
        "recent_activity": [
            {
                "quotation_id": q.id,
                "text": f"{q.customer.name} — {q.number} is {q.get_status_display()}",
                "at": q.last_activity_at,
            }
            for q in recent
        ],
    }


def _money_summary(qs, open_statuses) -> dict:
    """Pipeline, won revenue and won margin for a set of quotations.

    Kept deliberately separate because they answer different questions.
    Pipeline is a forecast of deals still in flight; won_value is revenue on
    deals that closed; won_margin is the only one of the three that is profit.
    Collapsing them into a single "total" is what made the old hardcoded
    headline meaningless.
    """
    pipeline = qs.filter(status__in=open_statuses).aggregate(t=Sum("total"))["t"] or Decimal("0")
    won = qs.filter(status=QuotationStatus.CONFIRMED).aggregate(
        v=Sum("total"), m=Sum("margin_amount")
    )
    return {
        "pipeline_total": pipeline,
        "won_value": won["v"] or Decimal("0"),
        "won_margin": won["m"] or Decimal("0"),
        "quotation_count": qs.count(),
    }


def _pipeline_by_stage(open_statuses) -> list[dict]:
    """Real stage split, with percentages derived from value rather than typed in."""
    rows = (
        Quotation.objects.filter(status__in=open_statuses)
        .values("status")
        .annotate(count=Count("id"), value=Sum("total"))
    )
    by_status = {r["status"]: r for r in rows}
    total = sum((r["value"] or Decimal("0")) for r in rows) or Decimal("0")
    out = []
    for status in open_statuses:
        row = by_status.get(status)
        value = (row["value"] if row else None) or Decimal("0")
        out.append(
            {
                "status": status,
                "label": QuotationStatus(status).label,
                "count": row["count"] if row else 0,
                "value": value,
                "percent": float(round(value / total * 100, 1)) if total else 0.0,
            }
        )
    return out


#: Only these roles can create a quotation, so only these roles accumulate a
#: personal total. Kept in step with the guard on POST /quotations/.
OWNING_ROLES = (Role.SALES_REP, Role.ADMIN)


def _mine(user, open_statuses) -> dict | None:
    """Scoped to the deals this person owns.

    Returns None rather than a row of zeros for anyone who cannot own deals, so
    the UI hides the toggle instead of offering an empty personal scorecard.

    Note this is deliberately role-gated rather than "owns at least one". Seed
    data predates the creation rule and still has a Sales Manager and a Finance
    user owning quotations; their value stays in the company total, it simply is
    not attributed to them personally any more.
    """
    if user is None or user.role not in OWNING_ROLES:
        return None
    owned = Quotation.objects.filter(owner_rep=user)
    if not owned.exists():
        return None
    return _money_summary(owned, open_statuses)


@router.get("/deal-health", response=DealHealthOut)
def deal_health(request):
    counts = run_sweep()
    alerts = DealAlert.objects.filter(status=AlertStatus.OPEN).select_related(
        "quotation", "quotation__customer"
    ).order_by("-detected_at")
    return {
        "stalled_count": counts["stalled"],
        "anomaly_count": counts["anomalies"],
        "slippage_count": counts["slippage"],
        "alerts": list(alerts),
    }


@router.post("/alerts/{alert_id}/act", response=AlertOut)
def act_alert(request, alert_id: int, payload: AlertActionIn):
    """Nudge Rep / Escalate — screen 14's two buttons."""
    try:
        alert = DealAlert.objects.select_related("quotation", "quotation__customer").get(
            pk=alert_id
        )
    except DealAlert.DoesNotExist:
        raise NotFound("Alert not found")
    if payload.action_type not in AlertAction.ActionType.values:
        from apps.common.errors import ValidationError

        raise ValidationError(f"Unknown action {payload.action_type}")
    act_on_alert(alert, action_type=payload.action_type, actor=request.auth, note=payload.note)
    alert.refresh_from_db()
    return alert


@router.get("/reports", response=ReportOut)
def reports(
    request,
    date_from: date | None = None,
    date_to: date | None = None,
    rep_id: int | None = None,
    team_id: int | None = None,
    status: str | None = None,
    category_id: int | None = None,
):
    """Screen 15, with the brief's four filters:
    Period / Sales Team-Rep / Approval Status / Product-Category.
    """
    qs = Quotation.objects.select_related("customer", "owner_rep")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if rep_id:
        qs = qs.filter(owner_rep_id=rep_id)
    if team_id:
        qs = qs.filter(owner_rep__sales_team_id=team_id)
    if status:
        qs = qs.filter(status=status)
    if category_id:
        qs = qs.filter(lines__product__category_id=category_id).distinct()

    top_upsell = (
        UpsellSuggestionLog.objects.filter(action=UpsellSuggestionLog.Action.ADDED)
        .values("product__name")
        .annotate(n=Count("id"))
        .order_by("-n")
        .first()
    )

    return {
        "quotes_created": qs.count(),
        "quotes_value": qs.aggregate(total=Sum("total"))["total"] or Decimal("0"),
        "avg_approval_hours": _avg_approval_hours(),
        "top_upsold_product": top_upsell["product__name"] if top_upsell else None,
        "by_status": list(qs.values("status").annotate(count=Count("id"), value=Sum("total"))),
        "by_rep": list(
            qs.values("owner_rep__full_name").annotate(
                count=Count("id"), value=Sum("total"), avg_discount=Avg("discount_total")
            )
        ),
        "by_category": list(
            qs.values("lines__product__category__name").annotate(
                count=Count("lines__id"), value=Sum("lines__line_total")
            )
        ),
    }


@router.get("/reports/invoices")
def invoice_report(request):
    """Cash view for the Finance user."""
    qs = Invoice.objects.all()
    return {
        "outstanding": qs.filter(
            status__in=[InvoiceStatus.OPEN, InvoiceStatus.PARTIALLY_PAID]
        ).aggregate(total=Sum("total"))["total"]
        or Decimal("0"),
        "collected": qs.aggregate(total=Sum("amount_paid"))["total"] or Decimal("0"),
        "overdue": qs.filter(
            due_date__lt=timezone.now().date(),
            status__in=[InvoiceStatus.OPEN, InvoiceStatus.PARTIALLY_PAID],
        ).count(),
    }


def _avg_approval_hours() -> float:
    """Mean wall-clock time from request opened to closed."""
    from apps.approvals.models import ApprovalRequest

    closed = ApprovalRequest.objects.filter(closed_at__isnull=False).values_list(
        "created_at", "closed_at"
    )
    durations = [(end - start).total_seconds() / 3600 for start, end in closed]
    return round(sum(durations) / len(durations), 1) if durations else 0.0
