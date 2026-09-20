from app.opensearch.roles import WORKER_ROLES

WRITE_ACTIONS = {"read", "write"}


def _permissions(role_name: str) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for permission in WORKER_ROLES[role_name]["index_permissions"]:
        for pattern in permission["index_patterns"]:
            result.setdefault(pattern, set()).update(permission["allowed_actions"])
    return result


def test_worker_roles_are_separate_and_have_no_administrative_actions():
    assert set(WORKER_ROLES) == {
        "aiops_aggregation_worker_role",
        "aiops_incident_worker_role",
        "aiops_investigation_worker_role",
    }
    for role in WORKER_ROLES.values():
        assert role["cluster_permissions"] == ["indices:data/write/bulk"]
        actions = {
            action
            for permission in role["index_permissions"]
            for action in permission["allowed_actions"]
        }
        assert actions <= WRITE_ACTIONS


def test_aggregation_worker_can_only_read_spans_and_own_metrics_state():
    permissions = _permissions("aiops_aggregation_worker_role")
    assert permissions == {
        "otel-v1-apm-span*": {"read"},
        "aiops-service-metrics-v1*": WRITE_ACTIONS,
        "aiops-worker-state-v1": WRITE_ACTIONS,
    }


def test_incident_worker_cannot_write_raw_telemetry_or_investigations():
    permissions = _permissions("aiops_incident_worker_role")
    assert permissions["otel-v1-apm-span*"] == {"read"}
    assert permissions["aiops-logs*"] == {"read"}
    assert permissions["aiops-anomalies-v1*"] == WRITE_ACTIONS
    assert permissions["aiops-incidents-v1*"] == WRITE_ACTIONS
    assert "aiops-investigations-v1*" not in permissions


def test_investigation_worker_writes_only_jobs_and_evidence():
    permissions = _permissions("aiops_investigation_worker_role")
    writable = {pattern for pattern, actions in permissions.items() if "write" in actions}
    assert writable == {"aiops-investigations-v1*", "aiops-evidence-v1*"}
    assert permissions["aiops-incidents-v1*"] == {"read"}
    assert permissions["otel-v1-apm-span*"] == {"read"}
