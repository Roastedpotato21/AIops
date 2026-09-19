import json
from pathlib import Path


def test_real_compatibility_probe_artifact() -> None:
    artifact = Path("artifacts/latest-probe.json")
    assert artifact.exists(), "Run the real compatibility-probe Compose service first"
    result = json.loads(artifact.read_text(encoding="utf-8"))
    assert result["run_id"]
    assert all(result["checks"].values()), result
    assert result["counts"]["spans"] >= 3
    assert result["counts"]["logs"] >= 3
