import pytest

pytestmark = pytest.mark.django_db


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_me_needs_login(client):
    assert client.get("/api/me").status_code == 401


def test_me_lists_tenants_and_the_current_one(client, tenant_a, tenant_b, make_user):
    client.force_login(make_user("ann", tenant_a))
    assert client.get("/api/me").json() == {
        "username": "ann",
        "tenants": [{"slug": "alpha", "name": "Alpha"}],
        "current_tenant": None,
    }
    assert client.get("/api/me", headers={"X-Tenant": "alpha"}).json()["current_tenant"] == "alpha"


def test_tenant_header_needs_a_membership(client, tenant_a, tenant_b, make_user):
    client.force_login(make_user("ann", tenant_a))
    assert client.get("/api/me", headers={"X-Tenant": "beta"}).status_code == 403
    assert client.get("/api/me", headers={"X-Tenant": "nope"}).status_code == 403


def test_tenant_header_needs_login(client, tenant_a):
    assert client.get("/api/me", headers={"X-Tenant": "alpha"}).status_code == 401
