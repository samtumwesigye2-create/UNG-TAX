import pathlib

from password_reset_ui import inject_password_reset_ui


def _rendered_filing_ui():
    source = pathlib.Path("static/index.html").read_text()
    return inject_password_reset_ui(source)


def test_filing_login_uses_server_selected_mfa_method():
    source = _rendered_filing_ui()
    assert "mfa_method" in source, "Filing UI must honor the MFA method returned by /auth/login"
    assert "verification code sent to your email" in source.lower(), "Filing UI must explain email OTP when selected"


def test_filing_email_otp_replaces_stale_authenticator_copy():
    source = _rendered_filing_ui()
    assert 'authMfaIntro' in source, "Filing UI needs a dynamic MFA explanation"
    assert 'mfaLoginLabel' in source, "Filing UI needs a dynamic MFA code label"
    assert '6-digit code sent to your email' in source.lower(), "Email OTP must label the code as an email code"
    assert 'we sent a new verification code to your email' in source.lower(), "Email OTP must tell the user a new code was sent"


def test_filing_login_uses_current_mfa_verify_endpoint():
    source = _rendered_filing_ui()
    assert 'AUTH_API + "/mfa/verify"' in source
    assert "/mfa/login-verify" not in source
