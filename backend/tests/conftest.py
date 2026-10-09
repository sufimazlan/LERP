import pytest

from lerp.tenancy.context import tenant_context
from lerp.tenancy.models import LegalEntity, Membership, RoleGrant, Tenant


@pytest.fixture
def make_tenant(db):
    def make(slug: str, **fields) -> Tenant:
        return Tenant.objects.create(slug=slug, name=slug.title(), **fields)

    return make


@pytest.fixture
def tenant_a(make_tenant):
    return make_tenant("alpha")


@pytest.fixture
def tenant_b(make_tenant):
    return make_tenant("beta")


@pytest.fixture
def make_user(db, django_user_model):
    def make(username: str, tenant: Tenant | None = None, roles=(), legal_entity=None):
        user = django_user_model.objects.create_user(username=username, password="pw")
        if tenant is not None:
            Membership.objects.create(user=user, tenant=tenant)
            with tenant_context(tenant):
                for role in roles:
                    RoleGrant.objects.create(user=user, role=role, legal_entity=legal_entity)
        return user

    return make


@pytest.fixture
def entity_a(tenant_a):
    with tenant_context(tenant_a):
        return LegalEntity.objects.create(code="HQ", name="Alpha Holdings Sdn Bhd")


@pytest.fixture
def entity_b(tenant_b):
    with tenant_context(tenant_b):
        return LegalEntity.objects.create(code="HQ", name="Beta Holdings Sdn Bhd")
