"""StarNet → Nexus City: new NEXUS_* names, with every old STARNET_* name, cookie and Stripe key still honoured."""
import importlib

from backend.env import env, legacy_names_in_use, set_env


def test_nexus_name_wins_and_legacy_name_still_works(monkeypatch):
    monkeypatch.delenv("NEXUS_MODE", raising=False)
    monkeypatch.setenv("STARNET_MODE", "live")
    assert env("MODE", "sim") == "live"                      # an old deployment keeps working
    monkeypatch.setenv("NEXUS_MODE", "sim")
    assert env("MODE") == "sim"                              # the new name wins when both are set
    monkeypatch.delenv("NEXUS_MODE")
    monkeypatch.delenv("STARNET_MODE")
    assert env("MODE", "sim") == "sim" and env("MODE") is None


def test_legacy_names_in_use_lists_names_only(monkeypatch):
    monkeypatch.setenv("STARNET_FEED_SECRET", "s3cret-value")
    monkeypatch.delenv("NEXUS_FEED_SECRET", raising=False)
    assert "STARNET_FEED_SECRET" in legacy_names_in_use()
    assert not any("s3cret" in n for n in legacy_names_in_use())
    monkeypatch.setenv("NEXUS_FEED_SECRET", "s3cret-value")
    assert "STARNET_FEED_SECRET" not in legacy_names_in_use()   # renamed: nothing left to do


def test_set_env_overrides_a_legacy_value(monkeypatch):
    monkeypatch.setenv("STARNET_LINKEDIN_PERSON", "old")
    monkeypatch.delenv("NEXUS_LINKEDIN_PERSON", raising=False)
    set_env("LINKEDIN_PERSON", "urn:li:person:abc")
    assert env("LINKEDIN_PERSON") == "urn:li:person:abc"
    monkeypatch.delenv("NEXUS_LINKEDIN_PERSON")


def test_old_and_new_session_cookie_both_log_in(monkeypatch):
    monkeypatch.setenv("NEXUS_MODE", "sim")
    monkeypatch.setenv("NEXUS_PASSWORD", "pw")
    import backend.main as main
    importlib.reload(main)
    gate = main.PasswordGate(None)
    for name in ("nexus_auth", "starnet_auth"):
        assert gate._authorized({b"cookie": f"{name}={gate.token}".encode()}) == (True, False)
    assert gate._authorized({b"cookie": b"nexus_auth=wrong"}) == (False, False)


def test_stripe_sales_read_new_and_legacy_metadata(tmp_path):
    from backend.station.economy import Treasury
    from backend.station.store import Store
    t = Treasury(Store(str(tmp_path)))
    for sid, meta in (("cs_new", {"nexus_venture": "V-009", "nexus_product": "binder"}),
                      ("cs_old", {"starnet_venture": "V-009", "starnet_product": "binder"})):
        sale = t.book_stripe_sale({"id": sid, "payment_status": "paid", "amount_total": 1200, "metadata": meta})
        assert sale and sale["venture"] == "V-009" and "binder" in sale["note"]


def test_stored_trading_desk_name_is_migrated(tmp_path):
    from backend.station.ultron import Ultron
    u = Ultron(str(tmp_path), client=None)
    u.store.update("ventures", "V-001", {"name": "Starnet City Trading Desk"}, "test")
    again = Ultron(str(tmp_path), client=None)
    assert again.store.get("ventures", "V-001")["name"] == "Nexus City Trading Desk"
