"""CarbonLensAI — practical carbon-footprint estimation MVP."""
import base64
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "carbonlens.db"
FACTORS_PATH = BASE_DIR / "templates" / "data" / "emission_factors.json"
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["JSON_SORT_KEYS"] = False

with FACTORS_PATH.open(encoding="utf-8") as f:
    FACTORS = json.load(f)


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            transport REAL NOT NULL,
            electricity REAL NOT NULL,
            food REAL NOT NULL,
            meals REAL NOT NULL DEFAULT 1,
            total REAL NOT NULL,
            distance_km REAL NOT NULL,
            electricity_units REAL NOT NULL,
            food_type TEXT NOT NULL,
            vehicle TEXT NOT NULL
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
        if "meals" not in columns:
            conn.execute("ALTER TABLE entries ADD COLUMN meals REAL NOT NULL DEFAULT 1")
        conn.execute("""CREATE TABLE IF NOT EXISTS routine (
            id INTEGER PRIMARY KEY CHECK(id=1), origin TEXT NOT NULL,
            destination TEXT NOT NULL, vehicle TEXT NOT NULL
        )""")


init_db()


def json_error(message, status=400):
    return jsonify({"success": False, "message": message}), status


def safe_float(value, label, maximum=100000):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a valid number.")
    if number < 0 or number > maximum:
        raise ValueError(f"{label} must be between 0 and {maximum}.")
    return number


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"success": True, "status": "ok", "app": "CarbonLensAI"})


@app.get("/api/config")
def config():
    return jsonify({"success": True, "factors": FACTORS, "ai_available": bool(os.getenv("GEMINI_API_KEY"))})


@app.post("/api/calculate")
def calculate():
    data = request.get_json(silent=True) or {}
    try:
        distance = safe_float(data.get("distance_km", 0), "Distance")
        units = safe_float(data.get("electricity_units", 0), "Electricity units")
        meals = safe_float(data.get("meals", 1), "Meal count", maximum=10000)
        vehicle = str(data.get("vehicle", "car")).lower()
        food_type = str(data.get("food_type", "vegetarian")).lower()
        if vehicle not in FACTORS["transport"]:
            return json_error("Choose a valid transport type.")
        if food_type not in FACTORS["food"]:
            return json_error("Choose a valid food category.")
        transport = distance * FACTORS["transport"][vehicle]
        electricity = units * FACTORS["electricity"]
        food = FACTORS["food"][food_type] * meals
        total = transport + electricity + food
        result = {"success": True, "transport": round(transport, 2), "electricity": round(electricity, 2),
                  "food": round(food, 2), "total": round(total, 2), "unit": "kg CO₂e",
                  "assumptions": "Illustrative factors; estimates depend on region, vehicle, grid mix, food portion and methodology."}
        with db() as conn:
            conn.execute("INSERT INTO entries(created_at,transport,electricity,food,meals,total,distance_km,electricity_units,food_type,vehicle) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (datetime.now(timezone.utc).isoformat(), transport, electricity, food, meals, total, distance, units, food_type, vehicle))
        return jsonify(result)
    except ValueError as exc:
        return json_error(str(exc))


@app.get("/api/history")
def history():
    with db() as conn:
        rows = conn.execute("SELECT * FROM entries ORDER BY id DESC LIMIT 30").fetchall()
    return jsonify({"success": True, "entries": [dict(r) for r in rows]})


@app.delete("/api/history")
def clear_history():
    with db() as conn:
        conn.execute("DELETE FROM entries")
    return jsonify({"success": True, "message": "Calculation history cleared."})


@app.post("/api/recommendations")
def recommendations():
    data = request.get_json(silent=True) or {}
    try:
        values = {k: safe_float(data.get(k, 0), k) for k in ("transport", "electricity", "food")}
    except ValueError as exc:
        return json_error(str(exc))
    highest = max(values, key=values.get)
    prompt = ("Act as a practical sustainability coach. Give exactly 3 concise, specific, non-judgmental actions. "
              "Do not claim precise savings unless calculated. User's estimated kg CO2e: " +
              ", ".join(f"{k}: {v:.2f}" for k, v in values.items()) + f". Largest category: {highest}.")
    answer = call_gemini_text(prompt)
    if answer:
        return jsonify({"success": True, "message": answer, "mode": "Gemini AI"})
    tips = {
        "transport": ["Combine errands into one trip.", "Use public transport or carpool when practical.", "Walk or cycle for short journeys."],
        "electricity": ["Switch off appliances instead of leaving them on standby.", "Use efficient fans, lighting and appliances.", "Set AC to a moderate temperature and clean its filters."],
        "food": ["Plan meals to reduce food waste.", "Include more legumes and seasonal plant-based meals.", "Store food correctly and use leftovers safely."]
    }
    return jsonify({"success": True, "message": "\n".join(f"{i+1}. {tip}" for i, tip in enumerate(tips[highest])),
                    "mode": "Built-in recommendations", "note": "Gemini key not configured; these are rule-based tips."})


def call_gemini_text(prompt):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    return gemini_request(payload, key)


def gemini_request(payload, key):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=" + urllib.parse.quote(key)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = json.loads(response.read().decode())
        return "\n".join(p.get("text", "") for p in body.get("candidates", [{}])[0].get("content", {}).get("parts", [])).strip() or None
    except Exception:
        app.logger.exception("Gemini request failed")
        return None


@app.post("/api/analyze-food")
def analyze_food():
    if not os.getenv("GEMINI_API_KEY"):
        return json_error("Food-image AI needs GEMINI_API_KEY. You can still select the food category manually.", 503)
    if "image" not in request.files:
        return json_error("Choose a food image first.")
    image = request.files["image"]
    if not image.mimetype or not image.mimetype.startswith("image/"):
        return json_error("Upload a valid image file.")
    raw = image.read()
    if not raw or len(raw) > 7 * 1024 * 1024:
        return json_error("Image is empty or larger than 7 MB.")
    mime = image.mimetype if image.mimetype in ("image/jpeg", "image/png", "image/webp") else "image/jpeg"
    prompt = ("Identify the main food visible. Return JSON only with keys food_type (one of vegetarian, chicken, fish, mutton, mixed, unknown), "
              "dish_name, confidence (0 to 1), and explanation. Do not infer ingredients that are not visually apparent. "
              "This is a rough visual classification, not a measured portion or footprint.")
    payload = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode()}}]}],
               "generationConfig": {"responseMimeType": "application/json"}}
    answer = gemini_request(payload, os.getenv("GEMINI_API_KEY"))
    if not answer:
        return json_error("Food-image analysis is temporarily unavailable. Select the category manually.", 502)
    try:
        parsed = json.loads(answer)
        if parsed.get("food_type") not in ("vegetarian", "chicken", "fish", "mutton", "mixed", "unknown"):
            raise ValueError()
        return jsonify({"success": True, "result": parsed, "disclaimer": "Visual classification can be wrong; confirm the category and portion yourself."})
    except (ValueError, json.JSONDecodeError):
        return json_error("The image model returned an unreadable result. Try again or select manually.", 502)


def geocode(place):
    query = urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/search?" + query,
                                 headers={"User-Agent": "CarbonLensAI/1.0 (local carbon estimator)"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            items = json.loads(response.read().decode())
        if items:
            return float(items[0]["lat"]), float(items[0]["lon"])
    except Exception:
        app.logger.exception("Geocoding failed")
    return None


def route_distance(a, b):
    # OSRM gives a routable road distance. This public demo service is best-effort.
    coords = f"{a[1]},{a[0]};{b[1]},{b[0]}"
    url = "https://router.project-osrm.org/route/v1/driving/" + coords + "?overview=false"
    req = urllib.request.Request(url, headers={"User-Agent": "CarbonLensAI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.loads(response.read().decode())
        routes = result.get("routes") or []
        if routes:
            return round(routes[0]["distance"] / 1000, 2)
    except Exception:
        app.logger.exception("OSRM routing failed")
    return None


@app.post("/api/route")
def route():
    data = request.get_json(silent=True) or {}
    origin, destination = str(data.get("origin", "")).strip(), str(data.get("destination", "")).strip()
    if not origin or not destination or len(origin) > 180 or len(destination) > 180:
        return json_error("Enter valid origin and destination names (under 180 characters).")
    a = geocode(origin)
    time.sleep(1.05)  # Respect the public Nominatim service usage limit.
    b = geocode(destination)
    if not a or not b:
        return json_error("Could not locate one or both places. Add a city or more specific address.", 422)
    distance = route_distance(a, b)
    if distance is None:
        return json_error("A road route could not be calculated right now. Please try again later.", 503)
    factors = FACTORS["transport"]
    comparison = {name.title(): round(distance * factor, 2) for name, factor in factors.items()}
    return jsonify({"success": True, "distance_km": distance, "comparison": comparison,
                    "best_mode": min(comparison, key=comparison.get),
                    "source": "OpenStreetMap geocoding + OSRM driving route",
                    "note": "The distance follows a driving route; emissions for other modes are factor-based estimates, not mode-specific route calculations."})


@app.get("/api/routine")
def get_routine():
    with db() as conn:
        row = conn.execute("SELECT origin,destination,vehicle FROM routine WHERE id=1").fetchone()
    return jsonify({"success": True, "routine": dict(row) if row else None})


@app.put("/api/routine")
def put_routine():
    data = request.get_json(silent=True) or {}
    origin, destination = str(data.get("origin", "")).strip(), str(data.get("destination", "")).strip()
    vehicle = str(data.get("vehicle", "car")).lower()
    if not origin or not destination:
        return json_error("Enter both your routine start and destination.")
    if vehicle not in FACTORS["transport"]:
        return json_error("Choose a valid vehicle type.")
    with db() as conn:
        conn.execute("INSERT INTO routine(id,origin,destination,vehicle) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET origin=excluded.origin,destination=excluded.destination,vehicle=excluded.vehicle",
                     (origin, destination, vehicle))
    return jsonify({"success": True, "message": "Daily routine saved on this server."})


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return json_error("Upload is too large. Maximum request size is 8 MB.", 413)


@app.errorhandler(500)
def server_error(_error):
    return json_error("Something went wrong on the server. Check the terminal logs.", 500)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
