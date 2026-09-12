def test_health_reports_all_dependencies_ok(client):
    response = client.get("/health")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["storage"] == "ok"


def test_responses_carry_security_headers(client):
    """`/assets/{id}/content` replays a media type recorded at ingestion.

    Anything a browser sniffed into HTML there would execute on the API's own
    origin, so these are asserted on the response rather than assumed.
    """
    headers = client.get("/health").headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
