RESET_UI = r'''
    <div id="passwordResetRequestForm" class="hidden">
      <p class="sub">Enter the email address for your URA-PROMET account. We will send a 6-digit reset code.</p>
      <label>Email</label>
      <input type="email" id="resetEmail" autocomplete="email">
      <div class="actions">
        <button class="btn-text" type="button" onclick="cancelPasswordReset()">Back to sign in</button>
        <button class="btn-primary" type="button" onclick="requestPasswordReset()">Send reset code</button>
      </div>
      <div class="hint hidden" id="resetRequestStatus"></div>
    </div>

    <div id="passwordResetConfirmForm" class="hidden">
      <p class="sub">Enter the 6-digit code from your email and choose a new password.</p>
      <label>6-digit reset code</label>
      <input type="text" id="resetCode" maxlength="6" inputmode="numeric" autocomplete="one-time-code">
      <label>New password <span class="hint">(10+ characters)</span></label>
      <input type="password" id="resetNewPassword" autocomplete="new-password">
      <label>Confirm new password</label>
      <input type="password" id="resetNewPasswordConfirm" autocomplete="new-password">
      <div class="actions">
        <button class="btn-text" type="button" onclick="cancelPasswordReset()">Cancel</button>
        <button class="btn-primary" type="button" onclick="confirmPasswordReset()">Reset password</button>
      </div>
    </div>
'''

RESET_SCRIPT = r'''
<script>
let passwordResetId = null;
let passwordResetEmail = "";

function resetUiHideAuthForms(){
  ["authLoginForm","authRegisterForm","mfaSetupForm","mfaLoginForm","passwordResetRequestForm","passwordResetConfirmForm"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.add("hidden");
  });
}

function showPasswordResetRequest(){
  if (typeof hideErr0 === "function") hideErr0();
  resetUiHideAuthForms();
  const heading = document.getElementById("authHeading");
  if (heading) heading.textContent = "Reset password";
  const email = document.getElementById("resetEmail");
  const loginEmail = document.getElementById("authEmail");
  if (email && loginEmail && !email.value) email.value = loginEmail.value.trim();
  document.getElementById("passwordResetRequestForm").classList.remove("hidden");
}

function cancelPasswordReset(){
  passwordResetId = null;
  resetUiHideAuthForms();
  const heading = document.getElementById("authHeading");
  if (heading) heading.textContent = "Sign in";
  document.getElementById("authLoginForm").classList.remove("hidden");
}

async function requestPasswordReset(){
  if (typeof hideErr0 === "function") hideErr0();
  const email = document.getElementById("resetEmail").value.trim().toLowerCase();
  if (!email){
    if (typeof showErr0 === "function") showErr0("Enter your account email address.");
    return;
  }
  try{
    const response = await fetch("/auth/password/request", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({email})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not send reset code.");
    passwordResetEmail = email;
    passwordResetId = data.reset_id || null;
    const status = document.getElementById("resetRequestStatus");
    if (status){
      status.textContent = data.message || "If that account exists, a reset code has been sent.";
      status.classList.remove("hidden");
    }
    if (passwordResetId){
      document.getElementById("passwordResetRequestForm").classList.add("hidden");
      document.getElementById("passwordResetConfirmForm").classList.remove("hidden");
    }
  }catch(error){
    if (typeof showErr0 === "function") showErr0(error.message);
  }
}

async function confirmPasswordReset(){
  if (typeof hideErr0 === "function") hideErr0();
  const code = document.getElementById("resetCode").value.trim();
  const password = document.getElementById("resetNewPassword").value;
  const confirmation = document.getElementById("resetNewPasswordConfirm").value;
  if (!passwordResetId){
    if (typeof showErr0 === "function") showErr0("Request a new reset code first.");
    return;
  }
  if (!/^\d{6}$/.test(code)){
    if (typeof showErr0 === "function") showErr0("Enter the 6-digit reset code.");
    return;
  }
  if (password.length < 10){
    if (typeof showErr0 === "function") showErr0("Password must be at least 10 characters.");
    return;
  }
  if (password !== confirmation){
    if (typeof showErr0 === "function") showErr0("The new passwords do not match.");
    return;
  }
  try{
    const response = await fetch("/auth/password/confirm", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({reset_id: passwordResetId, code, new_password: password})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not reset password.");
    resetUiHideAuthForms();
    const heading = document.getElementById("authHeading");
    if (heading) heading.textContent = "Sign in";
    const loginEmail = document.getElementById("authEmail");
    if (loginEmail) loginEmail.value = passwordResetEmail;
    const loginPassword = document.getElementById("authPassword");
    if (loginPassword) loginPassword.value = "";
    document.getElementById("authLoginForm").classList.remove("hidden");
    passwordResetId = null;
    const status = document.getElementById("resetRequestStatus");
    if (status){
      status.textContent = "Password updated. Sign in with your new password.";
      status.classList.remove("hidden");
    }
  }catch(error){
    if (typeof showErr0 === "function") showErr0(error.message);
  }
}
</script>
'''


def inject_password_reset_ui(html: str) -> str:
    login_actions = '''      <div class="actions">\n        <button class="btn-text" onclick="toggleAuthMode()">Need an account? Register</button>\n        <button class="btn-primary" onclick="doLogin()">Sign in</button>\n      </div>'''
    enhanced_actions = login_actions + '''\n      <div style="margin-top:10px;text-align:right">\n        <button class="btn-text" type="button" onclick="showPasswordResetRequest()">Forgot password?</button>\n      </div>'''
    if login_actions in html:
        html = html.replace(login_actions, enhanced_actions, 1)

    mfa_marker = '    <div id="mfaSetupForm" class="hidden">'
    if mfa_marker in html:
        html = html.replace(mfa_marker, RESET_UI + "\n" + mfa_marker, 1)

    # Keep the filing wizard aligned with the current authentication contract.
    # The server selects email OTP when Resend is configured and otherwise falls
    # back to TOTP.  Older static markup assumed TOTP and used a retired endpoint.
    old_heading = '$("authHeading").textContent = "Enter your authenticator code";'
    new_heading = '$("authHeading").textContent = data.mfa_method === "email_otp" ? "Enter the verification code sent to your email" : "Enter your authenticator code";'
    if old_heading in html:
        html = html.replace(old_heading, new_heading, 1)
    html = html.replace('AUTH_API + "/mfa/login-verify"', 'AUTH_API + "/mfa/verify"')

    if "</body>" in html:
        html = html.replace("</body>", RESET_SCRIPT + "\n</body>", 1)
    return html
