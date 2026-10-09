from decimal import Decimal

import pytest

from lerp.approvals import services
from lerp.approvals.models import ApprovalPolicy, ApprovalRequest
from lerp.approvals.services import Band, NotAuthorised, SegregationOfDutiesError
from lerp.audit.models import AuditEvent
from lerp.tenancy.context import tenant_context
from lerp.tenancy.models import Role

pytestmark = pytest.mark.django_db

AP_BANDS = [
    Band(Decimal("0"), Decimal("50000"), Role.APPROVER),
    Band(Decimal("50000"), None, Role.CFO, approvals_required=2),
]


@pytest.fixture
def people(tenant_a, make_user):
    return {
        "maker": make_user("maker", tenant_a, roles=[Role.TENANT_ADMIN]),
        "checker": make_user("checker", tenant_a, roles=[Role.TENANT_ADMIN]),
        "clerk": make_user("clerk", tenant_a, roles=[Role.AP_CLERK, Role.APPROVER]),
        "approver": make_user("approver", tenant_a, roles=[Role.APPROVER]),
        "cfo1": make_user("cfo1", tenant_a, roles=[Role.CFO]),
        "cfo2": make_user("cfo2", tenant_a, roles=[Role.CFO]),
    }


@pytest.fixture
def active_policy(tenant_a, people):
    with tenant_context(tenant_a):
        policy = services.create_policy(
            document_type="ap_invoice", bands=AP_BANDS, created_by=people["maker"]
        )
        return services.activate_policy(policy, activated_by=people["checker"])


def submit(entity, people, amount: str, ref="INV-1"):
    return services.submit(
        legal_entity=entity,
        document_type="ap_invoice",
        document_ref=ref,
        amount=Decimal(amount),
        currency="MYR",
        requested_by=people["clerk"],
    )


def test_policy_maker_cannot_activate_it(tenant_a, people):
    with tenant_context(tenant_a):
        policy = services.create_policy(
            document_type="ap_invoice", bands=AP_BANDS, created_by=people["maker"]
        )
        with pytest.raises(SegregationOfDutiesError):
            services.activate_policy(policy, activated_by=people["maker"])
        with pytest.raises(NotAuthorised):
            services.activate_policy(policy, activated_by=people["approver"])


def test_new_version_retires_the_old_one(tenant_a, people, active_policy):
    with tenant_context(tenant_a):
        v2 = services.create_policy(
            document_type="ap_invoice", bands=AP_BANDS, created_by=people["checker"]
        )
        services.activate_policy(v2, activated_by=people["maker"])
        statuses = dict(ApprovalPolicy.objects.values_list("version", "status"))
        assert statuses == {1: "retired", 2: "active"}


@pytest.mark.parametrize(
    "bands",
    [
        [],
        [Band(Decimal("10"), None, Role.APPROVER)],  # doesn't start at 0
        [Band(Decimal("0"), Decimal("100"), Role.APPROVER)],  # top band not open-ended
        [
            Band(Decimal("0"), Decimal("100"), Role.APPROVER),
            Band(Decimal("200"), None, Role.CFO),  # gap
        ],
        [Band(Decimal("0"), None, "janitor")],
    ],
)
def test_decision_tables_must_cover_every_amount_once(tenant_a, people, bands):
    with tenant_context(tenant_a), pytest.raises(services.ApprovalError):
        services.create_policy(document_type="ap_invoice", bands=bands, created_by=people["maker"])


def test_amount_picks_the_band(tenant_a, entity_a, people, active_policy):
    with tenant_context(tenant_a):
        small = submit(entity_a, people, "49999.99", "INV-1")
        large = submit(entity_a, people, "50000.00", "INV-2")
        assert (small.required_role, small.approvals_required) == (Role.APPROVER, 1)
        assert (large.required_role, large.approvals_required) == (Role.CFO, 2)


def test_requester_cannot_approve_their_own_request(tenant_a, entity_a, people, active_policy):
    with tenant_context(tenant_a):
        request = submit(entity_a, people, "100.00")
        # The clerk holds the approver role too, but segregation of duties wins.
        with pytest.raises(SegregationOfDutiesError):
            services.decide(request, approver=people["clerk"], approve=True)


def test_approver_needs_the_required_role(tenant_a, entity_a, people, active_policy):
    with tenant_context(tenant_a):
        request = submit(entity_a, people, "75000.00")
        with pytest.raises(NotAuthorised):
            services.decide(request, approver=people["approver"], approve=True)


def test_two_cfo_approvals_complete_a_large_request(tenant_a, entity_a, people, active_policy):
    with tenant_context(tenant_a):
        request = submit(entity_a, people, "75000.00")
        request = services.decide(request, approver=people["cfo1"], approve=True)
        assert request.status == ApprovalRequest.Status.PENDING
        with pytest.raises(services.ApprovalError):
            services.decide(request, approver=people["cfo1"], approve=True)
        request = services.decide(request, approver=people["cfo2"], approve=True)
        assert request.status == ApprovalRequest.Status.APPROVED and request.decided_at
        actions = list(AuditEvent.objects.values_list("action", flat=True))
        assert actions[-3:] == ["approval.submitted", "approval.approved", "approval.approved"]


def test_one_rejection_rejects(tenant_a, entity_a, people, active_policy):
    with tenant_context(tenant_a):
        request = submit(entity_a, people, "100.00")
        request = services.decide(request, approver=people["approver"], approve=False)
        assert request.status == ApprovalRequest.Status.REJECTED
        with pytest.raises(services.ApprovalError):
            services.decide(request, approver=people["cfo1"], approve=True)


def test_money_must_be_decimal(tenant_a, entity_a, people, active_policy):
    with tenant_context(tenant_a), pytest.raises(TypeError):
        services.submit(
            legal_entity=entity_a,
            document_type="ap_invoice",
            document_ref="INV-1",
            amount=100.0,
            currency="MYR",
            requested_by=people["clerk"],
        )
