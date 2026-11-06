# Moving Navrist to an always-on free server (Oracle Cloud Always Free)

Why: ai.navrist.com is a Cloudflare Tunnel to the Navrist app on the owner's PC. When the PC is off, asleep or offline the tunnel
disconnects and visitors see Cloudflare Error 1033. Running the same app and tunnel on a free always-on Oracle VM fixes that.

## Step 1 - Create the account (you, about 10 minutes)
1. Go to https://www.oracle.com/cloud/free/ and press **Start for free**. Use your own name, email and a card (identity check only; the
   Always Free resources are not charged). Choose the **home region** carefully: it cannot be changed later. Prefer **India South (Mumbai)**
   or **India West (Hyderabad)**; if free ARM machines are out of capacity there, pick another region (Singapore, Seoul).
2. Wait for the "account ready" email, then sign in to the console.

## Step 2 - Create the VM
1. Menu -> **Compute -> Instances -> Create instance**.
2. Image: **Canonical Ubuntu 24.04** (Change image). Shape: **Ampere (VM.Standard.A1.Flex)**, **4 OCPU and 24 GB memory** (still Always Free).
   If it says "out of capacity", try again later or in another availability domain.
3. Networking: keep the defaults (a public IP is needed). No inbound ports have to be opened: the Cloudflare Tunnel connects outwards.
4. **Add SSH keys -> Generate a key pair for me -> download BOTH keys.** Keep the private key (`ssh-key-....key`) safe.
5. Boot volume: set **100 GB** (the free allowance is 200 GB in total). Create.
6. When the instance is *Running*, copy its **Public IP address**.

## Step 3 - Pack the project on your PC (PowerShell, in the project folder)
```powershell
tar --exclude=venv --exclude=node_modules --exclude=.next --exclude=.next-prod --exclude=__pycache__ --exclude="*.log" --exclude=.git -czf $env:TEMP\navrist.tgz .
Copy-Item "$env:USERPROFILE\.cloudflared\d6190f48-31d7-4621-91ac-abf5b85874a9.json" $env:TEMP\tunnel.json
```
This includes `.env` and `data/` (about 1.7 GB, so the upload takes a while) and your current uncommitted edits.

## Step 4 - Upload (PowerShell; replace the key path and IP)
```powershell
scp -i C:\path\to\ssh-key.key $env:TEMP\navrist.tgz $env:TEMP\tunnel.json ubuntu@<PUBLIC-IP>:~
```

## Step 5 - Install and start (on the server)
```bash
ssh -i C:\path\to\ssh-key.key ubuntu@<PUBLIC-IP>
mkdir -p ~/navrist && tar -xzf ~/navrist.tgz -C ~/navrist
mkdir -p ~/.cloudflared && mv ~/tunnel.json ~/.cloudflared/tunnel.json
cd ~/navrist && bash deploy/server_setup.sh
```
The script installs everything, builds the site and creates three services (backend, web, tunnel) that start on boot and restart on a crash.

## Step 6 - Switch over
1. **Close the tunnel on your PC first** (a tunnel can have connectors in two places; both would share traffic and the PC copy would keep
   serving old data): stop `cloudflared` there and delete any local scheduled task for it.
2. Open https://ai.navrist.com on a phone. Then **shut the PC down and open it again** - it must still load.

## Check that the data feeds work from the server (important)
NSE and Screener.in sometimes block cloud/data-centre addresses. On the server run:
```bash
curl -s -o /dev/null -w "NSE %{http_code}\n" -A "Mozilla/5.0" https://www.nseindia.com
curl -s -o /dev/null -w "Screener %{http_code}\n" -A "Mozilla/5.0" https://www.screener.in/company/RELIANCE/
```
Then open a stock page and look at Key Metrics, Shareholding, News and the Tools menu pages. If they come back empty, tell the assistant:
the options are a paid Indian VPS, or running the data refresh on the PC and copying results to the server.

## Operating it
- Logs: `journalctl -u navrist-api -f` (also `navrist-web`, `navrist-tunnel`). Restart: `sudo systemctl restart navrist-api`.
- Update the site: upload a new tarball (Step 3-4), extract over `~/navrist`, rebuild with
  `cd ~/navrist/navrist-web && NEXT_DIST_DIR=.next-prod npm run build`, then `sudo systemctl restart navrist-web navrist-api`.
- Oracle reclaims Always Free VMs that stay idle (CPU, network and memory all very low) for 7 days; Navrist's scheduled refreshes keep it busy.
- Rotate the secrets that were exposed earlier (SITE_PASSWORD, JWT_SECRET_KEY, Angel key) in `~/navrist/.env`, then restart the services.
