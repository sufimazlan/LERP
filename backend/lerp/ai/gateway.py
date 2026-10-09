"""The single exit for every model call (plan sections 5.2 and 7.1).

Every call is routed by tenant policy and data class, redacted before it leaves for a
hosted model, checked against the tenant's monthly budget, and metered. AI output is
always a proposal: nothing here posts, pays or changes master data.

Cost defaults: AI is off per tenant, a hosted call needs a budget above zero, the
default hosted model is the cheapest small one, and a hosted model with no configured
price is refused.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from lerp.ai.models import AIUsage
from lerp.ai.redaction import redact
from lerp.tenancy.context import TenantContextRequired, current_tenant_id
from lerp.tenancy.models import Tenant


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"  # never leaves for a hosted model


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int


class Provider(Protocol):
    name: str
    is_local: bool

    def complete(
        self, *, model: str, system: str, prompt: str, max_output_tokens: int
    ) -> ProviderResponse: ...


class AIError(Exception):
    pass


class AIDisabled(AIError):
    pass


class AIUnavailable(AIError):
    pass


class BudgetExceeded(AIError):
    pass


@dataclass(frozen=True)
class Route:
    provider: Provider
    model: str
    redact: bool


_providers: dict[str, Provider] = {}


def register_provider(provider: Provider) -> None:
    _providers[provider.name] = provider


def route(tenant: Tenant, data_class: DataClass) -> Route:
    config = settings.LERP_AI
    if tenant.ai_mode == Tenant.AIMode.OFF:
        raise AIDisabled("AI is turned off for this tenant.")
    if tenant.ai_mode == Tenant.AIMode.LOCAL_ONLY or data_class == DataClass.RESTRICTED:
        local = _configured_provider("LOCAL_PROVIDER", must_be_local=True)
        if local is None:
            raise AIUnavailable("This request may only use a local model, and none is configured.")
        return Route(local, config["LOCAL_MODEL"], redact=False)
    hosted = _configured_provider("HOSTED_PROVIDER")
    if hosted is not None:
        return Route(hosted, config["HOSTED_MODEL"], redact=not hosted.is_local)
    local = _configured_provider("LOCAL_PROVIDER", must_be_local=True)
    if local is not None:
        return Route(local, config["LOCAL_MODEL"], redact=False)
    raise AIUnavailable("No AI provider is configured.")


def complete(
    tenant: Tenant,
    *,
    task: str,
    prompt: str,
    system: str = "",
    data_class: DataClass = DataClass.INTERNAL,
    max_output_tokens: int = 1024,
    actor=None,
) -> ProviderResponse:
    if current_tenant_id() != tenant.pk:
        raise TenantContextRequired("AI calls must run inside the calling tenant's context.")
    chosen = route(tenant, data_class)
    if chosen.redact:
        prompt = redact(prompt)
    if not chosen.provider.is_local:
        # A rough upper bound of 3 characters per token. The check is soft: calls already
        # in flight on other workers can overshoot the budget by one call each.
        estimate = cost_myr(chosen.model, (len(system) + len(prompt)) // 3 + 1, max_output_tokens)
        if month_to_date_spend_myr() + estimate > tenant.ai_monthly_budget_myr:
            raise BudgetExceeded(
                f"This call would take AI spend past the tenant's monthly budget of "
                f"RM {tenant.ai_monthly_budget_myr}."
            )
    response = chosen.provider.complete(
        model=chosen.model, system=system, prompt=prompt, max_output_tokens=max_output_tokens
    )
    AIUsage.objects.create(
        task=task,
        provider=chosen.provider.name,
        model=chosen.model,
        is_local=chosen.provider.is_local,
        data_class=data_class,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_myr=(
            Decimal(0)
            if chosen.provider.is_local
            else cost_myr(chosen.model, response.input_tokens, response.output_tokens)
        ),
        actor=actor,
    )
    return response


def cost_myr(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    config = settings.LERP_AI
    try:
        price_in, price_out = config["PRICES_USD_PER_MTOK"][model]
    except KeyError:
        raise AIError(
            f"No price configured for {model!r}; unmetered hosted calls are refused."
        ) from None
    usd = (price_in * input_tokens + price_out * output_tokens) / Decimal(1_000_000)
    return (usd * config["USD_TO_MYR"]).quantize(Decimal("0.000001"))


def month_to_date_spend_myr() -> Decimal:
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = AIUsage.objects.filter(occurred_at__gte=month_start).aggregate(total=Sum("cost_myr"))
    return total["total"] or Decimal(0)


def _configured_provider(key: str, *, must_be_local: bool = False) -> Provider | None:
    name = settings.LERP_AI[key]
    if not name:
        return None
    provider = _providers.get(name)
    if provider is None:
        raise AIUnavailable(f"AI provider {name!r} is configured but not registered.")
    if must_be_local and not provider.is_local:
        raise AIUnavailable(f"{key} names {name!r}, which is not a local provider.")
    return provider
