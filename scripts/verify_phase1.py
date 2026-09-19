import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]


def run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMPOSE, *args], cwd=ROOT, check=True, text=True, capture_output=capture
    )


def verify_ports() -> None:
    rendered = run("config", "--format", "json", capture=True).stdout
    config = json.loads(rendered)
    expected = {
        "api": {("127.0.0.1", 8000)},
        "frontend": {("127.0.0.1", 4173)},
        "opensearch-dashboards": {("127.0.0.1", 5601)},
    }
    observed: dict[str, set[tuple[str, int]]] = {}
    for service, definition in config["services"].items():
        bindings = set()
        for port in definition.get("ports", []):
            bindings.add((port.get("host_ip", ""), int(port["published"])))
        if bindings:
            observed[service] = bindings
    if observed != expected:
        raise AssertionError(f"Unsafe/unexpected published ports: {observed}")
    print("Published ports: api, frontend, dashboards on 127.0.0.1 only")


def wait_status(path: str, expected: int, timeout: int = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"http://127.0.0.1:8000{path}", timeout=3.0)
            if response.status_code == expected:
                return response.json()
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise AssertionError(f"{path} did not reach HTTP {expected}")


def main() -> None:
    verify_ports()
    assert wait_status("/health", 200)["status"] == "ok"
    assert wait_status("/ready", 200)["status"] == "ready"
    env = {key: value for key, value in os.environ.items() if "PASSWORD" not in key.upper()}
    del env
    try:
        run("stop", "opensearch")
        assert wait_status("/health", 200, 30)["status"] == "ok"
        assert wait_status("/ready", 503, 60)["status"] == "not_ready"
    finally:
        run("start", "opensearch")
    assert wait_status("/ready", 200, 180)["status"] == "ready"
    run("--profile", "tools", "run", "--rm", "bootstrap")
    run("--profile", "tools", "run", "--rm", "bootstrap")
    artifact = ROOT / "artifacts" / "latest-probe.json"
    if not artifact.exists():
        raise AssertionError("Real compatibility probe artifact is missing")
    print("Phase 1 verification passed")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, subprocess.CalledProcessError) as exc:
        print(f"Phase 1 verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
