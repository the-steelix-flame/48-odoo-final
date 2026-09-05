"""Approval chain execution.  Owner: the-steelix-flame."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import ApprovalRequest, ApprovalStep
from apps.common.enums import ApprovalStatus, QuotationEventType, QuotationStatus, Role
from apps.common.errors import InvalidTransition, PermissionDenied, ValidationError
from apps.quotations import services as quotation_services
from apps.quotations.models import Quotation


@transaction.atomic
def open_approval_request(quotation: Quotation, *, actor=None) -> ApprovalRequest:
    """Create the request and materialise one step per required role."""
    breakdown = quotation_services.risk_breakdown(quotation)
    chain = quotation_services.chain_for(quotation)
    if not chain:
        raise ValidationError("This quotation does not require approval")

    request = ApprovalRequest.objects.create(
        quotation=quotation,
        risk_score=quotation.blended_risk_score,
        risk_band=quotation.risk_band,
        reason=breakdown.explanation,
    )
    for index, role in enumerate(chain, start=1):
        ApprovalStep.objects.create(
            request=request,
            sequence=index,
            role_required=role,
            assignee=_resolve_assignee(quotation, role),
        )
    return request


def _resolve_assignee(quotation: Quotation, role: str) -> User | None:
    """Prefer the rep's own team manager, else anyone holding the role."""
    if role == Role.SALES_MANAGER:
        team = quotation.owner_rep.sales_team
        if team and team.manager_id:
            return team.manager
    return User.objects.filter(role=role, is_active=True).order_by("id").first()


@transaction.atomic
def act(
    request: ApprovalRequest,
    *,
    actor: User,
    decision: str,
    note: str = "",
) -> ApprovalRequest:
    """Approve, reject, or return the current step.

    Advances to the next step, or closes the request and moves the quotation.
    """
    if request.status != ApprovalStatus.PENDING:
        raise InvalidTransition(
            "This approval request is already closed", current_status=request.status
        )

    step = request.current_step
    if step is None:
        raise InvalidTransition("No pending step on this request")

    # Admins can act on any step; everyone else must hold the required role.
    if actor.role not in (step.role_required, Role.ADMIN):
        raise PermissionDenied(f"This step requires role {step.role_required}")

    if decision in (ApprovalStatus.REJECTED, ApprovalStatus.RETURNED) and not note.strip():
        raise ValidationError("A reason is required when rejecting or returning a quotation")

    step.status = decision
    step.decision_note = note
    step.acted_by = actor
    step.acted_at = timezone.now()
    step.save()

    quotation = request.quotation

    if decision == ApprovalStatus.APPROVED:
        remaining = request.steps.filter(status=ApprovalStatus.PENDING).exists()
        if remaining:
            # Hand off to the next approver (e.g. Manager -> Finance).
            quotation_services.record_event(
                quotation, QuotationEventType.APPROVED, actor=actor, note=note, step=step.sequence
            )
            return request
        _close(request, ApprovalStatus.APPROVED)
        quotation_services.transition(quotation, QuotationStatus.APPROVED, actor=actor)
        quotation_services.record_event(
            quotation, QuotationEventType.APPROVED, actor=actor, note=note, final=True
        )
        return request

    if decision == ApprovalStatus.REJECTED:
        _close(request, ApprovalStatus.REJECTED)
        quotation_services.transition(quotation, QuotationStatus.REJECTED, actor=actor)
        quotation_services.record_event(
            quotation, QuotationEventType.REJECTED, actor=actor, note=note
        )
        return request

    if decision == ApprovalStatus.RETURNED:
        _close(request, ApprovalStatus.RETURNED)
        quotation_services.transition(quotation, QuotationStatus.DRAFT, actor=actor)
        quotation_services.record_event(
            quotation, QuotationEventType.RETURNED, actor=actor, note=note
        )
        return request

    raise ValidationError(f"Unknown decision {decision}")


def _close(request: ApprovalRequest, status: str) -> None:
    request.status = status
    request.closed_at = timezone.now()
    request.save(update_fields=["status", "closed_at", "updated_at"])
    # Steps never reached are skipped, not left dangling as "pending".
    request.steps.filter(status=ApprovalStatus.PENDING).update(status=ApprovalStatus.SKIPPED)
