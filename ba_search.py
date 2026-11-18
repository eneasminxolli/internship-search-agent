"""
Step 3, source 2: Internships from the job search of the German Federal Employment Agency (BA).

Usage:  python ba_search.py           (normal run)
        python ba_search.py --test    (only a test call to the BA API, without Claude, free)

Division of labour:
- Python fetches the data (two custom client tools, no web search, free).
- Claude only decides WHAT to search for and WHICH hits to save.
  Claude only sees title, company and location, not the full postings. That saves tokens.
- Scoring happens afterwards as usual with:  python score_all.py

The BA API is not officially documented (community docs: github.com/bundesAPI/jobsuche-api).
It may change. If something breaks: run python ba_search.py --test and send the output to Claude.
(The tool names and their German input fields are part of the German prompt.)
"""
import base64
import json
import sys
from datetime import date

import anthropic
import httpx  # already installed together with the anthropic package

from score_posting import PRICE_INPUT, PRICE_OUTPUT, PROFILE_FILE
from web_search import (TARGET_DIR, already_saved_list, make_filename,
                        normalize_url, saved_urls)

# --- Settings = cost limits ------------------------------------------------
MODEL = "claude-haiku-5-5"
MAX_ITERATIONS = 10          # API calls to Claude
MAX_BA_SEARCHES = 15         # search requests to the BA (free, but we want to be fair)
MAX_POSTINGS = 15            # stop after this many
MAX_TOKENS_PER_CALL = 6000
HITS_PER_SEARCH = 25         # Claude sees this many hits per search (title/company/location only)
MAX_AGE_DAYS = 60            # only postings from the last 60 days

BA_BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
BA_HEADERS = {"X-API-Key": "jobboerse-jobsuche"}  # public key of the BA website, not a secret
# The BA changes API versions now and then. We try them in order (2026-11-11: v4 search removed).
SEARCH_PATHS = ["/pc/v6/jobs", "/pc/v4/app/jobs"]
DETAIL_PATHS = ["/pc/v4/jobdetails/", "/pc/v3/jobdetails/"]


# --- The two client tools: what Claude sees ---------------------------------
TOOLS = [
    {
        "name": "ba_jobsuche",
        "description": (
            "Sucht Praktikums- und Trainee-Stellen in der Jobbörse der Bundesagentur für Arbeit "
            "(nur Deutschland). Gibt pro Treffer refnr, Titel, Firma, Ort und Veröffentlichungsdatum "
            "zurück, NICHT den Anzeigentext."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "was": {"type": "string", "description": "Suchbegriff, z. B. 'Data Analytics' oder 'Business Development'"},
                "wo": {"type": "string", "description": "Stadt, z. B. 'Berlin'"},
                "umkreis_km": {"type": "integer", "description": "Umkreis in km (Standard 25)"},
            },
            "required": ["was", "wo"],
        },
    },
    {
        "name": "ba_anzeige_speichern",
        "description": (
            "Lädt die vollständige Anzeige zu einer refnr aus ba_jobsuche und speichert sie für die "
            "Bewertung. Nur für Treffer aufrufen, die nach Titel und Firma zum Profil passen könnten."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"refnr": {"type": "string", "description": "refnr aus ba_jobsuche"}},
            "required": ["refnr"],
        },
    },
]


# --- What Python actually does ---------------------------------------------
def ba_get(path, params=None):
    response = httpx.get(BA_BASE + path, params=params, headers=BA_HEADERS, timeout=60)
    response.raise_for_status()  # clear error message on HTTP errors (e.g. 403)
    return response.json()


def ba_get_first(paths, suffix="", params=None):
    """Tries several API versions until one answers."""
    last_error = None
    for path in paths:
        try:
            return ba_get(path + suffix, params)
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in (403, 404):
                raise
            last_error = error
    raise last_error


# Field names differ between versions (v6 since 11/2026: "ergebnisliste",
# "stellenangebotsTitel", "stellenlokationen"). So we try several names.
def field(d, *names):
    for name in names:
        value = d.get(name)
        if isinstance(value, dict):
            value = value.get("name") or value.get("von")
        if value:
            return str(value)
    return "?"


def hit_list(data):
    return data.get("ergebnisliste") or data.get("stellenangebote") or []


def refnr_of(hit):
    value = field(hit, "refnr", "referenznummer", "hashId")
    return "" if value == "?" else value


def title_of(d):
    return field(d, "stellenangebotsTitel", "titel", "beruf")


def company_of(d):
    return field(d, "firma", "arbeitgeber", "arbeitgeberName", "unternehmen")


def location_of(d):
    locations = d.get("stellenlokationen") or d.get("arbeitsorte") or []
    if locations:
        address = locations[0].get("adresse", locations[0])
        return address.get("ort", "?")
    return (d.get("arbeitsort") or {}).get("ort", "?")


def description_of(d):
    return d.get("stellenangebotsBeschreibung") or d.get("stellenbeschreibung") or ""


# Remember hits from the searches: in v6 the posting text is often already in the search result.
LAST_HITS = {}


def ba_job_search(tool_input):
    data = ba_get_first(SEARCH_PATHS, params={
        "angebotsart": 34,  # 34 = internship/trainee
        "was": tool_input["was"],
        "wo": tool_input["wo"],
        "umkreis": tool_input.get("umkreis_km", 25),
        "veroeffentlichtseit": MAX_AGE_DAYS,
        "size": HITS_PER_SEARCH,
        "page": 1,
    })
    hits = hit_list(data)
    if not hits:
        return "Keine Treffer. Versuche einen anderen Suchbegriff oder Ort."
    already = saved_urls()
    lines = [f"{data.get('maxErgebnisse', len(hits))} Treffer insgesamt, die ersten {len(hits)}:"]
    for h in hits:
        refnr = refnr_of(h)
        LAST_HITS[refnr] = h
        marker = " [schon gespeichert]" if normalize_url(ba_url(refnr)) in already else ""
        lines.append(f"- {refnr} | {title_of(h)} | {company_of(h)} | {location_of(h)} | "
                     f"Start {field(h, 'eintrittszeitraum', 'eintrittsdatum')}{marker}")
    return "\n".join(lines)


def ba_url(refnr):
    return f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"


def ba_save_posting(tool_input, saved):
    if len(saved) >= MAX_POSTINGS:
        return f"Limit von {MAX_POSTINGS} Anzeigen erreicht. Beende jetzt.", True
    refnr = tool_input["refnr"].strip()
    url = ba_url(refnr)
    if normalize_url(url) in saved_urls():
        return "Schon gespeichert (Duplikat).", True

    d = LAST_HITS.get(refnr, {})
    if len(description_of(d)) < 200:
        # Text not in the search result: fetch details separately
        encoded = base64.b64encode(refnr.encode()).decode()
        d = {**d, **ba_get_first(DETAIL_PATHS, suffix=encoded)}
    description = description_of(d)
    if len(description) < 200:
        # Some companies only link to their own site. Then the text is missing here.
        external = d.get("externeUrl") or d.get("allianzpartnerUrl") or ""
        return (f"Kein Anzeigentext bei der BA (nur extern: {external or 'unbekannt'}). "
                "Nicht gespeichert."), True

    company = company_of(d)
    title = title_of(d)
    # Further details (location, start date, pay ...) are appended as raw data.
    extras = {k: v for k, v in d.items()
              if k not in ("stellenangebotsBeschreibung",) and isinstance(v, (str, int, float, dict, list))}
    header = (f"URL: {url}\nFirma: {company}\nTitel: {title}\nOrt: {location_of(d)}\n"
              f"Gefunden am: {date.today().isoformat()} (Quelle: Bundesagentur für Arbeit)\n---\n")
    text = (header + description + "\n\n--- Weitere Angaben der BA ---\n"
            + json.dumps(extras, ensure_ascii=False, indent=1)[:4000])
    path = TARGET_DIR / make_filename(company, title)
    path.write_text(text, encoding="utf-8")
    saved.append(path.name)
    print(f"  💾 gespeichert: {path.name}")
    return f"Gespeichert ({len(saved)}/{MAX_POSTINGS}): {company} – {title}", False


def test():
    """Only checks the BA API, without Claude (free). Shows raw data for debugging."""
    variants = [
        ("ohne Filter", {"wo": "Berlin", "size": 2}),
        ("nur Praktikum", {"angebotsart": 34, "wo": "Berlin", "size": 2}),
        ("Praktikum + Data", {"angebotsart": 34, "was": "Data", "wo": "Berlin", "size": 2}),
        ("Text 'Praktikum Data'", {"was": "Praktikum Data", "wo": "Berlin", "size": 2}),
    ]
    for path in SEARCH_PATHS:
        print(f"\n===== {path} =====")
        for label, params in variants:
            try:
                data = ba_get(path, params)
            except httpx.HTTPStatusError as error:
                print(f"{label}: HTTP {error.response.status_code}")
                continue
            print(f"{label}: Schlüssel {list(data.keys())}, maxErgebnisse={data.get('maxErgebnisse')}")
            if label == "Praktikum + Data" and hit_list(data):
                first = hit_list(data)[0]
                print("  Felder eines Treffers:", list(first.keys()))
                print("  Länge Anzeigentext im Suchergebnis:", len(description_of(first)))
    print("\n===== So sieht Claude die Treffer =====")
    print(ba_job_search({"was": "Data", "wo": "Berlin"}))

    print("\n===== Test: Anzeigentext eines Treffers laden =====")
    refnr = next(iter(LAST_HITS), "")
    for path in DETAIL_PATHS:
        try:
            d = ba_get(path + base64.b64encode(refnr.encode()).decode())
            print(f"{path}: OK, Länge Anzeigentext {len(description_of(d))}, Felder {list(d.keys())[:12]}")
        except httpx.HTTPStatusError as error:
            print(f"{path}: HTTP {error.response.status_code}")


# --- Agent loop (like in web_search.py, but with client tools only) ---------
def main():
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic()
    profile = PROFILE_FILE.read_text(encoding="utf-8")

    system_prompt = f"""Du suchst Praktikumsanzeigen in der Jobbörse der Bundesagentur für Arbeit.
Heutiges Datum: {date.today().isoformat()}.

<suchprofil>
{profile}
</suchprofil>

Vorgehen:
1. Suche mit ba_jobsuche mit wechselnden Suchbegriffen (z. B. Data Analytics, Business Analytics,
   Data Science, Business Intelligence, Strategy, Business Development, FinTech, Consulting,
   Prozessmanagement, Risk, Controlling Data) in den Wunschstädten (Berlin, München, Frankfurt am Main,
   Würzburg). Höchstens {MAX_BA_SEARCHES} Suchen.
2. Wähle nur nach Titel und Firma die Treffer aus, die zum Profil passen könnten, und speichere sie
   mit ba_anzeige_speichern. Überspringe offensichtlich Unpassendes (Vertrieb, Handwerk, Pflege,
   Schülerpraktika, reine Pflichtpraktika, Werkstudentenstellen während des Semesters, Start vor
   Juni 2027 ohne Flexibilität) und Treffer mit [schon gespeichert].
3. Speichere ein breites Spektrum (sehr passend bis Grenzfall), höchstens {MAX_POSTINGS} Anzeigen.

Schon gespeichert (nicht erneut):
{already_saved_list()}

Bewerte nichts. Am Ende reicht eine kurze Liste, was du gespeichert hast."""

    messages = [{"role": "user", "content": "Finde passende Praktika in der BA-Jobbörse und speichere sie."}]
    ba_searches = 0
    saved = []
    cost = 0.0

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- Durchlauf {iteration}/{MAX_ITERATIONS} ---")
        response = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS_PER_CALL,
                                          system=system_prompt, tools=TOOLS, messages=messages)
        u = response.usage
        cost += u.input_tokens / 1e6 * PRICE_INPUT + u.output_tokens / 1e6 * PRICE_OUTPUT
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            closing = "".join(b.text for b in response.content if b.type == "text")
            print("\nClaude:", closing.strip())
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                if block.name == "ba_jobsuche":
                    if ba_searches >= MAX_BA_SEARCHES:
                        text, is_error = "Suchbudget aufgebraucht. Speichere nur noch oder beende.", True
                    else:
                        ba_searches += 1
                        print(f"  🔎 BA-Suche {ba_searches}/{MAX_BA_SEARCHES}: {block.input.get('was')} in {block.input.get('wo')}")
                        text, is_error = ba_job_search(block.input), False
                        print(f"     → {text.splitlines()[0]}")  # e.g. "22 Treffer insgesamt, die ersten 22:"
                elif block.name == "ba_anzeige_speichern":
                    text, is_error = ba_save_posting(block.input, saved)
                else:
                    text, is_error = f"Unbekanntes Tool: {block.name}", True
            except httpx.HTTPError as e:
                # Report BA API errors to Claude instead of crashing
                text, is_error = f"Fehler bei der BA-Schnittstelle: {e}", True
                print(f"  ⚠️  {text}")
            tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                 "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": tool_results})
        print(f"  Stand: {ba_searches} BA-Suchen, {len(saved)} gespeichert, ca. {cost:.3f} $")
    else:
        print(f"\nObergrenze von {MAX_ITERATIONS} Durchläufen erreicht.")

    print(f"\nFertig: {len(saved)} Anzeigen aus der BA-Jobbörse. Kosten ca. {cost:.3f} $")
    print("Weiter mit:  python score_all.py")


if __name__ == "__main__":
    test() if "--test" in sys.argv else main()
