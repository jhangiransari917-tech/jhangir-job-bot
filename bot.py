import csv, html, json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup

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
SEARCH_KEYWORDS = [
    "Accountant", "Credit Controller", "Accounts Receivable", "Accounts Payable",
    "Accounts Executive", "Accounts Assistant", "Bookkeeper", "Collections Officer",
    "Billing Accountant", "VAT Accountant", "Audit Associate", "Finance Executive",
]
LOCATION = "United Arab Emirates"
INCLUDE = [
    "accountant", "accounts", "accounting", "bookkeep", "credit control",
    "receivable", "payable", "collection", "billing", "invoic", "vat", "tax",
    "audit", "finance executive", "finance assistant", "finance officer",
    "treasury", "petty cash", "reconciliation", "gl ", "general ledger",
    "month-end", "month end", "r2r", "record to report",
]
EXCLUDE = [
    "manager", "head of", "director", "chief", "cfo", "financial controller",
    "vp ", "vice president", "payroll", "fp&a", "analyst", "intern", "teacher",
    "lecturer", "sales", "developer", "engineer", "arabic", "emirati",
    "uae national", "nationals only",
]
ALWAYS_KEEP = ["credit controller", "credit control"]


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"seen": [], "chat_id": ""}


def save_state(state):
    state["seen"] = state["seen"][-5000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)


def title_ok(title):
    t = " " + title.lower() + " "
    if any(k in t for k in ALWAYS_KEEP):
        return not any(x in t for x in ["arabic", "uae national", "emirati"])
    if any(x in t for x in EXCLUDE):
        return False
    return any(k in t for k in INCLUDE)


def linkedin_search(keyword, pages=2):
    jobs = []
    for page in range(pages):
        url = ("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
               f"?keywords={quote_plus(keyword)}&location={quote_plus(LOCATION)}"
               f"&f_TPR=r86400&start={page * 25}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as e:
            print(f"[LinkedIn] {keyword}: {e}")
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
                "source": "LinkedIn",
                "title": title_el.get_text(strip=True),
                "company": comp_el.get_text(strip=True) if comp_el else "",
                "city": loc_el.get_text(strip=True) if loc_el else "UAE",
                "link": link,
            })
        time.sleep(2)
    return jobs


def tg(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                      data=params, timeout=30)
    return r.json()


def find_chat_id(state):
    if CHAT_ID:
        return CHAT_ID
    if state.get("chat_id"):
        return state["chat_id"]
    for upd in reversed(tg("getUpdates").get("result", [])):
        msg = upd.get("message") or upd.get("edited_message")
        if msg and msg.get("chat", {}).get("id"):
            state["chat_id"] = str(msg["chat"]["id"])
            return state["chat_id"]
    return ""


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
            w.writerow(["Found (Dubai time)", "Source", "Job Title", "Company",
                        "City", "Link", "Status"])
        for j in rows:
            w.writerow([j["found"], j["source"], j["title"], j["company"],
                        j["city"], j["link"], "New - not applied"])


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_TOKEN secret missing hai.")
    state = load_state()
    chat_id = find_chat_id(state)
    if not chat_id:
        save_state(state)
        sys.exit("Chat ID nahi mila: bot ko Telegram par 'Hi' bhejen, phir dobara chalayen.")
    seen = set(state["seen"])
    found = {}
    for kw in SEARCH_KEYWORDS:
        for j in linkedin_search(kw):
            if j["id"] not in seen and j["id"] not in found and title_ok(j["title"]):
                found[j["id"]] = j
    now = datetime.now(DUBAI).strftime("%Y-%m-%d %H:%M")
    new_jobs = list(found.values())
    for j in new_jobs:
        j["found"] = now
    if new_jobs:
        send(chat_id, f"🔎 <b>{len(new_jobs)} nayi jobs mili</b> ({now} Dubai)")
        for j in new_jobs:
            send(chat_id,
                 f"💼 <b>{html.escape(j['title'])}</b>\n"
                 f"🏢 {html.escape(j['company'])}\n"
                 f"📍 {html.escape(j['city'])} · {j['source']}\n"
                 f"🔗 {j['link']}")
        append_csv(new_jobs)
    else:
        print("Koi nayi job nahi mili.")
    state["seen"] = list(seen) + [j["id"] for j in new_jobs]
    save_state(state)
    print(f"Done: {len(new_jobs)} nayi jobs bheji.")


if __name__ == "__main__":
    main()
