from datetime import date

from src import linkedin, render


def test_template_rotation_by_day_of_year():
    # Jan 1 = day 1 → index 1; Jan 2 → 2; Jan 3 → 0
    assert render.template_for(date(2026, 1, 1)) == "dark_accent"
    assert render.template_for(date(2026, 1, 2)) == "warm_editorial"
    assert render.template_for(date(2026, 1, 3)) == "clean_white"
    seen = {render.template_for(date(2026, 3, d)) for d in range(1, 4)}
    assert seen == set(render.TEMPLATES)


def test_build_html_escapes_and_embeds_fonts():
    page = render.build_html("clean_white", "AI & <you>", "via Hugging Face", "Jane")
    assert "AI &amp; &lt;you&gt;" in page
    assert "data:font/ttf;base64," in page
    assert "{{" not in page


def test_linkedin_escape_keeps_hashtags():
    text = "Models (small) beat giants @ 3B_params!\n\n#AI #OpenSource"
    out = linkedin.escape_commentary(text)
    assert r"\(small\)" in out and r"\@" in out and r"3B\_params" in out
    assert out.endswith("#AI #OpenSource")


def test_token_age(monkeypatch):
    from src import config
    monkeypatch.setattr(config, "LINKEDIN_TOKEN_ISSUED", "2026-08-01")
    assert linkedin.token_age_days(date(2026, 9, 20)) == 50
    monkeypatch.setattr(config, "LINKEDIN_TOKEN_ISSUED", "")
    assert linkedin.token_age_days() is None
