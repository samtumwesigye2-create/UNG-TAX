from datetime import date
from fastapi.testclient import TestClient
import main

client = TestClient(main.app)


def test_new_2026_paye_threshold():
    r = client.post('/tax/paye/calculate', json={'gross_monthly_pay':335000,'pay_date':'2026-07-01','resident':True,'nssf_applicable':True})
    assert r.status_code == 200
    d = r.json()
    assert d['paye'] == 0
    assert d['employee_nssf'] == 16750
    assert d['employer_nssf'] == 33500
    assert d['rules_version'] == 'UG-PAYE-2026-07'


def test_new_2026_paye_band_edges():
    cases = [(410000,15000),(485000,33750),(10000000,2888250),(15000000,4888250)]
    for gross, expected in cases:
        r = client.post('/tax/paye/calculate', json={'gross_monthly_pay':gross,'pay_date':'2026-08-01'})
        assert r.status_code == 200
        assert r.json()['paye'] == expected


def test_historical_schedule_preserved():
    r = client.post('/tax/paye/calculate', json={'gross_monthly_pay':335000,'pay_date':'2026-06-30'})
    assert r.status_code == 200
    assert r.json()['paye'] == 10000
    assert r.json()['rules_version'] == 'UG-PAYE-PRE-2026-07'


def test_corporate_rate():
    r = client.post('/tax/corporate/calculate', json={'chargeable_income':1000000})
    assert r.status_code == 200
    assert r.json()['corporate_income_tax'] == 300000
