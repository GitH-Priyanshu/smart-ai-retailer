import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

from composer import Composer

def spotcheck():
    composer = Composer()
    exp_dir = Path(__file__).parent.parent / "dataset" / "expanded"

    merchants = {}
    for f in (exp_dir / "merchants").glob("*.json"):
        with open(f) as fp:
            m = json.load(fp)
            merchants[m["merchant_id"]] = m

    triggers = {}
    for f in (exp_dir / "triggers").glob("*.json"):
        with open(f) as fp:
            t = json.load(fp)
            triggers[t["id"]] = t

    customers = {}
    for f in (exp_dir / "customers").glob("*.json"):
        with open(f) as fp:
            c = json.load(fp)
            customers[c["customer_id"]] = c

    # Pick 2 triggers from the expanded set not in the seed files
    non_seed_triggers = [
        t for t in triggers.values()
        if not t["id"].startswith(("trg_001", "trg_002", "trg_003", "trg_004", "trg_005", "trg_006", "trg_007", "trg_008"))
    ][:2]

    for trig in non_seed_triggers:
        merch = merchants.get(trig["merchant_id"])
        cust = customers.get(trig.get("customer_id")) if trig.get("customer_id") else None
        cat_slug = merch.get("category_slug") if merch else trig.get("payload", {}).get("category")
        
        cat_path = Path(__file__).parent.parent / "dataset" / "categories" / f"{cat_slug}.json"
        with open(cat_path) as f:
            cat = json.load(f)

        res = composer.compose(category=cat, merchant=merch, trigger=trig, customer=cust)
        print("\n" + "=" * 70)
        print(f"Trigger: {trig['id']} | Kind: {trig.get('kind')} | Category: {cat_slug}")
        print(f"Merchant: {merch.get('identity', {}).get('name') if merch else 'Unknown'}")
        print(f"Send As: {res.send_as} | CTA: {res.cta}")
        print(f"Body:\n\"{res.body}\"")
        print(f"Rationale:\n{res.rationale}")

if __name__ == "__main__":
    spotcheck()
