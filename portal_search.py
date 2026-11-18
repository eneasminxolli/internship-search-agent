"""
Step 3, source 3: Internships straight from the applicant tracking systems (ATS) of target companies.

Usage:  python portal_search.py --detect         (once: finds out which ATS each company uses)
        python portal_search.py --detect --all   (re-detect all companies, not only missing ones)
        python portal_search.py                  (normal run: fetches new internships and saves them)

No Claude, no costs: many startups, scale-ups and FinTechs publish their jobs via applicant
portals (Greenhouse, Lever, Ashby, Personio, SmartRecruiters, Recruitee) that offer a public
API. Python queries them directly and filters by internship and location.
This is a pure WORKFLOW (fixed steps), not an agent. Scoring happens afterwards as usual:
    python score_all.py

Large companies (Google, Accenture, Big Four ...) and research institutes mostly use their own
portals and are not found here. After --detect they are listed as "nicht erreichbar".
"""
import html
import json
import re
import sys
from datetime import date

import httpx

from web_search import TARGET_DIR, make_filename, normalize_url, saved_urls
from score_posting import PROJECT_DIR

# --- Target companies (from the vault note "Praktikum-Agent Wunschfirmen") ---
# Second entry = extra slugs under which the company might be listed in the portal.
COMPANIES = [
    ("Revolut", []), ("Trade Republic", []), ("N26", []), ("Scalable Capital", []),
    ("Raisin", []), ("SumUp", []), ("Upvest", []), ("Mambu", []), ("Solaris", ["solarisbank"]),
    ("Feedzai", []), ("Google", []), ("Amazon", []), ("Microsoft", []), ("Celonis", []),
    ("Personio", []), ("Zalando", []), ("Delivery Hero", []), ("HelloFresh", []),
    ("GetYourGuide", []), ("Flix", ["flixbus"]), ("DeepL", []), ("Emma", ["emmasleep", "emma-sleep"]),
    ("Unbabel", []), ("OutSystems", []), ("Talkdesk", []), ("Sword Health", []),
    ("EY-Parthenon", []), ("Porsche Consulting", []), ("Capgemini", []), ("IBM", []),
    ("Accenture", []), ("Simon-Kucher", []), ("zeb", ["zebconsulting"]), ("d-fine", []),
    ("McKinsey", []), ("BCG", []), ("Bain", []), ("Roland Berger", []), ("Oliver Wyman", []),
    ("Deloitte", []), ("PwC", []), ("KPMG", []), ("Fraunhofer", []), ("DFKI", []),
    ("SAFE Frankfurt", []), ("ifo Institut", []), ("Fraunhofer Portugal", []), ("INESC TEC", []),
    ("Champalimaud Foundation", []),
]

# --- Filters ----------------------------------------------------------------
TITLE_YES = re.compile(r"intern\b|internship|praktik|estági|estagi|trainee|summer", re.I)
TITLE_NO = re.compile(r"werkstudent|working student|thesis|abschlussarbeit|masterarbeit|apprentice|ausbildung", re.I)
LOCATIONS = re.compile(r"germany|deutschland|berlin|m[uü]nchen|munich|frankfurt|hamburg|k[oö]ln|cologne|"
                       r"w[uü]rzburg|stuttgart|d[uü]sseldorf|portugal|lisbo|porto|remote", re.I)
MAX_NEW_POSTINGS = 30   # per run; protects against a flood when scoring
CACHE = PROJECT_DIR / "ergebnisse" / "portale.json"
client = httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": "internship-search-agent (private)"})


# --- Helper functions -------------------------------------------------------
def slugs(name, extra):
    base = re.sub(r"[^a-z0-9 -]", "", name.lower().replace("ü", "u").replace("ö", "o").replace("ä", "a"))
    candidates = [base.replace(" ", "").replace("-", ""), base.replace(" ", "-")] + extra
    return list(dict.fromkeys(c for c in candidates if c))  # no duplicates, order is kept


def text_from_html(raw):
    raw = html.unescape(raw or "")
    raw = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"[ \t]+", " ", html.unescape(raw)).strip()


def fetch_json(url):
    r = client.get(url)
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# --- One reader per portal: returns a list of jobs --------------------------
# Every job: {"title", "location", "url", "text"}
def greenhouse(slug):
    d = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not d or "jobs" not in d:
        return None
    return [{"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
             "url": j.get("absolute_url", ""), "text": text_from_html(j.get("content"))} for j in d["jobs"]]


def lever(slug):
    for base in ("https://api.lever.co", "https://api.eu.lever.co"):
        d = fetch_json(f"{base}/v0/postings/{slug}?mode=json")
        if isinstance(d, list) and d:
            return [{"title": j.get("text", ""), "location": (j.get("categories") or {}).get("location", ""),
                     "url": j.get("hostedUrl", ""),
                     "text": "\n\n".join([j.get("descriptionPlain", "")]
                                         + [f"{l.get('text', '')}\n{text_from_html(l.get('content'))}" for l in j.get("lists", [])]
                                         + [j.get("additionalPlain", "")])} for j in d]
    return None


def ashby(slug):
    d = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not d or "jobs" not in d:
        return None
    return [{"title": j.get("title", ""), "location": j.get("location", ""), "url": j.get("jobUrl", ""),
             "text": j.get("descriptionPlain") or text_from_html(j.get("descriptionHtml"))}
            for j in d["jobs"] if j.get("isListed", True)]


def personio(slug):
    for tld in ("de", "com"):
        r = client.get(f"https://{slug}.jobs.personio.{tld}/xml")
        if r.status_code == 200 and "<position" in r.text:
            jobs = []
            for pos in re.findall(r"<position>(.*?)</position>", r.text, re.S):
                tag = lambda n: (re.search(rf"<{n}>(.*?)</{n}>", pos, re.S) or [None, ""])[1]
                description = "\n\n".join(text_from_html(v) for v in re.findall(r"<value>(.*?)</value>", pos, re.S))
                jobs.append({"title": html.unescape(tag("name")), "location": html.unescape(tag("office")),
                             "url": f"https://{slug}.jobs.personio.{tld}/job/{tag('id')}", "text": description})
            return jobs
    return None


def smartrecruiters(slug):
    d = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    if not d or not d.get("content"):
        return None
    jobs = []
    for j in d["content"]:
        location = ", ".join(filter(None, [(j.get("location") or {}).get("city"), (j.get("location") or {}).get("country")]))
        jobs.append({"title": j.get("name", ""), "location": location, "id": j.get("id"),
                     "url": f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", "text": ""})
    return jobs


def smartrecruiters_text(slug, job):
    """SmartRecruiters has no text in the list; it is only loaded for matching jobs."""
    d = fetch_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{job['id']}")
    sections = ((d or {}).get("jobAd") or {}).get("sections") or {}
    return "\n\n".join(text_from_html((sections.get(k) or {}).get("text"))
                       for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))


def recruitee(slug):
    d = fetch_json(f"https://{slug}.recruitee.com/api/offers/")
    if not d or "offers" not in d:
        return None
    return [{"title": j.get("title", ""), "location": j.get("location", ""), "url": j.get("careers_url", ""),
             "text": text_from_html((j.get("description") or "") + (j.get("requirements") or ""))} for j in d["offers"]]


PORTALS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "personio": personio,
           "smartrecruiters": smartrecruiters, "recruitee": recruitee}


# --- 1. Detect: which portal does which company use? ------------------------
def detect(only_missing=True):
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for name, extra in COMPANIES:
        if only_missing and name in cache:
            continue
        found = {"portal": None}
        for slug in slugs(name, extra):
            for portal, reader in PORTALS.items():
                try:
                    jobs = reader(slug)
                except httpx.HTTPError:
                    jobs = None
                if jobs:  # portal exists and has jobs
                    example = "; ".join(f"{j['title'][:40]} ({j['location'][:20]})" for j in jobs[:2])
                    found = {"portal": portal, "slug": slug, "stellen": len(jobs), "beispiel": example}
                    break
            if found["portal"]:
                break
        cache[name] = found
        if found["portal"]:
            print(f"✅ {name:24} {found['portal']:15} {found['slug']:18} {found['stellen']:>4} Stellen | {found['beispiel']}")
        else:
            print(f"–  {name:24} nicht erreichbar")
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    unreachable = [n for n, v in cache.items() if not v.get("portal")]
    print(f"\nErreichbar: {len(cache) - len(unreachable)} | nicht erreichbar: {len(unreachable)} → Job-Alerts oder manuell:")
    print("   " + ", ".join(unreachable))
    print(f"\nGespeichert in {CACHE}. Prüfe bei ✅ die Beispiele: Ist es wirklich die richtige Firma?")
    print("Falsche Treffer im Cache auf  \"portal\": null  setzen.")
    return cache


# --- 2. Normal run: fetch and save new internships --------------------------
def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    if any(name not in cache for name, _ in COMPANIES):
        print("Erst die Portale erkennen (einmalig) …\n")
        cache = detect()
        print()
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    known = saved_urls()
    new = 0
    for name, info in cache.items():
        if not info.get("portal"):
            continue
        try:
            jobs = PORTALS[info["portal"]](info["slug"]) or []
        except httpx.HTTPError as error:
            print(f"⚠️  {name}: {error}")
            continue
        matching = [j for j in jobs if TITLE_YES.search(j["title"]) and not TITLE_NO.search(j["title"])
                    and (not j["location"] or LOCATIONS.search(j["location"]))]
        print(f"{name:24} {len(jobs):>4} Stellen, davon {len(matching)} Praktika in DE/PT")
        for j in matching:
            if new >= MAX_NEW_POSTINGS or normalize_url(j["url"]) in known:
                continue
            if info["portal"] == "smartrecruiters":
                j["text"] = smartrecruiters_text(info["slug"], j)
            if len(j["text"]) < 200:
                continue  # no posting text, no meaningful scoring
            header = (f"URL: {j['url']}\nFirma: {name}\nTitel: {j['title']}\nOrt: {j['location']}\n"
                      f"Gefunden am: {date.today().isoformat()} (Quelle: {info['portal']})\n---\n")
            path = TARGET_DIR / make_filename(name, j["title"])
            if path.exists():
                continue  # same company + same title already saved from another source
            path.write_text(header + j["text"], encoding="utf-8")
            known.add(normalize_url(j["url"]))
            new += 1
            print(f"   💾 {path.name}")
    print(f"\nFertig: {new} neue Praktika gespeichert (Kosten: 0 $). Weiter mit:  python score_all.py")


if __name__ == "__main__":
    if "--detect" in sys.argv:
        detect(only_missing="--all" not in sys.argv)
    else:
        main()
