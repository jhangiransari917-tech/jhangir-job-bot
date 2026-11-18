import csv, html, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

# Sirf PART-TIME / ONLINE / REMOTE / DATA ENTRY kaam Telegram par bhejta hai.
# Full-time jobs Claude raat ko khud apply karta hai, unka message nahi aata.

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

SEARCHES = [
    ("data entry", "United Arab Emirates", "&f_JT=P%2CC%2CT", "Part-time (UAE)"),
    ("accountant", "United Arab Emirates", "&f_JT=P%2CC%2CT", "Part-time (UAE)"),
    ("bookkeeper", "United Arab Emirates", "&f_JT=P%2CC%2CT", "Part-time (UAE)"),
    ("accounts assistant", "United Arab Emirates", "&f_JT=P%2CC%2CT", "Part-time (UAE)"),
    ("VAT", "United Arab Emirates", "&f_JT=P%2CC%2CT", "Part-time (UAE)"),
    ("data entry", "United Arab Emirates", "&f_WT=2", "Remote (UAE)"),
    ("bookkeeper", "United Arab Emirates", "&f_WT=2", "Remote (UAE)"),
    ("accountant", "United Arab Emirates", "&f_WT=2", "Remote (UAE)"),
    ("data entry", "Worldwide", "&f_WT=2&f_JT=P%2CC", "Remote (online)"),
    ("bookkeeper", "Worldwide", "&f_WT=2&f_JT=P%2CC", "Remote (online)"),
    ("bookkeeping zoho", "Worldwide", "&f_WT=2", "Remote (online)"),
    ("quickbooks bookkeeper", "Worldwide", "&f_WT=2&f_JT=P%2CC", "Remote (online)"),
    ("excel data entry", "Worldwide", "&f_WT=2", "Remote (online)"),
]

INCLUDE = [
    "data entry", "data-entry", "bookkeep", "accountant", "accounts", "accounting",
    "vat", "tax", "reconciliation", "excel", "zoho", "quickbooks", "xero",
    "billing", "invoic", "receivable", "payable", "finance assistant",
    "finance executive", "admin assistant", "back office", "data processor",
    "data operator", "virtual assistant",
]
EXCLUDE = [
    "manager", "head of", "director", "chief", "cfo", "financial controller",
    "vp ", "vice president", "senior manager", "partner", "lead ", "principal",
    "sales", "developer", "engineer", "teacher", "tutor", "nurse", "driver",
    "arabic", "emirati", "uae national", "nationals only",
    "typing", "copy paste", "copy-paste", "earn daily", "earn money", "crypto",
    "forex", "trading", "investment", "commission only", "mlm", "reshipping",
    "package", "parcel", "survey", "captcha",
]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": [], "chat_id": ""}


def save_state(state):
    state["seen"] = state["seen"][-8000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def title_ok(title):
    t = " " + title.lower() + " "
    if any(x in t for x in EXCLUDE):
        return False
    return any(k in t for k in INCLUDE)


def linkedin_search(keyword, location, extra, label, pages=2):
    jobs = []
    for page in range(pages):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
               f"?keywords={quote_plus(keyword)}&location={quote_plus(location)}"
               f"&f_TPR=r86400{extra}&start={page * 25}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"[LinkedIn] {keyword}: {e}")
            break
        if r.status_code != 200 or not r.text.strip():
            print(f"[LinkedIn] {keyword} ({label}) page {page}: status {r.status_code}")
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
                "type": label,
                "title": title_el.get_text(strip=True),
                "company": comp_el.get_text(strip=True) if comp_el else "",
                "city": loc_el.get_text(strip=True) if loc_el else "",
                "link": link,
            })
        time.sleep(2)
    return jobs


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
                        "City", "Link"])
        for j in rows:
            w.writerow([j["found"], j["type"], j["title"], j["company"],
                        j["city"], j["link"]])


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_TOKEN secret missing hai.")
    state = load_state()
    chat_id = CHAT_ID or state.get("chat_id", "")
    if not chat_id:
        sys.exit("TELEGRAM_CHAT_ID secret missing hai.")
    seen = set(state["seen"])
    found = {}
    for kw, loc, extra, label in SEARCHES:
        for j in linkedin_search(kw, loc, extra, label):
            if j["id"] not in seen and j["id"] not in found and title_ok(j["title"]):
                found[j["id"]] = j
    now = datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M")
    new_jobs = list(found.values())
    for j in new_jobs:
        j["found"] = now
    if new_jobs:
        send(chat_id, f"🕒 <b>{len(new_jobs)} naye part-time / online kaam</b>")
        for j in new_jobs:
            send(chat_id,
                 f"🕒 <b>{html.escape(j['title'])}</b>\n"
                 f"🏢 {html.escape(j['company'])}\n"
                 f"📍 {html.escape(j['city'])} · {j['type']}\n"
                 f"🔗 {j['link']}")
        append_csv(new_jobs)
    else:
        print("Koi naya part-time / online kaam nahi mila.")
    state["seen"] = list(seen) + [j["id"] for j in new_jobs]
    save_state(state)
    print(f"Done: {len(new_jobs)} bheje.")


if __name__ == "__main__":
    main()
