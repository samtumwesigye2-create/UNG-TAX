import pathlib


def test_taxpayer_login_uses_current_mfa_endpoint_and_email_copy():
    source = pathlib.Path("static/index.html").read_text()
    assert "/mfa/login-verify" not in source, "Taxpayer UI must not call the removed MFA endpoint"
    assert 'AUTH_API + "/mfa/verify"' in source, "Taxpayer UI must use the current MFA verification endpoint"
    assert "data.mfa_method==='email_otp'" in source, "Taxpayer UI must render email OTP instructions when login selects email OTP"
