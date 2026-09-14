from fastapi.testclient import TestClient


def test_login_page_exposes_inline_password_reset_flow():
    from main import app

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Forgot password?" in response.text
    assert 'id="passwordResetRequestForm"' in response.text
    assert 'id="passwordResetConfirmForm"' in response.text
    assert '/auth/password/request' in response.text
    assert '/auth/password/confirm' in response.text


def test_reset_confirmation_requires_code_and_new_password_fields():
    from main import app

    client = TestClient(app)
    response = client.get("/")

    assert 'id="resetCode"' in response.text
    assert 'id="resetNewPassword"' in response.text
    assert 'id="resetNewPasswordConfirm"' in response.text
