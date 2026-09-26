import os
import sys
import json
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8080"
exp_dir = Path(__file__).parent.parent / "dataset" / "expanded"

merchants = {}
for f in (exp_dir / "merchants").glob("*.json"):
    with open(f, encoding="utf-8") as fp:
        m = json.load(fp)
        merchants[m["merchant_id"]] = m

triggers = {}
for f in (exp_dir / "triggers").glob("*.json"):
    with open(f, encoding="utf-8") as fp:
        t = json.load(fp)
        triggers[t["id"]] = t

customers = {}
for f in (exp_dir / "customers").glob("*.json"):
    with open(f, encoding="utf-8") as fp:
        c = json.load(fp)
        customers[c["customer_id"]] = c

categories = {}
for f in (Path(__file__).parent.parent / "dataset" / "categories").glob("*.json"):
    with open(f, encoding="utf-8") as fp:
        cat = json.load(fp)
        categories[cat["slug"]] = cat

target_triggers = [
    triggers["trg_009_winback_glamour"],
    triggers["trg_010_ipl_match_delhi"]
]

client = httpx.Client(base_url=BASE_URL, timeout=30.0)

for trig in target_triggers:
    merch = merchants.get(trig["merchant_id"])
    cust = customers.get(trig.get("customer_id")) if trig.get("customer_id") else None
    cat_slug = merch.get("category_slug") if merch else trig.get("payload", {}).get("category")
    cat = categories.get(cat_slug)

    # 1. Post contexts to real server
    if cat:
        r1 = client.post("/v1/context", json={"scope": "category", "context_id": cat_slug, "version": 1, "payload": cat})
        assert r1.status_code in (200, 409), f"Failed to push category: {r1.text}"
    if merch:
        r2 = client.post("/v1/context", json={"scope": "merchant", "context_id": merch["merchant_id"], "version": 1, "payload": merch})
        assert r2.status_code in (200, 409), f"Failed to push merchant: {r2.text}"
    if cust:
        r3 = client.post("/v1/context", json={"scope": "customer", "context_id": cust["customer_id"], "version": 1, "payload": cust})
        assert r3.status_code in (200, 409), f"Failed to push customer: {r3.text}"
    
    r4 = client.post("/v1/context", json={"scope": "trigger", "context_id": trig["id"], "version": 1, "payload": trig})
    assert r4.status_code in (200, 409), f"Failed to push trigger: {r4.text}"
    
    # 2. Call real POST /v1/tick
    tick_payload = {
        "available_triggers": [trig["id"]]
    }
    tick_resp = client.post("/v1/tick", json=tick_payload)
    print("=" * 80)
    print(f"HTTP POST /v1/tick -> Status: {tick_resp.status_code}")
    print(f"Trigger ID: {trig['id']} | Kind: {trig.get('kind')} | Category: {cat_slug}")
    print(f"Merchant: {merch.get('identity', {}).get('name') if merch else 'Unknown'}")
    resp_data = tick_resp.json()
    actions = resp_data.get("actions", [])
    print(f"Actions returned ({len(actions)}):")
    for act in actions:
        print(f"  Action: {act.get('action')} | Send As: {act.get('send_as')} | CTA: {act.get('cta')}")
        print(f"  Conversation ID: {act.get('conversation_id')}")
        print(f"  Body:\n    {act.get('body')}")
        print(f"  Rationale:\n    {act.get('rationale')}")
