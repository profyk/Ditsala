from app.core.security import (
    generate_numeric_code,
    hash_secret,
    validate_ditsala_code_strength,
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
