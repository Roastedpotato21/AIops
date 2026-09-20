# AIOps Demo Script

Target duration: 2 minutes 45 seconds. Use the persisted, visibly labeled development fixture for the incident/investigation portion unless genuine RCF has reached READY.

## 0:00–0:20 — Problem

“Distributed systems produce plenty of telemetry, but operators still lose time connecting a symptom to its service, impact, supporting traces, and a safe next step. This project turns OpenTelemetry data into deterministic, evidence-backed incidents without giving an AI agent operational write access.”

Show the Overview page and the three services.

## 0:20–1:50 — Working product

### 0:20–0:45 — Live telemetry

Run bounded normal traffic:

```console
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile load run --rm -e LOAD_DURATION_SECONDS=20 -e LOAD_REQUESTS_PER_SECOND=2 load-generator
```

Open a service page.

Say: “Order calls Payment and Inventory in one distributed trace. Traces, correlated logs, and metrics go through the Collector and Data Prepper into OpenSearch. The worker computes one-minute p95 latency and error rate from completed server spans.”

### 0:45–1:15 — Incident and evidence

Open the persisted Payment incident.

Say: “This incident is visibly marked FIXTURE because the native RCF model was still warming. We never present it as a real anomaly. The downstream path is real and persisted: deterministic incident ID, frozen baseline, impact severity, chronology, and a bounded 33-item evidence bundle.”

Expand an anomaly/metric item, a log or span, and the dependency edge. Point to the evidence ID and quality/provenance fields.

### 1:15–1:50 — Safe investigation

Open the succeeded investigation.

Say: “The investigation is asynchronous and persisted in OpenSearch. Its worker is separate from the incident engine. The agent has exactly seven read-only tools, every tool call is host-scoped, and every material claim must cite stored evidence.”

Point out:

- `insufficient_evidence` and low confidence;
- no suspected root service;
- evidence citations;
- explicit fixture and deterministic-provider limitations;
- no executed remediation.

## 1:50–2:20 — Architecture, OpenSearch, and AWS

Show the README architecture diagram.

Say: “OpenSearch is the only application datastore. It stores telemetry, one-minute features, native RCF state/results, normalized anomalies, incidents, immutable evidence, investigation jobs, and worker progress. Separate OpenSearch roles enforce least privilege.”

“The same Compose topology is ready for Phase 10 on AWS. The public deployment will add a single TLS-authenticated edge, private storage/ingestion networks, retention enforcement, snapshots, disk alarms, and target-shape performance evidence.”

Do not show a deployment URL until Phase 10 replaces `<PHASE_10_URL_PENDING>`.

## 2:20–2:45 — Evidence, limitations, and learning

Say: “The local beta passed restart persistence, an OpenSearch outage/recovery cycle, live least-privilege checks, and browser verification. The six native detectors are real but still in INIT, so genuine positive RCF evidence remains pending and nothing was fabricated.”

Close with: “The core lesson was to keep anomaly scoring, deterministic incident state, and probabilistic investigation separate. That makes uncertainty visible and keeps operations safe.”

## Presenter checklist

- Confirm `/health` and `/ready` are 200 before recording.
- Confirm the incident still displays `FIXTURE`.
- Do not enable public ports, show `.env`, or open OpenSearch credentials.
- Do not claim the deterministic provider is a live external LLM.
- Do not claim capacity, high availability, or a positive native anomaly.
- Use [the accepted screenshot](../assets/screenshots/phase9-persisted-incident.png) if the live browser becomes unavailable.
