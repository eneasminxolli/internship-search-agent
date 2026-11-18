"""
Step 4: One command for the whole weekly run.

Usage:  python weekly_run.py                    (default, approx. $0.02-0.05: applicant portals -> scoring -> shortlist)
        python weekly_run.py --with-web-search  (adds web_search.py, approx. $0.10-0.15; every 2-4 weeks)
        python weekly_run.py --with-ba          (adds ba_search.py; only worth it from January)
        python weekly_run.py --all              (all sources)
        python weekly_run.py --shortlist-only   (only shortlist.py and dashboard.py, $0)
        python weekly_run.py --yes              (start without confirmation)
        python weekly_run.py --no-browser       (build the dashboard without opening it)

Why web search is not the default: until 2026-11-12 it found 22 postings for approx. $0.60
(approx. 3 cents per posting), the applicant portals 22 postings for $0. The Federal
Employment Agency (BA) returned 3 postings in November. Scoring itself is cheap
(approx. $0.002 per posting).

Runs the scripts one after another. If one source fails, the others keep running.
Cost limits: every script has its own limits (web_search.py max. $0.20, ba_search.py
max. 10 API calls, score_all.py max. 40 scorings). This script only adds them up
and asks for confirmation before starting.
"""
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).parent

# (label, script, estimated maximum cost in $) - upper bounds, real runs usually cost less
STEPS = [
    ("Websuche",             "web_search.py",    0.20),
    ("Bundesagentur",        "ba_search.py",     0.10),
    ("Bewerberportale",      "portal_search.py", 0.00),
    ("Bewertung",            "score_all.py",     0.10),
    ("Shortlist",            "shortlist.py",     0.00),
    ("Dashboard",            "dashboard.py",     0.00),
]


def main():
    run_all = "--all" in sys.argv
    skip = set()
    if not (run_all or "--with-web-search" in sys.argv):
        skip.add("web_search.py")
    if not (run_all or "--with-ba" in sys.argv):
        skip.add("ba_search.py")
    if "--shortlist-only" in sys.argv:
        skip = {s[1] for s in STEPS} - {"shortlist.py", "dashboard.py"}
    steps = [s for s in STEPS if s[1] not in skip]

    max_cost = sum(s[2] for s in steps)
    print("Wochenlauf:", " → ".join(s[0] for s in steps))
    print(f"Geschätzte Kosten: höchstens ca. {max_cost:.2f} $ (meist deutlich weniger)")
    if "--yes" not in sys.argv and max_cost > 0:
        if input("Starten? (j/n) ").strip().lower() != "j":
            print("Abgebrochen.")
            return

    log = []
    for label, script, _ in steps:
        print(f"\n{'=' * 60}\n▶ {label} ({script})\n{'=' * 60}")
        start = time.time()
        extra = ["--no-open"] if script == "dashboard.py" and "--no-browser" in sys.argv else []
        # sys.executable = exactly the Python that started weekly_run.py (i.e. the one from the venv)
        result = subprocess.run([sys.executable, script] + extra, cwd=PROJECT_DIR)
        ok = result.returncode == 0
        log.append((label, ok, time.time() - start))
        if not ok:
            print(f"⚠️  {label} ist mit Fehler beendet worden. Weiter mit dem nächsten Schritt.")

    print(f"\n{'=' * 60}\nZusammenfassung")
    for label, ok, duration in log:
        print(f"  {'✅' if ok else '❌'} {label:<18} {duration:5.0f} s")
    print("Die genauen Kosten stehen jeweils oben in der Ausgabe der einzelnen Skripte.")


if __name__ == "__main__":
    main()
