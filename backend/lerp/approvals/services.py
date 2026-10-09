from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from lerp.approvals.models import ApprovalDecision, ApprovalPolicy, ApprovalRequest, ApprovalRule
from lerp.audit import services as audit
from lerp.tenancy.models import LegalEntity, Role, has_role


class ApprovalError(Exception):
    pass


class SegregationOfDutiesError(ApprovalError):
    """The same person tried to act on both sides of a control."""


class NotAuthorised(ApprovalError):
    pass


@dataclass(frozen=True)
class Band:
    min_amount: Decimal
    max_amount: Decimal | None
    required_role: str
    approvals_required: int = 1


def create_policy(
    *, document_type: str, bands: list[Band], created_by, currency: str = "MYR"
) -> ApprovalPolicy:
    """Create a draft policy. Bands must cover every amount from 0 upward exactly once."""
    if not has_role(created_by, Role.TENANT_ADMIN):
        raise NotAuthorised("Only a tenant admin can create approval policies.")
    _check_bands(bands)
    with transaction.atomic():
        latest = (
            ApprovalPolicy.objects.filter(document_type=document_type).order_by("-version").first()
        )
        policy = ApprovalPolicy.objects.create(
            document_type=document_type,
            version=latest.version + 1 if latest else 1,
            currency=currency,
            created_by=created_by,
        )
        for band in bands:
            ApprovalRule.objects.create(
                policy=policy,
                min_amount=band.min_amount,
                max_amount=band.max_amount,
                required_role=band.required_role,
                approvals_required=band.approvals_required,
            )
        audit.record(
            "approval_policy.created",
            object_type="approval_policy",
            object_id=policy.pk,
            actor=created_by,
            data={"document_type": document_type, "version": policy.version},
        )
    return policy


def activate_policy(policy: ApprovalPolicy, *, activated_by) -> ApprovalPolicy:
    """Maker-checker: a second tenant admin activates the policy; the previous one retires."""
    if not has_role(activated_by, Role.TENANT_ADMIN):
        raise NotAuthorised("Only a tenant admin can activate approval policies.")
    if activated_by.pk == policy.created_by_id:
        raise SegregationOfDutiesError(
            "A policy must be activated by someone other than its maker."
        )
    with transaction.atomic():
        policy = ApprovalPolicy.objects.select_for_update().get(pk=policy.pk)
        if policy.status != ApprovalPolicy.Status.DRAFT:
            raise ApprovalError(
                f"Only a draft policy can be activated; this one is {policy.status}."
            )
        ApprovalPolicy.objects.filter(
            document_type=policy.document_type, status=ApprovalPolicy.Status.ACTIVE
        ).update(status=ApprovalPolicy.Status.RETIRED)
        policy.status = ApprovalPolicy.Status.ACTIVE
        policy.activated_by = activated_by
        policy.activated_at = timezone.now()
        policy.save(update_fields=["status", "activated_by", "activated_at"])
        audit.record(
            "approval_policy.activated",
            object_type="approval_policy",
            object_id=policy.pk,
            actor=activated_by,
            data={"document_type": policy.document_type, "version": policy.version},
        )
    return policy


def submit(
    *,
    legal_entity: LegalEntity,
    document_type: str,
    document_ref: str,
    amount: Decimal,
    currency: str,
    requested_by,
) -> ApprovalRequest:
    if not isinstance(amount, Decimal):
        raise TypeError("Money amounts must be Decimal, never float.")
    policy = ApprovalPolicy.objects.filter(
        document_type=document_type, status=ApprovalPolicy.Status.ACTIVE
    ).first()
    if policy is None:
        raise ApprovalError(f"No active approval policy for {document_type!r}.")
    if currency != policy.currency:
        raise ApprovalError(f"The {document_type} policy is in {policy.currency}, not {currency}.")
    rule = _matching_rule(policy, amount)
    with transaction.atomic():
        request = ApprovalRequest.objects.create(
            legal_entity=legal_entity,
            policy=policy,
            document_type=document_type,
            document_ref=document_ref,
            amount=amount,
            currency=currency,
            required_role=rule.required_role,
            approvals_required=rule.approvals_required,
            requested_by=requested_by,
        )
        audit.record(
            "approval.submitted",
            object_type="approval_request",
            object_id=request.pk,
            actor=requested_by,
            data={
                "document_type": document_type,
                "document_ref": document_ref,
                "amount": amount,
                "currency": currency,
                "policy_version": policy.version,
                "required_role": rule.required_role,
            },
        )
    return request


def decide(
    request: ApprovalRequest, *, approver, approve: bool, comment: str = ""
) -> ApprovalRequest:
    with transaction.atomic():
        request = ApprovalRequest.objects.select_for_update().get(pk=request.pk)
        if request.status != ApprovalRequest.Status.PENDING:
            raise ApprovalError(f"This request is already {request.status}.")
        if approver.pk == request.requested_by_id:
            raise SegregationOfDutiesError("Nobody can approve their own request.")
        if not has_role(approver, request.required_role, request.legal_entity):
            raise NotAuthorised(f"Approving this request needs the {request.required_role} role.")
        if request.decisions.filter(approver=approver).exists():
            raise ApprovalError("You have already decided on this request.")
        ApprovalDecision.objects.create(
            request=request, approver=approver, approved=approve, comment=comment
        )
        if not approve:
            request.status = ApprovalRequest.Status.REJECTED
        elif request.decisions.filter(approved=True).count() >= request.approvals_required:
            request.status = ApprovalRequest.Status.APPROVED
        if request.status != ApprovalRequest.Status.PENDING:
            request.decided_at = timezone.now()
        request.save(update_fields=["status", "decided_at"])
        audit.record(
            "approval.approved" if approve else "approval.rejected",
            object_type="approval_request",
            object_id=request.pk,
            actor=approver,
            data={"status": request.status, "comment": comment},
        )
    return request


def _matching_rule(policy: ApprovalPolicy, amount: Decimal) -> ApprovalRule:
    for rule in policy.rules.all():
        if amount >= rule.min_amount and (rule.max_amount is None or amount < rule.max_amount):
            return rule
    raise ApprovalError(f"No band in {policy} covers {amount}.")


def _check_bands(bands: list[Band]) -> None:
    if not bands:
        raise ApprovalError("A policy needs at least one band.")
    expected_min = Decimal(0)
    for i, band in enumerate(sorted(bands, key=lambda b: b.min_amount)):
        if band.min_amount != expected_min:
            raise ApprovalError(
                f"Bands must be contiguous from 0; a band should start at {expected_min}."
            )
        if band.required_role not in Role.values:
            raise ApprovalError(f"Unknown role {band.required_role!r}.")
        is_last = i == len(bands) - 1
        if band.max_amount is not None and band.max_amount <= band.min_amount:
            raise ApprovalError("Each band's upper limit must be above its lower limit.")
        if band.max_amount is None and not is_last:
            raise ApprovalError("Only the highest band may be open-ended.")
        if is_last and band.max_amount is not None:
            raise ApprovalError("The highest band must be open-ended, so every amount is covered.")
        expected_min = band.max_amount
