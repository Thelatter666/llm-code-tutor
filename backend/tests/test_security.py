from app.core.security import hash_password, verify_password
from app.domain.auth.user import ACTIVE, ADMIN, DISABLED, STUDENT, can_login, is_admin


def test_hash_is_not_plaintext_and_verifies():
    h = hash_password("Secret123!")
    assert h != "Secret123!"
    assert verify_password("Secret123!", h)
    assert not verify_password("wrong", h)


def test_can_login_only_active():
    assert can_login(ACTIVE)
    assert not can_login(DISABLED)


def test_is_admin():
    assert is_admin(ADMIN)
    assert not is_admin(STUDENT)
