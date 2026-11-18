"""
Central configuration: where the search profile, the CV and the shortlist notes live.

If VAULT_PATH is set in .env, the files are read from (and written to) the Obsidian vault.
Otherwise the fictional example files in example/ are used, so anyone who clones the
repository can run the code without a vault.

    VAULT_PATH=~/path/to/your/vault      (in .env, see .env.example)
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).parent
# .env holds ANTHROPIC_API_KEY=sk-ant-... and optionally VAULT_PATH=...
load_dotenv(PROJECT_DIR / ".env")

_vault = os.getenv("VAULT_PATH", "").strip()
VAULT_PATH = Path(_vault).expanduser() if _vault else None

if VAULT_PATH:
    VAULT_PROJECT_DIR = VAULT_PATH / "10 Projekte"
    # Profile v2 since 2026-11-11 (v1 = "Praktikum-Agent Suchprofil.md", kept for comparison)
    PROFILE_FILE = VAULT_PROJECT_DIR / "Praktikum-Agent Suchprofil v2.md"
    CV_FILE = VAULT_PROJECT_DIR / "Praktikum-Agent Lebenslauf (für Agent).md"
    SHORTLIST_DIR = VAULT_PROJECT_DIR / "Praktikum-Agent Shortlists"
    PROJECT_NOTE = VAULT_PROJECT_DIR / "Praktikum-Agent.md"
else:
    EXAMPLE_DIR = PROJECT_DIR / "example"
    PROFILE_FILE = EXAMPLE_DIR / "search_profile.md"
    CV_FILE = EXAMPLE_DIR / "cv.md"
    SHORTLIST_DIR = PROJECT_DIR / "ergebnisse" / "shortlists"
    PROJECT_NOTE = EXAMPLE_DIR / "project_note.md"  # optional, the dashboard works without it
