"""
Make decisions without opening the CSV file in an editor.

Usage:  python decide.py                     (all postings without a status)
        python decide.py --later             (also all with status "später")
        python decide.py --all               (all postings, also change decided ones)
        python decide.py --company bundesbank (only postings of this company, also decided ones)

One key per posting, then Enter:
  b = bewerben   a = abgeschickt   n = nein   s = später
  o = open link in the browser       Enter = skip   q = quit
Then optionally a short note (e.g. why "nein"). That helps to improve the profile later.

Every decision is saved immediately in ergebnisse/entscheidungen.csv. No Claude, no costs.
"""
import csv
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
RESULTS_DIR = PROJECT_DIR / "ergebnisse"
DECISIONS_CSV = RESULTS_DIR / "entscheidungen.csv"
SCORES_CSV = RESULTS_DIR / "agent_scores.csv"
POSTINGS_DIR = PROJECT_DIR / "anzeigen" / "gefunden"
COLUMNS = ["datei", "firma", "titel", "status", "notiz"]
KEYS = {"b": "bewerben", "a": "abgeschickt", "n": "nein", "s": "später"}


def read_csv(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def save(rows):
    with open(DECISIONS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def posting_link(filename):
    path = POSTINGS_DIR / filename
    if path.exists():
        first = path.read_text(encoding="utf-8").splitlines()[:1]
        if first and first[0].startswith("URL: "):
            return first[0][5:].strip()
    return ""


def main():
    rows = read_csv(DECISIONS_CSV)
    if not rows:
        sys.exit("Keine entscheidungen.csv gefunden. Erst: python shortlist.py")
    scores = {r["datei"]: r for r in read_csv(SCORES_CSV)}

    if "--company" in sys.argv:
        i = sys.argv.index("--company")
        term = " ".join(sys.argv[i + 1:]).strip().lower()
        if not term:
            sys.exit("Nach --company fehlt der Name, z. B.: python decide.py --company bundesbank")
        pending = [r for r in rows if term in (r.get("firma") or "").lower()]
    elif "--all" in sys.argv:
        pending = rows
    elif "--later" in sys.argv:
        pending = [r for r in rows if (r.get("status") or "").strip() in ("", "später")]
    else:
        pending = [r for r in rows if not (r.get("status") or "").strip()]
    if not pending:
        print("✅ Nichts offen. (Mit --later oder --all siehst du auch entschiedene Stellen.)")
        return

    print(f"{len(pending)} Stelle(n). Tasten: b=bewerben a=abgeschickt n=nein s=später o=Link öffnen "
          f"Enter=überspringen (Status bleibt) q=beenden\n")
    changed = 0
    for nr, r in enumerate(pending, 1):
        s = scores.get(r["datei"], {})
        link = posting_link(r["datei"])
        print("─" * 70)
        print(f"[{nr}/{len(pending)}] {r.get('firma')} – {r.get('titel')}")
        print(f"   Score: {s.get('score', '?')} | Chancen: {s.get('chancen', '?')} | Ort: {s.get('ort', '?')}"
              f" | Status bisher: {r.get('status') or '–'}")
        reasoning = (s.get("begruendung") or "").strip()
        if reasoning:
            print(f"   {reasoning[:300]}{' …' if len(reasoning) > 300 else ''}")
        if link:
            print(f"   {link}")

        while True:
            key = input("   Entscheidung: ").strip().lower()
            if key == "o":
                if link:
                    subprocess.run(["open", link])  # macOS
                else:
                    print("   Kein Link gespeichert.")
                continue
            break
        if key == "q":
            break
        if key not in KEYS:
            print("   → übersprungen")
            continue
        r["status"] = KEYS[key]
        note = input("   Notiz (optional, Enter = keine): ").strip()
        if note:
            r["notiz"] = note
        save(rows)  # save immediately so nothing gets lost
        changed += 1
        print(f"   ✅ {KEYS[key]}")

    print(f"\nFertig: {changed} Entscheidung(en) gespeichert.")
    if changed and (PROJECT_DIR / "dashboard.py").exists():
        print("Aktualisiere das Dashboard …")
        subprocess.run([sys.executable, str(PROJECT_DIR / "dashboard.py")])


if __name__ == "__main__":
    main()
