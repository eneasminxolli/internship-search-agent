# Suchprofil (Beispiel)

> Erfundenes Beispielprofil, damit der Code ohne eigenen Obsidian-Vault läuft.
> Eigenes Profil: Datei kopieren, anpassen und `VAULT_PATH` in `.env` setzen
> (oder diese Datei direkt bearbeiten).

## Wer sucht

Alex Beispiel, Masterstudent Business Analytics, sucht ein Praktikum im Sommer 2027
(Juni bis August, 2–4 Monate).

## Eckdaten

- **Länder/Städte:** Deutschland (Berlin, München, Frankfurt am Main), Portugal (Lissabon, Porto), remote
- **Zeitraum:** Start ab Juni 2027, Dauer 2–4 Monate
- **Sprachen:** Deutsch, Englisch (Portugiesisch keine Voraussetzung)
- **Vergütung:** bezahlt bevorzugt

## Was begeistert

- Data Science und Machine Learning mit Anwendungsbezug
- Analytics an der Schnittstelle von Daten und Business
- Eigenverantwortung, sichtbare Wirkung, Kontakt zu den Anwendern

## Was abschreckt

- Reiner Vertrieb, Kaltakquise, Social Media
- Reine Präsentations- oder Dokumentationsarbeit ohne Datenbezug

## Unternehmen (grobe Rangfolge, bei gleicher Rolle)

1. Zentralbanken, Forschungsinstitute, Tech-Scale-ups und FinTechs
2. Top-Strategieberatungen
3. Big Four und mittlere Beratungen
4. Industriekonzerne

## No-Gos (Score 0)

- Kostenpflichtige Programme
- Werkstudentenstellen während des Semesters
- Pflichtpraktika, die eine Einschreibung in Deutschland voraussetzen

## Bewertung (Score 0–100)

| Kriterium | Punkte |
|---|---|
| **Inhalt** passt zu den Interessen (wichtigstes Kriterium) | 0–50 |
| **Unternehmen** nach der Rangfolge oben (1 = 20, 2 = 14, 3 = 8, 4 = 5) | 0–20 |
| **Start:** ab Juni 2027 = 12; keine Angabe = 8; vor Juni = 7 (dafür `radar`) | 0–12 |
| **Dauer:** bis 4 Monate = 8; 5–6 Monate = 6; länger = 4; keine Angabe = 5 | 0–8 |
| **Bekanntheit:** international = 10, national = 5, unbekannt = 0 | 0–10 |
| Bonus: Masterarbeit möglich und Thema passt | +5 |
| Abzug: Industriekonzern | −10 |
| Abzug: ausdrücklich unbezahlt | −25 |
| Abzug: Ort außerhalb der Wunschstädte | −3 bis 0 |

**Inhalts-Schwelle:** Weniger als 15/50 beim Inhalt → Score höchstens 25.

**Hinweise zur Bewertung:**
- Den Inhalt nach den tatsächlichen Aufgaben beurteilen, nicht nach dem Titel.
- Die ganze Skala nutzen: 85+ nur für Stellen, auf die man sich sofort bewerben würde.
- **Radar:** Inhalt ab 35/50, aber Bewerbung gerade nicht direkt möglich (Start vor Juni,
  Dauer über 6 Monate, Bewerbung geschlossen) → kurzer Grund im Feld `radar`.
- Hohe Anforderungen geben keinen Abzug, sondern werden als `chancen` angegeben.

## Kalibrierung (bei sonst gleichen Stellen)

- Scale-up statt Industriekonzern: deutlich besser
- 3 statt 6 Monate: deutlich besser
- Data Analytics vs. Strategie ohne Daten: klar für Data Analytics
- Bezahlt vs. unbezahlt: klar für bezahlt
