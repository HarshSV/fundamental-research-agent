# Navrist Research Terminal - Deployment Guide

Phase-1 fundamental equity research terminal. FastAPI backend + single-file React
dashboard, served together from one origin.

> **Note (2026-10-09):** this guide dates from the 2026-06 architecture. The dashboard is now the Vite build in
> `frontend/` (`npm run build`), and section 6's data-source table is out of date (financials now come from audited
> Annual Reports/XBRL, not yfinance; LLM calls are disabled). See [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md)
> sections E, N and O for the current picture.

> **Hosting requirement:** this app scrapes NSE for promoter-pledge (F-11) and
> FII/DII flow (F-12) data. NSE blocks most datacenter IPs **outside India**.
> Deploy in an **Indian region** (AWS `ap-south-1` Mumbai, or an Indian VPS).
> US/EU hosts will get the fundamentals but F-11/F-12 scraping will be blocked.

---

## 1. Prerequisites

- Python 3.11+
- A server in an Indian region (e.g. AWS Mumbai EC2, or an Indian VPS)
- Ports: one HTTP port (default 8000), fronted by Nginx/Caddy for TLS

## 2. Setup

```bash
git clone <repo> && cd fundamental-research-agent
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # then edit .env with real secrets
```

Fill in `.env` (see `.env.example` for every field):
- `ANGEL_*` - Angel One SmartAPI creds for live prices (optional; blank = yfinance fallback)
- `GROQ_API_KEY` - for the AI qualitative sections
- `SITE_PASSWORD` - the shared login password
- `JWT_SECRET_KEY` - long random string: `python -c "import secrets;print(secrets.token_urlsafe(48))"`
- `HOST=0.0.0.0`, `PORT=8000`, `RELOAD=0` for production

## 3. Run

```bash
# Production (binds all interfaces, no auto-reload)
HOST=0.0.0.0 PORT=8000 RELOAD=0 python app.py
```

The dashboard is served at `http://<server>:8000/` and the API under `/api/*` on
the **same origin** - the frontend auto-detects this, so no frontend edit is
needed for any domain.

Health probe: `GET /api/health` → `{"status":"online"}`.

## 4. Keep it running (systemd example)

`/etc/systemd/system/navrist.service`:

```ini
[Unit]
Description=Navrist Research Terminal
After=network.target

[Service]
WorkingDirectory=/opt/fundamental-research-agent
EnvironmentFile=/opt/fundamental-research-agent/.env
ExecStart=/opt/fundamental-research-agent/venv/bin/python app.py
Restart=always
User=www-data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now navrist
```

## 5. TLS / domain (recommended)

Put Nginx or Caddy in front for HTTPS and proxy to `127.0.0.1:8000`. Caddy example:

```
research.navrist.com {
    reverse_proxy 127.0.0.1:8000
}
```

## 6. Data sources & freshness

| Feature | Source | Freshness |
|--------|--------|-----------|
| Live price (F-01) | Angel One SmartAPI → yfinance fallback | real-time / ~15 min |
| Financials, ratios, DCF, peers | yfinance | as filed |
| Promoter pledge (F-11) | NSE `corporate-pledgedata` | quarterly filing |
| Institutional flows (F-12) | NSE `fiidiiTradeReact` (market-wide) | daily |
| AI qualitative (F-07/14/15/16/20) | Groq `llama-3.3-70b` | on demand |

Shareholding data is cached on disk under `cache/` (pledge 12h, FII/DII 4h).

**Upgrade path:** per-stock quarter-over-quarter FII/DII deltas need a multi-quarter
feed. `tools/shareholding_scraper.py` exposes a `ShareholdingProvider` interface -
implement it for a paid vendor (Trendlyne / Tickertape) and register it in
`get_provider()`; nothing else changes.
