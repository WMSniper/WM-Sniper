from flask import Flask, request, jsonify, render_template, send_file
import requests
import threading
import time
import json
import os
import sys

# try to import rapidfuzz (preferred); fallback to difflib
try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except Exception:
    from difflib import get_close_matches
    HAS_RAPIDFUZZ = False

# Flask + CORS (auto)
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # enable CORS for all routes

# -------------------------
# Config / storage / cache
# -------------------------
MATCHES = []
DEFAULT_MAX_RANK = 10

ITEM_MAX_RANKS = {
    "serration": 10,
    "point_strike": 10,
    "vitality": 10,
    "hornet_strike": 10,
    "pressure_point": 10,
    "redirection": 10,
    "streamline": 5,
    "intensify": 5,
    "continuity": 5,
    "stretch": 5,
    "flow": 5,
    # add more items/mods with their actual max rank
}

FAVORITES_FILE = "favorites.json"
ITEMS_CACHE_FILE = "items_cache.json"
ITEMS_CACHE_TTL = 3600  # 1 hour (reduced from 24 hours)
MAX_AUTOCOMPLETE_RESULTS = 12
FUZZY_SCORE_THRESHOLD = 60  # minimum WRatio threshold to consider a fuzzy match

# in-memory caches
_items_cache = {"fetched_at": 0, "items": []}  # items: dicts {url_name, display_name, icon}
favorites = {"categories": {"default": []}}  # persistent structure

# -------------------------
# Thread management
# -------------------------
active_watches = {}
stop_events = {}
matches_lock = threading.Lock()
stop_events_lock = threading.Lock()

# -------------------------
# Utility: favorites file
# -------------------------
def load_favorites():
    global favorites
    if os.path.exists(FAVORITES_FILE):
        try:
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                favorites = json.load(f)
        except Exception as e:
            print("Error loading favorites.json:", e)
            favorites = {"categories": {"default": []}}
    else:
        favorites = {"categories": {"default": []}}

def save_favorites():
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving favorites.json:", e)

# -------------------------
# Utility: items cache
# -------------------------
def load_items_cache_from_disk():
    global _items_cache
    if os.path.exists(ITEMS_CACHE_FILE):
        try:
            with open(ITEMS_CACHE_FILE, "r", encoding="utf-8") as f:
                _items_cache = json.load(f)
        except Exception as e:
            print("Error loading items cache:", e)

def save_items_cache_to_disk():
    try:
        with open(ITEMS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_items_cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Error saving items cache:", e)

def fetch_items_from_api(force=False):
    """
    Maintains a cache of items from warframe.market.
    Returns a list of dicts: {url_name, display_name, icon}
    """
    global _items_cache
    now = time.time()
    if not force and _items_cache.get("items") and (now - _items_cache.get("fetched_at", 0) < ITEMS_CACHE_TTL):
        return _items_cache["items"]

    try:
        url = "https://api.warframe.market/v1/items"
        res = requests.get(url, timeout=10, headers={"User-Agent": "wf-sniper/1.0"})
        res.raise_for_status()
        payload = res.json().get("payload", {}) or {}
        items_raw = payload.get("items") or payload.get("data") or []

        normalized = []
        
        for it in items_raw:
            url_name = it.get("url_name") or it.get("url") or it.get("item_url")
            display_en = None
            if isinstance(it.get("en"), str):
                display_en = it.get("en")
            else:
                display_en = it.get("item_name") or it.get("name") or it.get("en_name")
            icon = it.get("icon") or it.get("thumb") or None

            if isinstance(display_en, dict):
                display_en = display_en.get("en") or display_en.get("en_US") or next(iter(display_en.values()), None)

            if url_name:
                normalized.append({
                    "url_name": url_name,
                    "display_name": (display_en or url_name.replace("_", " ").title()),
                    "icon": icon
                })

        _items_cache = {"fetched_at": now, "items": normalized}
        save_items_cache_to_disk()
        return normalized
    except Exception as e:
        print("Error fetching items from API:", e)
        load_items_cache_from_disk()
        return _items_cache.get("items", [])

# Load cache synchronously at startup
load_items_cache_from_disk()
fetch_items_from_api(force=False)

# -------------------------
# Helpers
# -------------------------
def to_item_url(display_name: str) -> str:
    return display_name.replace(" ", "_").lower()

def get_max_rank_for_item(item_url, override_max_rank):
    if override_max_rank is not None and override_max_rank != "":
        try:
            return int(override_max_rank)
        except Exception:
            pass
    if item_url in ITEM_MAX_RANKS:
        return ITEM_MAX_RANKS[item_url]
    return DEFAULT_MAX_RANK

# -------------------------
# Watcher logic
# -------------------------
def watch_item(item_url, item_display_name, max_price, desired_rank, override_max_rank):
    """
    Thread that periodically queries orders for item_url.
    Handles:
     - adding new MATCHES when valid offers are found
     - removing from MATCHES offers that no longer appear in the API
     - if the item is removed (404/410), cleans up matches and terminates the watcher
    """
    effective_max_rank = get_max_rank_for_item(item_url, override_max_rank)
    
    # Create a stop event for this watch
    stop_event = threading.Event()
    
    with stop_events_lock:
        if item_url not in stop_events:
            stop_events[item_url] = []
        stop_events[item_url].append(stop_event)
    
    while not stop_event.is_set():
        try:
            # Increase limit to 100 results and add sorting parameters
            url = f"https://api.warframe.market/v1/items/{item_url}/orders?limit=100&order_by=creation_date"
            res = requests.get(url, timeout=10, headers={"User-Agent": "wf-sniper/1.0"})

            # If the item has been removed from the market, API may respond with 404/410
            if res.status_code in (404, 410):
                print(f"🗑️ Item '{item_url}' removed from market (status {res.status_code}). Cleaning matches and terminating watcher.")
                with matches_lock:
                    global MATCHES
                    MATCHES = [m for m in MATCHES if m["item"] != item_url]
                break

            res.raise_for_status()
            orders = res.json().get("payload", {}).get("orders", []) or []

            # Build set of current offers (identifier: item_seller_price),
            # considering only offers that meet filters (price, status, rank)
            current_msg_ids = set()
            for order in orders:
                if not (order.get("order_type") == "sell"):
                    continue
                price = order.get("platinum", 999999)
                if price is None:
                    continue
                try:
                    if int(price) > int(max_price):
                        continue
                except Exception:
                    continue

                status = order.get("user", {}).get("status")
                if status not in ["ingame", "online"]:
                    continue

                order_rank = order.get("mod_rank")
                if order_rank is None:
                    order_rank = order.get("rank")

                if desired_rank == "Maxed":
                    if order_rank is None:
                        continue
                    try:
                        if int(order_rank) < int(effective_max_rank):
                            continue
                    except Exception:
                        continue

                seller = order.get("user", {}).get("ingame_name") or ""
                # use string for price to avoid float/int issues
                msg_id = f"{item_url}_{seller}_{price}"
                current_msg_ids.add(msg_id)

            # Add new offers (those in current_msg_ids but not in MATCHES)
            with matches_lock:
                # build set of msg_ids already in MATCHES for this item
                existing_msg_ids = set()
                for m in MATCHES:
                    try:
                        if m.get("item") == item_url:
                            s = m.get("seller") or ""
                            p = m.get("price")
                            existing_msg_ids.add(f"{item_url}_{s}_{p}")
                    except Exception:
                        continue

                # Find new ids to add
                to_add_ids = current_msg_ids - existing_msg_ids

            # To reinsert, we need to iterate through orders again (or map order by msg_id)
            # Create msg_id -> order info map to add missing matches
            msgid_to_order = {}
            for order in orders:
                seller = order.get("user", {}).get("ingame_name") or ""
                price = order.get("platinum", 999999)
                try:
                    msg_id = f"{item_url}_{seller}_{price}"
                except Exception:
                    continue
                if msg_id in to_add_ids:
                    msgid_to_order[msg_id] = order

            # Add new matches
            with matches_lock:
                for mid, order in msgid_to_order.items():
                    order_rank = order.get("mod_rank")
                    if order_rank is None:
                        order_rank = order.get("rank")
                    seller = order.get("user", {}).get("ingame_name")
                    price = order.get("platinum")
                    match = {
                        "item": item_url,
                        "display_name": item_display_name,
                        "price": price,
                        "seller": seller,
                        "status": order.get("user", {}).get("status"),
                        "rank": order_rank,
                        "desired_rank": desired_rank,
                        "effective_max_rank": effective_max_rank
                    }
                    if match not in MATCHES:
                        MATCHES.append(match)
                        print("✅ New offer found:", match)

                # Remove from MATCHES offers that belong to this item but are
                # no longer present in current_msg_ids (cancelled from market)
                initial_len = len(MATCHES)
                MATCHES = [m for m in MATCHES if not (m.get("item") == item_url and f"{item_url}_{(m.get('seller') or '')}_{m.get('price')}" not in current_msg_ids)]
                removed_count = initial_len - len(MATCHES)
                if removed_count > 0:
                    print(f"ℹ️ Removed {removed_count} offers no longer present for item '{item_url}'")

        except requests.exceptions.RequestException as e:
            # If there's a network/proxy error, log it and continue (but don't remove matches in this case)
            print("Error refreshing items (network):", e)
        except Exception as e:
            print("Error refreshing items:", e)

        # Sleep with stop event check
        for _ in range(10):
            if stop_event.is_set():
                break
            time.sleep(1)
    
    # Cleanup after thread termination
    with stop_events_lock:
        if item_url in stop_events and stop_event in stop_events[item_url]:
            stop_events[item_url].remove(stop_event)
            if not stop_events[item_url]:
                del stop_events[item_url]

# -------------------------
# Routes
# -------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/download-overlay")
def download_overlay():
    try:
        return send_file("ov.py", as_attachment=True, download_name="warframe_market_sniper_overlay.py")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/start_watch", methods=["POST"])
def start_watch():
    item_display_name = request.form.get("item", "").strip()
    item_url = request.form.get("item_url", "").strip()
    if not item_url and item_display_name:
        item_url = to_item_url(item_display_name)

    try:
        max_price = int(request.form.get("max_price", "999999"))
    except Exception:
        max_price = 999999

    rank_choice = request.form.get("rank_choice", "All")
    override_max_rank = request.form.get("max_rank_override") or None

    # Remove existing matches for this item
    with matches_lock:
        global MATCHES
        MATCHES = [m for m in MATCHES if m["item"] != item_url]

    threading.Thread(
        target=watch_item,
        args=(item_url, item_display_name or item_url.replace("_", " ").title(), max_price, rank_choice, override_max_rank),
        daemon=True
    ).start()

    return jsonify({
        "status": "started",
        "item": item_url,
        "max_price": max_price,
        "rank_choice": rank_choice,
        "max_rank_override": override_max_rank
    })

@app.route("/stop_watch", methods=["POST"])
def stop_watch():
    item_url = request.form.get("item_url", "").strip()
    if not item_url:
        return jsonify({"error": "item_url required"}), 400
        
    events_list = []
    with stop_events_lock:
        if item_url in stop_events:
            events_list = stop_events[item_url][:]  # Copy to avoid modifications during iteration
            
    for event in events_list:
        event.set()  # Signal the thread to stop
        
    return jsonify({
        "status": "stopped", 
        "item": item_url,
        "count": len(events_list)
    })

@app.route("/clear_matches", methods=["POST"])
def clear_matches():
    item_url = request.form.get("item_url", "").strip()
    if not item_url:
        return jsonify({"error": "item_url required"}), 400
        
    with matches_lock:
        global MATCHES
        initial_count = len(MATCHES)
        MATCHES = [m for m in MATCHES if m["item"] != item_url]
        removed_count = initial_count - len(MATCHES)
        
    return jsonify({
        "status": "cleared",
        "item": item_url,
        "removed_count": removed_count
    })

@app.route("/matches")
def get_matches():
    with matches_lock:
        matches_copy = MATCHES[:]  # Copy to avoid thread conflicts
    return jsonify(matches_copy)

@app.route("/manual_offers", methods=["GET"])
def manual_offers():
    item_url = request.args.get("item_url")
    rank = request.args.get("rank", "all").lower()
    max_rank_override = request.args.get("max_rank_override")
    
    if not item_url:
        return jsonify({"error": "item_url required"}), 400

    try:
        url = f"https://api.warframe.market/v1/items/{item_url}/orders"
        res = requests.get(url, timeout=10, headers={"User-Agent": "wf-sniper/1.0"})
        res.raise_for_status()
        orders = res.json().get("payload", {}).get("orders", []) or []

        # Pre-set filters: Sellers and In Game
        filtered_orders = []
        for order in orders:
            if order.get("order_type") != "sell":
                continue
                
            # Seller status filter: only "ingame"
            if order.get("user", {}).get("status") != "ingame":
                continue
                
            # Rank filter
            order_rank = order.get("mod_rank") or order.get("rank")
            if rank == "maxed":
                # Use override if specified, otherwise default value
                max_rank = get_max_rank_for_item(item_url, max_rank_override)
                if order_rank is None or int(order_rank) < max_rank:
                    continue
            elif rank == "all":
                # Accept any rank, including None (which means not applicable or 0)
                pass

            filtered_orders.append(order)

        # Sort by price (ascending)
        filtered_orders.sort(key=lambda x: x.get("platinum", 999999))

        # Take the first 10 offers
        filtered_orders = filtered_orders[:10]

        # Format output like other offers
        results = []
        for order in filtered_orders:
            results.append({
                "item": item_url,
                "display_name": item_url.replace("_", " ").title(),
                "price": order.get("platinum"),
                "seller": order.get("user", {}).get("ingame_name"),
                "status": order.get("user", {}).get("status"),
                "rank": order.get("mod_rank") or order.get("rank")
            })

        return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# Favorites management
# -------------------------
load_favorites()

@app.route("/favorites", methods=["GET"])
def api_get_favorites():
    return jsonify(favorites)

@app.route("/favorites/add_category", methods=["POST"])
def api_add_category():
    name = request.form.get("category_name", "").strip()
    if not name:
        return jsonify({"error": "category_name required"}), 400
    if name in favorites["categories"]:
        return jsonify({"error": "category already exists"}), 400
    favorites["categories"][name] = []
    save_favorites()
    return jsonify({"status": "created", "category": name})

@app.route("/favorites/remove_category", methods=["POST"])
def api_remove_category():
    name = request.form.get("category_name", "").strip()
    if not name or name not in favorites["categories"]:
        return jsonify({"error": "category not found"}), 404
    del favorites["categories"][name]
    save_favorites()
    return jsonify({"status": "removed", "category": name})

@app.route("/favorites/add_item", methods=["POST"])
def api_add_item_to_category():
    category = request.form.get("category", "default")
    display_name = request.form.get("display_name", "").strip()
    if not display_name:
        return jsonify({"error": "display_name required"}), 400
    item_url = to_item_url(display_name)
    entry = {"display_name": display_name, "item_url": item_url}
    if category not in favorites["categories"]:
        return jsonify({"error": "category not found"}), 404
    if entry in favorites["categories"][category]:
        return jsonify({"error": "item already in category"}), 400
    favorites["categories"][category].append(entry)
    save_favorites()
    return jsonify({"status": "added", "category": category, "item": entry})

@app.route("/favorites/remove_item", methods=["POST"])
def api_remove_item_from_category():
    category = request.form.get("category", "default")
    display_name = request.form.get("display_name", "").strip()
    if not display_name:
        return jsonify({"error": "display_name required"}), 400
    item_url = to_item_url(display_name)
    entry = {"display_name": display_name, "item_url": item_url}
    if category not in favorites["categories"]:
        return jsonify({"error": "category not found"}), 404
    try:
        favorites["categories"][category].remove(entry)
    except ValueError:
        return jsonify({"error": "item not found in category"}), 404
    save_favorites()
    return jsonify({"status": "removed", "category": category, "item": entry})

@app.route("/start_watch_selected", methods=["POST"])
def start_watch_selected():
    category = request.form.get("category")
    selected_items = request.form.get("selected_items")
    try:
        max_price = int(request.form.get("max_price", "999999"))
    except Exception:
        max_price = 999999
    rank_choice = request.form.get("rank_choice", "All")
    override_max_rank = request.form.get("max_rank_override") or None

    items_to_start = []
    if selected_items:
        for dn in [s.strip() for s in selected_items.split(",") if s.strip()]:
            items_to_start.append({"display_name": dn, "item_url": to_item_url(dn)})
    else:
        if not category or category not in favorites["categories"]:
            return jsonify({"error": "category required or not found"}), 400
        items_to_start = favorites["categories"][category]

    for entry in items_to_start:
        # Remove existing matches for this item
        with matches_lock:
            MATCHES = [m for m in MATCHES if m["item"] != entry["item_url"]]
            
        threading.Thread(
            target=watch_item,
            args=(entry["item_url"], entry["display_name"], max_price, rank_choice, override_max_rank),
            daemon=True
        ).start()

    return jsonify({"status": "started", "count": len(items_to_start)})

# -------------------------
# Enhanced Autocomplete
# -------------------------
@app.route("/autocomplete")
def autocomplete():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])

    items = fetch_items_from_api(force=False)
    if not items:
        return jsonify([])

    results = []
    for item in items:
        if q in item['display_name'].lower():
            results.append(item)

    # Sort by query position in the name
    results.sort(key=lambda x: x['display_name'].lower().index(q))
    
    # Limit results
    results = results[:MAX_AUTOCOMPLETE_RESULTS]
    
    # Format output
    out = [{
        "url_name": r["url_name"],
        "display_name": r["display_name"],
        "icon": r.get("icon")
    } for r in results]
    
    return jsonify(out)

@app.route("/_refresh_items_cache", methods=["POST"])
def refresh_items_cache():
    try:
        fetch_items_from_api(force=True)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# -------------------------
# Run server
# -------------------------
if __name__ == "__main__":
    print("HAS_RAPIDFUZZ =", HAS_RAPIDFUZZ)
    app.run(host="0.0.0.0", port=8080, debug=True)