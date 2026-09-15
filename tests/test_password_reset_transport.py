import pathlib


def test_password_reset_does_not_use_blocking_smtp_transport():
    source = pathlib.Path("password_reset.py").read_text()
    assert "smtplib" not in source, "Password reset must not block the request on SMTP"
    assert "RESEND_API_KEY" in source, "Password reset should use the Resend transactional API"
