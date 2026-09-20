import secrets
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def password(length: int = 36) -> str:
    alphabet = string.ascii_letters + string.digits + "-_!"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(character in group for character in value) for group in (string.ascii_lowercase, string.ascii_uppercase, string.digits, "!")):
            return value


def main() -> None:
    required = [
        "OPENSEARCH_ADMIN_USERNAME=admin",
        f"OPENSEARCH_ADMIN_PASSWORD={password()}",
        "OPENSEARCH_API_USERNAME=aiops-api",
        f"OPENSEARCH_API_PASSWORD={password()}",
        "OPENSEARCH_DATA_PREPPER_USERNAME=data-prepper",
        f"OPENSEARCH_DATA_PREPPER_PASSWORD={password()}",
        "OPENSEARCH_WORKER_USERNAME=aiops-worker",
        f"OPENSEARCH_WORKER_PASSWORD={password()}",
    ]
    existing = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    existing_keys = {
        line.split("=", 1)[0]
        for line in existing.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    additions = [line for line in required if line.split("=", 1)[0] not in existing_keys]
    if not additions:
        print("Local .env credentials already complete; left unchanged.")
        return
    prefix = existing.rstrip("\n")
    content = "\n".join(filter(None, [prefix, *additions, ""])) + "\n"
    ENV_FILE.write_text(content, encoding="utf-8", newline="\n")
    print("Generated missing ignored local .env credentials.")


if __name__ == "__main__":
    main()
