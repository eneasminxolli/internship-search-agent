"""
Step 3b (second part): Compare your scores with the agent's scores.

Usage:  python evaluate.py           (test set 1)
        python evaluate.py --set 2   (test set 2)

Metrics:
- Mean absolute deviation: by how many points is the agent off on average?
- Rank correlation (Spearman, -1 to 1): does the agent put the postings in the same
  ORDER as you? For a shortlist this matters more than exact points.
"""
import csv
import sys

from score_posting import PROJECT_DIR

AGENT_CSV = PROJECT_DIR / "ergebnisse" / "agent_scores.csv"
SET_NR = int(sys.argv[sys.argv.index("--set") + 1]) if "--set" in sys.argv else 1
TEST_CSV = PROJECT_DIR / "testset" / ("meine_bewertung.csv" if SET_NR == 1 else f"meine_bewertung_{SET_NR}.csv")


def ranks(values):
    """Rank of each value (1 = smallest); ties get the average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    r = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def correlation(x, y):
    mx, my = sum(x) / len(x), sum(y) / len(y)
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = sum((a - mx) ** 2 for a in x) ** 0.5
    sy = sum((b - my) ** 2 for b in y) ** 0.5
    return cov / (sx * sy) if sx and sy else float("nan")


def is_number(value):
    try:
        float(value.replace(",", "."))
        return True
    except ValueError:
        return False


def main():
    with open(AGENT_CSV, encoding="utf-8-sig") as f:
        agent = {r["datei"]: r for r in csv.DictReader(f, delimiter=";")}
    with open(TEST_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    # Empty fields or placeholders like "-" (e.g. posting no longer available) are skipped
    mine = [r for r in rows if is_number(r["mein_score"].strip())]
    skipped = [r["firma"] for r in rows if r["mein_score"].strip() and not is_number(r["mein_score"].strip())]
    if skipped:
        print("Ohne Zahl, übersprungen:", ", ".join(skipped))

    if len(mine) < 3:
        print("Bitte erst mindestens 3 Zeilen mit mein_score ausfüllen.")
        return

    pairs = []
    for r in mine:
        a = agent[r["datei"]]
        pairs.append((r, float(r["mein_score"].replace(",", ".")), float(a["score"]), a["begruendung"]))

    human = [p[1] for p in pairs]
    model = [p[2] for p in pairs]
    mad = sum(abs(a - b) for a, b in zip(human, model)) / len(pairs)
    rho = correlation(ranks(human), ranks(model))

    print(f"{len(pairs)} Anzeigen verglichen")
    print(f"Mittlere Abweichung: {mad:.1f} Punkte")
    print(f"Rangkorrelation:     {rho:.2f}   (1 = gleiche Reihenfolge, 0 = kein Zusammenhang)\n")
    print("Größte Abweichungen zuerst (hier lohnt sich ein Blick in den Prompt):")
    for r, m, a, reason in sorted(pairs, key=lambda p: -abs(p[1] - p[2])):
        print(f"  ich {m:>3.0f} | Agent {a:>3.0f} | {r['firma']} – {r['titel']}")
        print(f"      Agent: {reason}")


if __name__ == "__main__":
    main()
