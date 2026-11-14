from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)

def test_legacy_checkout_endpoints_are_removed():
    for path in ['/api/paypal/create/1','/api/paypal/capture/1']:
        assert client.post(path).status_code == 404
    assert client.get('/api/paypal/status/1').status_code == 404
    assert 'paypal_configured' not in client.get('/health').json()

def test_live_ui_is_near_only_and_demo_checkout_stays_unpaid():
    js=client.get('/static/app.js').text.lower()
    near=client.get('/static/near.js').text.lower()
    assert 'paypal' not in js and 'paypal' not in near
    assert 'near coordination' in js
    assert 'unpaid demo' in client.get('/static/marketplace.js').text.lower()
