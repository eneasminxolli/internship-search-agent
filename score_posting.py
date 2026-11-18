"""
Step 2: Score one job posting against the search profile.

Usage:  python score_posting.py anzeigen/test.txt

Since step 3 also usable as a building block (e.g. by score_all.py):
    from score_posting import score_posting
"""
import json
import sys
from datetime import date
from pathlib import Path

import anthropic

# config.py loads .env (API key) and decides whether profile and CV come
# from the Obsidian vault (VAULT_PATH) or from the example/ folder.
from config import CV_FILE, PROFILE_FILE, PROJECT_DIR  # noqa: F401 (PROJECT_DIR is re-exported)

# --- Settings --------------------------------------------------------------
MODEL = "claude-haiku-5-5"  # cheapest model; for comparison: "claude-sonnet-5-5"
PRICE_INPUT = 0.10   # $ per million input tokens (Haiku 5.5)
PRICE_OUTPUT = 0.50  # $ per million output tokens (Haiku 5.5)


def build_system_prompt(profile, cv):
    # The system prompt tells Claude WHO it is and HOW to answer.
    # The actual rules live in the profile (vault), not here in the code.
    return f"""Du bewertest Praktikumsanzeigen für einen Studenten.
Heutiges Datum: {date.today().isoformat()} (wichtig für Fristen, Startdaten und das Alter der Anzeige).

<suchprofil>
{profile}
</suchprofil>

<lebenslauf>
{cv}
</lebenslauf>

Bewerte die Anzeige streng nach dem Abschnitt "Bewertung" im Suchprofil und erfinde nichts.
Ein No-Go ergibt Score 0. Nutze die Kalibrierung aus dem Profil und die ganze Skala.
Den Lebenslauf verwendest du NUR für das Feld "chancen" (keine Punkte dafür).
"radar": kurzer Grund laut Abschnitt "Radar" im Profil (z. B. "Start 12/2026 – nach Juni fragen"), sonst "".
Antworte NUR mit JSON in genau diesem Format, ohne weiteren Text:
{{
  "firma": "...",
  "titel": "...",
  "ort": "...",
  "teilscores": {{"inhalt": 0-50, "unternehmen": 0-20, "start": 0-12, "dauer": 0-8, "bekanntheit": 0-10,
                  "bonus_masterarbeit": 0 oder 5, "abzug_konzern": -10 oder 0, "abzug_unbezahlt": -25 oder 0, "abzug_ort": -3 bis 0}},
  "score": 0-100 (Summe der Teilscores, zwischen 0 und 100),
  "no_go": true/false,
  "chancen": "gut" | "mittel" | "schwierig",
  "radar": "" oder kurzer Grund,
  "pro": ["...", "..."],
  "contra": ["...", "..."],
  "begruendung": "2-3 Sätze"
}}"""


def score_posting(posting, client):
    """Scores the text of one job posting.

    Returns three things: (result as dict or None, raw response text, cost in $).
    """
    profile = PROFILE_FILE.read_text(encoding="utf-8")
    cv = CV_FILE.read_text(encoding="utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,  # upper bound for thinking + answer combined (= cost limit)
        system=build_system_prompt(profile, cv),
        messages=[{"role": "user", "content": f"<anzeige>\n{posting}\n</anzeige>"}],
    )

    # stop_reason says WHY the model stopped:
    # "end_turn" = finished, "max_tokens" = cut off because max_tokens was too small.
    if response.stop_reason == "max_tokens":
        print("WARNUNG: Antwort wurde abgeschnitten (max_tokens erreicht).")

    # Haiku 5.5 thinks first (ThinkingBlock), then comes the answer (TextBlock).
    # So we take the first text block, not simply the first block.
    text = next((block.text for block in response.content if block.type == "text"), "")

    # Sometimes the model wraps the JSON in ```json ... ``` fences. We strip them.
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = None

    u = response.usage
    cost = u.input_tokens / 1e6 * PRICE_INPUT + u.output_tokens / 1e6 * PRICE_OUTPUT
    return result, text, cost


# This part ONLY runs when you start the file directly (python score_posting.py ...),
# not when another script uses it as a building block via "import".
if __name__ == "__main__":
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY (from .env)
    posting = Path(sys.argv[1]).read_text(encoding="utf-8")
    result, text, cost = score_posting(posting, client)

    if result is None:
        print("Antwort war kein gültiges JSON. Rohtext:\n", text)
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nKosten: ca. {cost:.5f} $")
