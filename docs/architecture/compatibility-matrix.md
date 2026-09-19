# Phase 1 Compatibility Matrix

Verified on 2026-09-19 against the local Docker Compose stack. Image references are immutable digest pins; Python and frontend dependencies are additionally locked by `backend/uv.lock` and `frontend/package-lock.json`.

| Component | Exact version | Digest / lock reference | Official source | Observed result |
|---|---:|---|---|---|
| OpenSearch | 3.8.0 | `sha256:fafe3fc3587088674669235575aa166228c48bdb940294a8cdbbc1da75236a40` | [OpenSearch 3.8.0 release](https://github.com/opensearch-project/OpenSearch/releases/tag/3.8.0) | Healthy with security enabled; probe documents persisted. |
| OpenSearch Dashboards | 3.8.0 | `sha256:7fb7ec1b33f1ef49796dc31180f17f227361263c15bb19c56a8a6e5a38852bbd` | [Dashboards 3.8.0 release](https://github.com/opensearch-project/OpenSearch-Dashboards/releases/tag/3.8.0) | Running and authenticated to OpenSearch; browser check deferred. |
| Data Prepper | 2.16.0 | `sha256:6e74ebeddfd66549f623e6f3b8131111b34e85695f54bd68aac7563e80d6b546` | [Data Prepper 2.16.0 release](https://github.com/opensearch-project/data-prepper/releases/tag/2.16.0) | Accepted OTLP logs, metrics, and traces; emitted native service map. |
| OTel Collector Contrib | 0.161.0 | `sha256:fd328de2552466ad78385e1b1289c3f2402b1c45f265b252aab1955b42845ac1` | [Collector Contrib v0.161.0 release](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.161.0) | OTLP receiver, batching, memory limit, retry queue, health, and file storage active. |
| Python | 3.12.12-slim | `sha256:f3fa41d74a768c2fce8016b98c191ae8c1bacd8f1152870a3f9f87d350920b7c` | [Python official image](https://hub.docker.com/_/python) | API and probe images built and ran. |
| uv | 0.11.18 | `sha256:78bc42400d77b0678ba95765305c826652ed5431f399257271dda681d0318f03` | [uv 0.11.18 release](https://github.com/astral-sh/uv/releases/tag/0.11.18) | Frozen backend environment installed. |
| Node.js | 24.21.0-alpine | `sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1` | [Node.js v24.21.0 release](https://github.com/nodejs/node/releases/tag/v24.21.0) | Frontend image built and shell served. |
| OpenTelemetry Python API/SDK/exporters | 1.44.0 | `apps/uv.lock` | [OpenTelemetry Python v1.44.0](https://github.com/open-telemetry/opentelemetry-python/releases/tag/v1.44.0) | Real traces, logs, and metrics exported through the Collector and persisted. |
| OpenTelemetry Python instrumentation/semantic conventions | 0.65b0 | `apps/uv.lock` | [OpenTelemetry Python Contrib v0.65b0](https://github.com/open-telemetry/opentelemetry-python-contrib/releases/tag/v0.65b0) | FastAPI and HTTPX propagation verified across all three containers. |

The deadline-reduced gate did not repeat the authenticated plugin inventory. Prior configuration creates no detector. Plugin inventory verification is deferred to Phase 9 hardening.
