import re, requests
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (huis-tracker; persoonlijk overzicht)"}
def txt(h):
    s = BeautifulSoup(h, "html.parser")
    for t in s(["script", "style", "svg"]): t.decompose()
    return re.sub(r"[ \t]+", " ", s.get_text("\n"))
u = "https://www.rochdale.nl/aanbod/?view=list&page=1&size=10&sorting=published-&advertisementType=sale"
h = requests.get(u, headers=UA, timeout=25).text
s = BeautifulSoup(h, "html.parser")
a = s.select_one('a[href*="/advertentie/detail/"]')
card = a
for _ in range(6):
    if card.parent: card = card.parent
    if len(str(card)) > 1500: break
print("=== ROCHDALE CARD HTML\n", str(card)[:3500])
print("aantal detail links", len({x['href'].split('?')[0] for x in s.select('a[href*="/advertentie/detail/"]')}))
print("pagina-links", sorted({x['href'] for x in s.select('a[href*="page="]')})[:10])
d = "https://www.rochdale.nl" + a["href"].split("?")[0]
t = txt(requests.get(d, headers=UA, timeout=25).text)
i = t.find("Type"); print("\n=== ROCHDALE DETAIL", d, "\n", re.sub(r"\n\s*\n+", "\n", t)[:6000])
u = "https://www.eigenhaard.nl/te-koop/zoek?&regions=&prijs_min=0&prijs_max=1000000&straal=0&woningtype=-1&bouwvorm=-1&oppervlakte=-1&kamers=-1&view=List"
s = BeautifulSoup(requests.get(u, headers=UA, timeout=25).text, "html.parser")
a = s.select_one('a[href*="/te-koop/7"]'); card = a
for _ in range(6):
    if card.parent: card = card.parent
    if len(str(card)) > 1200: break
print("\n=== EH CARD HTML\n", str(card)[:3000])
t = txt(requests.get("https://www.eigenhaard.nl/te-koop/72861-amstelveen-suze-groeneweglaan-187", headers=UA, timeout=25).text)
i = t.find("Te koop\n"); print("\n=== EH DETAIL 2\n", re.sub(r"\n\s*\n+", "\n", t)[t.find('Terug naar zoeken'):][:3500])
