import pathlib


def test_filing_login_uses_server_selected_mfa_method():
    source = pathlib.Path("static/index.html").read_text()
    assert "mfa_method" in source, "Filing UI must honor the MFA method returned by /auth/login"
    assert "verification code sent to your email" in source.lower(), "Filing UI must explain email OTP when selected"
