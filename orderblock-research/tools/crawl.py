"""Polite public-surface crawler for order-block.com. Sequential, >=1s between requests."""
import json, re, time, sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md
import tldextract
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
S = ROOT / "scrape"
BASE = "https://order-block.com"
UA = "research-bot/1.0"
SKIP = re.compile(r"^/(app|api|auth|login)(/|$)")
SEEDS = ["/", "/blog", "/updates", "/testimonials", "/about", "/terms", "/privacy",
         "/refund-policy", "/disclaimer", "/disclosures"]
last = 0.0


def wait():
    global last
    d = 1.1 - (time.time() - last)
    if d > 0:
        time.sleep(d)
    last = time.time()


def slug(path):
    p = path.strip("/") or "home"
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", p)


def internal(url):
    u = urlparse(url)
    ex = tldextract.extract(url)
    return f"{ex.domain}.{ex.suffix}" == "order-block.com" and u.netloc in ("order-block.com", "www.order-block.com")


sess = requests.Session()
sess.headers["User-Agent"] = UA
queue = list(SEEDS)
sm = (S / "sitemap.xml").read_text(encoding="utf-8")
for loc in re.findall(r"<loc>(.*?)</loc>", sm):
    p = urlparse(loc).path or "/"
    if p not in queue:
        queue.append(p)
seen, index, pages = set(), [], {}

while queue:
    path = queue.pop(0)
    if path in seen or SKIP.match(path):
        continue
    seen.add(path)
    wait()
    url = BASE + path
    t0 = time.time()
    try:
        r = sess.get(url, timeout=30, allow_redirects=True)
    except Exception as e:
        index.append({"url": url, "error": str(e)}); continue
    ft = round(time.time() - t0, 2)
    s = slug(path)
    (S / "headers" / f"{s}.json").write_text(json.dumps(
        {"url": url, "final_url": r.url, "status": r.status_code, "headers": dict(r.headers),
         "set_cookie_names_attrs": [re.sub(r"=[^;]*", "=<redacted>", c, count=1) for c in r.raw.headers.getlist("Set-Cookie")]},
        indent=2))
    ctype = r.headers.get("content-type", "")
    entry = {"url": url, "final_url": r.url, "status_code": r.status_code, "fetch_time_s": ft}
    if r.status_code == 200 and "html" in ctype:
        (S / "raw_html" / f"{s}.html").write_text(r.text, encoding="utf-8")
        soup = BeautifulSoup(r.text, "html.parser")
        entry["title"] = soup.title.get_text(strip=True) if soup.title else None
        m = soup.find("meta", attrs={"name": "description"})
        entry["meta_description"] = m.get("content") if m else None
        entry["outline"] = [[h.name, h.get_text(" ", strip=True)] for h in soup.find_all(["h1", "h2", "h3"])]
        main = soup.find("main") or soup.body or soup
        for t in main.find_all(["script", "style", "noscript"]):
            t.decompose()
        text_md = md(str(main), heading_style="ATX")
        text_md = re.sub(r"\n{3,}", "\n\n", text_md)
        (S / "markdown" / f"{s}.md").write_text(text_md, encoding="utf-8")
        entry["word_count"] = len(text_md.split())
        for a in soup.find_all("a", href=True):
            h = urldefrag(urljoin(url, a["href"]))[0]
            if internal(h):
                p = urlparse(h).path or "/"
                if p not in seen and p not in queue and not SKIP.match(p) and not re.search(r"\.(png|jpg|svg|webp|pdf|xml|txt|ico)$", p):
                    queue.append(p)
        pages[path] = s
    index.append(entry)
    print(r.status_code, path, flush=True)

(S / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False))

# Screenshots + network log (sequential, 1s gap)
netlog = {}
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for path, s in pages.items():
        for w, h in ((1440, 900), (390, 844)):
            wait()
            ctx = b.new_context(viewport={"width": w, "height": h}, user_agent=UA)
            pg = ctx.new_page()
            reqs = []
            pg.on("request", lambda rq: reqs.append((urlparse(rq.url).scheme, urlparse(rq.url).netloc, rq.resource_type)))
            try:
                pg.goto(BASE + path, wait_until="networkidle", timeout=45000)
                pg.screenshot(path=str(S / "screenshots" / f"{s}_{w}.png"), full_page=True)
            except Exception as e:
                print("shot fail", path, w, e)
            if w == 1440:
                agg = {}
                for sc, host, rt in reqs:
                    agg[(sc, host, rt)] = agg.get((sc, host, rt), 0) + 1
                netlog[path] = [{"scheme": k[0], "host": k[1], "type": k[2], "count": v} for k, v in agg.items()]
            ctx.close()
    b.close()
(S / "network_hosts.json").write_text(json.dumps(netlog, indent=2))
print("done", len(pages))
