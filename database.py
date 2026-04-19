"""
Supabase database manager for Nahdah Asia bot
"""
import os
import logging
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def get_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key)


# ─── Clients ───────────────────────────────────────────────────────────────────

def upsert_client(user_id: int, username: str | None, full_name: str) -> dict:
    db = get_client()
    data = {
        "id": user_id,
        "username": username,
        "full_name": full_name,
        "updated_at": "now()",
    }
    result = db.table("clients").upsert(data, on_conflict="id").execute()
    return result.data[0] if result.data else {}


def is_client_active(user_id: int) -> bool:
    db = get_client()
    result = db.table("clients").select("active").eq("id", user_id).single().execute()
    if not result.data:
        return True  # عميل جديد — نشط افتراضياً
    return result.data.get("active", True)


# ─── Conversations ──────────────────────────────────────────────────────────────

def save_message(client_id: int, role: str, message: str) -> None:
    db = get_client()
    db.table("conversations").insert({
        "client_id": client_id,
        "role": role,
        "message": message,
    }).execute()


def get_conversation_history(client_id: int, limit: int = 10) -> list[dict]:
    db = get_client()
    result = (
        db.table("conversations")
        .select("role, message, created_at")
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    messages = result.data or []
    return list(reversed(messages))


# ─── Products ──────────────────────────────────────────────────────────────────

def get_all_products(limit: int = 200) -> list[dict]:
    db = get_client()
    result = (
        db.table("products")
        .select("*, categories(name, name_ar)")
        .eq("in_stock", True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def search_products(query: str) -> list[dict]:
    db = get_client()
    result = (
        db.table("products")
        .select("*, categories(name, name_ar)")
        .or_(f"name.ilike.%{query}%,name_ar.ilike.%{query}%,description.ilike.%{query}%")
        .eq("in_stock", True)
        .limit(10)
        .execute()
    )
    return result.data or []


def get_products_by_category(category_id: int) -> list[dict]:
    db = get_client()
    result = (
        db.table("products")
        .select("*, categories(name, name_ar)")
        .eq("category_id", category_id)
        .eq("in_stock", True)
        .limit(20)
        .execute()
    )
    return result.data or []


def get_categories() -> list[dict]:
    db = get_client()
    result = db.table("categories").select("*").execute()
    return result.data or []


def upsert_products(products: list[dict]) -> int:
    if not products:
        return 0
    db = get_client()
    db.table("products").upsert(products, on_conflict="product_url").execute()
    return len(products)


def upsert_categories(categories: list[dict]) -> int:
    if not categories:
        return 0
    db = get_client()
    db.table("categories").upsert(categories, on_conflict="slug").execute()
    return len(categories)


# ─── Orders ────────────────────────────────────────────────────────────────────

def save_order(client_id: int, product_name: str, notes: str = "") -> dict:
    db = get_client()
    result = db.table("orders").insert({
        "client_id": client_id,
        "product_name": product_name,
        "notes": notes,
        "status": "pending",
    }).execute()
    return result.data[0] if result.data else {}
