from django.db import DatabaseError, connection
from ninja import NinjaAPI, Schema, Status
from ninja.security import django_auth

from lerp.tenancy.models import Membership

api = NinjaAPI(title="LERP API", version="0.1.0")


class HealthOut(Schema):
    status: str
    database: str


class TenantOut(Schema):
    slug: str
    name: str


class MeOut(Schema):
    username: str
    tenants: list[TenantOut]
    current_tenant: str | None


@api.get("/health", response={200: HealthOut, 503: HealthOut}, auth=None)
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return Status(503, {"status": "degraded", "database": "unavailable"})
    return Status(200, {"status": "ok", "database": "ok"})


@api.get("/me", response=MeOut, auth=django_auth)
def me(request):
    memberships = Membership.objects.filter(user=request.user, is_active=True).select_related(
        "tenant"
    )
    return {
        "username": request.user.get_username(),
        "tenants": [m.tenant for m in memberships],
        "current_tenant": request.tenant.slug if request.tenant else None,
    }
