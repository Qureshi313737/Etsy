import random
from datetime import date

from etsy_engine import bandit
from etsy_engine.analysis import percentile_ranks, quality_audit
from etsy_engine.copywriter import _validate, build_content_pack, rule_tags, season_context
from etsy_engine.etsy_client import EtsyClient, money, normalize_listing
from etsy_engine.llm import extract_json
from etsy_engine.market import seed_keywords
from etsy_engine.pinterest_campaign import utm_link
from etsy_engine.report import markdown_to_html
from etsy_engine.secrets_store import TokenStore, generate_key
from etsy_engine.text_utils import clean_tag, clean_tags, clean_title


def test_clean_tag_limits_and_chars():
    assert clean_tag("Birth Flower Necklace!!") == "birth flower"  # 21 chars -> word boundary
    assert len(clean_tag("a" * 30)) == 20
    assert clean_tags(["Gift", "gift", "Gift for Mom"] + [f"tag {i}" for i in range(20)]) [:3] == \
        ["gift", "gift for mom", "tag 0"]
    assert len(clean_tags([f"tag {i}" for i in range(20)])) == 13


def test_clean_title_rules():
    t = clean_title("Gift & Love & Joy: a: b " + "word " * 40)
    assert len(t) <= 140
    assert t.count("&") == 1 and t.count(":") == 1


def test_money_and_normalize():
    assert money({"amount": 1999, "divisor": 100}) == 19.99
    raw = {"listing_id": 5, "title": "X", "price": {"amount": 500, "divisor": 100, "currency_code": "EUR"},
           "images": [{"rank": 2, "url_fullxfull": "b"}, {"rank": 1, "url_fullxfull": "a"}], "tags": ["t"]}
    n = normalize_listing(raw)
    assert n["price"] == 5.0 and n["currency"] == "EUR" and n["image_urls"] == ["a", "b"]


def test_etsy_key_header_uses_keystring_and_secret(tmp_path):
    c = EtsyClient("KEY", "SECRET", TokenStore(tmp_path / "t.enc", None))
    assert c.key_header == {"x-api-key": "KEY:SECRET"}


def test_etsy_refresh_stores_rotated_token(tmp_path):
    store = TokenStore(tmp_path / "t.enc", generate_key())
    c = EtsyClient("KEY", "SECRET", store, refresh_token_seed="seed-token")

    class Resp:
        content = b"{}"

        def json(self):
            return {"access_token": "1.abc", "refresh_token": "rotated", "expires_in": 3600}

    calls = []
    c.http.request = lambda method, url, **kw: calls.append(kw) or Resp()
    assert c.access_token() == "1.abc"
    assert calls[0]["data"]["refresh_token"] == "seed-token"
    reopened = TokenStore(tmp_path / "t.enc", store.key)
    assert reopened.get("etsy")["refresh_token"] == "rotated"


def test_token_store_without_key_is_memory_only(tmp_path):
    s = TokenStore(tmp_path / "t.enc", "")
    s.set("x", {"a": 1})
    assert s.get("x") == {"a": 1} and not (tmp_path / "t.enc").exists()


def test_extract_json_variants():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"b": [1,2]} done') == {"b": [1, 2]}


def test_percentiles_and_quality():
    assert percentile_ranks([1, 2, 3]) == [0.0, 0.5, 1.0]
    good = {"title": "x" * 120, "tags": [f"two words{i}" for i in range(13)], "image_urls": ["u"] * 9,
            "has_video": True, "description": "d" * 600}
    bad = {"title": "Mug", "tags": ["mug"], "image_urls": ["u"], "has_video": False, "description": ""}
    assert quality_audit(good)[0] == 100
    score, issues = quality_audit(bad)
    assert score < 30 and len(issues) >= 4


def test_seed_keywords_prefers_title_phrase():
    l = {"title": "Custom Pet Portrait from Photo, Dog Art", "tags": ["pet portrait", "dog mom gift", "art"]}
    seeds = seed_keywords(l, 3)
    assert seeds[0] == "custom pet portrait photo"
    assert "dog mom gift" in seeds


def test_rule_tags_fill_13_from_market():
    l = {"title": "Earrings", "tags": ["earrings"]}
    ins = {"top_tags": [(f"gift idea {i}", 10 - i) for i in range(15)] + [("earrings", 3)], "top_phrases": []}
    tags = rule_tags(l, ins)
    assert len(tags) == 13 and tags[0] == "earrings"


def test_llm_output_is_sanitized():
    fallback = {"seo": {"title": "Fallback title that is long enough to count", "tags": [f"t{i}" for i in range(13)],
                        "description_intro": "intro", "rationale": []},
                "pins": [{"style": "gift", "headline": "h", "subline": "s", "title": "t", "description": "d",
                          "alt_text": "a"}],
                "social": {"instagram": "x"}, "conversion_tips": ["tip"]}
    raw = {"seo": {"title": "Great & Nice & Cool " + "w " * 100, "tags": ["A Very Long Tag That Exceeds Limit"] * 2
                   + [f"tag {i}" for i in range(12)]},
           "pins": [{"headline": "H" * 100}]}
    out = _validate(raw, fallback, 1)
    assert len(out["seo"]["title"]) <= 140 and out["seo"]["title"].count("&") == 1
    assert all(len(t) <= 20 for t in out["seo"]["tags"]) and len(out["seo"]["tags"]) == 13
    assert len(out["pins"][0]["headline"]) <= 48


def test_content_pack_without_llm(demo_cfg):
    from etsy_engine.analysis import ListingMetrics

    l = {"listing_id": 1, "title": "Soy Candle, Lavender Candle", "tags": ["soy candle"], "price": 18.0,
         "materials": ["soy wax"], "description": ""}
    m = ListingMetrics(listing=l, diagnosis="traffic")
    pack = build_content_pack(None, l, m, None, 4, ["gift", "question"], "$", date(2026, 12, 1))
    assert pack["source"] == "rules" and len(pack["pins"]) == 4
    assert pack["season"]["occasion"] == "Christmas"
    assert all(len(p["title"]) <= 100 for p in pack["pins"])


def test_season_context():
    assert season_context(date(2026, 2, 5))["occasion"] == "Valentine's Day"
    assert season_context(date(2026, 5, 1))["occasion"] == "Mother's Day"


def test_bandit_prefers_winner():
    stats = {"a": {"imp": 50000, "clicks": 1000, "saves": 0, "pin_clicks": 0},
             "b": {"imp": 50000, "clicks": 50, "saves": 0, "pin_clicks": 0}}
    rng = random.Random(1)
    picks = [bandit.choose(["a", "b"], stats, 1, rng)[0] for _ in range(200)]
    assert picks.count("a") > 180
    assert sorted(bandit.choose(["a", "b", "c"], {}, 3, rng)) == ["a", "b", "c"]  # variety first


def test_utm_link_keeps_existing_query(cfg):
    url = utm_link("https://www.etsy.com/listing/1/x?ref=shop", cfg, "banner-gift")
    assert "ref=shop" in url and "utm_source=pinterest" in url and "utm_content=banner-gift" in url


def test_markdown_to_html_table_and_code():
    html = markdown_to_html("# T\n| a | b |\n|---|---|\n| 1 | 2 |\n```\ncode\n```\n- [ ] todo", "t")
    assert "<table>" in html and "<pre>code</pre>" in html and "☐ todo" in html


def test_update_listing_falls_back_to_json_when_tags_not_stored(tmp_path):
    store = TokenStore(tmp_path / "t.enc", None)
    store.set("etsy", {"access_token": "1.tok", "expires_at": 9e12})
    c = EtsyClient("KEY", "SECRET", store, shop_id=7)
    sent = []

    class Resp:
        def __init__(self, body):
            self.body, self.content = body, b"x"

        def json(self):
            return self.body

    def fake(method, url, **kw):
        sent.append(kw)
        if "data" in kw:
            return Resp({"tags": ["a,b"]})  # simulate Etsy treating the string as one tag
        return Resp({"tags": kw["json"]["tags"]})

    c.http.request = fake
    out = c.update_listing(1, {"title": "T", "tags": ["a", "b"]})
    assert out["tags"] == ["a", "b"] and sent[0]["data"]["tags"] == "a,b" and sent[1]["json"] == {"tags": ["a", "b"]}
    assert sent[0]["headers"]["x-api-key"] == "KEY:SECRET"


def test_passphrase_works_as_encryption_key(tmp_path):
    s = TokenStore(tmp_path / "t.enc", "my long phone password 2026!")
    s.set("etsy", {"refresh_token": "r"})
    assert TokenStore(tmp_path / "t.enc", "my long phone password 2026!").get("etsy")["refresh_token"] == "r"
    assert TokenStore(tmp_path / "t.enc", "wrong password").get("etsy") == {}


def test_phone_connect_flow_etsy(tmp_path, monkeypatch):
    from etsy_engine import oauth
    from etsy_engine.config import load_config

    monkeypatch.setenv("ETSY_API_KEY", "KEY")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "phone passphrase long enough")
    cfg = load_config(root=tmp_path)
    store = TokenStore(cfg.path("token_file"), cfg.secret("TOKEN_ENCRYPTION_KEY"))
    url = oauth.remote_start("etsy", cfg, store)
    assert "code_challenge=" in url and "client_id=%4B%45%59" in url
    state = store.get("pending_etsy")["state"]
    seen = {}

    def fake_exchange(api_key, code, verifier, redirect):
        seen.update(code=code, verifier=verifier)
        return {"access_token": "1.a", "refresh_token": "ref", "expires_in": 3600}

    monkeypatch.setattr(oauth.etsy_client.EtsyClient, "exchange_code", staticmethod(fake_exchange))
    reopened = TokenStore(cfg.path("token_file"), cfg.secret("TOKEN_ENCRYPTION_KEY"))
    oauth.remote_finish("etsy", cfg, reopened, f"http://localhost:3003/callback?code=C1&state={state}")
    assert seen["code"] == "C1" and seen["verifier"]
    assert TokenStore(cfg.path("token_file"), "phone passphrase long enough").get("etsy")["refresh_token"] == "ref"


def test_login_link_client_id_survives_log_masking(tmp_path, monkeypatch):
    import urllib.parse

    from etsy_engine.config import load_config
    from etsy_engine.oauth import remote_start

    monkeypatch.setenv("ETSY_API_KEY", "abc123key")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "a long phone friendly passphrase 123")
    cfg = load_config(root=tmp_path)
    store = TokenStore(tmp_path / "t.enc", cfg.secret("TOKEN_ENCRYPTION_KEY"))
    url = remote_start("etsy", cfg, store)
    assert "abc123key" not in url  # GitHub's *** mask can't hit it
    qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert qs["client_id"] == "abc123key" and qs["code_challenge_method"] == "S256"


def test_digital_listing_copy_has_no_shipping_or_handmade():
    from etsy_engine.analysis import ListingMetrics
    from etsy_engine.copywriter import is_digital

    l = {"listing_id": 9, "title": "Real Estate Website Template | Animated Property Listings Site | HTML Template",
         "tags": ["html template", "digital download", "website template"], "price": 49.0, "materials": [],
         "description": ""}
    assert is_digital(l)
    pack = build_content_pack(None, l, ListingMetrics(listing=l, diagnosis="conversion"), None, 6,
                              ["keyword", "gift", "question", "seasonal", "benefit", "price"], "$", date(2026, 12, 1))
    text = (pack["seo"]["description_intro"] + " ".join(p["headline"] + p["description"] for p in pack["pins"])
            + " ".join(pack["social"].values()) + " ".join(pack["conversion_tips"])).lower()
    assert "ships" not in text and "handmade" not in text and "christmas gift" not in text
    assert pack["primary_phrase"] == "real estate website template"
    assert pack["seo"]["title"].startswith("Real Estate Website Template")


def test_gemini_falls_back_to_lite_model_when_busy(cfg, monkeypatch):
    from etsy_engine.http import ApiError
    from etsy_engine.llm import LLM

    monkeypatch.setitem(cfg.secrets, "GEMINI_API_KEY", "k")
    llm = LLM(cfg)
    tried = []

    def fake_call(model, system, prompt, max_tokens):
        tried.append(model)
        if model == "gemini-flash-latest":
            raise ApiError(503, "high demand")
        return '{"ok": true}'

    llm._gemini_call = fake_call
    assert llm.generate_json("s", "p") == {"ok": True}
    assert tried == ["gemini-flash-latest", "gemini-flash-lite-latest"]
