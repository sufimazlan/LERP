from django.http import JsonResponse

from lerp.tenancy.context import tenant_context
from lerp.tenancy.models import Membership, Tenant


class TenantMiddleware:
    """Scope each request to the tenant named in the X-Tenant header.

    The tenant is accepted only if the signed-in user has an active membership in it,
    and the whole request then runs in one tenant-scoped transaction. When Keycloak
    arrives (Phase 1), the organisation claim in the access token replaces the header.
    """

    header = "X-Tenant"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.tenant = None
        slug = request.headers.get(self.header)
        if not slug:
            return self.get_response(request)
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Authentication required."}, status=401)
        membership = (
            Membership.objects.select_related("tenant")
            .filter(
                user=request.user,
                tenant__slug=slug,
                is_active=True,
                tenant__status=Tenant.Status.ACTIVE,
            )
            .first()
        )
        if membership is None:
            return JsonResponse({"detail": "Unknown tenant, or no access to it."}, status=403)
        request.tenant = membership.tenant
        with tenant_context(membership.tenant):
            return self.get_response(request)
