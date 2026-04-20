"""
Supabase database manager — direct REST API (works with anon/publishable key)
"""
import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
REST_URL = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _get(table: str, params: dict = None) -> list[dict]:
    try:
        r = requests.get(f"{REST_URL}/{table}", headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json() if isinstance(r.json(), list) else []
    except Exception as exc:
        logger.error(f"GET {table} failed: {exc}")
        return []


def _post(table: str, data: dict | list, prefer: str = "return=representation") -> list[dict]:
    try:
        h = {**HEADERS, "Prefer": prefer}
        r = requests.post(f"{REST_URL}/{table}", headers=h, json=data, timeout=10)
        r.raise_for_status()
        return r.json() if r.text else []
    except Exception as exc:
        logger.error(f"POST {table} failed: {exc}")
        return []


def _upsert(table: str, data: dict | list, on_conflict: str) -> list[dict]:
    try:
        h = {**HEADERS, "Prefer": f"resolution=merge-duplicates,return=representation"}
        params = {"on_conflict": on_conflict}
        r = requests.post(f"{REST_URL}/{table}", headers=h, json=data, params=params, timeout=10)
        r.raise_for_status()
        return r.json() if r.text else []
    except Exception as exc:
        logger.error(f"UPSERT {table} failed: {exc}")
        return []


# ─── Clients ───────────────────────────────────────────────────────────────────

def upsert_client(user_id: int, username: str | None, full_name: str) -> dict:
    data = {
        "id": user_id,
        "username": username,
        "full_name": full_name,
    }
    result = _upsert("clients", data, on_conflict="id")
    return result[0] if result else {}


def is_client_active(user_id: int) -> bool:
    rows = _get("clients", params={"id": f"eq.{user_id}", "select": "active"})
    if not rows:
        return True  # عميل جديد — نشط افتراضياً
    return rows[0].get("active", True)


# ─── Conversations ──────────────────────────────────────────────────────────────

def save_message(client_id: int, role: str, message: str) -> None:
    _post("conversations", {
        "client_id": client_id,
        "role": role,
        "message": message,
    })


def get_conversation_history(client_id: int, limit: int = 10) -> list[dict]:
    rows = _get("conversations", params={
        "client_id": f"eq.{client_id}",
        "select": "role,message,created_at",
        "order": "created_at.desc",
        "limit": limit,
    })
    return list(reversed(rows))


# ─── Products ──────────────────────────────────────────────────────────────────

def get_all_products(limit: int = 200) -> list[dict]:
    return _get("products", params={
        "in_stock": "eq.true",
        "select": "*, categories(name, name_ar)",
        "limit": limit,
    })


def search_products(query: str) -> list[dict]:
    return _get("products", params={
        "or": f"(name.ilike.*{query}*,name_ar.ilike.*{query}*,description.ilike.*{query}*)",
        "in_stock": "eq.true",
        "select": "*, categories(name, name_ar)",
        "limit": 10,
    })


def get_products_by_category(category_id: int) -> list[dict]:
    return _get("products", params={
        "category_id": f"eq.{category_id}",
        "in_stock": "eq.true",
        "select": "*, categories(name, name_ar)",
        "limit": 20,
    })


def get_categories() -> list[dict]:
    return _get("categories")


def upsert_products(products: list[dict]) -> int:
    if not products:
        return 0
    # نرفع على دفعات عشان ما يطول الطلب
    batch_size = 50
    total = 0
    for i in range(0, len(products), batch_size):
        batch = products[i:i + batch_size]
        result = _upsert("products", batch, on_conflict="product_url")
        total += len(result)
    return total


def upsert_categories(categories: list[dict]) -> int:
    if not categories:
        return 0
    result = _upsert("categories", categories, on_conflict="slug")
    return len(result)


# ─── Orders ────────────────────────────────────────────────────────────────────

def save_order(client_id: int, product_name: str, notes: str = "") -> dict:
    result = _post("orders", {
        "client_id": client_id,
        "product_name": product_name,
        "notes": notes,
        "status": "pending",
    })
    return result[0] if result else {}
