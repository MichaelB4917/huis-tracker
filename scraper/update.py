"""Dagelijkse update van data/woningen.json.

Haalt het koopaanbod op van de Alliantie (alle pagina's), Lieven de Key, Rochdale en Eigen Haard,
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
    zinnen = [m.group(0) for m in re.finditer(r"[^.\n;]*(erfpacht|canon|eigen grond)[^.\n;]*(?:[.;][^.\n;]*){0,1}", t, re.I)][:4]
    if not zinnen:
        return ""
    alles = " ".join(zinnen)
    if re.search(r"\beigen grond\b", alles, re.I) and not re.search(r"geen eigen grond", alles, re.I):
        return "Eigen grond"
    if re.search(r"eeuwigdurend afgekocht", alles, re.I):
        return "Canon eeuwigdurend afgekocht"
    eind = []
    datum = r"(\d{1,2})[-/ ](\d{1,2}|[a-z]+)[-/ ](\d{4})"
    for m in re.finditer(r"(?:t/m|t\.m\.|tot en met|tot|afgekocht tot|einde)\s+(?:\w+\s+){0,2}" + datum, alles, re.I):
        mnd = int(m[2]) if m[2].isdigit() else MAANDEN.get(m[2].lower())
        if mnd:
            eind.append((int(m[3]), mnd, int(m[1])))
    if eind:
        j, mnd, d = max(eind)
        if j >= dt.date.today().year:
            return f"Canon afgekocht t/m {d:02d}-{mnd:02d}-{j}"
    if re.search(r"voortdurend|jaarlijks|canon bedraagt|canon van", alles, re.I):
        return "Voortdurende erfpacht"
    return "Erfpacht (zie advertentie)"


LABEL_RX = re.compile(r"(?i:\be[a-z]{4,9}label)\s*:?\s*(?:is\s*)?([A-G]\+*)(?![A-Za-z])")  # ook typo's als 'Enegrielabel'


def label_uit(t):
    m = LABEL_RX.search(t)
    return m[1] if m else ""


def num(s):
    s = (s or "").strip().rstrip(".")
    if re.fullmatch(r"\d+\.\d{1,2}", s):  # 232.61 = punt als decimaalteken
        return float(s)
    s = s.replace(".", "").replace(",", ".")
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
            energielabel=label_uit(t), bouwjaar=int(bj) if bj else "",
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
    w["energielabel"] = label_uit(t) or w.get("energielabel", "")
    w["erfpacht"] = erfpacht_kort(t) or w.get("erfpacht", "")


WOORDEN = {"een": 1, "twee": 2, "drie": 3, "vier": 4, "vijf": 5, "zes": 6}


def details_uit_tekst(t):
    """Algemene velden uit de tekst van een advertentie."""
    g = lambda rx: (re.search(rx, t, re.I) or [None, ""])[1].strip()
    m2 = g(r"[Ww]oonoppervlakte[^\d\n]{0,20}(\d+)[,.]?\d*\s*m") or g(r"[Tt]otale oppervlakte\s*\n?\s*(\d+)")
    kamers = g(r"(\d+)[- ]?kamer") or str(WOORDEN.get(g(r"\b(een|twee|drie|vier|vijf|zes)[- ]?kamer").lower(), ""))
    bj = g(r"[Bb]ouwjaar[:\s]*\n?\s*(\d{4})")
    return dict(m2=int(m2) if m2 else "", kamers=int(kamers) if kamers else "", bouwjaar=int(bj) if bj else "",
                energielabel=label_uit(t),
                servicekosten=num(g(r"(?:[Ss]ervicekosten|VvE[- ]bijdrage|bijdrage VvE)[^€\n]{0,60}€\s*([\d.,]+)")),
                erfpacht=erfpacht_kort(t))


# ---------- Rochdale (eigen aanbodpagina) ----------
SPEC_ROCHDALE = "Voorrang voor huurders van Rochdale (zie advertentie) · eigen hoofdbewoning (of kind vanaf 18), verkoop- en verhuurbeperking in de akte"


def rochdale():
    base = "https://www.rochdale.nl"
    seen, out = set(), []
    for p in range(0, 30):
        s = BeautifulSoup(get(f"{base}/aanbod/?view=list&page={p}&size=10&sorting=published-&advertisementType=sale"), "html.parser")
        cards = s.select("article.card")
        nieuw = 0
        for c in cards:
            a = c.select_one('a[href*="/advertentie/detail/"]')
            if not a:
                continue
            href = a["href"].split("?")[0]
            if href in seen:
                continue
            seen.add(href)
            nieuw += 1
            small = re.sub(r"\s+", " ", c.select_one("small").get_text(" ") if c.select_one("small") else "")
            if "AMSTERDAM" not in small.upper() or "Koop" not in small:
                continue
            pc = (re.search(r"(\d{4} ?[A-Z]{2})", small) or [None, ""])[1]
            adres = re.sub(r",\s*AMSTERDAM$", "", (c.select_one("p").get_text(strip=True) if c.select_one("p") else a.get_text(strip=True)), flags=re.I)
            prijs = int(re.sub(r"\D", "", (c.select_one("a.button").get_text() if c.select_one("a.button") else "")) or 0)
            lab = c.get_text(" ").lower()
            status = "verkocht o.v.b." if "verkocht" in lab else "onder bod" if "onder bod" in lab or "optie" in lab else "beschikbaar"
            w = dict(id="rd-" + href.rstrip("/").split("/")[-1][:8], adres=adres.replace(" -", "-"), plaats="Amsterdam",
                     postcode=pc[:4] + " " + pc[-2:] if pc else "", corporatie="Rochdale", prijs=prijs, status=status,
                     voorrangLabel="ja", voorJou="nee", voorrangSpec=SPEC_ROCHDALE, url=base + href, bron="rochdale.nl")
            try:
                t = text_of(get(base + href))
                d = details_uit_tekst(t)
                w.update({k: v for k, v in d.items() if v != ""})
                w["type"] = (re.search(r"(appartement|bovenwoning|benedenwoning|maisonnette|eengezinswoning|tussenwoning|hoekwoning|portiekwoning|galerijflat|portiekflat)", t, re.I) or [None, ""])[1].capitalize()
                w["tuin"] = "ja" if re.search(r"\btuin\b", t, re.I) else "nee"
                time.sleep(0.5)
            except Exception:
                pass
            out.append(w)
        if not nieuw:
            break
    return out


# ---------- Eigen Haard (eigen aanbodpagina) ----------
def eigenhaard():
    base = "https://www.eigenhaard.nl"
    zoek = "/te-koop/zoek?&regions=&prijs_min=0&prijs_max=1000000&straal=0&woningtype=-1&bouwvorm=-1&oppervlakte=-1&kamers=-1&view=List"
    seen, out = set(), []
    for p in range(1, 15):
        s = BeautifulSoup(get(base + zoek + (f"&page={p}" if p > 1 else "")), "html.parser")
        nieuw = 0
        for a in s.select('a[href^="/te-koop/"]'):
            href = a["href"]
            if not re.match(r"/te-koop/\d+-", href) or href in seen or not a.select_one("h3"):
                continue
            seen.add(href)
            nieuw += 1
            info = a.select_one("p").get_text("\n", strip=True) if a.select_one("p") else ""
            if not info.lower().startswith("amsterdam"):
                continue
            m = re.search(r"(\d+)\s*m\s*2?\s*\|\s*(\d+) kamers?\s*\|\s*(\w+)", info.replace("\n", " "))
            labels = " ".join(x.get_text(strip=True).lower() for x in a.select(".label"))
            prijs = int(re.sub(r"\D", "", a.select_one(".extra-large").get_text() if a.select_one(".extra-large") else "") or 0)
            if not m or m[3].lower() == "overig" or int(m[1]) < 20:  # parkeerplaatsen en bergingen overslaan
                continue
            w = dict(id="eh-" + href.split("/")[-1], adres=a.select_one("h3").get_text(strip=True), plaats="Amsterdam",
                     corporatie="Eigen Haard", prijs=prijs, m2=int(m[1]) if m else "", kamers=int(m[2]) if m else "",
                     type=(m[3] if m else "").capitalize(),
                     status="verkocht o.v.b." if "verkocht" in labels else "onder bod" if "bod" in labels or "optie" in labels else "beschikbaar",
                     voorrangLabel="ja", voorJou="mogelijk", url=base + href, bron="eigenhaard.nl")
            try:
                t = text_of(get(base + href))
                d = details_uit_tekst(t)
                w.update({k: v for k, v in d.items() if v != "" and k not in ("m2", "kamers")})
                spec = ["Eerst voor huurders van Eigen Haard"]
                r = re.search(r"gereserveerd voor verkoop aan huurders van Eigen Haard tot (\d{1,2}) (\w+) (\d{4})", t, re.I)
                if r and r[2].lower() in MAANDEN:
                    w["deadline"] = f"{r[3]}-{MAANDEN[r[2].lower()]:02d}-{int(r[1]):02d}"
                    spec[0] += f" (tot {int(r[1])} {r[2].lower()})"
                spec.append("sociale huurders van andere corporaties in de regio kunnen ook voorrang krijgen (vragen bij bezichtiging)")
                if re.search(r"koopgarant", t, re.I):
                    spec.append("Koopgarant: korting met terugkoopregeling, waardeontwikkeling gedeeld")
                ink = re.search(r"maximaal bruto jaarinkomen[^€]{0,40}€\s*([\d.]+)", t, re.I)
                if ink:
                    spec.append(f"max. bruto jaarinkomen € {ink[1].rstrip('.')}")
                w["voorrangSpec"] = " · ".join(spec)
                w["tuin"] = "ja" if re.search(r"\btuin\b", t, re.I) else "nee"
                time.sleep(0.5)
            except Exception:
                w["voorrangSpec"] = "Eerst voor huurders van Eigen Haard; andere sociale huurders mogelijk voorrang"
            out.append(w)
        if not nieuw:
            break
    return out


def adres_sleutel(adres):
    """'Eerste Constantijn Huygensstraat 54 F' en '1e Constantijn Huygensstraat 54-f' -> zelfde sleutel."""
    a = adres.lower().replace("eerste ", "1e ").replace("tweede ", "2e ").replace("derde ", "3e ")
    a = re.sub(r"\b(huis|hs|h)\b$", "h", a)
    return re.sub(r"[^a-z0-9]", "", a)


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
    for naam, fn in (("Alliantie", alliantie), ("Lieven de Key", dekey), ("Rochdale", rochdale), ("Eigen Haard", eigenhaard)):
        try:
            rows = fn()
            if not rows:
                raise RuntimeError("geen woningen gevonden (site veranderd?)")
            gescraped[naam] = rows
        except Exception as e:  # bron tijdelijk stuk: bestaande woningen laten staan
            fouten.append(f"{naam}: {e}")
    # Woningen uit de Funda-mail blijven staan, tenzij dezelfde woning ook op de eigen site van de corporatie staat
    gescraped_adressen = {adres_sleutel(r["adres"]) for rows in gescraped.values() for r in rows}
    resultaat = [w for w in oud if w["corporatie"] not in gescraped
                 or (str(w.get("bron", "")).lower().startswith("funda") and adres_sleutel(w["adres"]) not in gescraped_adressen)]
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
                         erfpacht="", deadline="")
                w.update({k: v for k, v in r.items() if v != "" or k not in w})
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
