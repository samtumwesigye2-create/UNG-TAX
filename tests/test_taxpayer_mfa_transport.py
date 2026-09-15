import pathlib

from password_reset_ui import inject_password_reset_ui


def test_taxpayer_login_uses_current_mfa_endpoint_and_email_copy():
    source = inject_password_reset_ui(pathlib.Path("static/index.html").read_text())
    assert "/mfa/login-verify" not in source, "Rendered taxpayer UI must not call the removed MFA endpoint"
    assert 'AUTH_API + "/mfa/verify"' in source, "Rendered taxpayer UI must use the current MFA verification endpoint"
    assert "mfa_method" in source, "Rendered taxpayer UI must honor the MFA method selected by the server"
    assert "verification code sent to your email" in source.lower(), "Rendered taxpayer UI must explain email OTP"
