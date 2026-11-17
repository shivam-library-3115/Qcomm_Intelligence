# Plush Stock Checker

A small web app: enter a **SKU / item ID**, pick a **platform**, enter one or
more **pincodes**, and see live availability (in stock / out of stock / not
sold), price, MRP, discount and inventory — streamed in as each pincode is
checked, with a **Download CSV** button.

It's the web version of the batch availability script, using the same
QuickCommerceAPI (`/v1/item`) and the same India Post coordinate lookup, served
through Flask and deployable to Render via GitHub (same flow as Plush Buddy).

```
Browser  --POST /check-->  Flask  --per pincode-->  QuickCommerceAPI
   <------------- SSE: a row streams back per pincode -------------
```

## Important: API key & credits

- **Each successful lookup costs 1 API credit** (a 404 "not sold here" is free).
  Checking 50 pincodes = up to 50 credits. That's why there's a password gate
  and a per-run cap.
- The **QC_API_KEY lives only in the server environment** (Render), never in the
  committed code — don't paste the real key into GitHub.
- Set **SITE_PASSWORD** so the site isn't an open, credit-spending endpoint.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `QC_API_KEY` | yes | Your QuickCommerceAPI key |
| `SECRET_KEY` | recommended | Signs the login session (keep stable) |
| `SITE_PASSWORD` | recommended | Password gate; unset = open site |
| `MAX_PINCODES` | no | Max pincodes per run (default 60) |
| `REQUEST_DELAY_SECONDS` | no | Pause between calls (default 1.0; rate limit is 100/min) |

## Run locally

```bash
cd stock-checker
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then put your real QC_API_KEY in .env
python app.py                  # http://localhost:5001
```

## Deploy on Render

1. Push this folder to a new GitHub repo (the `.env` file is gitignored — good).
2. Render → New → Web Service → pick the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --timeout 120`
5. Environment → add `QC_API_KEY`, `SECRET_KEY`, `SITE_PASSWORD`.
6. Deploy, open the URL, log in, check a SKU.

## Notes

- **Instamart (Swiggy)** can return several pack-size variants for one ID; each
  is its own row, and the pincode counts as *In Stock* only if every variant is
  in stock.
- The item ID is **platform-specific** — pick the platform the ID belongs to.
- Coordinate lookup for a new area takes ~2–3s the first time, then is cached in
  memory for the life of the process.
