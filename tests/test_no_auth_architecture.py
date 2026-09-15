from pathlib import Path


def test_main_has_no_authentication_stack():
    src = Path('main.py').read_text()
    forbidden = ['import auth', 'auth_migrate', 'auth_store', 'password_reset', 'mfa_ui', 'require_auth']
    for marker in forbidden:
        assert marker not in src


def test_revenue_operations_have_no_auth_dependency():
    for name in ('ops.py', 'ops_cases_notices.py', 'ops_reports.py'):
        src = Path(name).read_text()
        assert 'import auth' not in src
        assert 'Depends(auth.require_auth)' not in src
        assert 'require_revenue_user' not in src


def test_authentication_modules_removed():
    for name in ('auth.py', 'auth_store.py', 'auth_migrate.py', 'mfa_ui.py', 'password_reset.py', 'password_reset_ui.py', 'ops_auth.py'):
        assert not Path(name).exists(), f'{name} must be removed'


def test_health_reports_direct_access():
    src = Path('main.py').read_text()
    assert '"access":"direct"' in src.replace(' ', '')
    assert 'password_reset_ui' not in src
    assert 'email_otp_configured' not in src
