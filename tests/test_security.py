"""Проверки middleware безопасности: Host-check, CSRF, CSP-заголовки."""
from fastapi.testclient import TestClient

from masking.app import app

client = TestClient(app)


def test_host_header_rejected():
    """DNS-rebinding: внешний домен, указавший на 127.0.0.1, не должен работать."""
    r = client.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_cross_origin_post_rejected():
    """POST с чужой страницы (Origin не наш) должен быть отбит."""
    r = client.post(
        "/api/projects",
        json={"name": "x"},
        headers={"origin": "http://evil.example.com", "sec-fetch-site": "cross-site"},
    )
    assert r.status_code == 403


def test_same_origin_post_ok():
    """Нормальный POST с нашей же страницы проходит."""
    r = client.post(
        "/api/projects",
        json={"name": "Проверка"},
        headers={"sec-fetch-site": "same-origin"},
    )
    assert r.status_code in (201, 409)   # 409 если имя уже занято — ок


def test_safe_methods_pass_without_origin():
    """GET без Origin — обычный заход в UI, разрешён."""
    assert client.get("/api/health").status_code == 200


def test_security_headers_present():
    r = client.get("/api/health")
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
