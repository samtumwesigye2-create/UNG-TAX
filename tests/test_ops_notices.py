from fastapi.testclient import TestClient

def test_issued_notice_content_is_immutable_and_replacement_supported():
    from main import app
    client=TestClient(app)
    r=client.post("/ops/notices",json={"taxpayer_id":"tp-notice","notice_type":"assessment","subject":"Assessment issued","content":"Original notice"}); assert r.status_code==201
    nid=r.json()["id"]
    assert client.patch(f"/ops/notices/{nid}",json={"status":"approved"}).status_code==200
    issued=client.patch(f"/ops/notices/{nid}",json={"status":"issued"}); assert issued.status_code==200; assert issued.json()["issued_by"]=="promet-direct"
    assert client.patch(f"/ops/notices/{nid}",json={"content":"Changed after issue"}).status_code==409
