import pathlib


def test_login_otp_does_not_use_blocking_smtp_transport():
    source = pathlib.Path("auth.py").read_text()
    assert "smtplib" not in source, "Login OTP must not block the request on SMTP"
    assert "RESEND_API_KEY" in source, "Login OTP should use the Resend transactional API"
