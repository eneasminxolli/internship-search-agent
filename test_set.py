"""
Step 3b: Build the test set for blind rating.

Usage:  python test_set.py            (test set 1: testset/meine_bewertung.csv)
        python test_set.py --set 2    (test set 2: testset/meine_bewertung_2.csv, only postings
                                       that do not appear in any earlier test set)

Fills the test set from ergebnisse/agent_scores.csv with up to 10 postings spread over the
whole score range (good, medium, bad), shuffles the order and writes
testset/meine_bewertung.csv WITHOUT the agent's scores.
Rows where you already entered mein_score are kept.
In the column mein_score you enter your own rating (0-100).
"""
import csv
import random
import sys

from score_posting import PROJECT_DIR

AGENT_CSV = PROJECT_DIR / "ergebnisse" / "agent_scores.csv"
TEST_DIR = PROJECT_DIR / "testset"


def test_file(nr):
    return TEST_DIR / ("meine_bewertung.csv" if nr == 1 else f"meine_bewertung_{nr}.csv")


def set_number():
    """Reads --set N from the command line (default: 1)."""
    if "--set" in sys.argv:
        return int(sys.argv[sys.argv.index("--set") + 1])
    return 1


SET_NR = set_number()
TEST_CSV = test_file(SET_NR)
SIZE = 10


def link_of(filename):
    """Reads the URL from the first line of the saved posting."""
    path = PROJECT_DIR / "anzeigen" / "gefunden" / filename
    if not path.exists():
        return ""
    first = path.read_text(encoding="utf-8").splitlines()[0]
    return first[5:] if first.startswith("URL: ") else ""


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def main():
    # 1. Load the existing test set. Rows with your own score are ALWAYS kept.
    keep = []
    if TEST_CSV.exists():
        with open(TEST_CSV, encoding="utf-8-sig") as f:
            keep = [r for r in csv.DictReader(f, delimiter=";") if r["mein_score"].strip()]
    already_in = {r["datei"] for r in keep}
    # Postings from earlier test sets do not belong in a new one (otherwise not a fair test)
    for earlier in range(1, SET_NR):
        if test_file(earlier).exists():
            with open(test_file(earlier), encoding="utf-8-sig") as f:
                already_in |= {r["datei"] for r in csv.DictReader(f, delimiter=";")}
    free = SIZE - len(keep)
    if free <= 0:
        print(f"Test-Set ist voll ({len(keep)} Anzeigen). Nichts geändert.")
        return

    # 2. Candidates: scored postings not yet in the test set, sorted by agent score
    with open(AGENT_CSV, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f, delimiter=";") if r["datei"] not in already_in]
    rows.sort(key=lambda r: to_float(r["score"]))

    # 3. Pick evenly spread over the sorted list: lowest, highest and in between
    n = len(rows)
    if n <= free:
        new = rows
    else:
        positions = sorted({round(i * (n - 1) / (free - 1)) for i in range(free)}) if free > 1 else [n // 2]
        new = [rows[p] for p in positions]
    random.shuffle(new)  # otherwise the order reveals the scores

    # 4. Write: first your already rated rows, then the new ones (with empty mein_score)
    TEST_CSV.parent.mkdir(exist_ok=True)
    with open(TEST_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["nr", "datei", "firma", "titel", "ort", "mein_score", "notiz", "link"])
        nr = 0
        for r in keep:
            nr += 1
            writer.writerow([nr, r["datei"], r["firma"], r["titel"], r["ort"], r["mein_score"], r["notiz"],
                             r.get("link") or link_of(r["datei"])])
        for r in new:
            nr += 1
            writer.writerow([nr, r["datei"], r["firma"], r["titel"], r["ort"], "", "", link_of(r["datei"])])

    print(f"Test-Set: {len(keep)} schon bewertet + {len(new)} neu = {nr} Anzeigen ({TEST_CSV})")
    if new:
        print("Trage bei den neuen Zeilen mein_score (0-100) ein. agent_scores.csv erst danach öffnen.")


if __name__ == "__main__":
    main()
