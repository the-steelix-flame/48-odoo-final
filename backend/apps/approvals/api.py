"""Approvals list & detail (screens 5, 6).  Owner: the-steelix-flame."""

from datetime import datetime
from decimal import Decimal

from ninja import Router, Schema

from apps.accounts.auth import internal_auth
from apps.approvals.models import ApprovalRequest
from apps.approvals.services import act
from apps.common.enums import ApprovalStatus
from apps.common.errors import NotFound
from apps.quotations.schemas import QuotationEventOut, RiskBreakdownOut
from apps.quotations.services import risk_breakdown

router = Router(auth=internal_auth)


class ApprovalStepOut(Schema):
    id: int
    sequence: int
    role_required: str
    assignee_name: str | None = None
    status: str
    decision_note: str
    acted_by_name: str | None = None
    acted_at: datetime | None = None

    @staticmethod
    def resolve_assignee_name(obj) -> str | None:
        return (obj.assignee.full_name or obj.assignee.email) if obj.assignee_id else None

    @staticmethod
    def resolve_acted_by_name(obj) -> str | None:
        return (obj.acted_by.full_name or obj.acted_by.email) if obj.acted_by_id else None


class ApprovalRowOut(Schema):
    """One row on screen 5."""

    id: int
    quotation_id: int
    quotation_number: str
    customer_name: str
    customer_tier: str
    risk_score: Decimal
    risk_band: str
    status: str
    current_stage: str | None = None
    assigned_to: str | None = None
    created_at: datetime

    @staticmethod
    def resolve_quotation_number(obj) -> str:
        # _detail-style endpoints hand Ninja a plain dict that already carries this
        # value; Ninja passes the RAW dict to the resolver, so attribute access
        # would raise AttributeError and the field would be dropped as "missing".
        if isinstance(obj, dict):
            return obj["quotation_number"]
        return obj.quotation.number

    @staticmethod
    def resolve_customer_name(obj) -> str:
        if isinstance(obj, dict):
            return obj["customer_name"]
        return obj.quotation.customer.name

    @staticmethod
    def resolve_customer_tier(obj) -> str:
        if isinstance(obj, dict):
            return obj["customer_tier"]
        return obj.quotation.customer.tier

    @staticmethod
    def resolve_current_stage(obj) -> str | None:
        if isinstance(obj, dict):
            return obj.get("current_stage")
        step = obj.current_step
        return step.role_required if step else None

    @staticmethod
    def resolve_assigned_to(obj) -> str | None:
        if isinstance(obj, dict):
            return obj.get("assigned_to")
        step = obj.current_step
        if step is None or step.assignee_id is None:
            return None
        return step.assignee.full_name or step.assignee.email


class ApprovalDetailOut(ApprovalRowOut):
    reason: str
    steps: list[ApprovalStepOut]
    risk: RiskBreakdownOut
    audit_trail: list[QuotationEventOut]


class DecisionIn(Schema):
    decision: str  # APPROVED | REJECTED | RETURNED
    note: str = ""


def _get(request_id: int) -> ApprovalRequest:
    try:
        return ApprovalRequest.objects.select_related(
            "quotation", "quotation__customer"
        ).get(pk=request_id)
    except ApprovalRequest.DoesNotExist:
        raise NotFound("Approval request not found")


@router.get("/", response=list[ApprovalRowOut])
def list_approvals(request, status: str | None = None, mine: bool = False):
    qs = ApprovalRequest.objects.select_related("quotation", "quotation__customer").prefetch_related(
        "steps__assignee"
    )
    if status:
        qs = qs.filter(status=status)
    if mine:
        qs = qs.filter(
            steps__status=ApprovalStatus.PENDING, steps__role_required=request.auth.role
        ).distinct()
    return list(qs)


@router.get("/counts")
def approval_counts(request):
    """The three chips at the top of screen 5."""
    qs = ApprovalRequest.objects.all()
    return {
        "pending": qs.filter(status=ApprovalStatus.PENDING).count(),
        "returned": qs.filter(status=ApprovalStatus.RETURNED).count(),
        "approved": qs.filter(status=ApprovalStatus.APPROVED).count(),
        "rejected": qs.filter(status=ApprovalStatus.REJECTED).count(),
    }


@router.get("/{request_id}", response=ApprovalDetailOut)
def get_approval(request, request_id: int):
    approval = _get(request_id)
    quotation = approval.quotation
    data = {
        f: getattr(approval, f)
        for f in ("id", "quotation_id", "risk_score", "risk_band", "status", "reason", "created_at")
    }
    step = approval.current_step
    data.update(
        quotation_number=quotation.number,
        customer_name=quotation.customer.name,
        customer_tier=quotation.customer.tier,
        current_stage=step.role_required if step else None,
        assigned_to=(step.assignee.full_name or step.assignee.email)
        if step and step.assignee_id
        else None,
        steps=list(approval.steps.select_related("assignee", "acted_by")),
        risk=risk_breakdown(quotation),
        audit_trail=list(quotation.events.select_related("actor")),
    )
    return data


@router.post("/{request_id}/decide", response=ApprovalDetailOut)
def decide(request, request_id: int, payload: DecisionIn):
    """Approve / Reject / Return for revision — screen 6's three buttons."""
    approval = _get(request_id)
    act(approval, actor=request.auth, decision=payload.decision, note=payload.note)
    return get_approval(request, request_id)
