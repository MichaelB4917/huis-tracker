import re, requests
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (huis-tracker; persoonlijk overzicht)"}
for u in ["https://www.vindjeplekbijdekey.nl/kopen/amsterdam/amerbos-73-1025xz", "https://www.vindjeplekbijdekey.nl/kopen/amsterdam/blasiusstraat-26-h-1091cs", "https://www.vindjeplekbijdekey.nl/kopen/amsterdam/deymanstraat-28-1091se", "https://www.eigenhaard.nl/te-koop/73032-amsterdam-nieuw-west-boutenburg-233", "https://www.eigenhaard.nl/te-koop/72971-amsterdam-nieuw-west-boutenburg-271", "https://ikzoek.stadgenoot.nl/detail/41402/aardbeistraat-16-amsterdam", "https://ikzoek.stadgenoot.nl/detail/39926/balboaplein-18-amsterdam"]:
    r = requests.get(u, headers=UA, timeout=25)
    s = BeautifulSoup(r.text, "html.parser")
    for t in s(["script","style","svg"]): t.decompose()
    t = re.sub(r"\s+", " ", s.get_text(" "))
    hits = [t[max(0,m.start()-80):m.end()+80] for m in re.finditer(r"(?i)energie|label|EPA", t)]
    print("\n===", u, r.status_code, len(r.text), "bytes; tekstlengte", len(t))
    print(" hits:", hits[:6])
    raw = [r.text[max(0,m.start()-100):m.end()+100] for m in re.finditer(r"(?i)energ", r.text)][:4]
    print(" raw:", raw)
