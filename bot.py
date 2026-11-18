import csv, html, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus, unquote, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

# Har nayi matching job Telegram par bhejta hai:
# 💼 full-time + 📢 LinkedIn posts -> "UAE Jobs" group, 🕒 part-time / data entry ->
# "Part-time / Data Entry" group, 🌍 UK/NZ/USA -> "UK NZ USA Jobs" group.
# Indeed / Naukrigulf / GulfTalent / Bayt -> har ek ka apna group (naam mein site ka naam).
# Koi group na mile to private chat mein bhejta hai.
# jobs_found.csv mein save karta hai - Claude wahan se email walon ko CV bhejta hai.

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
STATE_FILE = "seen.json"
JOBS_CSV = "jobs_found.csv"
DUBAI = timezone(timedelta(hours=4))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
UAE = "United Arab Emirates"
PT = "&f_JT=P%2CC%2CT"
RM = "&f_WT=2"

SEARCHES = [(k, UAE, "", "FT") for k in [
    "Accountant", "Credit Controller", "Accounts Receivable", "Accounts Payable",
    "Accounts Executive", "Accounts Assistant", "Bookkeeper", "Collections Officer",
    "Billing Accountant", "VAT Accountant", "Audit Associate", "Finance Executive",
]] + [
    ("data entry", UAE, PT, "PT"), ("accountant", UAE, PT, "PT"),
    ("bookkeeper", UAE, PT, "PT"), ("accounts assistant", UAE, PT, "PT"),
    ("data entry", UAE, RM, "PT"), ("bookkeeper", UAE, RM, "PT"),
    ("data entry", "Worldwide", RM + "&f_JT=P%2CC", "PT"),
    ("bookkeeper", "Worldwide", RM + "&f_JT=P%2CC", "PT"),
    ("bookkeeping zoho", "Worldwide", RM, "PT"),
    ("excel data entry", "Worldwide", RM, "PT"),
]

# UK / NZ / USA visa-sponsor jobs
ABROAD = [
    ("accountant visa sponsorship", "United Kingdom"),
    ("credit controller visa sponsorship", "United Kingdom"),
    ("assistant accountant visa sponsorship", "United Kingdom"),
    ("accountant visa sponsorship", "New Zealand"),
    ("accountant accredited employer", "New Zealand"),
    ("accountant H1B sponsorship", "United States"),
    ("staff accountant visa sponsorship", "United States"),
]
SPONSOR_NO = ["no sponsorship", "not able to sponsor", "unable to sponsor",
              "cannot sponsor", "can't sponsor", "will not sponsor",
              "does not sponsor", "not offer sponsorship", "without sponsorship",
              "not provide sponsorship", "sponsorship is not available",
              "sponsorship not available"]

# Doosri job sites (search engine ke zariye, pichle 1 din ki listings)
SITES = {
    "INDEED": ("ae.indeed.com", ["accountant", '"credit controller"', '"accounts assistant"',
                                 "bookkeeper", '"accounts receivable"', '"part time" accountant']),
    "NAUKRI": ("naukrigulf.com", ["accountant uae", '"credit controller" uae',
                                  '"accounts assistant" uae', "bookkeeper uae"]),
    "GULF": ("gulftalent.com", ["accountant uae", '"credit controller" uae',
                                '"accounts executive" uae']),
    "BAYT": ("bayt.com", ["accountant uae", '"credit controller" uae',
                          '"accounts assistant" uae', "bookkeeper uae"]),
}
SITE_JOB_PATH = {
    "INDEED": re.compile(r"(viewjob|/rc/clk|jk=|/job/)", re.I),
    "NAUKRI": re.compile(r"(jid-|job-listing|/jobs?-)", re.I),
    "GULF": re.compile(r"/jobs?/.*\d{4,}", re.I),
    "BAYT": re.compile(r"/jobs?/.*-\d{5,}", re.I),
}

# LinkedIn hiring posts (search engine se dhoonde jaate hain)
POST_QUERIES = [
    'site:linkedin.com/posts hiring accountant Dubai "send your CV"',
    'site:linkedin.com/posts hiring accountant UAE email CV',
    'site:linkedin.com/posts credit controller hiring Dubai',
    'site:linkedin.com/posts accounts assistant hiring UAE CV',
    'site:linkedin.com/posts "accountant required" Dubai',
    'site:linkedin.com/posts finance executive hiring Dubai CV',
    'site:linkedin.com/posts part time accountant Dubai',
    'site:linkedin.com/posts data entry hiring Dubai',
]

FT_INCLUDE = [
    "accountant", "accounts", "accounting", "bookkeep", "credit control",
    "receivable", "payable", "collection", "billing", "invoic", "vat", "tax",
    "audit", "finance executive", "finance assistant", "finance officer",
    "treasury", "petty cash", "reconciliation", "general ledger", "gl ",
    "month-end", "month end", "r2r", "record to report",
]
PT_INCLUDE = FT_INCLUDE + [
    "data entry", "data-entry", "excel", "zoho", "quickbooks", "xero",
    "admin assistant", "back office", "data processor", "data operator",
    "virtual assistant",
]
EXCLUDE = [
    "manager", "head of", "director", "chief", "cfo", "financial controller",
    "vp ", "vice president", "partner", "principal", "payroll", "fp&a",
    "analyst", "intern", "teacher", "tutor", "lecturer", "sales", "developer",
    "engineer", "nurse", "driver", "arabic", "emirati", "uae national",
    "nationals only", "typing", "copy paste", "copy-paste", "earn daily",
    "earn money", "crypto", "forex", "trading", "investment", "commission only",
    "mlm", "reshipping", "parcel", "survey", "captcha",
]
ALWAYS_KEEP = ["credit controller", "credit control"]
# Jhangir khud yahan kaam karta hai - in ki jobs kabhi nahi
OWN_COMPANIES = ["acora", "viva", "coverb", "cover b", "insureme", "insure me",
                 "sandra", "rapid"]
DESC_SKIP = [
    "arabic speaker", "arabic speaking", "fluent in arabic", "arabic is a must",
    "arabic is mandatory", "arabic language is required", "uae nationals only",
    "emirati nationals", "acca qualified", "cpa qualified", "qualified acca",
    "qualified cpa", "qualified ca ", "registration fee", "training fee",
    "visa fee", "pay for visa", "female only", "females only", "ladies only",
]
UAE_WORDS = ["dubai", "abu dhabi", "sharjah", "ajman", "uae", "united arab emirates"]
HIRING_WORDS = ["hiring", "vacancy", "required", "looking for", "opening",
                "send your cv", "share your cv", "send cv", "apply"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+|00)?971[\s-]?0?5\d[\s-]?\d{3}[\s-]?\d{4}|\b05\d[\s-]?\d{3}[\s-]?\d{4}\b")
BAD_EMAIL = ("linkedin.com", "example.com", "sentry.io", "w3.org", "noreply", "no-reply")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": [], "chat_id": ""}


def save_state(state):
    state["seen"] = state["seen"][-10000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def own_company(text):
    t = text.lower()
    return any(c in t for c in OWN_COMPANIES)


def title_ok(title, kind):
    t = " " + title.lower() + " "
    if any(k in t for k in ALWAYS_KEEP):
        return not any(x in t for x in ["arabic", "uae national", "emirati"])
    if any(x in t for x in EXCLUDE):
        return False
    return any(k in t for k in (FT_INCLUDE if kind == "FT" else PT_INCLUDE))


def find_contacts(text):
    emails = [e for e in EMAIL_RE.findall(text)
              if not e.lower().endswith((".png", ".jpg", ".gif", ".webp"))
              and not any(b in e.lower() for b in BAD_EMAIL)]
    phones = []
    for p in PHONE_RE.findall(text):
        d = re.sub(r"\D", "", p)
        if d.startswith("00"):
            d = d[2:]
        if d.startswith("0"):
            d = "971" + d[1:]
        if d.startswith("9710"):
            d = "971" + d[4:]
        if d not in phones:
            phones.append(d)
    return (emails[0] if emails else ""), (phones[0] if phones else "")


def linkedin_search(keyword, location, extra, kind, pages=1):
    jobs = []
    for page in range(pages):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
               f"?keywords={quote_plus(keyword)}&location={quote_plus(location)}"
               f"&f_TPR=r86400{extra}&start={page * 25}")
        r = None
        for attempt in range(3):
            try:
                r = requests.get(url, headers=HEADERS, timeout=30)
            except requests.RequestException as e:
                print(f"[LinkedIn] {keyword}: {e}")
                r = None
                break
            if r.status_code != 429:
                break
            print(f"[LinkedIn] {keyword}: 429, ruk kar dobara...")
            time.sleep(30 * (attempt + 1))
        if r is None:
            break
        if r.status_code != 200 or not r.text.strip():
            print(f"[LinkedIn] {keyword} page {page}: status {r.status_code}")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("li")
        if not cards:
            break
        for c in cards:
            title_el = c.select_one(".base-search-card__title")
            comp_el = c.select_one(".base-search-card__subtitle")
            loc_el = c.select_one(".job-search-card__location")
            link_el = c.select_one("a.base-card__full-link") or c.select_one("a")
            if not title_el or not link_el:
                continue
            link = link_el.get("href", "").split("?")[0]
            m = re.search(r"(\d{8,})", link)
            jobs.append({
                "id": "li-" + (m.group(1) if m else link),
                "num": m.group(1) if m else "",
                "kind": kind,
                "title": title_el.get_text(strip=True),
                "company": comp_el.get_text(strip=True) if comp_el else "",
                "city": loc_el.get_text(strip=True) if loc_el else "",
                # www.linkedin.com wala link iPhone par seedha LinkedIn app mein khulta hai
                "link": (f"https://www.linkedin.com/jobs/view/{m.group(1)}/" if m else link),
            })
        time.sleep(5)
    return jobs


def job_details(num, abroad=False):
    if not num:
        return "", "", True if abroad else False
    try:
        r = requests.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{num}",
                         headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return "", "", False
        text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
    except requests.RequestException:
        return "", "", False
    low = text.lower()
    skip = any(s in low for s in DESC_SKIP) or own_company(text[:300])
    if abroad:
        # sirf woh jahan sponsorship ki baat ho aur "no sponsorship" na likha ho
        if "sponsor" not in low or any(n in low for n in SPONSOR_NO):
            skip = True
    email, phone = find_contacts(text)
    return email, phone, skip


def bing_search(query):
    """Bing RSS se (title, link) list - GitHub par DuckDuckGo block ho jaata hai."""
    out = []
    try:
        r = requests.get("https://www.bing.com/search",
                         params={"q": query, "format": "rss", "count": "30",
                                 "qft": 'interval="7"'},  # pichle 24 ghante
                         headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        print(f"[Bing] {e}")
        return out
    if r.status_code != 200 or "<item>" not in r.text:
        print(f"[Bing] {query}: status {r.status_code}, items 0")
        return out
    for item in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        t = re.search(r"<title>(.*?)</title>", item, re.S)
        l = re.search(r"<link>(.*?)</link>", item, re.S)
        if t and l:
            out.append((html.unescape(t.group(1)).strip(), html.unescape(l.group(1)).strip()))
    return out


def ddg_search(query, days="d"):
    """Pehle Bing, agar kuch na mile to DuckDuckGo."""
    res = bing_search(query)
    if res:
        return res
    out = []
    try:
        r = requests.get("https://html.duckduckgo.com/html/",
                         params={"q": query, "df": days}, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        print(f"[DDG] {e}")
        return out
    if r.status_code != 200:
        print(f"[DDG] {query}: status {r.status_code}")
        return out
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        out.append((a.get_text(" ", strip=True), href))
    return out


def find_site_jobs(seen):
    jobs = []
    for kind, (domain, queries) in SITES.items():
        got = 0
        for q in queries:
            for title, link in ddg_search(f"site:{domain} {q}"):
                if domain not in link or not SITE_JOB_PATH[kind].search(link):
                    continue
                jid = kind + "-" + re.sub(r"\W", "", link)[-60:]
                if jid in seen or any(j["id"] == jid for j in jobs):
                    continue
                parts = [p.strip() for p in re.split(r" - | \| | – ", title) if p.strip()]
                jt = parts[0] if parts else title
                comp = parts[1] if len(parts) > 2 else ""
                city = parts[2] if len(parts) > 3 else "UAE"
                low = title.lower()
                if own_company(title) or not title_ok(jt, "PT" if "part" in low else "FT"):
                    continue
                if any(x in low for x in ["saudi", "qatar", "kuwait", "oman", "bahrain", "india"]):
                    continue
                jobs.append({"id": jid, "kind": kind, "title": jt, "company": comp,
                             "city": city, "link": link, "email": "", "phone": ""})
                got += 1
            time.sleep(3)
        print(f"[{kind}] {got} nayi jobs")
    return jobs


def search_post_links(query):
    links = []
    for _title, href in ddg_search(query, "w"):
        if "linkedin.com/posts/" in href:
            href = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", href)
            links.append(href.split("?")[0])
    return links


def read_post(link):
    try:
        r = requests.get(link, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    body = soup.select_one(".attributed-text-segment-list__content")
    og = soup.find("meta", attrs={"property": "og:description"})
    text = body.get_text(" ", strip=True) if body else (og.get("content", "") if og else "")
    if not text:
        return None
    author = soup.find("meta", attrs={"property": "og:title"})
    return text, (author.get("content", "") if author else "")


def find_posts(seen):
    posts = []
    links = []
    for q in POST_QUERIES:
        for l in search_post_links(q):
            if l not in links:
                links.append(l)
        time.sleep(3)
    for link in links:
        pid = "post-" + link.rstrip("/").split("/")[-1][-40:]
        if pid in seen:
            continue
        got = read_post(link)
        time.sleep(1)
        if not got:
            continue
        text, author = got
        low = text.lower()
        if not any(w in low for w in UAE_WORDS) or not any(w in low for w in HIRING_WORDS):
            continue
        if not any(k in low for k in PT_INCLUDE) or any(s in low for s in DESC_SKIP):
            continue
        if own_company(text) or own_company(author):
            continue
        if any(x in low for x in ["crypto", "forex", "earn daily", "typing job", "copy paste"]):
            continue
        email, phone = find_contacts(text)
        if not email and not phone:
            continue
        posts.append({"id": pid, "kind": "POST", "title": text[:160],
                      "company": author[:80], "city": "UAE", "link": link,
                      "email": email, "phone": phone})
    return posts


def refresh_chats(state):
    """Bot ko jis group mein add kiya ho, uska ID naam se pehchaan kar yaad rakhta hai."""
    chats = state.setdefault("chats", {})
    try:
        ups = tg("getUpdates").get("result", [])
    except Exception:
        return chats
    for u in ups:
        for key in ("my_chat_member", "message", "channel_post", "edited_message"):
            ch = (u.get(key) or {}).get("chat") or {}
            if ch.get("type") not in ("group", "supergroup", "channel"):
                continue
            title = (ch.get("title") or "").lower()
            cid = str(ch["id"])
            if "indeed" in title:
                chats["INDEED"] = cid
            elif "naukri" in title:
                chats["NAUKRI"] = cid
            elif "gulf" in title:
                chats["GULF"] = cid
            elif "bayt" in title:
                chats["BAYT"] = cid
            elif "part" in title or "data" in title:
                chats["PT"] = cid
            elif any(w in title for w in ["uk", "usa", "nz", "abroad", "foreign", "bahar"]):
                chats["ABROAD"] = cid
            elif "uae" in title or "linkedin" in title or "job" in title:
                chats["FT"] = chats["POST"] = cid
    return chats


def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      data=params, timeout=30)
    return r.json()


def send(chat_id, text):
    res = tg("sendMessage", chat_id=chat_id, text=text,
             parse_mode="HTML", disable_web_page_preview="true")
    if not res.get("ok"):
        print("Telegram error:", res)
    time.sleep(1)


def append_csv(rows):
    new_file = not os.path.exists(JOBS_CSV)
    with open(JOBS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["Found (Dubai time)", "Type", "Job Title", "Company",
                        "City", "Email", "Phone", "Link"])
        for j in rows:
            w.writerow([j["found"], j["kind"], j["title"], j["company"],
                        j["city"], j["email"], j["phone"], j["link"]])


def message(j):
    head = {"FT": "💼 Full-time", "PT": "🕒 Part-time / Online",
            "POST": "📢 LinkedIn hiring post",
            "ABROAD": "🌍 UK / NZ / USA (visa sponsor)",
            "INDEED": "🟦 Indeed", "NAUKRI": "🟧 Naukrigulf",
            "GULF": "🟩 GulfTalent", "BAYT": "🟥 Bayt"}[j["kind"]]
    msg = (f"{head}\n<b>{html.escape(j['title'])}</b>\n"
           f"🏢 {html.escape(j['company'])}\n📍 {html.escape(j['city'])}\n")
    if j["email"]:
        msg += f"📧 {html.escape(j['email'])} (Claude CV bhej dega)\n"
    if j["phone"]:
        msg += f"📱 +{j['phone']} · WhatsApp: https://wa.me/{j['phone']}\n"
    return msg + f"🔗 {j['link']}"


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_TOKEN secret missing hai.")
    state = load_state()
    chat_id = CHAT_ID or state.get("chat_id", "")
    if not chat_id:
        sys.exit("TELEGRAM_CHAT_ID secret missing hai.")
    seen = set(state["seen"])
    found = {}
    for kw, loc, extra, kind in SEARCHES:
        for j in linkedin_search(kw, loc, extra, kind):
            if j["id"] in seen or j["id"] in found or own_company(j["company"]):
                continue
            if title_ok(j["title"], kind):
                found[j["id"]] = j
    skipped, keep = [], []
    for j in found.values():
        j["email"], j["phone"], bad = job_details(j["num"])
        time.sleep(3)
        (skipped if bad else keep).append(j)
    for kw, loc in ABROAD:
        for j in linkedin_search(kw, loc, "", "ABROAD"):
            if j["id"] in seen or j["id"] in found or own_company(j["company"]):
                continue
            if not title_ok(j["title"], "FT"):
                continue
            found[j["id"]] = j
            j["email"], j["phone"], bad = job_details(j["num"], abroad=True)
            time.sleep(3)
            (skipped if bad else keep).append(j)
    try:
        keep += find_posts(seen)
    except Exception as e:
        print("[Posts] error:", e)
    try:
        keep += find_site_jobs(seen)
    except Exception as e:
        print("[Sites] error:", e)
    now = datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M")
    for j in keep:
        j["found"] = now
    chats = refresh_chats(state)
    # posts aur full-time main chat mein, part-time aur UK/NZ/USA apne group mein
    for kind in ("POST", "FT", "PT", "ABROAD", "INDEED", "NAUKRI", "GULF", "BAYT"):
        cid = chats.get(kind, chat_id)
        for j in [j for j in keep if j["kind"] == kind]:
            send(cid, message(j))
    if keep:
        append_csv(keep)
    else:
        print("Koi nayi job nahi mili.")
    counts = {k: len([j for j in keep if j["kind"] == k])
              for k in ("FT", "PT", "POST", "ABROAD", "INDEED", "NAUKRI", "GULF", "BAYT")}
    state["seen"] = list(seen) + [j["id"] for j in keep + skipped]
    save_state(state)
    print(f"Done: {counts}; {len(skipped)} skip; groups: {chats}")


if __name__ == "__main__":
    main()
