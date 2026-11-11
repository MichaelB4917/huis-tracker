"""Verrijkt data/woningen.json na de dagelijkse update.

Elk onderdeel staat los: als één bron faalt, gaan de andere gewoon door.
1. Historie   -> data/historie.json (status/prijs per datum, offline-detectie)
2. Buurt-WOZ  -> data/buurten.json + velden buurtcode/buurt/buurtWozM2 (api.data.amsterdam.nl, BBGA)
3. Energielabel uit EP-Online (alleen als de woning nog geen label heeft; secret EP_ONLINE_KEY)
4. Funderingsindicatie per postcode (PDOK / KCAF, indicatief)
"""
import datetime as dt
import json
import os
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

from update import MAANDEN, details_uit_tekst, label_uit, text_of

ROOT = pathlib.Path(__file__).resolve().parents[1]
D = ROOT / "data"
TODAY = dt.date.today().isoformat()
UA = {"User-Agent": "huis-tracker (persoonlijk overzicht corporatiewoningen)"}
AMS = "https://api.data.amsterdam.nl/v1"
AMS_H = dict(UA, **({"X-Api-Key": os.environ["AMS_API_KEY"]} if os.environ.get("AMS_API_KEY") else {}))
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    print(s, flush=True)


def jget(url, params=None, headers=UA, tries=2):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=(10, 40))
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            err = e
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"{url}: {err}")


def load(name, default):
    p = D / name
    return json.loads(p.read_text()) if p.exists() else default


def save(name, data, indent=1):
    (D / name).write_text(json.dumps(data, ensure_ascii=False, indent=indent))


# ---------- 0. Stadgenoot-status: komt via mail binnen, dus hier dagelijks de detailpagina controleren ----------
def stadgenoot_status(W):
    weg, gewijzigd = [], 0
    for w in W:
        if w.get("corporatie") != "Stadgenoot" or "stadgenoot.nl/detail" not in w.get("url", ""):
            continue
        try:
            r = requests.get(w["url"], headers=UA, timeout=30)
            t = text_of(r.text) if r.ok else ""
        except Exception as e:
            log("stadgenoot status mislukt:", w["adres"], str(e)[:60])
            continue
        if r.status_code == 404 or "opgevraagde pagina bestaat niet" in t:
            w["sgMis"] = w.get("sgMis", 0) + 1
            if w["sgMis"] >= 2:  # twee dagen achter elkaar weg: echt offline (niet bij een storing)
                weg.append(w)
            continue
        if not r.ok:
            continue
        w.pop("sgMis", None)
        m = re.search(r"\b(Verkocht onder voorbehoud|Verkocht|Onder bod|In optie|Optie|Te koop)\b", t)
        status = {"Verkocht onder voorbehoud": "verkocht o.v.b.", "Verkocht": "verkocht o.v.b.", "Onder bod": "onder bod", "In optie": "onder bod", "Optie": "onder bod", "Te koop": "beschikbaar"}.get(m[1] if m else "", "")
        if status and status != w.get("status"):
            w["status"] = status
            gewijzigd += 1
        w["gezienOp"] = TODAY
        time.sleep(0.3)
    for w in weg:
        W.remove(w)
    log(f"stadgenoot-status: {gewijzigd} status gewijzigd, {len(weg)} offline")


# ---------- 0b. Funda-woningen (Ymere): status niet te volgen, dus na FUNDA_DAGEN offline met uitkomst 'onbekend' ----------
FUNDA_DAGEN = 21


def funda_verlopen(W):
    grens = (dt.date.today() - dt.timedelta(days=FUNDA_DAGEN)).isoformat()
    weg = [w for w in W if str(w.get("bron", "")).lower().startswith("funda") and (w.get("eerstGezien") or TODAY) <= grens]
    for w in weg:
        W.remove(w)
    log(f"funda: {len(weg)} woningen na {FUNDA_DAGEN} dagen offline gezet (status onbekend)")


# ---------- 1. Historie ----------
def historie(W):
    H = load("historie.json", {})
    nu = {w["id"]: w for w in W}
    for id_, w in nu.items():
        h = H.get(id_)
        punt = {"d": TODAY, "status": w.get("status", ""), "prijs": w.get("prijs", "")}
        if not h:
            H[id_] = {"adres": w["adres"], "corporatie": w["corporatie"], "eerstGezien": w.get("eerstGezien") or TODAY,
                      "offline": "", "log": [punt]}
            continue
        if h.get("offline"):
            h["offline"] = ""
            h["log"].append(dict(punt, status="weer online: " + punt["status"]))
            continue
        laatst = h["log"][-1]
        if laatst.get("status") != punt["status"] or laatst.get("prijs") != punt["prijs"]:
            h["log"].append(punt)
    for id_, h in H.items():
        if id_ not in nu and not h.get("offline"):
            h["offline"] = TODAY
            h["log"].append({"d": TODAY, "status": "offline", "prijs": h["log"][-1].get("prijs", "")})
    save("historie.json", H)
    log(f"historie: {len(H)} woningen, {sum(1 for h in H.values() if h.get('offline'))} offline")


# ---------- 2. Buurt-WOZ ----------
# BBGA heeft geen WOZ per m². Schatting: gemiddelde WOZ-waarde van de buurt gedeeld door het gemiddelde
# woonoppervlak, geschat uit de oppervlakteklassen (midden van elke klasse).
KLASSEN = {"WOPP0040": 32, "WOPP4060": 50, "WOPP6080": 70, "WOPP80100": 90, "WOPP100PLUS": 125}


def laatste_jaar(var):
    j = jget(f"{AMS}/bbga/kerncijfers/", {"indicatorDefinitie.variabele": var, "gebiedcode15": "AD05", "_format": "json"}, AMS_H)
    return max(k["jaar"] for k in j["_embedded"]["kerncijfers"] if k.get("waarde") is not None)


def bbga_alle(var, jaar):
    """Alle kerncijfers van één indicator voor één jaar: {gebiedcode: (jaar, waarde)}."""
    out, url, params = {}, f"{AMS}/bbga/kerncijfers/", {"indicatorDefinitie.variabele": var, "jaar": jaar, "_pageSize": 1000, "_format": "json"}
    pages = 0
    while url and pages < 20:
        pages += 1
        t = time.time()
        j = jget(url, params, AMS_H)
        log(f"  bbga {var} {jaar} pagina {pages}: {len(j['_embedded']['kerncijfers'])} records, {time.time() - t:.1f}s")
        for k in j["_embedded"]["kerncijfers"]:
            if k.get("waarde") is None:
                continue
            c = k["gebiedcode15"]
            if c not in out or k["jaar"] > out[c][0]:
                out[c] = (k["jaar"], float(k["waarde"]))
        url, params = (j.get("_links", {}).get("next") or {}).get("href"), None
    return out


def buurten_cbs():
    """Alle actuele Amsterdamse buurten: {CBS-buurtcode: (Amsterdamse code, naam)}."""
    out, url, params = {}, f"{AMS}/gebieden/buurten/", {"_format": "json", "_pageSize": 2000, "_fields": "code,naam,cbsCode,eindGeldigheid"}
    while url:
        j = jget(url, params, AMS_H)
        for b in j["_embedded"]["buurten"]:
            if not b.get("eindGeldigheid") and b.get("cbsCode"):
                out[b["cbsCode"]] = (b["code"], b["naam"])
        url, params = (j.get("_links", {}).get("next") or {}).get("href"), None
    return out


def cbs_buurt(w):
    """CBS-buurtcode van een adres via de PDOK Locatieserver."""
    q = f"{w['adres']} {w.get('postcode', '')} Amsterdam".strip()
    j = jget("https://api.pdok.nl/bzk/locatieserver/search/v3_1/free", {"q": q, "fq": "type:adres", "rows": 1, "fl": "buurtcode"})
    docs = (j or {}).get("response", {}).get("docs", [])
    return docs[0].get("buurtcode", "") if docs else ""


def buurt_woz(W):
    B = load("buurten.json", {})
    # buurtcijfers maandelijks verversen (komen jaarlijks uit)
    if not B.get("_bijgewerkt") or B["_bijgewerkt"][:7] != TODAY[:7]:
        jaar = laatste_jaar("WWOZ_GEM")
        woz = bbga_alle("WWOZ_GEM", jaar)
        kj = laatste_jaar("WOPP0040")
        klassen = {v: bbga_alle(v, kj) for v in KLASSEN}
        n = 0
        for code, (jaar, w) in woz.items():
            tot = sum(klassen[v].get(code, (0, 0))[1] for v in KLASSEN)
            if tot <= 0:
                continue
            m2 = sum(klassen[v].get(code, (0, 0))[1] * mid for v, mid in KLASSEN.items()) / tot
            B[code] = dict(B.get(code, {}), woz=round(w), jaar=jaar, m2=round(m2), wozM2=round(w / m2))
            n += 1
        B["_bijgewerkt"] = TODAY
        log(f"buurt-WOZ: {n} gebieden met WOZ/m²-schatting (WOZ-jaar {max((j for j, _ in woz.values()), default='?')})")
    nieuw, start, cbs = 0, time.time(), None
    for w in W:
        if not w.get("buurtcode") and time.time() - start < 240:
            try:
                if cbs is None:
                    cbs = buurten_cbs()
                    log(f"buurt-WOZ: {len(cbs)} Amsterdamse buurten met CBS-code")
                r = cbs.get(cbs_buurt(w))
            except Exception as e:
                log("buurt opzoeken mislukt:", w["adres"], e)
                continue
            if not r:
                continue
            w["buurtcode"], w["buurt"] = r
            nieuw += 1
        b = B.get(w.get("buurtcode", ""))
        if b and b.get("wozM2"):
            w["buurtWozM2"], w["buurtWozJaar"] = b["wozM2"], b["jaar"]
    save("buurten.json", B)
    log(f"buurt-WOZ: {nieuw} woningen nieuw aan buurt gekoppeld, {sum(1 for w in W if w.get('buurtWozM2'))} met buurtwaarde")


# ---------- 3. Energielabel (EP-Online) ----------
def adres_delen(adres):
    """'Bilderdijkstraat 176-3' -> (176, '3'); 'Huygensstraat 54 F' -> (54, 'F'); 'Kade 263-C' -> (263, 'C')."""
    m = re.search(r"\s(\d+)\s*(?:-\s*|\s+)?([A-Za-z0-9]{0,6})\s*$", adres)
    return (int(m[1]), m[2].upper()) if m else (None, "")


def ep_label(W):
    key = os.environ.get("EP_ONLINE_KEY")
    if not key:
        log("energielabel: geen EP_ONLINE_KEY ingesteld, overgeslagen")
        return
    url = "https://public.ep-online.nl/api/v5/PandEnergielabel/Adres"
    H = dict(UA, Authorization=key)
    gevonden = 0
    for w in W:
        if w.get("energielabel") or w.get("labelGezocht") == TODAY[:7] or not w.get("postcode"):
            continue
        nr, toev = adres_delen(w["adres"])
        if not nr:
            continue
        pc = w["postcode"].replace(" ", "").upper()
        pogingen = []
        if toev:
            if re.fullmatch(r"[A-Z]", toev):
                pogingen.append({"huisletter": toev})
            pogingen.append({"huisnummertoevoeging": toev})
        pogingen.append({})
        label = None
        for extra in pogingen:
            try:
                j = jget(url, dict(postcode=pc, huisnummer=nr, **extra), H)
            except Exception as e:
                log("energielabel fout:", w["adres"], e)
                j = None
            rs = j if isinstance(j, list) else []
            klassen = {r.get("Energieklasse") or r.get("energieklasse") for r in rs} - {None, ""}
            if len(klassen) == 1:
                r = max(rs, key=lambda r: r.get("Registratiedatum") or r.get("registratiedatum") or "")
                label = (r.get("Energieklasse") or r.get("energieklasse"), (r.get("Geldig_tot") or r.get("geldig_tot") or "")[:10])
                break
            time.sleep(0.3)
        w["labelGezocht"] = TODAY[:7]
        if label:
            w["energielabel"], w["labelBron"], w["labelGeldigTot"] = label[0], "EP-Online", label[1]
            gevonden += 1
    log(f"energielabel: {gevonden} labels gevonden via EP-Online")


# ---------- 3b. Stadgenoot-details (de aanbodmail heeft geen label/bouwjaar; de detailpagina wel) ----------
def stadgenoot_details(W):
    n = 0
    for w in W:
        if w.get("corporatie") != "Stadgenoot" or "stadgenoot.nl/detail" not in w.get("url", "") or w.get("sgDetail"):
            continue
        try:
            r = requests.get(w["url"], headers=UA, timeout=30)
            r.raise_for_status()
        except Exception as e:
            log("stadgenoot detail mislukt:", w["adres"], e)
            continue
        s = BeautifulSoup(r.text, "html.parser")
        kv = {}
        for dl in s.select("dl"):
            for dt in dl.select("dt"):
                dd = dt.find_next_sibling("dd")
                if dd:
                    img = dd.select_one("img[alt]")
                    kv[dt.get_text(" ", strip=True).rstrip(":").lower()] = img["alt"] if img else dd.get_text(" ", strip=True)
        t = text_of(r.text)
        d = details_uit_tekst(t)
        lbl = kv.get("energielabel", "") or label_uit(t)
        if re.fullmatch(r"[A-G]\+*", lbl or ""):
            w["energielabel"], w["labelBron"] = lbl, "advertentie"
        for k in ("bouwjaar", "servicekosten", "erfpacht"):
            if not w.get(k) and d.get(k) != "":
                w[k] = d[k]
        for key, val in kv.items():
            if "bouwjaar" in key and not w.get("bouwjaar") and re.search(r"\d{4}", val):
                w["bouwjaar"] = int(re.search(r"\d{4}", val)[0])
        m = re.search(r"sluitingsdatum[^.]{0,60}?(\d{1,2}) (\w+)(?: (\d{4}))?", t, re.I)
        if m and m[2].lower() in MAANDEN:
            mnd = MAANDEN[m[2].lower()]
            jaar = int(m[3]) if m[3] else (int(TODAY[:4]) + (1 if mnd < int(TODAY[5:7]) - 2 else 0))
            w["deadline"] = f"{jaar}-{mnd:02d}-{int(m[1]):02d}"
        w["sgDetail"] = TODAY
        n += 1
        time.sleep(0.5)
    log(f"stadgenoot: {n} detailpagina's gelezen")


# ---------- 3c. Eerste foto (alleen de link naar de foto op de site van de corporatie, niets gekopieerd) ----------
def foto_klein(u):
    u = re.sub(r"([?&])width=\d+", r"\g<1>width=480", u)
    u = re.sub(r"([?&])height=\d+", r"\g<1>height=320", u)
    u = re.sub(r"/Crop/([^/]+)/\d+/\d+", r"/Crop/\1/480/320", u)
    u = re.sub(r"([?&])h=\d+", r"\g<1>h=320", u)
    return u


def fotos(W):
    from urllib.parse import urljoin
    n, start = 0, time.time()
    for w in W:
        if w.get("foto") or w.get("fotoGezocht") == TODAY[:7] or not w.get("url") or "funda.nl" in w["url"]:
            continue
        if time.time() - start > 240:
            log("foto's: tijdslimiet, rest volgende keer")
            break
        w["fotoGezocht"] = TODAY[:7]
        try:
            r = requests.get(w["url"], headers=UA, timeout=30)
            r.raise_for_status()
        except Exception as e:
            log("foto ophalen mislukt:", w["adres"], e)
            continue
        s = BeautifulSoup(r.text, "html.parser")
        src = ""
        eigen = s.select_one('img[src*="property_image"], img[data-src*="property_image"]')  # Eigen Haard: woningfoto
        if eigen:
            src = eigen.get("src") or eigen.get("data-src")
        for sel in (() if src else ('meta[property="og:image"]', 'meta[name="og:image"]', 'meta[name="twitter:image"]')):
            m = s.select_one(sel)
            if m and m.get("content") and not re.search(r"logo|icon|default", m["content"], re.I):
                src = m["content"]
                break
        if not src:
            for img in s.select("img[src]"):
                c = img["src"]
                if re.search(r"logo|icon|sprite|\.svg|avatar|placeholder|energielabel", c, re.I):
                    continue
                if re.search(r"\.(jpe?g|png|webp)|/Crop/|/media/|image", c, re.I):
                    src = c
                    break
        if src:
            w["foto"] = foto_klein(urljoin(w["url"], src))
            n += 1
        time.sleep(0.3)
    # Dezelfde foto bij veel woningen is een algemene sitefoto, geen woningfoto
    from collections import Counter
    vaak = {u for u, k in Counter(w.get("foto") for w in W if w.get("foto")).items() if k > 2}
    for w in W:
        if w.get("foto") in vaak:
            w.pop("foto")
    log(f"foto's: {n} gevonden, {sum(1 for w in W if w.get('foto'))} van {len(W)} woningen met foto")


# ---------- 3d. Buitenruimte (balkon / terras / tuin) uit de advertentietekst ----------
LABELS_BUITEN = r"(buitenruimte|balkon|tuin|terras|dakterras|loggia|tuinligging|ligging tuin|achtertuin|voortuin)"


BUITEN_VERSIE = 2  # ophogen als de herkenning verandert: dan worden alle advertenties opnieuw gelezen


def buiten_uit_tekst(t):
    """Geeft een lijst met 'balkon', 'terras', 'tuin' die echt bij de woning horen."""
    regels = [r.strip() for r in t.split("\n") if r.strip()]
    stukken = []
    for i, r in enumerate(regels):
        if len(r) >= 40:
            stukken.append(r)  # lopende tekst van de omschrijving
        elif re.fullmatch(LABELS_BUITEN + r":?", r, re.I) and i + 1 < len(regels) and len(regels[i + 1]) < 40:
            stukken.append(f"{r.rstrip(':')}: {regels[i + 1]}")  # kenmerk + waarde, bijv. "Buitenruimte: Balkon"
    x = " \n ".join(stukken).lower()
    # zinnen over de buurt (cafés, markten) gaan niet over de woning zelf
    x = " . ".join(z for z in re.split(r"(?<=[.!?])\s+|\n", x) if not re.search(r"caf[eé]|restaurant|horeca|borrel|terrasje|markt|winkel|park\b", z))
    x = re.sub(r"\b(balkon|tuin|terras|dakterras)\w*[^.]{0,40}\b(behoort|hoort|horen|behoren) niet\b", " ", x)
    x = re.sub(r"\b(beschikt|heeft)\s+niet\s+over\s+(een\s+)?(eigen\s+)?(buitenruimte|balkon|tuin|terras)", " ", x)
    x = re.sub(r"\bfranse?\s+balkon(s|netje|netjes)?\b", " ", x)
    x = re.sub(r"\bgeen\s+(eigen\s+|privé\s+)?(buitenruimte|balkon|tuin|terras|dakterras)\b", " ", x)
    x = re.sub(r"\b(balkon|tuin|terras|dakterras|loggia)\s*:\s*(nee|geen|-)\b", " ", x)
    x = re.sub(r"\bgemeenschappelijke?\s+(binnen|achter|daktuin|dak)?\s*(tuin|terras|binnentuin)\w*", " ", x)
    uit = []
    if re.search(r"\b(balkons?|loggia'?s?|zonnebalkon|balkon(?:\s+op|\s+aan|\s+met))\b", x):
        uit.append("balkon")
    if re.search(r"\b(dak|zonne|eigen\s+)?terras\b", x):
        uit.append("terras")
    if re.search(r"\b(achter|voor|zij|stads|eigen\s+)?tuin(en|tje)?\b", x) or re.search(r"\b(achter|voor)tuin\b", x):
        uit.append("tuin")
    return uit


def buitenruimte(W):
    n, start = 0, time.time()
    for w in W:
        if w.get("buitenGezocht") == BUITEN_VERSIE or not w.get("url") or "funda.nl" in w["url"]:
            continue
        if time.time() - start > 240:
            log("buitenruimte: tijdslimiet, rest volgende keer")
            break
        w["buitenGezocht"] = BUITEN_VERSIE
        try:
            r = requests.get(w["url"], headers=dict(UA, **{"Accept-Language": "nl"}), timeout=30)
            r.raise_for_status()
        except Exception as e:
            log("buitenruimte ophalen mislukt:", w["adres"], str(e)[:80])
            continue
        w["buiten"] = buiten_uit_tekst(text_of(r.text))
        w["tuin"] = "ja" if "tuin" in w["buiten"] else "nee"
        n += 1
        time.sleep(0.3)
    from collections import Counter
    c = Counter(b for w in W for b in w.get("buiten", []))
    log(f"buitenruimte: {n} advertenties gelezen · balkon {c['balkon']}, terras {c['terras']}, tuin {c['tuin']}, geen {sum(1 for w in W if 'buiten' in w and not w['buiten'])}")


# ---------- 4. Funderingsindicatie (KCAF, per postcode) ----------
def fundering(W):
    url = "https://api.pdok.nl/rvo/indicatieve-aandachtsgebieden-funderingsproblematiek/ogc/v1/collections/indgebfunderingsproblematiek/items"
    n, start = 0, time.time()
    for w in W:
        if time.time() - start > 180:
            log("fundering: tijdslimiet, rest volgende keer")
            break
        pc = (w.get("postcode") or "").replace(" ", "").upper()
        if not re.fullmatch(r"\d{4}[A-Z]{2}", pc) or w.get("funderingPc") == pc:
            continue
        j = jget(url, {"f": "json", "pc6": pc, "limit": 5})
        fs = [f["properties"] for f in (j or {}).get("features", []) if f.get("properties", {}).get("pc6") == pc]
        w["funderingPc"] = pc
        if fs:
            p = fs[0]
            w["fundering"] = p.get("legenda", "")
            w["funderingVoor1970"] = p.get("percvoor1970", "")
            w["funderingBodem"] = p.get("fgr", "")
            n += 1
        else:
            w["fundering"] = ""
        time.sleep(0.2)
    log(f"fundering: {n} postcodes opgezocht")


# ---------- 5. Archief: elke woning ooit gezien, met alle gegevens en afgeleide doorlooptijden ----------
WEG_UIT_ARCHIEF = {"fotoGezocht", "buitenGezocht", "sgDetail", "funderingPc", "gezienOp"}


def _dagen(a, b):
    try:
        return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
    except Exception:
        return ""


def archief(W):
    A = load("archief.json", {})
    H = load("historie.json", {})
    nu = {w["id"]: w for w in W}
    for id_, w in nu.items():
        rec = A.get(id_, {})
        rec.update({k: v for k, v in w.items() if k not in WEG_UIT_ARCHIEF})
        rec["laatstGezien"] = TODAY
        A[id_] = rec
    for id_, h in H.items():  # woningen van voor het archief, alleen uit de historie bekend
        if id_ not in A:
            A[id_] = {"id": id_, "adres": h.get("adres", ""), "corporatie": h.get("corporatie", ""), "eerstGezien": h.get("eerstGezien", "")}
    for id_, rec in A.items():
        h = H.get(id_, {})
        lg = [x for x in h.get("log", []) if not str(x.get("status", "")).startswith("weer online")]
        rec["actief"] = id_ in nu
        rec["offline"] = "" if rec["actief"] else (h.get("offline") or rec.get("offline") or rec.get("laatstGezien", ""))
        start = rec.get("eerstGezien") or (lg[0]["d"] if lg else "")
        rec["voorTracker"] = bool(rec.get("basis"))  # stond er al voor 8 nov 2026: doorlooptijden onbekend
        statussen = [x for x in lg if x.get("status") != "offline"]
        laatste = statussen[-1]["status"] if statussen else rec.get("status", "")
        funda = str(rec.get("bron", "")).lower().startswith("funda")
        rec["statusOnbekend"] = funda
        rec["uitkomst"] = "actief" if rec["actief"] else "onbekend" if funda else ("verkocht o.v.b." if laatste == "verkocht o.v.b." else "onder bod" if laatste == "onder bod" else "offline")
        eind = TODAY if rec["actief"] else rec["offline"]
        rec["dagenOnline"] = _dagen(start, eind)
        bod = next((x["d"] for x in statussen if x.get("status") in ("onder bod", "verkocht o.v.b.")), "")
        verk = next((x["d"] for x in statussen if x.get("status") == "verkocht o.v.b."), "")
        # verdwijnt een woning zonder dat we 'onder bod' zagen, dan telt de offline-datum als moment van verkoop
        if funda:
            bod = verk = ""
        elif not bod and not rec["actief"]:
            bod = rec["offline"]
        rec["bodOp"], rec["verkochtOp"] = bod, verk
        rec["dagenTotBod"] = _dagen(start, bod) if bod and not rec["voorTracker"] else ""
        rec["dagenTotVerkocht"] = _dagen(start, verk) if verk and not rec["voorTracker"] else ""
        prijzen = [x["prijs"] for x in lg if isinstance(x.get("prijs"), (int, float)) and x["prijs"]]
        rec["prijsStart"] = prijzen[0] if prijzen else rec.get("prijs", "")
        rec["prijsEind"] = prijzen[-1] if prijzen else rec.get("prijs", "")
        rec["prijsWijzigingen"] = sum(1 for a, b in zip(prijzen, prijzen[1:]) if a != b)
        pl = [x for x in lg if isinstance(x.get("prijs"), (int, float)) and x["prijs"]]
        eerste_daling = next((b["d"] for a, b in zip(pl, pl[1:]) if b["prijs"] < a["prijs"]), "")
        rec["verlagingen"] = sum(1 for a, b in zip(prijzen, prijzen[1:]) if b < a)
        rec["verlaagdOp"] = eerste_daling
        rec["dagenTotVerlaging"] = _dagen(start, eerste_daling) if eerste_daling and not rec["voorTracker"] else ""
        ps, pe = rec["prijsStart"], rec["prijsEind"]
        rec["prijsVerschil"] = pe - ps if isinstance(ps, (int, float)) and isinstance(pe, (int, float)) and ps and pe else ""
        rec["prijsVerschilPct"] = round((pe - ps) / ps * 100, 1) if rec["prijsVerschil"] != "" else ""
        rec["terugBeschikbaar"] = sum(1 for a, b in zip(statussen, statussen[1:]) if a.get("status") != "beschikbaar" and b.get("status") == "beschikbaar")
        dl = rec.get("deadline", "")
        rec["bodInVoorrang"] = (bod <= dl) if bod and dl and not rec["voorTracker"] else ""
        m2 = rec.get("m2")
        rec["ppm2"] = round(rec["prijsEind"] / m2) if isinstance(m2, (int, float)) and m2 and isinstance(rec["prijsEind"], (int, float)) and rec["prijsEind"] else ""
        rec["log"] = h.get("log", [])
    save("archief.json", A, indent=None)
    log(f"archief: {len(A)} woningen, {sum(1 for r in A.values() if not r['actief'])} niet meer online")


def main():
    W = json.loads((D / "woningen.json").read_text())
    for naam, fn in (("stadgenoot-status", stadgenoot_status), ("funda", funda_verlopen), ("historie", historie), ("buurt-WOZ", buurt_woz), ("stadgenoot", stadgenoot_details), ("fotos", fotos), ("buitenruimte", buitenruimte), ("energielabel", ep_label), ("fundering", fundering), ("archief", archief)):
        t = time.time()
        try:
            fn(W)
            log(f"{naam}: klaar in {time.time() - t:.0f}s")
        except Exception as e:
            log(f"{naam} mislukt: {e}")
    (D / "woningen.json").write_text(json.dumps(W, ensure_ascii=False, indent=1))
    meta = load("meta.json", {})
    meta["verrijking"] = LOG[-24:]
    save("meta.json", meta)


if __name__ == "__main__":
    main()
