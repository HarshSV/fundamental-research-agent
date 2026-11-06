# Navrist Research Terminal - Deployment Guide

Phase-1 fundamental equity research terminal. FastAPI backend + single-file React
dashboard, served together from one origin.

> **Note (2026-10-09):** this guide dates from the 2026-06 architecture. The dashboard is now the Vite build in
> `frontend/` (`npm run build`), and section 6's data-source table is out of date (financials now come from audited
> Annual Reports/XBRL, not yfinance; LLM calls are disabled). See [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md)
> sections E, N and O for the current picture.

> **Update (2026-11-06):** the live site is `https://ai.navrist.com`, published from the owner's PC through a Cloudflare Tunnel
> (see the section "Publishing as ai.navrist.com" at the end of this file and
> [`PROJECT_DOCUMENTATION.md` O.10](PROJECT_DOCUMENTATION.md#o10-public-deployment-at-ainavristcom)). The interface in use is the Next.js app in
> `navrist-web/` (port 3100, proxying `/api` to the backend on 8000), not the Vite app. `navrist.com` itself stays a WordPress site on Hostinger.

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

---

## Publishing as ai.navrist.com (Cloudflare Tunnel)

Hostinger shared hosting cannot run this app (Python backend plus Node web app), so the app is published as a subdomain through a tunnel.
No credentials belong in this file.

1. Add `navrist.com` to Cloudflare (Free plan). Compare the imported DNS records with Hostinger's. Set `autoconfig`, `autodiscover`,
   the `hostingermail-*._domainkey` CNAMEs and `ftp` to **DNS only**; delete any old `ai` A record. Keep the WordPress records proxied.
2. At Hostinger (Domains -> navrist.com -> Nameservers) replace the nameservers with the two Cloudflare ones. Wait for "Active".
3. Cloudflare -> SSL/TLS -> mode **Full**.
4. On the machine that runs the app: `winget install Cloudflare.cloudflared`, open a **new** terminal, then
   `cloudflared tunnel login` and **click the `navrist.com` row** on the page that opens.
5. `cloudflared tunnel create navrist`, then `cloudflared tunnel route dns navrist ai.navrist.com`.
6. Create `~/.cloudflared/config.yml`:
   ```yaml
   tunnel: navrist
   credentials-file: C:\Users\<user>\.cloudflared\<tunnel-id>.json
   ingress:
     - hostname: ai.navrist.com
       service: http://localhost:3100
     - service: http_status:404
   ```
7. Start the app (`start_navrist.bat`), then `cloudflared tunnel run navrist`.

**Keeping it running:** do **not** rely on `cloudflared service install` alone - on this machine it registered a service with no
`tunnel run` arguments, which exits immediately (error 1067), and a service reads config from the system profile, not the user folder.
Use a startup task that runs `cloudflared tunnel run navrist` (created from an Administrator shell), or copy `config.yml` and the credentials
JSON to `C:\Windows\System32\config\systemprofile\.cloudflared\` and fix the `credentials-file` path. A service stuck in STOP_PENDING
needs `taskkill /F /PID <pid>`. Cloudflare error 530 means no tunnel is connected.

**Serving mode (updated 2026-11-06):** the site now serves a production build from `navrist-web/.next-prod`. After changing web code run
`powershell -ExecutionPolicy Bypass -File scripts\build_web.ps1` (builds, then restarts; `scripts\keep_running.ps1` brings the new build up). In Cloudflare set
**Caching -> Configuration -> Browser Cache TTL = Respect Existing Headers**. For live-reload editing, run `npm run dev -- -p 3101` in `navrist-web/`.

**Before sharing the link:** (the production build is already in place; the rest still applies)
set a strong `SITE_PASSWORD` and a new `JWT_SECRET_KEY`; make sure the machine does not sleep. Login is rate limited (5 wrong passwords per
15 minutes per client address). While the app runs in dev mode, `navrist-web/next.config.ts` must list the public host in `allowedDevOrigins`.
