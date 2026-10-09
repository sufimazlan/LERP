# Architecture decision records

Short records of the decisions that shape LERP. The reasoning, sources and alternatives behind each one are in [architecture-plan.md](architecture-plan.md); the section numbers below point there. A record changes only through a new record that replaces it.

## ADR-001: Rent the ledger, build the process layer

**Status:** accepted, 9 Oct 2026 · plan §5.1, §8

**Decision:** LERP is a multi-tenant operations platform (documents, approvals, workflows, AI, analytics) that posts into a ledger it doesn't own. Every ledger sits behind one interface, `LedgerPort` (`backend/lerp/ledger/ports.py`), with one adapter per ledger: the pilot's existing system first, then ERPNext v16 as the bundled default. Every command carries an external reference and is idempotent.

**Why:** a credible GL, tax, close and consolidation would take an estimated 18–30 person-months to match what ERPNext ships free, and customers don't pay extra for it. The platform is where the differentiation is.

**Revisit when:** there are 4+ engineers and paying tenants need ledger behaviour no adapter can configure (gate G6). Then write a native adapter and move tenants one at a time.

## ADR-002: One shared database, isolation enforced by PostgreSQL

**Status:** accepted · plan §5.4

**Decision:** all tenants share one database. Every tenant-owned table has a `tenant_id`, forced row-level security keyed on `app.tenant_id` (set per transaction with `set_config(..., true)`), and composite `(tenant_id, id)` foreign keys. ORM managers filter by tenant as a second line of defence. Primary keys are UUIDv7. A tenant registry (`Tenant.db_alias`) lets any tenant move to its own database later.

**Why:** it costs almost nothing now; retrofitting tenancy later means touching every query. Enforcing it in the database means a missed filter in application code can't leak data.

**Guard rails:** a test fails if any `TenantScopedModel` table lacks forced row-level security, and the test suite refuses to run as a role that can bypass it.

**Revisit when:** an enterprise or regulated customer pays for dedicated infrastructure.

## ADR-003: Two database roles

**Status:** accepted · plan §5.4

**Decision:** `lerp_owner` owns the schema and runs migrations. The web app connects as `lerp_app`, which can read and write rows but can't alter tables, own them or bypass row-level security. Neither is a superuser.

**Why:** a SQL injection or a bug in the app can't switch off tenant isolation or the audit trigger.

## ADR-004: Money paths are deterministic; AI only proposes

**Status:** accepted · plan §5.3, §5.5

**Decision:** business processes are code and data: state machines, versioned decision tables (`backend/lerp/approvals`) and, later, durable workflows. AI fills fields, suggests and explains; its output is a proposal until a rule or a person accepts it. Money is `Decimal`, never float. Posted entries are reversed, never edited. Every financial and AI action lands in a hash-chained, append-only audit trail that the database itself protects.

**Why:** duplicate postings, unbalanced journals and fraud are stopped by the database and one posting service, not by careful users or careful models.

## ADR-005: AI is routed by policy and capped by budget

**Status:** accepted · plan §5.2, §7

**Decision:** every model call goes through one gateway (`backend/lerp/ai/gateway.py`). AI is off for a new tenant. Restricted data and local-only tenants use local models only. Hosted calls are redacted first, need a monthly RM budget above zero, are metered per tenant, and default to the cheapest small model (Claude Haiku 5.5, US$0.10 / 0.50 per million tokens). A hosted model with no configured price is refused.

**Why:** at LERP's volumes, local inference is a privacy decision, not a cost decision. A rented GPU at about RM 2,000 a month buys far more tokens than 50–200 ERP users generate.

**Revisit when:** a tenant forbids data egress (add a GPU tier), or hosted spend stays above about RM 2,000 a month.

## ADR-006: Minimum-cost defaults

**Status:** accepted · plan §9, §10E

**Decision:** run the smallest stack that is still credible: one PostgreSQL and one app container under Docker Compose on a single small VM in Malaysia or Singapore. PostgreSQL carries data, tenancy, audit, and later queues and workflows (DBOS) and vectors (pgvector, already in the database image). WhiteNoise serves static files, so there is no separate web-server container. Everything is open source with no per-user licence.

Deferred until a trigger fires:

| Deferred | Add it when |
|---|---|
| Keycloak (OIDC, MFA, Organizations) | The ledger needs single sign-on, a customer asks for SSO, or finance users go live (MFA is mandatory for them). Until then Django sessions keep the stack at two containers. |
| DBOS durable workflows | The first background job or multi-step workflow (OCR, ledger sync) lands in Phase 2 |
| Object storage (S3-compatible) | The first uploaded document |
| Valkey cache | Rate limits or locks outgrow PostgreSQL |
| Temporal, Kafka, Kubernetes, a vector database, GPUs | The written triggers in plan §10E |

**Why:** infrastructure for a proof of concept should cost RM 25–150 a month (plan §9.2). Each extra service adds memory, operations time and something else to secure.
