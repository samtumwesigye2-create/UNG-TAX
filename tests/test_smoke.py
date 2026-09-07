import os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['TAX_CORS_ORIGINS']='http://localhost:8000'
from fastapi.testclient import TestClient
import main

def test_health():
    r=TestClient(main.app).get('/health')
    assert r.status_code==200
    assert r.json()['live_transmission'] is False
