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
    if ENV_FILE.exists():
        print("Local .env already exists; left unchanged.")
        return
    lines = [
        "OPENSEARCH_ADMIN_USERNAME=admin",
        f"OPENSEARCH_ADMIN_PASSWORD={password()}",
        "OPENSEARCH_API_USERNAME=aiops-api",
        f"OPENSEARCH_API_PASSWORD={password()}",
        "OPENSEARCH_DATA_PREPPER_USERNAME=data-prepper",
        f"OPENSEARCH_DATA_PREPPER_PASSWORD={password()}",
        "",
    ]
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print("Generated ignored local .env credentials.")


if __name__ == "__main__":
    main()
