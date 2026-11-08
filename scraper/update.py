"""Dagelijkse update van data/woningen.json.

Haalt het koopaanbod op van de Alliantie (alle pagina's) en Lieven de Key,
vult details aan uit de detailpagina's, geocodeert nieuwe adressen via de
PDOK Locatieserver en markeert nieuwe woningen (eerstGezien = vandaag).
Woningen van andere corporaties (bijv. Stadgenoot uit de aanbodmail) blijven staan.
"""
import datetime as dt
import json
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "woningen.json"
TODAY = dt.date.today().isoformat()
UA = {"User-Agent": "huis-tracker (persoonlijk overzicht corporatiewoningen)"}
MAANDEN = {m: i + 1 for i, m in enumerate("januari februari maart april mei juni juli augustus september oktober november december".split())}

SPEC_ALLIANTIE = "Sociale huurders van de Alliantie én andere corporaties · bod ≥ vraagprijs · tot uiterste inschrijfdatum"
SPEC_DEKEY_APP = "Sociale huurders in Amsterdam/Diemen (ook andere corporaties); De Key-huurders gaan voor · eerste 2 weken na aanbieding · beste bod (prijs én voorwaarden)"
SPEC_DEKEY_HUIS = "Sociale huurders in Amsterdam/Diemen (ook andere corporaties) · eerste 4 weken na aanbieding · gezinswoning: De Key-huurders géén voorrang op anderen"


def get(url):
    for i in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            time.sleep(2 + 3 * i)
    raise RuntimeError("kon niet ophalen: " + url)


def text_of(html):
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "svg"]):
        t.decompose()
    return re.sub(r"[ \t]+", " ", s.get_text("\n"))


def stadsdeel_uit_postcode(pc):
    try:
        n = int(pc[:4])
    except ValueError:
        return ""
    if n == 1013: return "West"
    if 1011 <= n <= 1018: return "Centrum"
    if n == 1019: return "Oost"
    if 1020 <= n <= 1039: return "Noord"
    if 1051 <= n <= 1058: return "West"
    if n == 1059: return "Zuid"
    if 1060 <= n <= 1069: return "Nieuw-West"
    if 1070 <= n <= 1083: return "Zuid"
    if 1086 <= n <= 1099: return "Oost"
    if 1101 <= n <= 1109: return "Zuidoost"
    return ""


def erfpacht_kort(t):
    m = re.search(r"[^.\n;]*(erfpacht|canon|eigen grond)[^.\n;]*", t, re.I)
    if not m:
        return ""
    s = m.group(0)
    if re.search(r"eigen grond", s, re.I):
        return "Eigen grond"
    d = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if d:
        return f"Canon afgekocht t/m {int(d[1]):02d}-{int(d[2]):02d}-{d[3]}"
    d = re.search(r"(\d{1,2}) (\w+) (\d{4})", s)
    if d and d[2].lower() in MAANDEN:
        return f"Canon afgekocht t/m {int(d[1]):02d}-{MAANDEN[d[2].lower()]:02d}-{d[3]}"
    if re.search(r"voortdurend|jaarlijks", s, re.I):
        return "Voortdurende erfpacht"
    return ""


def num(s):
    s = (s or "").strip().replace(".", "").replace(",", ".").rstrip(".")
    try:
        return float(s)
    except ValueError:
        return ""


# ---------- De Alliantie ----------
def alliantie():
    out = []
    base = "https://ik-zoek.de-alliantie.nl/kopen/amsterdam/"
    for p in range(1, 15):
        s = BeautifulSoup(get(f"{base}?page={p}"), "html.parser")
        res = s.select(".result")
        if not res:
            break
        for r in res:
            a = r.select_one('a[href*="kopen/"]')
            slug = a["href"].split("?")[0].rstrip("/").split("/")[-1]
            info = r.select_one(".result__info")
            adres = re.sub(r"\s+", " ", info.select_one("h3").get_text()).strip().replace(" -", "-")
            path = re.sub(r"\s+", " ", info.select_one(".path").get_text()).strip()
            m = re.search(r"(\d+) m2 - (\d+) kamers? - (.+)", path)
            labels = [x.get_text(strip=True) for x in info.select(".result__info__property-labels span")]
            out.append(dict(slug=slug, adres=adres, m2=int(m[1]) if m else "", kamers=int(m[2]) if m else "",
                            type=(m[3] if m else "").replace(" - Tuin", ""), labels=labels))
    rows = []
    for o in out:
        t = text_of(get(base + o["slug"]))
        g = lambda rx: (re.search(rx, t) or [None, ""])[1].strip()
        dl = ""
        m = re.search(r"uiterste inschrijfdatum (?:tot )?(?:\w+dag )?(\d{1,2}) (\w+)(?: (\d{4}))?", t, re.I)
        if m and m[2].lower() in MAANDEN:
            dl = f"{m[3] or TODAY[:4]}-{MAANDEN[m[2].lower()]:02d}-{int(m[1]):02d}"
        besch = g(r"Beschikbaarheid\s*\n\s*([^\n]+)")
        status = {"Beschikbaar": "beschikbaar", "Verkocht onder voorbehoud": "verkocht o.v.b."}.get(besch, "onder bod" if "bod" in besch.lower() or "optie" in besch.lower() else "beschikbaar")
        area = g(r"\n\s*(G[A-Z]\d+ [^\n]+?)-?\n")
        bj = g(r"Bouwjaar\s*\n\s*(\d{4})")
        rows.append(dict(
            id=o["slug"], adres=o["adres"], plaats="Amsterdam", corporatie="Alliantie",
            prijs=int(g(r"Vraagprijs\s*\n\s*€\s*([\d.]+)").replace(".", "") or 0),
            m2=o["m2"], kamers=o["kamers"], type=o["type"], tuin="ja" if "Tuin" in o["labels"] else "nee",
            energielabel=g(r"[Ee]nergielabel\s*:?\s*([A-G]\+*)\b"), bouwjaar=int(bj) if bj else "",
            servicekosten=num(g(r"[Ss]ervicekosten[^€\n]{0,40}€\s*([\d.,]+)")), erfpacht=erfpacht_kort(t),
            status=status, voorrangLabel="ja" if any("Voorrang" in l for l in o["labels"]) else "nee",
            voorJou="ja", deadline=dl, voorrangSpec=SPEC_ALLIANTIE,
            url=base + o["slug"], bron="ik-zoek.de-alliantie.nl", _wijk=re.sub(r"^G[A-Z]\d+ ", "", area)))
        time.sleep(0.5)
    return rows


# ---------- Lieven de Key ----------
def dekey():
    base = "https://www.vindjeplekbijdekey.nl"
    seen, out = set(), []
    for p in range(1, 15):
        s = BeautifulSoup(get(f"{base}/?page={p}"), "html.parser")
        items = [li for li in s.select("li") if li.select_one(":scope > div .price")]
        new = 0
        for li in items:
            a = li.select_one("h2 a")
            href = a["href"]
            ribbon = (li.select_one(".ribbon").get_text(strip=True) if li.select_one(".ribbon") else "").lower()
            key = href
            if key in seen:
                continue
            seen.add(key)
            new += 1
            if ribbon == "verkocht":
                continue
            feats = [x.get_text(strip=True) for x in li.select(".features li")]
            m = re.search(r"(\d+) kamers? - (\d+) m", feats[0] if feats else "")
            span = a.select_one("span")
            pc = span.get_text(strip=True).split(",")[0] if span else ""
            adres = a.contents[0].strip() if a.contents else ""
            adres = re.sub(r" (\d+) ([A-Za-z0-9]+)$", r" \1-\2", adres)
            typ = feats[1] if len(feats) > 1 else ""
            out.append(dict(
                id=href.rstrip("/").split("/")[-1], adres=adres, plaats="Amsterdam", postcode=pc, corporatie="Lieven de Key",
                prijs=int(re.sub(r"\D", "", li.select_one(".price span").get_text()) or 0),
                m2=int(m[2]) if m else "", kamers=int(m[1]) if m else "", type=typ.capitalize(),
                tuin="ja" if any("tuin" in f.lower() for f in feats) else "nee",
                status="onder bod" if "bod" in ribbon else "verkocht o.v.b." if "verkocht" in ribbon else "beschikbaar",
                voorrangLabel="ja", voorJou="ja", url=base + href, bron="vindjeplekbijdekey.nl",
                _appartement=typ.lower() == "appartement"))
        if not new:
            break
    return out


def dekey_details(w):
    t = text_of(get(w["url"]))
    g = lambda rx: (re.search(rx, t) or [None, ""])[1].strip()
    bj = g(r"Bouwjaar\s*\n\s*(\d{4})")
    w["bouwjaar"] = int(bj) if bj else w.get("bouwjaar", "")
    w["servicekosten"] = num(g(r"Bijdrage VvE\s*\n\s*€\s*([\d.,]+)")) or w.get("servicekosten", "")
    w["energielabel"] = g(r"[Ee]nergielabel\s*:?\s*([A-G]\+*)\b") or w.get("energielabel", "")
    w["erfpacht"] = erfpacht_kort(t) or w.get("erfpacht", "")


# ---------- PDOK ----------
def geocode(adres, postcode=""):
    q = f"{adres} {postcode} Amsterdam".strip()
    try:
        r = requests.get("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
                         params={"q": q, "fq": "type:adres", "rows": 1, "fl": "centroide_ll,wijknaam,postcode"}, headers=UA, timeout=20).json()
        d = r["response"]["docs"][0]
        m = re.search(r"POINT\(([\d.]+) ([\d.]+)\)", d["centroide_ll"])
        return float(m[2]), float(m[1]), d.get("wijknaam", ""), d.get("postcode", "")
    except Exception:
        return "", "", "", ""


def main():
    oud = json.loads(DATA.read_text())
    by_id = {w["id"]: w for w in oud}
    nieuw_lijst, fouten = [], []
    gescraped = {}
    for naam, fn in (("Alliantie", alliantie), ("Lieven de Key", dekey)):
        try:
            gescraped[naam] = fn()
        except Exception as e:  # bron tijdelijk stuk: bestaande woningen laten staan
            fouten.append(f"{naam}: {e}")
    resultaat = [w for w in oud if w["corporatie"] not in gescraped]
    for corp, rows in gescraped.items():
        for r in rows:
            w = by_id.get(r["id"])
            extra = {k: r.pop(k) for k in list(r) if k.startswith("_")}
            if w:
                for k, v in r.items():
                    if v != "" or k == "status":
                        w[k] = v
                w["gezienOp"] = TODAY
                if corp == "Lieven de Key" and (not w.get("bouwjaar") or not w.get("energielabel")):
                    try: dekey_details(w)
                    except Exception: pass
            else:
                w = dict(postcode="", stadsdeel="", wijk=extra.get("_wijk", ""), energielabel="", bouwjaar="", servicekosten="",
                         erfpacht="", deadline="", **r)
                w.setdefault("voorrangSpec", "")
                if corp == "Lieven de Key":
                    try: dekey_details(w)
                    except Exception: pass
                    days = 14 if extra.get("_appartement") else 28
                    w["deadline"] = (dt.date.today() + dt.timedelta(days=days)).isoformat()
                    w["voorrangSpec"] = (SPEC_DEKEY_APP if extra.get("_appartement") else SPEC_DEKEY_HUIS) + " · deadline geschat vanaf eerste keer gezien"
                lat, lon, wijk, pc = geocode(w["adres"], w.get("postcode", ""))
                w.update(lat=lat, lon=lon, eerstGezien=TODAY, gezienOp=TODAY)
                if not w.get("wijk"): w["wijk"] = wijk
                if not w.get("postcode") and pc: w["postcode"] = pc[:4] + " " + pc[4:]
                w["stadsdeel"] = stadsdeel_uit_postcode(w.get("postcode", ""))
                nieuw_lijst.append(w)
            resultaat.append(w)
    # adressen zonder locatie alsnog proberen
    for w in resultaat:
        if not w.get("lat"):
            lat, lon, wijk, _ = geocode(w["adres"], w.get("postcode", ""))
            if lat:
                w.update(lat=lat, lon=lon)
                w["wijk"] = w.get("wijk") or wijk
    resultaat.sort(key=lambda w: (w["corporatie"], w["adres"]))
    DATA.write_text(json.dumps(resultaat, ensure_ascii=False, indent=1))
    meta = ROOT / "data" / "meta.json"
    meta.write_text(json.dumps({"bijgewerkt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
                                "nieuw": [w["id"] for w in nieuw_lijst], "fouten": fouten}, ensure_ascii=False, indent=1))
    print(f"{len(resultaat)} woningen, {len(nieuw_lijst)} nieuw, fouten: {fouten}")


if __name__ == "__main__":
    main()
