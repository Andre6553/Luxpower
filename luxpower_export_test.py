from pathlib import Path
import requests

ENV = Path(__file__).resolve().parent / ".env"
cfg = {k.strip().lower(): v.strip() for k, v in (l.split("=", 1) for l in ENV.read_text().splitlines() if "=" in l)}
s = requests.Session()
b = "https://af.luxpowertek.com"
h = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Accept": "application/json"}
s.post(b + "/WManage/api/login", data={"account": cfg["username"], "password": cfg["password"], "language": "ENGLISH"}, headers=h)
sn = cfg.get("inverter_sn", "").strip()
if not sn:
    raise RuntimeError("Missing inverter_sn in .env")
for d in ["2026-05-26", "2026-05-23"]:
    r = s.get(f"{b}/WManage/web/analyze/data/export/{sn}/{d}", timeout=60)
    print(d, "export status", r.status_code, "bytes", len(r.content), "type", r.headers.get("Content-Type", "")[:40])
    if r.ok and r.content:
        text = r.content[:500].decode("utf-8", errors="replace")
        print("  head:", text.replace("\n", " | ")[:200])
