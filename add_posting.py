"""
Step 5 (part 1): Add a posting by hand that the agent could not open.

Usage:  python add_posting.py <link>
        python add_posting.py <link> --status später   (instead of "bewerben")

Order matters (the clipboard holds only one thing):
  1. Copy the link of the posting, type  python add_posting.py  in the terminal,
     paste the link (⌘V) - do NOT press Enter yet.
  2. In the browser, copy the whole posting text (⌘A, ⌘C).
  3. Now press Enter in the terminal. The script reads the text from the clipboard
     and asks for company, title and location.

What the script does (no Claude, no costs):
  - saves the posting in anzeigen/gefunden/ (source: manuell)
  - ticks off the row(s) with this link in ergebnisse/manuell_pruefen.csv
  - adds the posting with status "bewerben" to ergebnisse/entscheidungen.csv
The next  python score_all.py  gives it a score (sanity check).
"""
import csv
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
POSTINGS_DIR = PROJECT_DIR / "anzeigen" / "gefunden"
RESULTS_DIR = PROJECT_DIR / "ergebnisse"
MANUAL_CSV = RESULTS_DIR / "manuell_pruefen.csv"
DECISIONS_CSV = RESULTS_DIR / "entscheidungen.csv"

MIN_CHARS = 300   # less text is certainly not a whole posting
ALLOWED_STATUS = {"bewerben", "später", "nein", "abgeschickt"}


def normalize_url(url):
    return (url or "").split("#")[0].split("?")[0].rstrip("/").lower()


def make_filename(company, title):
    """Same scheme as in web_search.py."""
    raw = f"{company}_{title}".lower()
    for old, new in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        raw = raw.replace(old, new)
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:70] + ".txt"


def read_csv(path):
    if not path.exists():
        return [], []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=";")
        return reader.fieldnames or [], list(reader)


def write_csv(path, columns, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def clipboard():
    try:
        return subprocess.run(["pbpaste"], capture_output=True, text=True, check=True).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        sys.exit("❌ Konnte die Zwischenablage nicht lesen (pbpaste gibt es nur auf dem Mac).")


def ask(text, default=""):
    hint = f" [{default}]" if default else ""
    answer = input(f"{text}{hint}: ").strip()
    return answer or default


def already_saved(url):
    target = normalize_url(url)
    for path in POSTINGS_DIR.glob("*.txt"):
        first = path.read_text(encoding="utf-8").splitlines()[:1]
        if first and first[0].startswith("URL: ") and normalize_url(first[0][5:]) == target:
            return path.name
    return None


def main():
    args = sys.argv[1:]
    status = "bewerben"
    if "--status" in args:
        i = args.index("--status")
        if i + 1 >= len(args):
            sys.exit("❌ Nach --status fehlt der Wert (bewerben, später, nein, abgeschickt).")
        status = args[i + 1].strip().lower()
        del args[i:i + 2]
        if status not in ALLOWED_STATUS:
            sys.exit(f"❌ Unbekannter Status '{status}'. Erlaubt: {', '.join(sorted(ALLOWED_STATUS))}")
    if len(args) != 1 or not args[0].startswith("http"):
        sys.exit("Aufruf: python add_posting.py <Link>   (Anleitung oben in der Datei)")
    url = args[0].strip()

    # 1. Check the clipboard
    text = clipboard().strip()
    if not text:
        sys.exit("❌ Die Zwischenablage ist leer. Erst den Anzeigentext im Browser kopieren (⌘A, ⌘C).")
    if re.fullmatch(r"\S+", text) or text.startswith("http") and len(text) < 500:
        sys.exit("❌ In der Zwischenablage liegt nur ein Link, nicht der Anzeigentext.\n"
                 "   Reihenfolge: Befehl mit Link eintippen (ohne Enter) → Text im Browser kopieren → Enter.")
    if len(text) < MIN_CHARS:
        sys.exit(f"❌ Nur {len(text)} Zeichen in der Zwischenablage. Das ist sicher nicht die ganze Anzeige.")

    existing = already_saved(url)
    if existing:
        sys.exit(f"ℹ️  Diese Stelle ist schon gespeichert: {existing}. Nichts geändert.")

    # 2. Title suggestion from manuell_pruefen.csv
    columns_m, rows_m = read_csv(MANUAL_CSV)
    matches = [r for r in rows_m if normalize_url(r.get("url")) == normalize_url(url)]
    title_default = (matches[0].get("titel") or "").replace("‍", "").strip() if matches else ""

    print(f"\n📋 {len(text)} Zeichen aus der Zwischenablage. Anfang:\n   {text[:150].replace(chr(10), ' ')} …\n")
    company = ask("Firma")
    title = ask("Titel", title_default)
    location = ask("Ort")
    if not company or not title:
        sys.exit("❌ Firma und Titel braucht das Skript. Nichts gespeichert.")

    # 3. Save the posting (same format as the other sources)
    POSTINGS_DIR.mkdir(parents=True, exist_ok=True)
    name = make_filename(company, title)
    path = POSTINGS_DIR / name
    if path.exists():
        sys.exit(f"❌ Es gibt schon eine Datei {name} (andere URL). Bitte Titel leicht ändern und neu starten.")
    header = (f"URL: {url}\nFirma: {company}\nTitel: {title}\nOrt: {location}\n"
              f"Gefunden am: {date.today().isoformat()} (Quelle: manuell)\n---\n")
    path.write_text(header + text + "\n", encoding="utf-8")
    print(f"💾 gespeichert: anzeigen/gefunden/{name}")

    # 4. Tick off manuell_pruefen.csv (all rows with this link, including duplicates)
    if matches:
        for r in rows_m:
            if normalize_url(r.get("url")) == normalize_url(url):
                r["erledigt"] = date.today().isoformat()
        write_csv(MANUAL_CSV, columns_m, rows_m)
        print(f"✅ manuell_pruefen.csv: {len(matches)} Zeile(n) abgehakt")
    else:
        print("ℹ️  Link steht nicht in manuell_pruefen.csv (ist ok, z. B. bei einer Stelle aus einem Job-Alert)")

    # 5. Add to entscheidungen.csv
    columns_d, rows_d = read_csv(DECISIONS_CSV)
    columns_d = columns_d or ["datei", "firma", "titel", "status", "notiz"]
    rows_d.append({"datei": name, "firma": company, "titel": title, "status": status,
                   "notiz": "manuell eingefügt"})
    write_csv(DECISIONS_CSV, columns_d, rows_d)
    print(f"✅ entscheidungen.csv: Status '{status}'")
    print("\nNächster Schritt: python score_all.py  (bewertet nur neue Anzeigen, ca. 0,002 $)")


if __name__ == "__main__":
    main()
