"""Least-privilege OpenSearch role specifications for persistent workers."""

AGGREGATION_WORKER_ROLE = {
    "cluster_permissions": ["indices:data/write/bulk"],
    "index_permissions": [
        {
            "index_patterns": ["otel-v1-apm-span*"],
            "allowed_actions": ["read"],
        },
        {
            "index_patterns": [
                "aiops-service-metrics-v1*",
                "aiops-worker-state-v1",
            ],
            "allowed_actions": ["read", "write"],
        },
    ],
    "tenant_permissions": [],
}

INCIDENT_WORKER_ROLE = {
    "cluster_permissions": ["indices:data/write/bulk"],
    "index_permissions": [
        {
            "index_patterns": [
                "otel-v1-apm-span*",
                "otel-v1-apm-service-map*",
                "aiops-logs*",
                "aiops-service-metrics-v1*",
                "aiops-anomalies-v1*",
                "aiops-incidents-v1*",
                "aiops-evidence-v1*",
            ],
            "allowed_actions": ["read"],
        },
        {
            "index_patterns": [
                "aiops-anomalies-v1*",
                "aiops-incidents-v1*",
                "aiops-evidence-v1*",
                "aiops-worker-state-v1",
            ],
            "allowed_actions": ["write"],
        },
    ],
    "tenant_permissions": [],
}

INVESTIGATION_WORKER_ROLE = {
    "cluster_permissions": ["indices:data/write/bulk"],
    "index_permissions": [
        {
            "index_patterns": [
                "otel-v1-apm-span*",
                "otel-v1-apm-service-map*",
                "aiops-logs*",
                "aiops-metrics-raw*",
                "aiops-service-metrics-v1*",
                "opensearch-ad-plugin-result-aiops-v1*",
                "aiops-incidents-v1*",
                "aiops-evidence-v1*",
            ],
            "allowed_actions": ["read"],
        },
        {
            "index_patterns": [
                "aiops-investigations-v1*",
                "aiops-evidence-v1*",
            ],
            "allowed_actions": ["read", "write"],
        },
    ],
    "tenant_permissions": [],
}

WORKER_ROLES = {
    "aiops_aggregation_worker_role": AGGREGATION_WORKER_ROLE,
    "aiops_incident_worker_role": INCIDENT_WORKER_ROLE,
    "aiops_investigation_worker_role": INVESTIGATION_WORKER_ROLE,
}
