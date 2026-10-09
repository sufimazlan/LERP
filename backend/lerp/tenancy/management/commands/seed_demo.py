from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from lerp.approvals.models import ApprovalPolicy
from lerp.approvals.services import Band, activate_policy, create_policy
from lerp.tenancy.context import tenant_context
from lerp.tenancy.models import LegalEntity, Membership, Role, RoleGrant, Tenant

USERS = {
    "alice": [Role.AP_CLERK],
    "bob": [Role.APPROVER],
    "carol": [Role.CFO, Role.TENANT_ADMIN],
    "dan": [Role.TENANT_ADMIN],
}


class Command(BaseCommand):
    help = "Create a demo tenant with two companies, four users and an AP approval policy."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="lerp-demo", help="Password for every demo user")

    def handle(self, *args, password, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo creates known passwords; run it only with DJANGO_DEBUG=1."
            )
        tenant, _ = Tenant.objects.get_or_create(
            slug="demo", defaults={"name": "Demo Group Sdn Bhd"}
        )
        users = {}
        for username in USERS:
            user, created = get_user_model().objects.get_or_create(username=username)
            if created:
                user.set_password(password)
                user.is_staff = username == "dan"
                user.save()
            Membership.objects.get_or_create(user=user, tenant=tenant)
            users[username] = user

        with tenant_context(tenant):
            for code, name in [("HQ", "Demo Holdings Sdn Bhd"), ("SVC", "Demo Services Sdn Bhd")]:
                LegalEntity.objects.get_or_create(code=code, defaults={"name": name})
            for username, roles in USERS.items():
                for role in roles:
                    RoleGrant.objects.get_or_create(
                        user=users[username], legal_entity=None, role=role
                    )
            if not ApprovalPolicy.objects.filter(
                document_type="ap_invoice", status=ApprovalPolicy.Status.ACTIVE
            ).exists():
                # The example in section 5.3 of the plan: RM 50,000 and above needs the CFO.
                policy = create_policy(
                    document_type="ap_invoice",
                    bands=[
                        Band(Decimal("0"), Decimal("50000"), Role.APPROVER),
                        Band(Decimal("50000"), None, Role.CFO),
                    ],
                    created_by=users["dan"],
                )
                activate_policy(policy, activated_by=users["carol"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Tenant 'demo' is ready. Users {', '.join(USERS)} share the --password value; "
                "dan can sign in at /admin/."
            )
        )
