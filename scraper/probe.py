import re, requests, collections, io
from urllib.parse import urljoin
UA = {"User-Agent": "Mozilla/5.0"}
for base in ["https://www.mijndak.nl/", "https://amsterdam.mijndak.nl/"]:
    try:
        h = requests.get(base, headers=UA, timeout=25).text
    except Exception as e:
        print(base, e); continue
    css = re.findall(r'<link[^>]+href="([^"]+\.css[^"]*)"', h) + re.findall(r'src="([^"]+\.js[^"]*)"', h)[:3]
    print("\n===", base, len(h), "css/js:", css)
    txt = h
    for c in css[:8]:
        try: txt += requests.get(urljoin(base, c), headers=UA, timeout=25).text
        except Exception as e: print("fout", c, e)
    cnt = collections.Counter(x.lower() for x in re.findall(r"#[0-9a-fA-F]{6}\b", txt))
    print(" kleuren:", cnt.most_common(25))
    print(" rgb:", collections.Counter(re.findall(r"rgba?\([^)]*\)", txt)).most_common(10))
    print(" vars:", sorted(set(re.findall(r"--[a-z0-9-]*(?:primary|brand|main|accent|secondary)[a-z0-9-]*\s*:\s*[^;]+", txt, re.I)))[:30])
    print(" fonts:", collections.Counter(re.findall(r"font-family\s*:\s*([^;}]+)", txt)).most_common(6))
    print(" imgs:", re.findall(r'src="([^"]+\.(?:png|svg|jpg))"', h)[:10])
from PIL import Image
for u in ["https://www.mijndak.nl/img/DAK-logo.png"]:
    try:
        im = Image.open(io.BytesIO(requests.get(u, headers=UA, timeout=25).content)).convert("RGBA")
        px = [p[:3] for p in im.getdata() if p[3] > 200]
        q = collections.Counter('#%02x%02x%02x' % (r//8*8, g//8*8, b//8*8) for r, g, b in px)
        print("\nLOGO", im.size, q.most_common(8))
    except Exception as e: print("logo fout", e)
