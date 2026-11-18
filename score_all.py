"""
Step 3: Score all found postings with the logic from score_posting.py.

Usage:  python score_all.py           (blind: shows NO scores)
        python score_all.py --show    (shows the scores)
        python score_all.py --new     (re-scores ALL postings, e.g. after a profile
                                       change; the old file is kept as
                                       agent_scores_bis_DATE_TIME.csv)

Output: ergebnisse/agent_scores.csv
Postings that were already scored are skipped (nothing is paid twice).

Important for blind rating (step 3b): open agent_scores.csv only
AFTER you have entered your own scores.
"""
import csv
import json
import sys
from datetime import datetime

import anthropic

from score_posting import PROJECT_DIR, score_posting

POSTINGS_DIR = PROJECT_DIR / "anzeigen" / "gefunden"
SCORES_CSV = PROJECT_DIR / "ergebnisse" / "agent_scores.csv"
MAX_SCORINGS = 40  # cost limit: at most this many API calls per run (40 × approx. $0.002)
COLUMNS = ["datei", "firma", "titel", "ort", "score", "no_go", "chancen", "radar", "teilscores", "begruendung"]
RADAR_CSV = PROJECT_DIR / "ergebnisse" / "radar.csv"
RADAR_COLUMNS = ["datum", "firma", "titel", "grund", "datei", "link", "erledigt"]


def link_of(filename):
    first = (POSTINGS_DIR / filename).read_text(encoding="utf-8").splitlines()[0]
    return first[5:] if first.startswith("URL: ") else ""


def add_to_radar(filename, result):
    """Interesting roles you cannot apply to right now → radar.csv."""
    known = set()
    if RADAR_CSV.exists():
        with open(RADAR_CSV, encoding="utf-8-sig") as f:
            known = {row["datei"] for row in csv.DictReader(f, delimiter=";")}
    if filename in known:
        return
    with open(RADAR_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RADAR_COLUMNS, delimiter=";")
        if not known and f.tell() == 0:
            writer.writeheader()
        writer.writerow({"datum": datetime.now().date().isoformat(), "firma": result.get("firma"),
                         "titel": result.get("titel"), "grund": result.get("radar"),
                         "datei": filename, "link": link_of(filename), "erledigt": ""})


def main():
    show = "--show" in sys.argv
    SCORES_CSV.parent.mkdir(exist_ok=True)
    if SCORES_CSV.exists() and "--new" not in sys.argv:
        with open(SCORES_CSV, encoding="utf-8-sig") as f:
            if csv.DictReader(f, delimiter=";").fieldnames != COLUMNS:
                print("Die alte agent_scores.csv hat ein anderes Format (Profil v1). "
                      "Bitte mit --new starten.")
                return
    if "--new" in sys.argv and SCORES_CSV.exists():
        old = SCORES_CSV.with_name(f"agent_scores_bis_{datetime.now():%Y-%m-%d_%H%M}.csv")
        SCORES_CSV.rename(old)
        print(f"Alte Bewertungen aufbewahrt als {old.name}, bewerte alles neu.")

    already_scored = set()
    if SCORES_CSV.exists():
        with open(SCORES_CSV, encoding="utf-8-sig") as f:
            already_scored = {row["datei"] for row in csv.DictReader(f, delimiter=";")}

    pending = [p for p in sorted(POSTINGS_DIR.glob("*.txt")) if p.name not in already_scored]
    if not pending:
        print("Nichts Neues zu bewerten.")
        return
    if len(pending) > MAX_SCORINGS:
        print(f"{len(pending)} offen, bewerte nur die ersten {MAX_SCORINGS}.")
        pending = pending[:MAX_SCORINGS]

    client = anthropic.Anthropic()
    create_new = not SCORES_CSV.exists()
    total = 0.0

    # utf-8-sig and ";" so that Excel/Numbers open the file with umlauts correctly
    with open(SCORES_CSV, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, delimiter=";")
        if create_new:
            writer.writeheader()

        for path in pending:
            result, raw_text, cost = score_posting(path.read_text(encoding="utf-8"), client)
            total += cost
            if result is None:
                print(f"  ⚠️  {path.name}: kein gültiges JSON, übersprungen")
                continue
            writer.writerow({
                "datei": path.name,
                "firma": result.get("firma"),
                "titel": result.get("titel"),
                "ort": result.get("ort"),
                "score": result.get("score"),
                "no_go": result.get("no_go"),
                "chancen": result.get("chancen"),
                "radar": result.get("radar", ""),
                "teilscores": json.dumps(result.get("teilscores"), ensure_ascii=False),
                "begruendung": result.get("begruendung"),
            })
            if result.get("radar"):
                add_to_radar(path.name, result)
            if show:
                print(f"  {result.get('score'):>3}  {path.name}")
            else:
                print(f"  ✓ bewertet: {path.name}")

    print(f"\nGespeichert in {SCORES_CSV}  |  Kosten ca. {total:.4f} $")
    print(f"Radar (später bewerben/nachfragen): {RADAR_CSV}")


if __name__ == "__main__":
    main()
