import re, requests
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (huis-tracker; persoonlijk overzicht)"}
URLS = [
 "https://www.rochdale.nl/woning-zoeken/koop/",
 "https://www.rochdale.nl/woning-zoeken/koop/koopvoorrang-voor-huurders/",
 "https://www.ymere.nl/ik-zoek/een-woning-van-ons-kopen/",
 "https://www.ymere.nl/ik-zoek/een-woning-van-ons-kopen/een-woning-van-ons-kopen-met-voorrang/",
 "https://www.eigenhaard.nl/te-koop/",
 "https://www.eigenhaard.nl/te-koop/voorrang-op-een-koopwoning/",
 "https://mva.nl/koop/woningen",
 "https://www.vanderlinden.nl/aanbod/",
 "https://www.openbaremakelaardij.nl/",
 "https://www.openbaremakelaardij.nl/aanbod/",
]
for u in URLS:
    try:
        r = requests.get(u, headers=UA, timeout=25, allow_redirects=True)
        s = BeautifulSoup(r.text, "html.parser")
        t = (s.title.get_text(strip=True) if s.title else "")[:80]
        links = sorted({a["href"] for a in s.select("a[href]") if re.search(r"koop|te-koop|aanbod|woning", a["href"], re.I)})
        txt = re.sub(r"\s+", " ", s.get_text(" "))
        print(f"\n=== {u}\n status {r.status_code} -> {r.url} | {len(r.text)} bytes | title: {t}")
        print(" scripts:", len(s.select("script")), "| api-hints:", sorted(set(re.findall(r"https?://[^\"' ]*(?:api|graphql|json)[^\"' ]*", r.text)))[:8])
        print(" links:", links[:40])
        print(" tekst:", txt[:700])
    except Exception as e:
        print(f"\n=== {u}\n FOUT {e}")
