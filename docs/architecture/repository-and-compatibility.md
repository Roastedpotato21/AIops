# Repository ownership and compatibility gate

## Target repository layout

This is a target layout, not authorization to implement every folder in Phase1. The root directory may remain named AIops; do not create an extra nested repository solely to match a suggested name.

```text
AIops/
  apps/
    order-service/
    payment-service/
    inventory-service/
    load-generator/
  backend/
    app/
      api/
      incidents/
      detection/
      telemetry/
        aggregation/
      correlation/
      agent/
      opensearch/
      repositories/
      workers/
      models/
      config.py
      main.py
    tests/
    pyproject.toml
    uv.lock
    Dockerfile
  frontend/
    src/
    package.json
    package-lock.json
    Dockerfile
  infra/
    otel/
    data-prepper/
    opensearch/
    proxy/
  contracts/
    domain.md
    processing.md
    agent.md
    api.md
    storage.md
  docs/
    architecture/
    phases/
  scripts/
  tests/
    integration/
    e2e/
    fixtures/otlp/
  docker-compose.yml
  docker-compose.dev.yml
  docker-compose.prod.yml          # Phase10, NOT implemented in Phase1
  .env.example
  .gitignore
  README.md
```

## Module responsibilities

| Path | Owns | Must not own |
|---|---|---|
| backend/app/api | HTTP validation, authentication boundary, DTO assembly, error mapping | Worker loops, query DSL exposed to callers |
| backend/app/incidents | Episode assignment, deterministic lifecycle/severity/recovery, scheduling coordination | LLM interpretation |
| backend/app/detection | Detector specification/registry, native result/status adapter | Custom ML or log anomaly classifier |
| backend/app/telemetry | Service/instance lookup, normalized span/log/native metric views, freshness | Product lifecycle rules |
| backend/app/telemetry/aggregation | Span filters, minute aggregations, finalization/late-data handling | Detector statistical decision |
| backend/app/correlation | Bounded trace/log/dependency lookup, evidence selection and redaction | Claims of proven causality |
| backend/app/agent | Investigator, allowlisted tools, provider adapter, structured report validation | Infrastructure or write tools |
| backend/app/opensearch | Client construction, TLS/auth config, error translation, native field-map adapter support | Domain severity or presentation |
| backend/app/repositories | Named query/write methods, CAS, aliases, persistence envelopes | Arbitrary model-generated queries |
| backend/app/workers | Separate entry points, cancellation, polling, recovery, heartbeat | Running implicitly inside API startup |
| backend/app/models | Pydantic domain/DTO/persistence types and validators | OpenSearch calls or provider dependencies |
| backend/app/config.py | Validated configuration and secret references | Embedded real secrets |
| backend/app/main.py | Application factory/lifespan and router wiring | Detection scheduling |
| frontend | Typed API client and React presentation | OpenSearch access, credentials, fault control |
| apps/order-service | Demo order request and Payment client | Platform backend logic |
| apps/payment-service | Demo payment request and Inventory client | Actual payment credentials or processing |
| apps/inventory-service | Demo inventory behavior | Infrastructure actions |
| apps/load-generator | Traffic and bounded scenario harness; expected outcomes | Product detector/agent inputs |
| infra/otel | Collector receivers/processors/exporters/queue config | Application instrumentation code |
| infra/data-prepper | Signal routes, native processors, sinks, templates integration | Incident rules |
| infra/opensearch | Bootstrap templates/roles/retention and future detector definitions | Browser credentials |
| infra/proxy | Local/deployed routing and later TLS/auth exposure config | Public storage port forwarding |
| contracts | Normative agreed schemas and generated artifacts later | Unreviewed contract drift |
| docs/architecture | ADRs, tested compatibility matrix, ownership | Executable secrets |
| docs/phases | Scoped handoffs and completion evidence | Automatic scope expansion |
| scripts | Bootstrap, compatibility probe, verification helpers | Global identity changes or auto-login |
| tests/integration | Real infrastructure boundary tests | Fake proof of real RCF behavior |
| tests/e2e | Later complete request-to-findings tests | Phase1 product implementation |

Dependencies flow API/workers → domain services → repositories/adapters. Domain models have no I/O. Agent tool implementations call named read services, never the API over HTTP just to reuse logic. One backend image can provide separate API/incident/investigation entry points later; Phase1 starts API only.

## Version policy: VERIFY BEFORE IMPLEMENTATION

No release numbers were guessed. The policy ranges below constrain selection; Sol must check official release/support documentation and record exact versions, compatibility evidence, platform architecture, and image digests in `docs/architecture/compatibility-matrix.md` before finalizing Phase1. Approval of Phase0 authorizes this routine verification, not automatic authentication or paid provisioning.

| Component | Selection policy | Mandatory check |
|---|---|---|
| OpenSearch | Exact stable supported release, `VERIFY BEFORE IMPLEMENTATION`; pin tag AND digest | Official image exists for host architecture; security/AD plugins included; client and template compatibility; disk/kernel/heap requirements |
| OpenSearch Dashboards | Exact same release version as OpenSearch; digest pinned | Login and authenticated cluster connection; compatible plugins; private admin binding |
| Data Prepper | Exact stable release, VERIFY BEFORE IMPLEMENTATION; digest pinned independently of OpenSearch version | OTLP source supports selected transport/encoding; signal output formats match processors; native trace/map templates work against chosen OpenSearch; auth/TLS/env interpolation verified |
| OTel Collector | Exact contrib distribution release/digest, VERIFY BEFORE IMPLEMENTATION | Includes OTLP receiver/exporter, memory_limiter, batch, health_check, file_storage; configuration keys actually supported |
| Python | Project policy `>=3.12,<3.13`; exact supported security patch and base-image digest verified | Compatible with OS client/FastAPI/Pydantic selected; uv lock resolves reproducibly on container OS |
| FastAPI / Pydantic | FastAPI `>=0.115,<1`; Pydantic `>=2.10,<3`; tested exact lock versions, VERIFY BEFORE IMPLEMENTATION | UTC validation, strict models, settings separation, lifespan and generated OpenAPI; do not infer all cross-range combinations supported |
| opensearch-py | Exact tested lock version, VERIFY BEFORE IMPLEMENTATION | Official compatibility with server; TLS/cert verification; sync client calls must not block async event loop |
| React / React DOM | Matching stable major/minor policy `>=19,<20`, exact package-lock versions, VERIFY BEFORE IMPLEMENTATION | Matching type packages and Vite React plugin; shell mounts successfully |
| Vite / TypeScript | Stable exact lock versions, VERIFY BEFORE IMPLEMENTATION | Official Node engine requirements and React plugin compatibility; no guessed latest major |
| Node / npm | Maintained Node LTS at verification date, exact patch/base-image digest; npm version recorded | Meets pinned Vite's engine requirements; npm ci reproduces package-lock; no engine override |
| Docker Engine / Compose | Supported Engine and Compose v2, exact tested client/server versions recorded | Long-form depends_on health/completion conditions, profiles, volumes, secret/env handling and override merging behave as used |
| uv | Exact stable tool version, VERIFY BEFORE IMPLEMENTATION | Frozen lock installation works; document installation rather than auto-login |

Ranges are acceptance policies, not permission for floating runtime resolution. Lock all transitive Python/JS dependencies, pin Docker tags/digests, use `uv sync --frozen` and `npm ci`. Updating a lock/pin requires rerunning affected compatibility checks. If a maintained/security-compatible selection cannot meet a policy range, report the concrete conflict and propose a narrow policy amendment; do not redesign the stack.

Use official sources: [OpenSearch releases](https://opensearch.org/releases.html), [Data Prepper repository/releases](https://github.com/opensearch-project/data-prepper/releases), [Collector releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases), [Python versions](https://devguide.python.org/versions/), [FastAPI releases](https://fastapi.tiangolo.com/release-notes/), [Pydantic](https://docs.pydantic.dev/latest/), [React versions](https://react.dev/versions), [Vite guide](https://vite.dev/guide/), [Node releases](https://nodejs.org/en/about/previous-releases). These links are verification entry points, not assertions of selected versions.

## Required compatibility matrix columns

Component; exact version; image digest/lockfile reference; platform/CPU architecture; official source URL; verification date; command; observed result; limitations. Unrun checks are `NOT RUN`, not passes. Redact secrets from captured commands/output.

## Exact compatibility checks

1. Validate host Docker/Compose, CPU architecture, available memory/disk and OpenSearch host prerequisites. On Windows verify Linux-container/WSL settings; do not silently change global kernel/security settings. Record prerequisites and any required explicit host action.
2. Pull/build exact candidate images. Confirm runtime versions from binaries/APIs and AD plugin list. Confirm OpenSearch and Dashboards version match. Record image digests. Do not create/start RCF detectors.
3. Validate Compose rendered configuration; no publicly bound ingestion/storage/admin ports. Base Compose has no host mappings for internal components. Development override may bind admin inspection to127.0.0.1 only. Inspect **rendered** config; merge behavior can preserve unexpected ports.
4. Bootstrap only probe aliases/templates, roles, and marker. Run twice. No duplicate templates/indexes, destructive index recreation, secret leaks, or privilege escalation to runtime clients.
5. Run fixture-based probe over actual network path: emitter → Collector OTLP → Data Prepper → OpenSearch. Fixed synthetic request trace spans for order/payment/inventory plus correlated log and native gauge/counter/histogram fixtures; clearly tagged `compatibility-probe`, never presented as application telemetry. This is a protocol fixture, not microservice instrumentation.
6. Assert trace IDs/parentage, log trace IDs, service/resource identity, native metric names/units/type/temporality and numeric fields. Wait with bounded deadline for actual service-map output. Capture redacted documents and exact field-map manifest. No guessed field-path assertions.
7. Resend fixture spans with identical IDs and confirm counted unique spans do not increase. Probe midnight/date-routing replay with fixture timestamps in retained range. If only the minimum transport path is possible in Phase1, record unverified replay behavior as a Phase4 blocker, not a pass.
8. Confirm wrong credentials are rejected, runtime TLS behavior matches documented local mode, backend ready->not_ready during storage outage and recovers afterward; health remains live.
9. Restart Collector/Data Prepper/OpenSearch without deleting volumes; stored probe records persist. Document source acknowledgment and queue limitations; this is not a proof of exactly-once delivery.
10. Verify backend OpenAPI and probes; install/build/test frontend shell; verify visible UI, network responses, browser console. No dashboard feature pages.

Phase1 must pass three-signal transport, native mapping compatibility, service relationship generation, and basic restart/probe behavior. Any product-level correctness not yet testable is explicitly handed to its later owning phase. Narrow compatibility failures are resolved within the locked component chain; broader changes return for architectural review.
