import pytest

from app.core.errors import ApiError
from app.core.security import create_access_token, create_refresh_token, decode_token


def test_access_token_roundtrip():
    payload = decode_token(create_access_token("u1", "student"))
    assert payload["sub"] == "u1"
    assert payload["role"] == "student"


def test_refresh_token_has_no_role():
    assert "role" not in decode_token(create_refresh_token("u1"))


def test_invalid_token_raises_4010():
    with pytest.raises(ApiError) as exc:
        decode_token("not-a-jwt")
    assert exc.value.code == 4010


def test_access_token_rejected_when_refresh_expected():
    with pytest.raises(ApiError) as exc:
        decode_token(create_access_token("u1", "student"), expect="refresh")
    assert exc.value.code == 4010
