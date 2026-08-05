"""Small, read-only helpers for public Albert Heijn product pages and invoices."""

import json
import re
from html import unescape
from io import BytesIO
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from pypdf import PdfReader


AH_HOST = "www.ah.nl"


def _get_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Nutrition tracker)"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def search_products(query: str) -> list[dict]:
    """Return a few public AH product pages matching a search phrase."""
    html = _get_html(f"https://{AH_HOST}/zoeken?query={quote_plus(query)}")
    paths = re.findall(r'href="(/producten/product/[^"]+)"', html)
    seen = set()
    products = []
    for path in paths:
        url = f"https://{AH_HOST}{unescape(path)}"
        if url in seen:
            continue
        seen.add(url)
        title_match = re.search(
            rf'href="{re.escape(path)}"[^>]*>.*?<[^>]+>(.*?)</', html, re.DOTALL
        )
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else url.rsplit("/", 1)[-1]
        products.append({"name": unescape(title), "url": url})
        if len(products) == 8:
            break
    return products


def get_product_page(product_url: str) -> dict:
    """Get the public title and the nutrition text from an AH product page."""
    if not product_url.startswith(f"https://{AH_HOST}/"):
        raise ValueError("Use a public product link from ah.nl.")
    html = _get_html(product_url)
    title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    title_text = unescape(title.group(1)) if title else product_url.rsplit("/", 1)[-1]

    # AH renders nutrition in structured data as well as visible HTML.  Keep
    # the relevant text intact, rather than inventing values if their layout
    # changes.
    plain = unescape(re.sub(r"<[^>]+>", " ", html))
    plain = re.sub(r"\s+", " ", plain)
    nutrition_match = re.search(
        r"Voedingswaarden(.{0,1800}?)(?:Ingrediënten|Allergie|Bewaren|$)",
        plain,
        re.IGNORECASE,
    )
    return {
        "name": title_text,
        "url": product_url,
        "nutrition_text": nutrition_match.group(1).strip() if nutrition_match else None,
    }


def extract_invoice_text(pdf_bytes: bytes) -> str:
    """Extract selectable text from an AH invoice PDF for user review."""
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def suggested_invoice_lines(text: str) -> list[str]:
    """Offer likely item lines; the UI always requires review before import."""
    suggestions = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if len(line) < 3 or len(line) > 120:
            continue
        if re.search(r"€|EUR|totaal|factuur|bestelling|btw|klantnummer", line, re.I):
            continue
        if re.search(r"[A-Za-zÀ-ÿ]", line):
            suggestions.append(line)
    return suggestions[:80]
