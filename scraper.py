"""
Scraper for نهضة أسيا — https://nhdah.com/ar
Scrapes products, prices, and categories then saves them to Supabase.
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup
import database as db

logger = logging.getLogger(__name__)

BASE_URL = "https://nhdah.com"
SHOP_URL = "https://nhdah.com/ar/shop"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _get(url: str, retries: int = 3) -> BeautifulSoup | None:
    for attempt in range(retries):
        try:
            resp = SESSION.get(url, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.warning(f"Attempt {attempt + 1} failed for {url}: {exc}")
            time.sleep(2 ** attempt)
    return None


def _clean_price(raw: str) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.]", "", raw.replace(",", "."))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def scrape_categories() -> list[dict]:
    soup = _get(SHOP_URL)
    if not soup:
        logger.error("Failed to load shop page")
        return []

    categories = []
    seen_slugs: set[str] = set()

    # محاولة إيجاد قائمة الفئات
    selectors = [
        "ul.product-categories li a",
        ".widget_product_categories li a",
        "nav.woocommerce-breadcrumb a",
        ".product-type-simple",
    ]

    for selector in selectors:
        links = soup.select(selector)
        if links:
            for link in links:
                href = link.get("href", "")
                name = link.get_text(strip=True)
                if not name or not href:
                    continue
                # استخرج الـ slug من الرابط
                slug = href.rstrip("/").split("/")[-1]
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                categories.append({
                    "name": name,
                    "name_ar": name,
                    "slug": slug,
                })
            if categories:
                break

    # فئة افتراضية إذا ما لقينا شي
    if not categories:
        categories = [{"name": "عام", "name_ar": "عام", "slug": "general"}]

    logger.info(f"Found {len(categories)} categories")
    return categories


def _scrape_products_from_page(soup: BeautifulSoup, default_category_id: int) -> list[dict]:
    products = []

    # WooCommerce standard selectors
    items = soup.select("ul.products li.product, .products .product")

    for item in items:
        # الاسم
        name_el = item.select_one("h2.woocommerce-loop-product__title, .product-title, h3")
        name = name_el.get_text(strip=True) if name_el else "منتج"

        # السعر
        price_el = item.select_one(".price ins .amount, .price .amount, .woocommerce-Price-amount")
        raw_price = price_el.get_text(strip=True) if price_el else ""
        price = _clean_price(raw_price)

        # الرابط
        link_el = item.select_one("a")
        product_url = link_el.get("href", "") if link_el else ""

        # الصورة
        img_el = item.select_one("img")
        image_url = (
            img_el.get("data-src") or img_el.get("src") or ""
            if img_el else ""
        )

        if not name or not product_url:
            continue

        products.append({
            "name": name,
            "name_ar": name,
            "price": price,
            "currency": "SAR",
            "image_url": image_url,
            "product_url": product_url,
            "category_id": default_category_id,
            "in_stock": True,
        })

    return products


def _get_total_pages(soup: BeautifulSoup) -> int:
    # WooCommerce pagination
    last = soup.select(".woocommerce-pagination a.page-numbers:not(.next)")
    if last:
        try:
            return int(last[-1].get_text(strip=True))
        except (ValueError, IndexError):
            pass
    return 1


def scrape_all_products(category_id: int = 1) -> list[dict]:
    all_products: list[dict] = []
    soup = _get(SHOP_URL)
    if not soup:
        return all_products

    total_pages = _get_total_pages(soup)
    logger.info(f"Total pages: {total_pages}")

    all_products.extend(_scrape_products_from_page(soup, category_id))

    for page in range(2, total_pages + 1):
        page_url = f"{SHOP_URL}/page/{page}/"
        page_soup = _get(page_url)
        if page_soup:
            products = _scrape_products_from_page(page_soup, category_id)
            all_products.extend(products)
            logger.info(f"Page {page}/{total_pages}: {len(products)} products")
        time.sleep(1)

    logger.info(f"Total scraped: {len(all_products)} products")
    return all_products


def _enrich_product(product: dict) -> dict:
    """يجيب الوصف من صفحة المنتج"""
    soup = _get(product["product_url"])
    if not soup:
        return product

    desc_el = soup.select_one(
        ".woocommerce-product-details__short-description, "
        ".product_description, "
        "[itemprop='description']"
    )
    if desc_el:
        product["description"] = desc_el.get_text(strip=True)[:500]

    return product


def run_full_scrape(enrich: bool = False) -> dict:
    """
    نشغّل السكرابر الكامل ونحفظ في Supabase.
    enrich=True يجيب وصف كل منتج (بطيء).
    """
    logger.info("Starting full scrape of نهضة أسيا...")

    # ─── الفئات ─────────────────────────────────
    raw_categories = scrape_categories()
    if not raw_categories:
        raw_categories = [{"name": "عام", "name_ar": "عام", "slug": "general"}]

    saved_cats = db.upsert_categories(raw_categories)
    logger.info(f"Saved {saved_cats} categories")

    categories = db.get_categories()
    default_cat_id = categories[0]["id"] if categories else 1

    # ─── المنتجات ────────────────────────────────
    products = scrape_all_products(category_id=default_cat_id)

    if enrich:
        enriched = []
        for i, p in enumerate(products):
            enriched.append(_enrich_product(p))
            if i % 10 == 0:
                logger.info(f"Enriched {i}/{len(products)}")
            time.sleep(0.5)
        products = enriched

    saved = db.upsert_products(products)
    logger.info(f"Saved {saved} products")

    return {"categories": saved_cats, "products": saved}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_full_scrape(enrich=False)
    print(f"Done: {result}")
