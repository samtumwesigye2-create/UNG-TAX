from fastapi.testclient import TestClient
from main import app

def test_health():
    r=TestClient(app).get('/health')
    assert r.status_code==200
    assert r.json()['status']=='ok'

def test_live_transmission_disabled():
    r=TestClient(app).post('/tax/returns/not-real/submit')
    assert r.status_code==503
