"""
QuickCommerceAPI (/v1/item) client + result formatting.

Checks one item id on one platform at one location. Mirrors the batch
scraper's proven request + retry logic. The API key is read from the
QC_API_KEY environment variable — never hardcode it in a public repo.
"""

import os
import time

import requests

API_URL = "https://api.quickcommerceapi.com/v1/item"
API_KEY = os.environ.get("QC_API_KEY", "")

HTTP_RETRIES = 3

# API platform value -> friendly label shown to the user
PLATFORM_LABEL = {
    "BlinkIt": "Blinkit",
    "Zepto": "Zepto",
    "Swiggy": "Instamart (Swiggy)",
    "Amazon": "Amazon",
    "Minutes": "Flipkart Minutes",
}


class ApiFatalError(Exception):
    """Key / credits / bad id or platform — don't retry, surface to the user."""


def fetch_item(item_id, platform, pincode, lat, lon):
    """Returns (status, items, detail). status is 'ok', 'not_available' or 'error'."""
    if not API_KEY:
        raise ApiFatalError("Server is missing QC_API_KEY.")
    params = {"item_id": item_id, "lat": lat, "lon": lon,
              "platform": platform, "pincode": pincode}
    detail = ""
    for attempt in range(HTTP_RETRIES + 1):
        try:
            resp = requests.get(API_URL, headers={"X-API-Key": API_KEY},
                                params=params, timeout=20)
        except requests.RequestException as e:
            detail = f"network error: {e}"
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            try:
                data = resp.json().get("data") or {}
            except ValueError:
                return "error", [], "invalid JSON in response"
            return "ok", data.get("items") or [], ""
        if resp.status_code == 404:
            return "not_available", [], resp.text[:200]
        if resp.status_code in (401, 402, 422):
            # 401 bad key, 402 out of credits, 422 bad item id / platform
            raise ApiFatalError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
        wait = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
        time.sleep(min(wait, 8))
    return "error", [], detail


def make_rows(status, items, detail, pincode, city, product_id, platform_label):
    base = {"Platform": platform_label, "Product ID": product_id,
            "Pincode": pincode, "City": city}
    if status == "not_available":
        return [{**base, "Availability": "Not available here",
                 "Note": "Item not sold at this location (HTTP 404)"}]
    if status == "error":
        return [{**base, "Availability": "Error", "Note": detail}]
    if not items:
        return [{**base, "Availability": "Not available here", "Note": "API returned no item"}]

    rows = []
    for it in items:
        price, mrp = it.get("price"), it.get("mrp")
        discount = ""
        if isinstance(price, (int, float)) and isinstance(mrp, (int, float)) and mrp:
            discount = f"{round((mrp - price) / mrp * 100, 1)}%"
        rows.append({**base,
                     "Product ID": it.get("item_id") or product_id,
                     "Product Name": it.get("name", ""),
                     "Brand": it.get("brand") or "",
                     "Pack Size": it.get("quantity", ""),
                     "Availability": "In Stock" if it.get("available") else "Out of Stock",
                     "Selling Price": price, "MRP": mrp, "Discount": discount,
                     "Inventory": it.get("inventory", ""),
                     "Store ID": it.get("store_id", ""),
                     "Note": ""})
    return rows


def pincode_status(rows):
    """One verdict per pincode: In Stock only if EVERY variant is in stock."""
    statuses = [r.get("Availability") for r in rows]
    if statuses and all(s == "In Stock" for s in statuses):
        return "In Stock"
    if "Out of Stock" in statuses:
        return "Out of Stock"
    return statuses[0] if statuses else "Error"
