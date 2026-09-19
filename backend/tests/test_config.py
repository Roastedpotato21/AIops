import pytest
from pydantic import ValidationError

from app.config import Settings


def test_tls_verification_can_be_disabled_only_in_development() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            opensearch_username="api",
            opensearch_password="a-strong-password",
            opensearch_verify_tls=False,
        )


def test_tls_verification_requires_ca_file() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            opensearch_username="api",
            opensearch_password="a-strong-password",
            opensearch_verify_tls=True,
        )
