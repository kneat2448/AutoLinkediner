"""Render the headline image card (HTML/CSS template → 1080×1350 PNG) with Playwright.

Run ``python -m src.render --preview`` to render all three templates with a sample headline.
"""
from __future__ import annotations

import argparse
import base64
import html
import logging
from datetime import date
from functools import lru_cache
from pathlib import Path

from src import config

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1350
TEMPLATES = ["clean_white", "dark_accent", "warm_editorial"]
FONT_FILES = {"FONT_INTER": "Inter.ttf", "FONT_FRAUNCES": "Fraunces.ttf"}

# Shrinks the headline until it fits its box (the box sits inside >=96px page padding).
FIT_SCRIPT = """
async () => {
  await document.fonts.ready;
  const box = document.querySelector('.headline-box');
  const h = document.querySelector('.headline');
  h.style.flex = 'none';
  const fits = () => {
    const b = box.getBoundingClientRect();
    const r = h.getBoundingClientRect();
    const padBottom = parseFloat(getComputedStyle(box).paddingBottom) || 0;
    return r.top >= b.top - 0.5 && r.bottom <= b.bottom - padBottom + 0.5
      && h.scrollWidth <= h.clientWidth + 0.5;
  };
  let size = parseFloat(getComputedStyle(h).fontSize);
  const min = 40;
  while (size > min && !fits()) {
    size -= 2;
    h.style.fontSize = size + 'px';
  }
  return size;
}
"""


def template_for(day: date) -> str:
    """Template name for a given date: rotates by day_of_year % 3."""
    return TEMPLATES[day.timetuple().tm_yday % len(TEMPLATES)]


@lru_cache(maxsize=None)
def _font_data_uri(filename: str) -> str:
    data = (config.FONTS_DIR / filename).read_bytes()
    return "data:font/ttf;base64," + base64.b64encode(data).decode("ascii")


def build_html(template: str, headline: str, source_tag: str, author: str) -> str:
    """Fill a template with escaped values and embedded (local) fonts."""
    page = (config.TEMPLATES_DIR / f"{template}.html").read_text(encoding="utf-8")
    values = {
        "HEADLINE": html.escape(headline),
        "SOURCE": html.escape(source_tag),
        "AUTHOR": html.escape(author),
    }
    for key, filename in FONT_FILES.items():
        values[key] = _font_data_uri(filename)
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def render(headline: str, source_tag: str, out_path: Path, template: str | None = None,
           author: str | None = None) -> Path:
    """Render a card to ``out_path`` (PNG, 1080×1350). Template defaults to today's rotation."""
    from playwright.sync_api import sync_playwright

    template = template or template_for(config.now().date())
    page_html = build_html(template, headline, source_tag, author or config.AUTHOR_NAME)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            page.set_content(page_html, wait_until="load", timeout=30_000)
            size = page.evaluate(FIT_SCRIPT)
            page.screenshot(path=str(out_path), clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
        finally:
            browser.close()
    log.info("render: %s -> %s (headline %.0fpx)", template, out_path.name, size)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Render image cards")
    parser.add_argument("--preview", action="store_true", help="render all templates with a sample")
    parser.add_argument("--headline", default="Small AI models are quietly catching up with the giants")
    parser.add_argument("--source", default="via Hugging Face")
    args = parser.parse_args()
    config.setup_logging()
    if not args.preview:
        parser.error("use --preview (cards are otherwise rendered by the pipeline)")
    long_headline = "Why a much longer headline about AI regulation in Europe still fits neatly on the card"
    for name in TEMPLATES:
        render(args.headline, args.source, config.OUT_DIR / f"preview_{name}.png", template=name)
        render(long_headline, args.source, config.OUT_DIR / f"preview_{name}_long.png", template=name)
    log.info("previews written to %s", config.OUT_DIR)


if __name__ == "__main__":
    main()
