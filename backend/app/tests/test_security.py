import uuid

from app.core.security import (
    generate_numeric_code,
    hash_secret,
    is_breached_code,
    is_weak_pin,
    validate_ditsala_code_strength,
    validate_pin_strength,
    verify_secret,
)


def test_hash_and_verify_roundtrip():
    hashed = hash_secret("correct-horse-battery-9")
    assert verify_secret(hashed, "correct-horse-battery-9") is True


def test_verify_rejects_wrong_secret():
    hashed = hash_secret("correct-horse-battery-9")
    assert verify_secret(hashed, "wrong-guess-1") is False


def test_hash_is_never_the_plaintext():
    hashed = hash_secret("correct-horse-battery-9")
    assert "correct-horse-battery-9" not in hashed


def test_generate_numeric_code_is_six_digits_by_default():
    code = generate_numeric_code()
    assert len(code) == 6
    assert code.isdigit()


def test_generate_numeric_code_is_not_constant():
    codes = {generate_numeric_code() for _ in range(20)}
    assert len(codes) > 1  # cryptographically random, not a fixed value


def test_ditsala_code_strength_rules():
    assert validate_ditsala_code_strength("short1") is False  # too short
    assert validate_ditsala_code_strength("noDigitsHere") is False  # no digit
    assert validate_ditsala_code_strength("longEnough1") is True


async def test_is_breached_code_flags_a_known_breached_password():
    """Real call to HIBP's Pwned Passwords API (§15) — 'password123' is
    certain to appear in a corpus this large, no mocking needed."""
    assert await is_breached_code("password123") is True


async def test_is_breached_code_allows_a_random_unbreached_string():
    random_code = f"ditsala-{uuid.uuid4()}-9"
    assert await is_breached_code(random_code) is False


def test_pin_strength_rules():
    assert validate_pin_strength("12345") is False  # too short
    assert validate_pin_strength("1234567") is False  # too long
    assert validate_pin_strength("12a456") is False  # not all digits
    assert validate_pin_strength("483920") is True


def test_is_weak_pin_rejects_common_and_patterned_pins():
    assert is_weak_pin("000000") is True
    assert is_weak_pin("123456") is True
    assert is_weak_pin("654321") is True
    assert is_weak_pin("111111") is True


def test_is_weak_pin_allows_a_non_obvious_pin():
    assert is_weak_pin("483920") is False
    assert is_weak_pin("725104") is False
