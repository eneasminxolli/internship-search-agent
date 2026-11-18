"""
Dashboard: a local HTML page with an overview of the internship agent.

Usage:  python dashboard.py            (build the page and open it in the browser)
        python dashboard.py --no-open  (only build it, e.g. in the weekly run)

No Claude, no costs, no internet. Only reads local files:
  ergebnisse/*.csv, anzeigen/gefunden/ (links), the project note and the shortlist notes
  (Obsidian vault if VAULT_PATH is set, otherwise example/ and ergebnisse/shortlists/).
Writes:  dashboard.html in the project folder (private, listed in .gitignore).

The page is a snapshot. If you change entscheidungen.csv, simply run
python dashboard.py again (takes 1 second).

The page itself is German (user-facing language). The JSON keys passed to the page
(e.g. "firma", "titel", "zeiten") are German because the JavaScript reads them.
"""
import html
import json
import re
import sys
import webbrowser
from datetime import date, datetime, timedelta

from config import PROJECT_NOTE, SHORTLIST_DIR
# Reuse paths and helpers from shortlist.py so both compute the same way
from shortlist import (
    DECISIONS_CSV, EXPIRED_CSV, HISTORY_CSV, MANUAL_CSV, PROJECT_DIR, RADAR_CSV, SCORES_CSV,
    is_no_go, read_csv, read_header, to_int,
)

TARGET = PROJECT_DIR / "dashboard.html"
WEEKLY_INTERVAL = 7  # days between two weekly runs


def modified(path):
    return datetime.fromtimestamp(path.stat().st_mtime) if path.exists() else None


def normalize_status(value):
    s = (value or "").strip().lower()
    return "später" if s in {"", "spaeter", "später"} else s


def md_to_html(text):
    """Only the essentials: **bold**, `code`, [[link]]."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    t = re.sub(r"\[\[(.+?)\]\]", r'<span class="wl">\1</span>', t)
    return t


def project_status():
    if not PROJECT_NOTE.exists():
        return {"schritte": [], "letzter": f"{PROJECT_NOTE.name} nicht gefunden."}
    text = PROJECT_NOTE.read_text(encoding="utf-8")
    steps = [
        {"nr": nr, "fertig": x.lower() == "x", "name": name}
        for nr, x, name in re.findall(r"^(\d)\. \[( |x|X)\] \*\*(.+?)\*\*", text, re.M)
    ]
    section = text.split("## Stand / Übergabe", 1)[-1].split("\n## ", 1)[0]
    entries = [e.strip() for e in re.split(r"\n- ", section) if e.strip().startswith("**") and "Arbeitsweise" not in e[:20]]
    last = entries[-1] if entries else "Kein Eintrag gefunden."
    return {"schritte": steps, "letzter": md_to_html(last.split("\n  >")[0])}


def collect_data():
    today = date.today()
    scores = {r["datei"]: r for r in read_csv(SCORES_CSV)}
    decisions = {r["datei"]: r for r in read_csv(DECISIONS_CSV)}
    expired = {r["datei"] for r in read_csv(EXPIRED_CSV)}

    def posting(filename, company="", title=""):
        s, h = scores.get(filename, {}), read_header(filename)
        return {
            "datei": filename,
            "firma": company or s.get("firma") or h.get("firma", ""),
            "titel": title or s.get("titel") or h.get("titel", ""),
            "ort": s.get("ort", ""),
            "score": to_int(s.get("score")) if s else None,
            "chancen": s.get("chancen", ""),
            "begruendung": s.get("begruendung", ""),
            "url": h["url"],
            "quelle": h["quelle"],
            "gefunden": h["gefunden"],
            "status": normalize_status(decisions.get(filename, {}).get("status")),
            "notiz": decisions.get(filename, {}).get("notiz", ""),
        }

    # 1. Shortlist = postings of the last run according to shortlist_verlauf.csv
    history = read_csv(HISTORY_CSV)
    last_shortlist = max((r["datum"] for r in history), default="")
    first_seen = {}
    for r in history:
        first_seen.setdefault(r["datei"], r["datum"])
    radar = read_csv(RADAR_CSV)
    radar_open = {r.get("datei") for r in radar if not (r.get("erledigt") or "").strip()}
    shortlist, seen = [], set()
    for r in history:
        if r["datum"] != last_shortlist or r["datei"] in seen:
            continue
        seen.add(r["datei"])
        p = posting(r["datei"], r["firma"], r["titel"])
        p["score"] = p["score"] if p["score"] is not None else to_int(r["score"])
        hints = []
        if first_seen.get(r["datei"]) == last_shortlist:
            hints.append("neu")
        if p["status"] != "später":
            hints.append(f"Status: {p['status']}")
        if r["datei"] in expired:
            hints.append("abgelaufen")
        if r["datei"] in radar_open:
            hints.append("Radar")
        if p["gefunden"]:
            try:
                if (today - date.fromisoformat(p["gefunden"])).days > 42:
                    hints.append("alt (> 6 Wochen)")
            except ValueError:
                pass
        if p["chancen"] == "schwierig":
            hints.append("Chancen schwierig")
        p["hinweise"] = hints
        shortlist.append(p)
    shortlist.sort(key=lambda p: -(p["score"] or 0))

    # 2. Radar
    radar_list = []
    for r in radar:
        p = posting(r.get("datei", ""), r.get("firma", ""), r.get("titel", ""))
        p.update(grund=r.get("grund", ""), url=r.get("link") or p["url"], datum=r.get("datum", ""),
                 erledigt=(r.get("erledigt") or "").strip())
        radar_list.append(p)
    radar_list.sort(key=lambda p: (bool(p["erledigt"]), -(p["score"] or 0)))

    # 3. Check manually (merge duplicates by URL)
    manual = {}
    for r in read_csv(MANUAL_CSV):
        url = (r.get("url") or "").strip()
        entry = manual.setdefault(url, {"titel": (r.get("titel") or "").replace("‍", "").strip(),
                                        "url": url, "datum": r.get("datum", ""), "fehler": r.get("fehler", ""),
                                        "erledigt": "", "anzahl": 0})
        entry["anzahl"] += 1
        entry["erledigt"] = entry["erledigt"] or (r.get("erledigt") or "").strip()
    manual_list = sorted(manual.values(), key=lambda m: (bool(m["erledigt"]), m["datum"]))

    # 4. Applications (all rows from entscheidungen.csv)
    applications = [posting(r["datei"], r.get("firma", ""), r.get("titel", "")) for r in read_csv(DECISIONS_CSV)]

    # 5. Timestamps
    notes = sorted(SHORTLIST_DIR.glob("*Shortlist*.md"), key=lambda p: p.stat().st_mtime) if SHORTLIST_DIR.exists() else []
    last_note = notes[-1] if notes else None
    t_shortlist = modified(last_note) if last_note else None
    t_scores = modified(SCORES_CSV)
    base = t_shortlist.date() if t_shortlist else (date.fromisoformat(last_shortlist) if last_shortlist else today)
    due = base + timedelta(days=WEEKLY_INTERVAL)
    warnings = []
    if t_shortlist and t_scores and t_scores > t_shortlist:
        warnings.append("agent_scores.csv ist neuer als die letzte Shortlist (z. B. neu bewertete Stellen). "
                        "Für eine frische Shortlist: <code>python weekly_run.py --shortlist-only</code> (0 $).")
    t_decisions = modified(DECISIONS_CSV)
    if t_shortlist and t_decisions and t_decisions > t_shortlist:
        warnings.append("entscheidungen.csv wurde nach der letzten Shortlist geändert. Die Shortlist unten "
                        "zeigt deshalb schon den neuen Status, aber noch keine Nachrücker.")
    times = {
        "shortlist": t_shortlist.strftime("%d.%m.%Y %H:%M") if t_shortlist else "noch nie",
        "shortlist_notiz": last_note.stem if last_note else "",
        "entscheidungen": t_decisions.strftime("%d.%m.%Y %H:%M") if t_decisions else "Datei fehlt",
        "scores": t_scores.strftime("%d.%m.%Y %H:%M") if t_scores else "Datei fehlt",
        "faellig": due.strftime("%d.%m.%Y"),
        "tage_bis": (due - today).days,
        "warnungen": warnings,
    }

    return {
        "erstellt": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "shortlist_datum": last_shortlist,
        "shortlist": shortlist,
        "radar": radar_list,
        "manuell": manual_list,
        "bewerbungen": applications,
        "zeiten": times,
        "projekt": project_status(),
        "anzahl_bewertet": len(scores),
        "anzahl_nogo": sum(1 for r in scores.values() if is_no_go(r.get("no_go"))),
    }


def main():
    data = collect_data()
    # escape </ so that text from postings cannot close the <script> tag
    json_text = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    TARGET.write_text(HTML_TEMPLATE.replace("__DATEN__", json_text), encoding="utf-8")
    print(f"Dashboard gespeichert: {TARGET}")
    if "--no-open" not in sys.argv:
        webbrowser.open(TARGET.resolve().as_uri())


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Praktikum-Agent · Dashboard</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1b;--mute:#6b6a66;--line:#e4e2dc;--acc:#2f5d8a;
--ok:#2e7d4f;--warn:#b26a00;--bad:#a8323a;--chip:#eeece6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecebe7;--mute:#9d9b95;
--line:#33322f;--acc:#7fa8d1;--ok:#6cc08f;--warn:#e0a54a;--bad:#e07a80;--chip:#2b2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:0 0 10px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}
.top{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:18px}
.mute{color:var(--mute)}.small{font-size:12px}
input[type=search]{padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);min-width:240px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;cursor:pointer}
.tile .n{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{color:var(--mute);font-size:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.warn{border-left:4px solid var(--warn);padding:8px 12px;background:var(--chip);border-radius:6px;margin:6px 0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;color:var(--mute);font-weight:600;cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--ink)}td.num{font-variant-numeric:tabular-nums;font-weight:600}
tr.det td{background:var(--chip);font-size:13px;color:var(--mute)}tr.klick{cursor:pointer}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--chip);font-size:12px;margin:0 4px 2px 0;white-space:nowrap}
.c-gut{color:var(--ok)}.c-mittel{color:var(--warn)}.c-schwierig{color:var(--bad)}
a{color:var(--acc);white-space:nowrap}#t-manuell td:first-child{white-space:nowrap}code{background:var(--chip);padding:0 4px;border-radius:4px;font-size:12px}
.pipe{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
@media (max-width:800px){.pipe{grid-template-columns:1fr 1fr}}
.col{background:var(--chip);border-radius:10px;padding:10px;min-height:80px}
.col h3{margin:0 0 8px;font-size:13px;display:flex;justify-content:space-between}
.kb{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px}
.kb b{display:block}.steps{list-style:none;padding:0;margin:0 0 12px}.steps li{padding:4px 0}
.box{display:inline-block;width:18px;text-align:center}.done{color:var(--ok)}.open{color:var(--mute)}
.wl{color:var(--acc)}.tabs{display:flex;gap:6px;margin-bottom:10px}.tabs button{border:1px solid var(--line);
background:var(--card);color:var(--ink);border-radius:999px;padding:3px 12px;cursor:pointer;font-size:12px}
.tabs button.on{background:var(--ink);color:var(--bg)}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:900px){.grid2{grid-template-columns:1fr}}.erl{opacity:.55}
</style></head><body><div class="wrap">
<div class="top"><div><h1>Praktikum-Agent</h1>
<div class="mute small">Stand der Daten: <span id="erstellt"></span> · lokale Datei, nicht veröffentlicht</div></div>
<input type="search" id="suche" placeholder="Firma oder Titel filtern …"></div>
<div class="tiles" id="tiles"></div>
<div class="grid2">
 <div class="card" id="zeit"><h2>Rhythmus</h2></div>
 <div class="card" id="projekt"><h2>Projektstand</h2></div>
</div>
<div class="card" id="sec-shortlist"><h2>Shortlist <span class="mute" id="sl-datum"></span></h2>
 <div class="mute small" style="margin-bottom:8px">Zeile anklicken für die Begründung des Agenten. Spaltenköpfe sortieren.</div>
 <table id="t-shortlist"></table></div>
<div class="card" id="sec-pipe"><h2>Bewerbungen</h2><div class="pipe" id="pipe"></div></div>
<div class="card" id="sec-radar"><h2>Radar</h2><div class="tabs" data-for="radar"></div><table id="t-radar"></table></div>
<div class="card" id="sec-manuell"><h2>Selbst prüfen</h2><div class="tabs" data-for="manuell"></div><table id="t-manuell"></table></div>
</div>
<script>
const D = __DATEN__;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const link = u => u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">öffnen ↗</a>` : '<span class="mute">–</span>';
const chancen = c => c ? `<span class="c-${esc(c)}">${esc(c)}</span>` : "";
let filter = "";
const passt = o => !filter || `${o.firma} ${o.titel}`.toLowerCase().includes(filter);
const filterAn = { radar: "offen", manuell: "offen" };

$("#erstellt").textContent = D.erstellt;
$("#sl-datum").textContent = D.shortlist_datum ? "· Lauf vom " + D.shortlist_datum.split("-").reverse().join(".") : "";

// Kacheln
const zaehl = st => D.bewerbungen.filter(b => b.status === st).length;
const tiles = [
  [D.shortlist.length, "auf der Shortlist", "#sec-shortlist"],
  [zaehl("bewerben"), "Status „bewerben“", "#sec-pipe"],
  [zaehl("abgeschickt"), "abgeschickt", "#sec-pipe"],
  [D.radar.filter(r => !r.erledigt).length, "Radar offen", "#sec-radar"],
  [D.manuell.filter(m => !m.erledigt).length, "selbst prüfen", "#sec-manuell"],
  [D.anzahl_bewertet, "Anzeigen bewertet", null],
];
$("#tiles").innerHTML = tiles.map(([n, l, z]) => `<div class="tile" ${z ? `onclick="document.querySelector('${z}').scrollIntoView({behavior:'smooth'})"` : ""}><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");

// Rhythmus
const Z = D.zeiten;
const tage = Z.tage_bis;
const fText = tage > 1 ? `in ${tage} Tagen` : tage === 1 ? "morgen" : tage === 0 ? "heute" : `<b style="color:var(--bad)">überfällig seit ${-tage} Tag${tage === -1 ? "" : "en"}</b>`;
$("#zeit").innerHTML += `<table>
<tr><td class="mute">Letzte Shortlist</td><td>${esc(Z.shortlist)} <span class="mute small">${esc(Z.shortlist_notiz)}</span></td></tr>
<tr><td class="mute">entscheidungen.csv bearbeitet</td><td>${esc(Z.entscheidungen)}</td></tr>
<tr><td class="mute">Letzte Bewertung (agent_scores)</td><td>${esc(Z.scores)}</td></tr>
<tr><td class="mute">Nächster Wochenlauf</td><td><b>${esc(Z.faellig)}</b> · ${fText}</td></tr></table>
<div class="small mute" style="margin-top:8px">Wochenlauf: <code>python weekly_run.py</code> · alle 2–4 Wochen <code>--with-web-search</code> · ab Januar <code>--with-ba</code></div>
${Z.warnungen.map(w => `<div class="warn small">${w}</div>`).join("")}`;

// Projektstand
const P = D.projekt;
$("#projekt").innerHTML += `<ul class="steps">${P.schritte.map(s => `<li><span class="box ${s.fertig ? "done" : "open"}">${s.fertig ? "✓" : "○"}</span> ${s.nr}. ${esc(s.name)}</li>`).join("")}</ul>
<div class="small"><div class="mute" style="margin-bottom:4px">Letzter Eintrag „Stand / Übergabe“:</div>${P.letzter}</div>`;

// Sortierbare Tabelle
function tabelle(id, spalten, zeilen, detail) {
  const t = $(id); let sortKey = null, auf = false;
  function zeichnen() {
    let z = zeilen().filter(passt);
    if (sortKey) z = [...z].sort((a, b) => { const x = a[sortKey] ?? "", y = b[sortKey] ?? ""; return (x > y ? 1 : x < y ? -1 : 0) * (auf ? 1 : -1); });
    t.innerHTML = `<tr>${spalten.map(s => `<th data-k="${s.k}">${s.t}${sortKey === s.k ? (auf ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>` +
      (z.length ? z.map((o, i) => `<tr class="${detail ? "klick" : ""} ${o.erledigt ? "erl" : ""}" data-i="${i}">${spalten.map(s => `<td class="${s.num ? "num" : ""}">${s.f ? s.f(o) : esc(o[s.k])}</td>`).join("")}</tr>` +
        (detail ? `<tr class="det" hidden><td colspan="${spalten.length}">${esc(detail(o))}</td></tr>` : "")).join("")
        : `<tr><td colspan="${spalten.length}" class="mute">Nichts gefunden.</td></tr>`);
    t.querySelectorAll("th").forEach(th => th.onclick = () => { auf = sortKey === th.dataset.k ? !auf : false; sortKey = th.dataset.k; zeichnen(); });
    t.querySelectorAll("tr.klick").forEach(tr => tr.onclick = e => { if (e.target.tagName !== "A") tr.nextElementSibling.hidden = !tr.nextElementSibling.hidden; });
  }
  zeichnen(); return zeichnen;
}

const neuZeichnen = [];
neuZeichnen.push(tabelle("#t-shortlist", [
  { k: "score", t: "Score", num: 1 }, { k: "firma", t: "Firma" }, { k: "titel", t: "Stelle" },
  { k: "ort", t: "Ort" }, { k: "chancen", t: "Chancen", f: o => chancen(o.chancen) },
  { k: "hinweise", t: "Hinweise", f: o => o.hinweise.map(h => `<span class="chip">${esc(h)}</span>`).join("") },
  { k: "url", t: "Link", f: o => link(o.url) },
], () => D.shortlist, o => o.begruendung || "Keine Begründung gespeichert."));

// Tabs für Radar und Selbst prüfen
function tabs(name, render) {
  const box = document.querySelector(`.tabs[data-for=${name}]`);
  const liste = D[name];
  const opts = [["offen", liste.filter(x => !x.erledigt).length], ["erledigt", liste.filter(x => x.erledigt).length], ["alle", liste.length]];
  const draw = () => { box.innerHTML = opts.map(([k, n]) => `<button class="${filterAn[name] === k ? "on" : ""}" data-k="${k}">${k} (${n})</button>`).join("");
    box.querySelectorAll("button").forEach(b => b.onclick = () => { filterAn[name] = b.dataset.k; draw(); render(); }); };
  draw();
}
const nachTab = name => () => D[name].filter(x => filterAn[name] === "alle" || (filterAn[name] === "offen") === !x.erledigt);

const rRadar = tabelle("#t-radar", [
  { k: "score", t: "Score", num: 1 }, { k: "firma", t: "Firma" }, { k: "titel", t: "Stelle" },
  { k: "grund", t: "Warum auf dem Radar" }, { k: "erledigt", t: "Erledigt" }, { k: "url", t: "Link", f: o => link(o.url) },
], nachTab("radar"));
tabs("radar", rRadar); neuZeichnen.push(rRadar);

const rManuell = tabelle("#t-manuell", [
  { k: "datum", t: "Gefunden" }, { k: "titel", t: "Stelle", f: o => esc(o.titel) + (o.anzahl > 1 ? ` <span class="chip">${o.anzahl}× in CSV</span>` : "") },
  { k: "fehler", t: "Grund" }, { k: "erledigt", t: "Erledigt / entfällt" }, { k: "url", t: "Link", f: o => link(o.url) },
], nachTab("manuell"));
tabs("manuell", rManuell); neuZeichnen.push(rManuell);

// Pipeline
const SPALTEN = [["später", "Offen / später"], ["bewerben", "Bewerben (Unterlagen)"], ["abgeschickt", "Abgeschickt"], ["nein", "Nein"]];
function pipe() {
  const bekannte = SPALTEN.map(s => s[0]);
  const andere = D.bewerbungen.filter(b => !bekannte.includes(b.status));
  $("#pipe").innerHTML = SPALTEN.map(([st, name]) => {
    const z = D.bewerbungen.filter(b => b.status === st && passt(b));
    return `<div class="col"><h3><span>${name}</span><span class="mute">${z.length}</span></h3>${z.map(b =>
      `<div class="kb"><b>${esc(b.firma)}</b>${esc(b.titel)}<div class="small mute">${b.score != null ? "Score " + b.score + " · " : ""}${chancen(b.chancen)} ${b.url ? "· " + link(b.url) : ""}${b.notiz ? "<br>" + esc(b.notiz) : ""}</div></div>`).join("")}</div>`;
  }).join("") + (andere.length ? `<div class="warn small" style="grid-column:1/-1">Unbekannter Status (Tippfehler?): ${andere.map(b => esc(b.firma) + " → „" + esc(b.status) + "“").join(", ")}</div>` : "");
}
pipe(); neuZeichnen.push(pipe);

$("#suche").oninput = e => { filter = e.target.value.trim().toLowerCase(); neuZeichnen.forEach(f => f()); };
</script></body></html>
"""

if __name__ == "__main__":
    main()
