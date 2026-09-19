from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.health import router
from app.opensearch.client import DependencyResult


class FakeSettings:
    build_version = "test-build"


class FakeOpenSearch:
    def __init__(self, cluster: DependencyResult, bootstrap: DependencyResult) -> None:
        self.cluster_result = cluster
        self.bootstrap_result = bootstrap
        self.cluster_calls = 0

    async def cluster(self) -> DependencyResult:
        self.cluster_calls += 1
        return self.cluster_result

    async def bootstrap(self) -> DependencyResult:
        return self.bootstrap_result


def make_client(fake: FakeOpenSearch) -> TestClient:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = FakeSettings()
        app.state.opensearch = fake
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(router)
    return TestClient(app)


def test_health_is_dependency_free() -> None:
    fake = FakeOpenSearch(DependencyResult("fail", "unreachable"), DependencyResult("fail"))
    with make_client(fake) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "aiops-api"
    assert datetime.fromisoformat(response.json()["checked_at"].replace("Z", "+00:00"))
    assert fake.cluster_calls == 0


def test_ready_reports_dependency_failure_without_details() -> None:
    fake = FakeOpenSearch(DependencyResult("fail", "unreachable"), DependencyResult("fail"))
    with make_client(fake) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["checks"][1]["reason_code"] == "unreachable"


def test_ready_passes_all_required_checks() -> None:
    fake = FakeOpenSearch(DependencyResult("pass"), DependencyResult("pass"))
    with make_client(fake) as client:
        response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert [item["name"] for item in response.json()["checks"]] == [
        "configuration",
        "opensearch",
        "bootstrap",
    ]
