"""Secrets stay out of errors, logs, URLs and anything the app shows."""
from backend.redact import MASK, redact
from backend.station import connectors


def test_redact_masks_secret_settings_and_credential_shapes(monkeypatch):
    monkeypatch.setenv("NEXUS_FB_PAGE_TOKEN", "EAAGpagetoken123456")
    monkeypatch.setenv("NEXUS_TRADERSPOST_WEBHOOKS", "https://webhooks.traderspost.io/trading/webhook/abc/def123,https://x.example.com/hook99999")
    monkeypatch.setenv("NEXUS_MODE", "live")   # not a secret: left alone
    text = ("HTTP 400 token EAAGpagetoken123456 at https://webhooks.traderspost.io/trading/webhook/abc/def123 "
            "and https://x.example.com/hook99999 mode live; Bearer abcdefghijklmnop; ?access_token=zzz123&x=1 "
            "sk_live_abcdefghijkl whsec_abcdefghijkl sk-ant-api03-abcdefghij")
    out = redact(text)
    for leaked in ("EAAGpagetoken123456", "def123", "hook99999", "abcdefghijklmnop", "zzz123", "sk_live_abc",
                   "whsec_abc", "sk-ant-api03"):
        assert leaked not in out, leaked
    assert "mode live" in out and MASK in out
    assert redact(None) == "" and redact("nothing secret") == "nothing secret"


def test_connector_errors_never_carry_a_secret(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_supersecretvalue1")
    err = connectors.ConnectorError("Stripe said: bad key sk_test_supersecretvalue1")
    assert "supersecretvalue1" not in str(err)


def test_meta_graph_reads_send_the_token_in_a_header_not_the_url(monkeypatch):
    monkeypatch.setenv("NEXUS_FB_PAGE_ID", "123")
    monkeypatch.setenv("NEXUS_FB_PAGE_TOKEN", "pagetoken-abcdef")
    calls = []
    monkeypatch.setattr(connectors, "_http_json", lambda method, url, headers=None, **kw: calls.append((url, headers)) or {"data": []})
    connectors.facebook_recent_posts()
    connectors.facebook_post_metrics("123_9")
    connectors.instagram_media_metrics("456")
    for url, headers in calls:
        assert "access_token" not in url and "pagetoken" not in url
        assert headers == {"Authorization": "Bearer pagetoken-abcdef"}


def test_feed_rejection_log_reveals_nothing_about_the_secret(monkeypatch):
    import importlib
    import backend.main as main
    monkeypatch.setenv("NEXUS_FEED_SECRET", "the-real-feed-secret")
    importlib.reload(main)
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    c.post("/api/feed", content=b'{"secret":"the-real-feed-secr')                      # malformed: must not be echoed
    c.post("/api/feed", json={"secret": "wrong-guess-123456", "ticker": "NQ1!"})
    logged = " ".join(e["reason"] for e in main.FEED_LOG)
    assert "the-real" not in logged and "characters" not in logged and "expected" not in logged


def test_env_example_documents_every_setting_with_placeholders_only():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    example = (root / ".env.example").read_text()
    used = set()
    for p in (root / "backend").rglob("*.py"):
        used |= set(re.findall(r"""(?<![A-Za-z_.])env\(['"]([A-Z0-9_]+)['"]""", p.read_text()))
        used |= {f"FUNDED_{m}" for m in re.findall(r'"FUNDED_([A-Z_]+)"', p.read_text())}
    documented = set(re.findall(r"NEXUS_([A-Z0-9_]+)=", example))
    vendor = {"ANTHROPIC_API_KEY", "ANTHROPIC_ADMIN_KEY", "STRIPE_API_KEY", "STRIPE_WEBHOOK_SECRET", "ETSY_KEYSTRING",
              "ETSY_SHARED_SECRET", "PINTEREST_APP_ID", "PINTEREST_APP_SECRET", "PINTEREST_SANDBOX", "PRINTIFY_API_TOKEN",
              "PRINTIFY_SHOP_ID", "RENDER_EXTERNAL_URL"}
    missing = sorted(used - documented - vendor)
    assert not missing, f"settings read by the code but not in .env.example: {missing}"
    for name in vendor - {"RENDER_EXTERNAL_URL"}:
        assert f"{name}=" in example, name
    # placeholders only: nothing shaped like a real credential
    for pattern in (r"sk_(live|test)_(?!REPLACE)[A-Za-z0-9]{8,}", r"whsec_(?!REPLACE)[A-Za-z0-9]{8,}", r"sk-ant-(?!REPLACE|admin-REPLACE)[A-Za-z0-9_-]{8,}",
                    r"EAA[A-Za-z0-9]{20,}", r"@gmail\.com"):
        assert not re.search(pattern, example), pattern
