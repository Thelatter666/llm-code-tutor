from app.core.crypto import decrypt_api_key, encrypt_api_key, mask_api_key


def test_api_key_roundtrip():
    cipher = encrypt_api_key("sk-test-1234")
    assert "sk-test-1234" not in cipher
    assert decrypt_api_key(cipher) == "sk-test-1234"


def test_mask_api_key():
    assert mask_api_key("sk-test-1234") == "sk-****1234"
    assert mask_api_key(None) == ""
