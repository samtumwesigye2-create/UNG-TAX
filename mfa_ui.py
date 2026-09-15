def inject_mfa_copy(html: str) -> str:
    """Make the filing login copy follow the MFA method selected by /auth/login."""
    html = html.replace(
        '<p class="sub">Secured with a password and a one-time code from your authenticator app.</p>',
        '<p class="sub" id="authMfaIntro">Secured with a password and multi-factor verification.</p>',
        1,
    )
    html = html.replace(
        '<label>6-digit code from your authenticator app</label>',
        '<label id="mfaLoginLabel">6-digit verification code</label>',
        1,
    )

    old_heading = '$("authHeading").textContent = data.mfa_method === "email_otp" ? "Enter the verification code sent to your email" : "Enter your authenticator code";'
    dynamic_copy = '''if (data.mfa_method === "email_otp") {
    $("authHeading").textContent = "Enter the verification code sent to your email";
    $("mfaLoginLabel").textContent = "6-digit code sent to your email";
    $("authMfaIntro").textContent = "We sent a new verification code to your email.";
  } else {
    $("authHeading").textContent = "Enter your authenticator code";
    $("mfaLoginLabel").textContent = "6-digit code from your authenticator app";
    $("authMfaIntro").textContent = "Enter the current code from your authenticator app.";
  }'''
    if old_heading in html:
        html = html.replace(old_heading, dynamic_copy, 1)

    return html
