import re, json, requests
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (huis-tracker; persoonlijk overzicht)"}
def show(u, n=2500):
    r = requests.get(u, headers=UA, timeout=25)
    s = BeautifulSoup(r.text, "html.parser")
    for t in s(["script", "style", "svg"]): t.decompose()
    print(f"\n=== {u}\n status {r.status_code} -> {r.url} | {len(r.text)} bytes")
    print(" links:", sorted({a['href'] for a in s.select('a[href]') if re.search(r'koop|aanbod', a['href'], re.I)})[:60])
    print(" tekst:", re.sub(r"\s+", " ", s.get_text(" "))[:n])
    return r
r = requests.get("https://www.rochdale.nl/aanbod-koopwoningen/", headers=UA, timeout=25)
print("ROCHDALE RAW HINTS", sorted(set(re.findall(r"https?://[^\"' <>]+", r.text)))[:80])
show("https://www.rochdale.nl/aanbod-koopwoningen/", 3000)
show("https://www.eigenhaard.nl/te-koop/zoek?&regions=&prijs_min=0&prijs_max=1000000&straal=0&woningtype=-1&bouwvorm=-1&oppervlakte=-1&kamers=-1&view=List", 3000)
show("https://www.eigenhaard.nl/te-koop/72648-amsterdam-oost-solostraat-93", 4000)
try:
    j = requests.get("https://cell01.data.marketsuite.nl/api/cms/properties?page=1", headers=UA, timeout=25)
    print("\n=== MVA API", j.status_code, j.text[:3000])
except Exception as e: print("MVA API fout", e)
r = requests.get("https://mva.nl/koop/woningen", headers=UA, timeout=25)
for kw in ["Rochdale", "Ymere", "Eigen Haard", "Stadgenoot", "voorrang", "sociale huur"]:
    print("MVA bevat", kw, r.text.count(kw))
i = r.text.find("Rochdale"); print("MVA ctx:", r.text[max(0,i-1500):i+500] if i>0 else "-")
