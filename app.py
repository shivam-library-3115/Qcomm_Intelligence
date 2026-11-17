import json
import os
import re
import time
from collections import defaultdict, deque

from flask import (Flask, request, Response, render_template,
                   stream_with_context, session, redirect, url_for)
from dotenv import load_dotenv

import locator
import qc_api

load_dotenv()

app = Flask(__name__)

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    print("WARNING: SECRET_KEY not set — using a random key (logins reset on restart).")
    SECRET_KEY = os.urandom(32).hex()
app.secret_key = SECRET_KEY

SITE_PASSWORD = os.environ.get("SITE_PASSWORD")
if not SITE_PASSWORD:
    print("WARNING: SITE_PASSWORD not set — the site is OPEN. Since each lookup "
          "costs API credits, set SITE_PASSWORD to protect it.")

if not os.environ.get("QC_API_KEY"):
    print("WARNING: QC_API_KEY not set — lookups will fail until it is configured.")

MAX_PINCODES = int(os.environ.get("MAX_PINCODES", "60"))   # per request, protects credits
REQUEST_DELAY_SECONDS = float(os.environ.get("REQUEST_DELAY_SECONDS", "1.0"))

PLATFORMS = ["BlinkIt", "Zepto", "Swiggy", "Amazon", "Minutes"]

# --- simple per-IP rate limiting for login attempts ---
LOGIN_RATE_LIMIT = 5
LOGIN_RATE_WINDOW = 300
_login_log = defaultdict(deque)


def login_rate_limited(ip):
    now = time.time()
    log = _login_log[ip]
    while log and now - log[0] > LOGIN_RATE_WINDOW:
        log.popleft()
    if len(log) >= LOGIN_RATE_LIMIT:
        return True
    log.append(now)
    return False


def sse(event, data):
    """Format one SSE event with a JSON payload."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def parse_pincodes(raw):
    """Split a free-text blob into a de-duped list of valid 6-digit pincodes."""
    tokens = re.split(r"[^0-9]+", raw or "")
    seen, out = set(), []
    for t in tokens:
        if len(t) == 6 and t not in seen:
            seen.add(t)
            out.append(t)
    return out


@app.before_request
def require_login():
    if not SITE_PASSWORD:
        return
    if request.endpoint in ("login", "static"):
        return
    if session.get("authed"):
        return
    if request.endpoint == "check":
        return {"error": "Session expired — refresh the page and log in again."}, 401
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr) or "?"
        if login_rate_limited(ip):
            error = "Too many attempts. Wait a few minutes."
        elif SITE_PASSWORD and request.form.get("password") == SITE_PASSWORD:
            session["authed"] = True
            return redirect(url_for("index"))
        else:
            error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template("index.html", platforms=PLATFORMS,
                           auth_enabled=bool(SITE_PASSWORD))


@app.route("/check", methods=["POST"])
def check():
    data = request.get_json(silent=True) or {}
    sku = (data.get("sku") or "").strip()
    platform = (data.get("platform") or "").strip()
    pincodes = parse_pincodes(data.get("pincodes"))

    if not sku:
        return {"error": "Enter a SKU / item ID."}, 400
    if platform not in PLATFORMS:
        return {"error": "Pick a valid platform."}, 400
    if not pincodes:
        return {"error": "Enter at least one valid 6-digit pincode."}, 400

    truncated = len(pincodes) > MAX_PINCODES
    pincodes = pincodes[:MAX_PINCODES]
    platform_label = qc_api.PLATFORM_LABEL.get(platform, platform)

    def generate():
        counts = {"In Stock": 0, "Out of Stock": 0, "Not available here": 0, "Error": 0}
        all_rows = []
        yield sse("start", {"total": len(pincodes), "platform": platform_label,
                            "truncated": truncated, "max": MAX_PINCODES})
        try:
            for i, pin in enumerate(pincodes, start=1):
                yield sse("status", {"i": i, "total": len(pincodes),
                                     "pincode": pin, "msg": "Resolving location…"})
                loc = locator.locate(pin)
                if not loc:
                    row = {"Platform": platform_label, "Product ID": sku, "Pincode": pin,
                           "City": "Unknown", "Availability": "Error",
                           "Note": "Pincode not found in India Post data"}
                    counts["Error"] += 1
                    row["Pincode Status"] = "Error"
                    all_rows.append(row)
                    yield sse("row", {"row": row, "i": i})
                    continue

                city, lat, lon = loc
                yield sse("status", {"i": i, "total": len(pincodes),
                                     "pincode": pin, "msg": f"Checking {city}…"})
                try:
                    status, items, detail = qc_api.fetch_item(sku, platform, pin, lat, lon)
                except qc_api.ApiFatalError as e:
                    yield sse("error", {"error": str(e)})
                    return

                rows = qc_api.make_rows(status, items, detail, pin, city, sku, platform_label)
                verdict = qc_api.pincode_status(rows)
                counts[verdict] = counts.get(verdict, 0) + 1
                for r in rows:
                    r["Pincode Status"] = verdict
                    all_rows.append(r)
                yield sse("row", {"rows": rows, "verdict": verdict, "i": i, "city": city})

                if i < len(pincodes):
                    time.sleep(REQUEST_DELAY_SECONDS)

            yield sse("done", {"counts": counts, "rows": all_rows,
                               "sku": sku, "platform": platform_label})
        except Exception as exc:
            yield sse("error", {"error": str(exc)})

    return Response(stream_with_context(generate()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "1") == "1")
