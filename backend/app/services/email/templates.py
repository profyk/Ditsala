VERIFICATION_SUBJECT = "Your DITSALA verification code"


def verification_body(code: str) -> tuple[str, str]:
    """Returns (text_body, html_body)."""
    text_body = f"Your DITSALA verification code is {code}. It expires in 10 minutes."
    html_body = (
        f"<p>Your DITSALA verification code is <strong>{code}</strong>.</p>"
        f"<p>It expires in 10 minutes.</p>"
    )
    return text_body, html_body
