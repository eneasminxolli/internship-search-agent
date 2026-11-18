"""
Step 3: The agent searches the web for internship postings itself and saves them.

Usage:  python web_search.py

Output: text files in anzeigen/gefunden/ (one per posting, WITHOUT a score).
Scoring happens separately with:  python score_all.py

Three kinds of tools:
- web_search  (server tool):  Anthropic searches the web. Costs $0.01 per search.
- web_fetch   (server tool):  Anthropic fetches a page. Costs only tokens.
- anzeige_speichern (client tool): runs HERE on your machine. Claude only says
  "please call this", your script executes it and reports the result back.
  (The tool name stays German because it is part of the German prompt.)
"""
import csv
import re
from datetime import date

import anthropic

# Profile path, prices and loading .env are taken from score_posting.py / config.py
from score_posting import PRICE_INPUT, PRICE_OUTPUT, PROFILE_FILE, PROJECT_DIR

# --- Settings = cost limits ------------------------------------------------
MODEL = "claude-haiku-5-5"
MAX_ITERATIONS = 8           # the agent loop runs at most this often (= max. 8 API calls)
MAX_SEARCHES = 8             # target: total web searches per run ($0.01 each)
MAX_FETCHES = 20             # target: total page fetches per run
SEARCHES_PER_CALL = 4        # hard limit per API call (max_uses)
FETCHES_PER_CALL = 8         # hard limit per API call (max_uses)
# Why two limits? The tool list must stay IDENTICAL in every call (otherwise the
# API rejects the thinking blocks). So we cannot adjust max_uses on the fly.
# Once the target is reached, there is exactly one last round for saving.
# Worst case: MAX_SEARCHES - 1 + SEARCHES_PER_CALL = 11 searches.
MAX_PAGE_TOKENS = 8000       # at most this much text per fetched page
MAX_POSTINGS = 10            # the agent should stop after this many
MAX_TOKENS_PER_CALL = 8000   # thinking + answer per API call
MAX_COST = 0.20              # $; if exceeded, the script aborts (real runs: $0.10-0.15)
PRICE_PER_SEARCH = 0.01      # $ per web search

TARGET_DIR = PROJECT_DIR / "anzeigen" / "gefunden"
MANUAL_CSV = PROJECT_DIR / "ergebnisse" / "manuell_pruefen.csv"  # postings the agent could not open
BLOCKED = [
    "linkedin.com", "glassdoor.com", "glassdoor.de",  # terms of service forbid scraping
    # Job boards that could not be fetched in the first run (2026-11-11):
    "jooble.org", "talent.com", "jobleads.com", "freehire.me",
    "indeed.com", "stepstone.de",
]

# --- The client tool: description for Claude -------------------------------
# Claude only sees the name, description and input schema.
# What happens next is decided by the Python function save_posting() below.
SAVE_TOOL = {
    "name": "anzeige_speichern",
    "description": (
        "Speichert eine Praktikumsanzeige, die du vorher mit web_fetch abgerufen hast. "
        "Gib die URL genau so an, wie du sie abgerufen hast. Ein Aufruf pro Anzeige. "
        "Der Anzeigentext wird automatisch aus dem Abruf übernommen."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL der abgerufenen Anzeige"},
            "firma": {"type": "string"},
            "titel": {"type": "string", "description": "Stellentitel"},
            "ort": {"type": "string"},
        },
        "required": ["url", "firma", "titel", "ort"],
    },
}


def normalize_url(url):
    return url.split("#")[0].rstrip("/")


def make_filename(company, title):
    raw = f"{company}_{title}".lower()
    for old, new in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        raw = raw.replace(old, new)
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:70] + ".txt"


def saved_urls():
    urls = set()
    for path in TARGET_DIR.glob("*.txt"):
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        if first_line.startswith("URL: "):
            urls.add(normalize_url(first_line[5:]))
    return urls


def save_posting(tool_input, fetched_pages, saved):
    """Executes the client tool. Returns (text for Claude, is_error)."""
    if len(saved) >= MAX_POSTINGS:
        return f"Limit von {MAX_POSTINGS} Anzeigen erreicht. Beende jetzt die Suche.", True

    url = normalize_url(tool_input["url"])
    if url in saved_urls():
        return "Diese Anzeige ist schon gespeichert (Duplikat). Suche eine andere.", True

    page_text = fetched_pages.get(url)
    if page_text is None:
        return "Diese URL wurde noch nicht mit web_fetch abgerufen. Erst abrufen, dann speichern.", True

    header = (
        f"URL: {tool_input['url']}\n"
        f"Firma: {tool_input['firma']}\n"
        f"Titel: {tool_input['titel']}\n"
        f"Ort: {tool_input['ort']}\n"
        f"Gefunden am: {date.today().isoformat()}\n"
        "---\n"
    )
    path = TARGET_DIR / make_filename(tool_input["firma"], tool_input["titel"])
    path.write_text(header + page_text, encoding="utf-8")
    saved.append(path.name)
    print(f"  💾 gespeichert: {path.name}")
    return f"Gespeichert ({len(saved)}/{MAX_POSTINGS}).", False


def remember_for_manual_check(failed_fetches):
    """Writes postings that could not be fetched to ergebnisse/manuell_pruefen.csv.

    Claude only fetches pages it considers promising after searching. If the fetch
    fails (e.g. the page loads via JavaScript, as with Revolut), the posting should
    not get lost: you then check it yourself in the browser.
    """
    if not failed_fetches:
        return []
    MANUAL_CSV.parent.mkdir(exist_ok=True)
    known = set()
    if MANUAL_CSV.exists():
        with open(MANUAL_CSV, encoding="utf-8-sig") as f:
            known = {normalize_url(row["url"]) for row in csv.DictReader(f, delimiter=";")}
    new = []
    for entry in failed_fetches:
        url = normalize_url(entry["url"])
        # Budget errors are not a problem of the page; duplicates are only added once
        if entry["fehler"] in ("max_uses_exceeded", "too_many_requests") or url in known:
            continue
        known.add(url)
        new.append(entry)
    with open(MANUAL_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["datum", "titel", "url", "fehler", "erledigt"], delimiter=";")
        if f.tell() == 0:
            writer.writeheader()
        for entry in new:
            writer.writerow({**entry, "datum": date.today().isoformat(), "erledigt": ""})
    return new


def known_unreachable():
    """URLs from manuell_pruefen.csv: failed before, do not fetch again."""
    if not MANUAL_CSV.exists():
        return "(keine)"
    with open(MANUAL_CSV, encoding="utf-8-sig") as f:
        return "\n".join(f"- {row['url']}" for row in csv.DictReader(f, delimiter=";")) or "(keine)"


def build_tools():
    """The tool list. It stays UNCHANGED for the whole run."""
    return [
        SAVE_TOOL,
        {"type": "web_search_20250305", "name": "web_search",
         "max_uses": SEARCHES_PER_CALL, "blocked_domains": BLOCKED},
        {"type": "web_fetch_20250910", "name": "web_fetch",
         "max_uses": FETCHES_PER_CALL, "blocked_domains": BLOCKED,
         "max_content_tokens": MAX_PAGE_TOKENS},
    ]


def already_saved_list():
    """Company and title of all postings saved so far (for the prompt)."""
    lines = []
    for path in sorted(TARGET_DIR.glob("*.txt")):
        header = dict(l.split(": ", 1) for l in path.read_text(encoding="utf-8").splitlines()[:4] if ": " in l)
        lines.append(f"- {header.get('Firma', '?')}: {header.get('Titel', '?')}")
    return "\n".join(lines) or "(noch keine)"


def main():
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    profile = PROFILE_FILE.read_text(encoding="utf-8")

    system_prompt = f"""Du suchst Praktikumsanzeigen für einen Studenten.
Heutiges Datum: {date.today().isoformat()}.

<suchprofil>
{profile}
</suchprofil>

Vorgehen:
1. Suche mit web_search nach konkreten, aktuell offenen Praktikumsanzeigen für Sommer 2027,
   die zum Profil passen könnten (Deutschland und Portugal). Variiere die Suchbegriffe
   (Deutsch und Englisch, verschiedene Rollen und Unternehmenstypen aus dem Profil).
   Nutze mindestens ein Drittel der Suchen für PORTUGAL (Lissabon, Porto), auf Englisch UND
   Portugiesisch (z. B. "internship Lisbon", "estágio", "estágio de verão", "estágio curricular").
   In Portugal laufen viele Stellen bei internationalen Firmen, FinTechs, Tech-Hubs und Beratungen
   auf Englisch.
2. Rufe vielversprechende Anzeigenseiten mit web_fetch ab. Nimm die Seite der EINZELNEN Anzeige,
   keine Übersichtslisten. Nur abgerufene Seiten können gespeichert werden.
3. Speichere jede brauchbare Anzeige mit anzeige_speichern.

Bevorzuge Karriereseiten der Firmen selbst und einfache Bewerberportale. Große Jobbörsen und
Aggregatoren lassen sich meist nicht abrufen. Schlägt ein Abruf fehl, versuche eine andere Anzeige.
Sehr ergiebig sind Suchen direkt auf Bewerberportalen mit dem site:-Operator, z. B.
  site:jobs.lever.co internship Lisbon
  site:job-boards.greenhouse.io intern Berlin 2027
  site:jobs.personio.de Praktikum 2027 Data
  site:join.com Praktikum Data Analytics
  site:jobs.ashbyhq.com internship Lisbon
  site:dreamworkhq.com internship Lisbon   (spiegelt u. a. Workday-Anzeigen großer Firmen, die sonst nicht abrufbar sind)
Diese Seiten lassen sich meist abrufen.

Diese Seiten waren schon früher NICHT abrufbar, rufe sie nicht erneut ab:
{known_unreachable()}

Schon aus früheren Läufen gespeichert (NICHT erneut suchen, andere Firmen und Rollen finden):
{already_saved_list()}

Wichtig:
- Speichere ein BREITES Spektrum: sehr passende, mittlere und Grenzfälle. Die Anzeigen dienen
  auch als Test-Set. Offensichtlich unpassende Stellen (z. B. reiner Vertrieb) nicht speichern.
- Budget: höchstens {MAX_SEARCHES} Suchen, {MAX_FETCHES} Abrufe und {MAX_POSTINGS} gespeicherte Anzeigen.
  Pro Antwort sind höchstens {SEARCHES_PER_CALL} Suchen und {FETCHES_PER_CALL} Abrufe möglich
  (Fehler "max_uses_exceeded"). Das ist NICHT das Gesamtbudget: Du bekommst danach eine neue
  Runde und kannst weitersuchen. Plane sparsam. Abgelaufene Anzeigen und Seiten ohne Anzeigentext überspringen.
- Bewerte nichts und nenne keine Scores. Am Ende reicht eine kurze Liste, was du gespeichert hast."""

    messages = [{"role": "user", "content": "Finde passende Praktikumsanzeigen und speichere sie."}]

    tools = build_tools()
    last_round = False
    searches = fetches = 0
    cost = 0.0
    fetched_pages = {}    # url -> page text (from the web_fetch results)
    search_titles = {}    # url -> title from the search results
    fetch_urls = {}       # id of the fetch -> url (to map errors to a URL)
    failed_fetches = []   # pages that could not be fetched -> check manually
    saved = []

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- Durchlauf {iteration}/{MAX_ITERATIONS} ---")
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS_PER_CALL,
                system=system_prompt,
                tools=tools,  # always the same list!
                messages=messages,
            )
        except anthropic.BadRequestError as error:
            print(f"API-Fehler, Lauf wird beendet: {error}")
            break

        # 1. What did Claude do in this iteration? Look at the blocks one by one.
        for block in response.content:
            b = block.model_dump()  # block as a plain Python dict
            if b["type"] == "server_tool_use" and b["name"] == "web_search":
                searches += 1
                print(f"  🔎 Suche: {b['input'].get('query')}")
            elif b["type"] == "server_tool_use" and b["name"] == "web_fetch":
                fetches += 1
                fetch_urls[b["id"]] = b["input"].get("url", "")
                print(f"  🌐 Abruf: {b['input'].get('url')}")
            elif b["type"] == "web_search_tool_result" and isinstance(b["content"], list):
                for hit in b["content"]:
                    if hit.get("url"):
                        search_titles[normalize_url(hit["url"])] = hit.get("title", "")
            elif b["type"] == "web_fetch_tool_result":
                content = b["content"]
                if content.get("type") == "web_fetch_result":
                    source = content["content"]["source"]
                    if source.get("type") == "text":  # we skip PDFs (base64)
                        fetched_pages[normalize_url(content["url"])] = source["data"]
                else:
                    url = fetch_urls.get(b["tool_use_id"], "")
                    print(f"     ⚠️  Abruf fehlgeschlagen ({content.get('error_code')}): {url}")
                    failed_fetches.append({"url": url, "fehler": content.get("error_code"),
                                           "titel": search_titles.get(normalize_url(url), "")})

        # 2. Track costs
        u = response.usage
        cost = (cost + u.input_tokens / 1e6 * PRICE_INPUT + u.output_tokens / 1e6 * PRICE_OUTPUT)
        print(f"  Stand: {searches}/{MAX_SEARCHES} Suchen, {fetches}/{MAX_FETCHES} Abrufe, "
              f"{len(saved)} gespeichert, ca. {cost + searches * PRICE_PER_SEARCH:.3f} $")
        if cost + searches * PRICE_PER_SEARCH > MAX_COST:
            print(f"Kostengrenze {MAX_COST} $ überschritten, Abbruch.")
            break

        # 3. Append Claude's answer to the history (unchanged, including the search results)
        messages.append({"role": "assistant", "content": response.content})

        # 4. Execute client tools (if Claude called any)
        tool_results = None
        if response.stop_reason == "tool_use":
            # EVERY tool_use block needs a tool_result in return.
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "anzeige_speichern":
                    text, is_error = save_posting(block.input, fetched_pages, saved)
                else:
                    text, is_error = f"Unbekanntes Tool: {block.name}", True
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                     "content": text, "is_error": is_error})

        # 5. Was this already the last round? Then stop (saving is done).
        if last_round:
            print("\nLetzte Runde beendet (Such- bzw. Abrufbudget aufgebraucht).")
            break

        # 6. Continue or stop depending on stop_reason
        if response.stop_reason == "pause_turn":
            # A long server-tool round was paused: simply send it again.
            continue

        if tool_results is not None:
            if searches >= MAX_SEARCHES or fetches >= MAX_FETCHES:
                # Budget reached: Claude may only save now, then it is over.
                tool_results.append({"type": "text", "text":
                    "Das Budget für Suchen und Abrufe ist aufgebraucht. Keine neuen Suchen oder "
                    "Abrufe mehr. Speichere nur noch bereits abgerufene passende Anzeigen und beende dann."})
                last_round = True
            messages.append({"role": "user", "content": tool_results})
            continue

        # end_turn: if budget is left, we send Claude into the next round.
        # That way the agent uses all iterations instead of stopping after one round.
        if (response.stop_reason == "end_turn" and not last_round
                and searches < MAX_SEARCHES and len(saved) < MAX_POSTINGS):
            print("  ↻ Budget übrig, nächste Runde")
            messages.append({"role": "user", "content":
                f"Weiter. Noch übrig: {MAX_SEARCHES - searches} Suchen, {MAX_FETCHES - fetches} Abrufe, "
                f"{MAX_POSTINGS - len(saved)} Anzeigen. Suche mit NEUEN Suchbegriffen "
                "(andere Firmen, Städte, Portale, site:-Suchen) und speichere passende Anzeigen."})
            continue

        # end_turn (finished) or max_tokens (cut off): end the loop
        if response.stop_reason == "max_tokens":
            print("WARNUNG: max_tokens erreicht, Antwort abgeschnitten.")
        closing = "".join(block.text for block in response.content if block.type == "text")
        print("\nClaude:", closing.strip())
        break
    else:
        # The else branch of a for loop runs if the loop was NOT left via break.
        print(f"\nObergrenze von {MAX_ITERATIONS} Durchläufen erreicht.")

    new_manual = remember_for_manual_check(failed_fetches)
    print(f"\nFertig: {len(saved)} Anzeigen in {TARGET_DIR}")
    if new_manual:
        print(f"\n👉 {len(new_manual)} Stellen konnte der Agent nicht öffnen. Bitte selbst prüfen "
              f"(Liste: ergebnisse/manuell_pruefen.csv):")
        for entry in new_manual:
            print(f"   - {entry['titel'] or '(ohne Titel)'}\n     {entry['url']}")
    print(f"Kosten ca. {cost + searches * PRICE_PER_SEARCH:.3f} $ "
          f"(davon {searches} Suchen = {searches * PRICE_PER_SEARCH:.2f} $)")


if __name__ == "__main__":
    main()
