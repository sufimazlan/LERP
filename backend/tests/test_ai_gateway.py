from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from lerp.ai import gateway
from lerp.ai.gateway import AIDisabled, AIUnavailable, BudgetExceeded, DataClass, ProviderResponse
from lerp.ai.models import AIUsage
from lerp.ai.redaction import redact
from lerp.tenancy.context import TenantContextRequired, tenant_context
from lerp.tenancy.models import Tenant

pytestmark = pytest.mark.django_db


@dataclass
class FakeProvider:
    name: str
    is_local: bool
    prompts: list[str] = field(default_factory=list)

    def complete(self, *, model, system, prompt, max_output_tokens):
        self.prompts.append(prompt)
        return ProviderResponse(text="ok", input_tokens=2_500, output_tokens=400)


@pytest.fixture
def providers(settings):
    hosted, local = FakeProvider("fake-hosted", False), FakeProvider("fake-local", True)
    gateway.register_provider(hosted)
    gateway.register_provider(local)
    settings.LERP_AI = {
        **settings.LERP_AI,
        "HOSTED_PROVIDER": "fake-hosted",
        "LOCAL_PROVIDER": "fake-local",
        "LOCAL_MODEL": "qwen3.5-4b",
    }
    return hosted, local


def test_ai_is_off_by_default(make_tenant, providers):
    tenant = make_tenant("quiet")
    assert tenant.ai_mode == Tenant.AIMode.OFF
    with tenant_context(tenant), pytest.raises(AIDisabled):
        gateway.complete(tenant, task="extract", prompt="hello")


def test_hosted_calls_need_a_budget(make_tenant, providers):
    tenant = make_tenant("nobudget", ai_mode=Tenant.AIMode.HYBRID)
    with tenant_context(tenant), pytest.raises(BudgetExceeded):
        gateway.complete(tenant, task="extract", prompt="hello")


def test_hosted_call_is_redacted_metered_and_capped(make_tenant, providers):
    hosted, _ = providers
    tenant = make_tenant(
        "acme", ai_mode=Tenant.AIMode.HYBRID, ai_monthly_budget_myr=Decimal("0.01")
    )
    with tenant_context(tenant):
        gateway.complete(tenant, task="extract", prompt="IC 900101-14-5678, ali@example.com")
        assert hosted.prompts == ["IC [IC], [EMAIL]"]
        usage = AIUsage.objects.get()
        # 2,500 in + 400 out on Haiku 5.5: (0.10 × 2500 + 0.50 × 400) / 1M = US$0.00045
        assert (usage.model, usage.cost_myr) == ("claude-haiku-5-5", Decimal("0.001845"))
        assert gateway.month_to_date_spend_myr() == Decimal("0.001845")
        # Four more calls fit in RM 0.01; the sixth would pass it, so it never leaves.
        for _ in range(4):
            gateway.complete(tenant, task="extract", prompt="hello", max_output_tokens=400)
        assert len(hosted.prompts) == 5
        with pytest.raises(BudgetExceeded):
            gateway.complete(tenant, task="extract", prompt="hello", max_output_tokens=400)
        assert len(hosted.prompts) == 5


def test_restricted_data_only_goes_to_a_local_model(make_tenant, providers):
    hosted, local = providers
    tenant = make_tenant("strict", ai_mode=Tenant.AIMode.HYBRID)  # zero budget is fine locally
    with tenant_context(tenant):
        gateway.complete(
            tenant, task="redact", prompt="IC 900101-14-5678", data_class=DataClass.RESTRICTED
        )
        assert hosted.prompts == [] and local.prompts == ["IC 900101-14-5678"]
        assert AIUsage.objects.get().cost_myr == 0


def test_local_only_tenant_never_reaches_hosted(make_tenant, providers, settings):
    hosted, _ = providers
    settings.LERP_AI = {**settings.LERP_AI, "LOCAL_PROVIDER": ""}
    tenant = make_tenant("onprem", ai_mode=Tenant.AIMode.LOCAL_ONLY)
    with tenant_context(tenant), pytest.raises(AIUnavailable):
        gateway.complete(tenant, task="extract", prompt="hello")
    assert hosted.prompts == []


def test_a_hosted_provider_cannot_pose_as_local(make_tenant, providers, settings):
    settings.LERP_AI = {**settings.LERP_AI, "LOCAL_PROVIDER": "fake-hosted"}
    tenant = make_tenant("trick", ai_mode=Tenant.AIMode.LOCAL_ONLY)
    with tenant_context(tenant), pytest.raises(AIUnavailable, match="not a local provider"):
        gateway.complete(tenant, task="extract", prompt="hello")


def test_unpriced_models_are_refused(make_tenant, providers, settings):
    settings.LERP_AI = {**settings.LERP_AI, "HOSTED_MODEL": "mystery-model"}
    tenant = make_tenant("pricey", ai_mode=Tenant.AIMode.HYBRID, ai_monthly_budget_myr=100)
    with tenant_context(tenant), pytest.raises(gateway.AIError, match="No price"):
        gateway.complete(tenant, task="extract", prompt="hello")


def test_calls_must_run_in_the_tenants_context(make_tenant, providers):
    tenant = make_tenant("ctx", ai_mode=Tenant.AIMode.HYBRID)
    with pytest.raises(TenantContextRequired):
        gateway.complete(tenant, task="extract", prompt="hello")


def test_redaction_leaves_ordinary_text_alone():
    assert redact("Invoice A-1001 total RM 1,234.50") == "Invoice A-1001 total RM 1,234.50"
