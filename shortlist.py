"""
Step 4: Weekly shortlist from all sources.

Usage:  python shortlist.py                  (normal run)
        python shortlist.py --no-link-check  (does not check whether links are still online)
        python shortlist.py --dry-run        (only print, save nothing)

No Claude, no costs. Plain Python:
  1. reads ergebnisse/agent_scores.csv (scores) and the header lines in anzeigen/gefunden/ (URL, source, date)
  2. merges duplicates across all sources (same URL, or same company + similar title)
  3. picks the best 3-5 postings, at most 2 per company, only from MIN_SCORE, no no-go and no radar
  4. checks for the candidates whether the link is still online (expired -> out)
  5. writes a Markdown note (Obsidian vault or ergebnisse/shortlists/), plus radar and
     manuell_pruefen as hints

You enter your decisions in ergebnisse/entscheidungen.csv (column status), or use decide.py:
  bewerben           -> prepare application documents (step 5), no longer shown
  abgeschickt / nein -> no longer shown
  später or empty    -> stays in the race
"""
import csv
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from difflib import SequenceMatcher

# SHORTLIST_DIR comes from VAULT_PATH in .env (fallback: ergebnisse/shortlists/)
from config import PROJECT_DIR, SHORTLIST_DIR

# --- Settings --------------------------------------------------------------
POSTINGS_DIR = PROJECT_DIR / "anzeigen" / "gefunden"
RESULTS_DIR = PROJECT_DIR / "ergebnisse"
SCORES_CSV = RESULTS_DIR / "agent_scores.csv"
RADAR_CSV = RESULTS_DIR / "radar.csv"
MANUAL_CSV = RESULTS_DIR / "manuell_pruefen.csv"
DECISIONS_CSV = RESULTS_DIR / "entscheidungen.csv"
EXPIRED_CSV = RESULTS_DIR / "abgelaufen.csv"
HISTORY_CSV = RESULTS_DIR / "shortlist_verlauf.csv"

MIN_SCORE = 60        # nothing below this goes on the shortlist, even if fewer than 3 remain
MAX_SHORTLIST = 5
MAX_PER_COMPANY = 2
MAX_LINK_CHECKS = 15  # check at most this many links per run (free, but be fair)
OLD_AFTER_DAYS = 42   # older postings get the hint "alt"

# Company names the rules below do not recognise. Left: normalised name, right: target.
COMPANY_ALIASES = {
    "bcg": "boston consulting",
    "the boston consulting": "boston consulting",
    "ezb": "european central bank",
    "ecb": "european central bank",
    "europaeische zentralbank": "european central bank",
    "pwc": "pricewaterhousecoopers",
    "ey": "ernst young",
}

LEGAL_FORMS = {
    "ag", "gmbh", "se", "kg", "co", "kgaa", "mbh", "group", "gruppe", "ltd", "limited", "inc", "llc",
    "sa", "lda", "plc", "bv", "nv", "holding", "deutschland", "germany", "portugal", "gmbh&co",
    "und", "and", "the", "partners", "partner", "international", "europe", "unipessoal",
}
# Words that appear in almost every internship title and therefore distinguish nothing
TITLE_FILLER_WORDS = {
    "m", "w", "d", "f", "x", "div", "mwd", "wmd", "fmd", "all", "genders", "gender",
    "praktikum", "praktikant", "praktikantin", "pflichtpraktikum", "intern", "internship", "interns",
    "estagio", "estagiario", "estagiaria", "summer", "sommer", "2026", "2027", "trainee",
    "im", "in", "der", "die", "das", "den", "fuer", "for", "the", "and", "und", "of", "at", "bereich",
    "de", "da", "do", "em", "e", "a", "mit", "with", "team", "studentisches", "student",
}
EXPIRED_HINTS = [
    "nicht mehr verfügbar", "nicht mehr verfuegbar", "stelle ist bereits besetzt", "no longer available",
    "no longer accepting", "position has been filled", "job not found", "this job is closed",
    "não está disponível", "nao esta disponivel", "vaga encerrada", "stellenangebot ist abgelaufen",
]


# --- Helper functions ------------------------------------------------------
def read_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def append_csv(path, columns, rows):
    if not rows:
        return
    is_new = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=";", extrasaction="ignore")
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def simplify(text):
    text = (text or "").lower()
    for old, new in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "ã": "a", "á": "a", "à": "a",
                     "â": "a", "ç": "c", "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o",
                     "ú": "u", "&": " "}.items():
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def company_key(name):
    words = [w for w in simplify(name).split() if w not in LEGAL_FORMS]
    key = " ".join(words) or simplify(name)
    return COMPANY_ALIASES.get(key, key)


def title_words(title):
    return {w for w in simplify(title).split() if w not in TITLE_FILLER_WORDS and len(w) > 1}


def normalize_url(url):
    return (url or "").split("#")[0].split("?")[0].rstrip("/").lower()


def is_no_go(value):
    return str(value or "").strip().lower() not in {"", "none", "null", "false", "nein", "no", "0", "-", "[]"}


def to_int(value):
    try:
        return int(float(str(value).replace(",", ".")))
    except ValueError:
        return None


def read_header(filename):
    """Reads the header lines of a saved posting (up to the line ---)."""
    header = {"url": "", "quelle": "Websuche", "gefunden": ""}
    path = POSTINGS_DIR / filename
    if not path.exists():
        return header
    for line in path.read_text(encoding="utf-8").splitlines()[:10]:
        if line.strip() == "---":
            break
        if line.startswith("URL: "):
            header["url"] = line[5:].strip()
        elif line.startswith("Gefunden am: "):
            rest = line[13:]
            header["gefunden"] = rest[:10]
            match = re.search(r"Quelle: ([^)]+)", rest)
            if match:
                header["quelle"] = match.group(1).strip()
        elif line.startswith("Firma: "):
            header["firma"] = line[7:].strip()
        elif line.startswith("Titel: "):
            header["titel"] = line[7:].strip()
    return header


def same_posting(a, b):
    if a["url_norm"] and a["url_norm"] == b["url_norm"]:
        return True
    if a["firma_key"] != b["firma_key"]:
        return False
    wa, wb = a["titel_woerter"], b["titel_woerter"]
    if not wa or not wb:
        return False  # a title like "Praktikum (m/w/d)" says too little, better not merge
    jaccard = len(wa & wb) / len(wa | wb)
    similarity = SequenceMatcher(None, " ".join(sorted(wa)), " ".join(sorted(wb))).ratio()
    return jaccard >= 0.6 or similarity >= 0.85


def link_status(url):
    """'online', 'abgelaufen' or 'unklar' (page blocks scripts, loads via JavaScript etc.)."""
    if not url.startswith("http"):
        return "unklar"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (internship-search-agent)"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            text = response.read(300_000).decode("utf-8", errors="ignore").lower()
    except urllib.error.HTTPError as error:
        return "abgelaufen" if error.code in (404, 410) else "unklar"
    except Exception:
        return "unklar"
    return "abgelaufen" if any(h in text for h in EXPIRED_HINTS) else "online"


def md(text, length=None):
    """Text for a Markdown table: without | and line breaks, optionally shortened."""
    text = " ".join(str(text or "").replace("|", "/").split())
    if length and len(text) > length:
        text = text[: length - 1].rstrip() + "…"
    return text


# --- Main part -------------------------------------------------------------
def load_postings():
    rows = read_csv(SCORES_CSV)
    if not rows:
        sys.exit(f"Keine Bewertungen gefunden ({SCORES_CSV}). Erst: python score_all.py")
    postings = []
    for r in rows:
        score = to_int(r.get("score"))
        if score is None:
            continue
        header = read_header(r["datei"])
        company = r.get("firma") or header.get("firma", "")
        title = r.get("titel") or header.get("titel", "")
        # dict keys stay German: they mirror the CSV columns and header fields
        postings.append({
            **r, "score": score, "firma": company, "titel": title,
            "url": header["url"], "url_norm": normalize_url(header["url"]),
            "quelle": header["quelle"], "gefunden": header["gefunden"],
            "firma_key": company_key(company), "titel_woerter": title_words(title),
        })
    return postings


def merge_duplicates(postings):
    """Returns groups. In each group the posting with the highest score comes first."""
    groups = []
    for p in sorted(postings, key=lambda p: -p["score"]):
        for g in groups:
            if any(same_posting(p, x) for x in g):
                g.append(p)
                break
        else:
            groups.append([p])
    return groups


def main():
    dry_run = "--dry-run" in sys.argv
    today = date.today().isoformat()

    postings = load_postings()
    groups = merge_duplicates(postings)
    duplicate_groups = [g for g in groups if len(g) > 1]

    decisions = {r["datei"]: (r.get("status") or "").strip().lower() for r in read_csv(DECISIONS_CSV)}
    expired = {r["datei"] for r in read_csv(EXPIRED_CSV)}
    radar_rows = [r for r in read_csv(RADAR_CSV) if not (r.get("erledigt") or "").strip()]
    radar_files = {r.get("datei") for r in radar_rows}
    history = {}
    for r in read_csv(HISTORY_CSV):
        history.setdefault(r["datei"], r["datum"])

    def is_done(group):
        """Group is out if one of its files is bewerben/abgeschickt/nein or expired."""
        for p in group:
            status = decisions.get(p["datei"], "")
            if (status and status != "später" and status != "spaeter") or p["datei"] in expired:
                return True
        return False

    candidates = []
    for g in groups:
        best = g[0]
        if is_done(g) or best["score"] < MIN_SCORE or is_no_go(best.get("no_go")):
            continue
        if is_no_go(best.get("radar")) or any(p["datei"] in radar_files for p in g):
            continue  # radar postings appear in their own section further down
        candidates.append(g)
    candidates.sort(key=lambda g: (-g[0]["score"], {"gut": 0, "mittel": 1}.get(g[0].get("chancen", ""), 2)))

    # Selection: at most MAX_PER_COMPANY per company, check links, until MAX_SHORTLIST is full
    shortlist, more_per_company, newly_expired = [], {}, []
    per_company, link_checks = {}, 0
    check_links = "--no-link-check" not in sys.argv
    for g in candidates:
        p = g[0]
        if len(shortlist) >= MAX_SHORTLIST:
            break
        if per_company.get(p["firma_key"], 0) >= MAX_PER_COMPANY:
            more_per_company.setdefault(p["firma"], []).append(p)
            continue
        p["link"] = "nicht geprüft"
        if check_links and link_checks < MAX_LINK_CHECKS:
            link_checks += 1
            p["link"] = link_status(p["url"])
            print(f"  Link {p['link']:>10}: {p['firma']} – {p['titel'][:50]}")
            if p["link"] == "abgelaufen":
                newly_expired.append({"datum": today, "datei": p["datei"], "firma": p["firma"],
                                      "titel": p["titel"], "url": p["url"]})
                continue
        shortlist.append(g)
        per_company[p["firma_key"]] = per_company.get(p["firma_key"], 0) + 1

    # Collect company hints also for candidates beyond rank 5
    for g in candidates:
        p = g[0]
        if g not in shortlist and per_company.get(p["firma_key"], 0) >= MAX_PER_COMPANY \
                and p not in more_per_company.get(p["firma"], []):
            more_per_company.setdefault(p["firma"], []).append(p)

    # --- Build the note (German, it is read in Obsidian) ---
    lines = [
        "---", "typ: analyse", f"erstellt: {today}", "tags: [praktikum-agent, shortlist]",
        "quelle: shortlist.py", "---", "",
        f"# Shortlist {today}", "",
        f"**Kurz:** {len(shortlist)} Stellen auf der Shortlist (Score ≥ {MIN_SCORE}, höchstens "
        f"{MAX_PER_COMPANY} pro Firma). Insgesamt {len(postings)} bewertete Anzeigen, "
        f"{len(duplicate_groups)} Duplikat-Gruppen zusammengefasst.", "",
    ]
    if len(shortlist) < 3:
        lines += [f"> Weniger als 3 Stellen über {MIN_SCORE}. Absichtlich nicht aufgefüllt: "
                  "lieber wenige gute als fünf mittelmäßige.", ""]

    lines += ["## Shortlist", "",
              "| # | Score | Chancen | Firma | Stelle | Ort | Quelle | Link | Neu? |",
              "|---|---|---|---|---|---|---|---|---|"]
    for nr, g in enumerate(shortlist, 1):
        p = g[0]
        sources = ", ".join(sorted({x["quelle"] for x in g}))
        old = ""
        if p["gefunden"]:
            days = (date.today() - datetime.strptime(p["gefunden"], "%Y-%m-%d").date()).days
            old = f" (alt: {days} Tage)" if days > OLD_AFTER_DAYS else ""
        new = "NEU" if p["datei"] not in history else f"seit {history[p['datei']]}"
        link = f"[öffnen]({p['url']})" if p["url"] else "–"
        if p["link"] == "unklar":
            link += " ⚠️"
        lines.append(f"| {nr} | {p['score']} | {md(p.get('chancen'))} | {md(p['firma'])} | "
                     f"{md(p['titel'], 60)} | {md(p.get('ort'), 25)} | {md(sources)}{old} | {link} | {new} |")
    lines.append("")
    if any(g[0]["link"] == "unklar" for g in shortlist):
        lines += ["⚠️ = Link konnte nicht automatisch geprüft werden (Seite blockiert Skripte). Vor dem Bewerben selbst öffnen.", ""]

    lines += ["### Begründungen", ""]
    for nr, g in enumerate(shortlist, 1):
        p = g[0]
        lines.append(f"{nr}. **{md(p['firma'])} – {md(p['titel'], 80)}:** {md(p.get('begruendung'), 350)}")
        if len(g) > 1:
            others = "; ".join(f"{x['quelle']} ({x['score']})" for x in g[1:])
            lines.append(f"    - Auch gefunden über: {others}")
    lines.append("")

    if more_per_company:
        lines += ["## Weitere Stellen bei denselben Firmen", ""]
        for company, items in more_per_company.items():
            text = "; ".join(f"{md(x['titel'], 50)} ({x['score']})" for x in items)
            lines.append(f"- **{md(company)}:** {text}")
        lines.append("")

    # All remaining candidates from MIN_SCORE: not top 5, but do not lose them either
    already_shown = {g[0]["datei"] for g in shortlist} | {x["datei"] for l in more_per_company.values() for x in l} \
        | {r["datei"] for r in newly_expired}
    rest = [g[0] for g in candidates if g[0]["datei"] not in already_shown]
    lines += [f"## Weitere Kandidaten ab {MIN_SCORE} ({len(rest)})", ""]
    if rest:
        lines += ["Nicht in den Top 5, Link nicht geprüft. Rutschen nach, sobald oben etwas erledigt ist.", ""]
        for p in rest:
            link = f" [Link]({p['url']})" if p["url"] else ""
            lines.append(f"- {p['score']} · {md(p.get('chancen'))} · **{md(p['firma'])}** – {md(p['titel'], 60)} ({md(p.get('ort'), 25)}){link}")
    else:
        lines.append("- (keine)")
    lines.append("")

    lines += ["## Radar (interessant, aber Rückfrage nötig)", ""]
    scores_by_file = {p["datei"]: p["score"] for p in postings}
    radar_sorted = sorted(radar_rows, key=lambda r: -(scores_by_file.get(r.get("datei"), 0)))
    if radar_sorted:
        for r in radar_sorted[:10]:
            score = scores_by_file.get(r.get("datei"), "–")
            link = f" [Link]({r['link']})" if r.get("link") else ""
            lines.append(f"- {score} · **{md(r.get('firma'))}** – {md(r.get('titel'), 60)}: {md(r.get('grund'), 80)}{link}")
        if len(radar_sorted) > 10:
            lines.append(f"- … und {len(radar_sorted) - 10} weitere in `ergebnisse/radar.csv`")
    else:
        lines.append("- (leer)")
    lines.append("")

    open_manual, seen = [], set()
    for r in read_csv(MANUAL_CSV):
        url = normalize_url(r.get("url"))
        if not (r.get("erledigt") or "").strip() and url not in seen:
            seen.add(url)
            open_manual.append(r)
    lines += [f"## Selbst prüfen ({len(open_manual)} offen in `manuell_pruefen.csv`)", ""]
    for r in open_manual[:8]:
        lines.append(f"- {md(r.get('titel'), 70)}: {r.get('url', '')}")
    if not open_manual:
        lines.append("- (nichts offen)")
    lines.append("")

    if newly_expired:
        lines += ["## Diese Woche abgelaufen (aussortiert)", ""]
        lines += [f"- {md(r['firma'])} – {md(r['titel'], 60)}" for r in newly_expired]
        lines.append("")

    if duplicate_groups:
        lines += ["## Zusammengefasste Duplikate (zum Gegenprüfen)", ""]
        for g in duplicate_groups[:15]:
            lines.append("- " + " = ".join(f"{md(x['firma'])} „{md(x['titel'], 45)}“ ({x['quelle']}, {x['score']})" for x in g))
        lines.append("")

    lines += ["## Status-Logik (`ergebnisse/entscheidungen.csv`)", "",
              "| Status | Bedeutung | Auf der Shortlist? |", "|---|---|---|",
              "| leer oder `später` | noch nicht entschieden | ja |",
              "| `bewerben` | Unterlagen erstellen lassen (Schritt 5) | nein |",
              "| `abgeschickt` | Bewerbung ist raus (nur zum Nachverfolgen) | nein |",
              "| `nein` | kein Interesse | nein |", "",
              "Ablauf: leer → `bewerben` → Entwurf prüfen und abschicken → `abgeschickt`.", ""]
    lines += ["## Nächste Schritte", "",
              "- In `ergebnisse/entscheidungen.csv` bei den Stellen, die du entschieden hast, `status` eintragen (siehe Status-Logik).",
              "- Für ausgewählte Stellen Unterlagen erstellen (Schritt 5).", "",
              "## Verwandte Notizen", "", "- [[Praktikum-Agent]]", "- [[Praktikum-Agent Radar]]",
              "- [[Praktikum-Agent shortlist.py]]", ""]
    note = "\n".join(lines)

    if dry_run:
        print("\n" + note)
        print("(--dry-run: nichts gespeichert)")
        return

    # --- Save: never overwrite a note ---
    SHORTLIST_DIR.mkdir(parents=True, exist_ok=True)
    target = SHORTLIST_DIR / f"{today} Shortlist.md"
    nr = 2
    while target.exists():
        target = SHORTLIST_DIR / f"{today} Shortlist ({nr}).md"
        nr += 1
    target.write_text(note, encoding="utf-8")

    append_csv(EXPIRED_CSV, ["datum", "datei", "firma", "titel", "url"], newly_expired)
    append_csv(HISTORY_CSV, ["datum", "datei", "firma", "titel", "score"],
               [{"datum": today, **{k: g[0][k] for k in ("datei", "firma", "titel", "score")}} for g in shortlist])
    append_csv(DECISIONS_CSV, ["datei", "firma", "titel", "status", "notiz"],
               [{"datei": g[0]["datei"], "firma": g[0]["firma"], "titel": g[0]["titel"], "status": "", "notiz": ""}
                for g in shortlist if g[0]["datei"] not in decisions])

    print(f"\n✅ {len(shortlist)} Stellen auf der Shortlist, {len(duplicate_groups)} Duplikat-Gruppen, "
          f"{len(newly_expired)} abgelaufen. Kosten: 0 $")
    print(f"Notiz: {target}")


if __name__ == "__main__":
    main()
