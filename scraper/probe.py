import sys, json, time
sys.path.insert(0, "scraper")
import update as u
for fn in (u.rochdale, u.eigenhaard):
    t = time.time()
    rows = fn()
    print(f"\n=== {fn.__name__}: {len(rows)} woningen in {time.time()-t:.0f}s")
    for r in rows: print(json.dumps(r, ensure_ascii=False))
