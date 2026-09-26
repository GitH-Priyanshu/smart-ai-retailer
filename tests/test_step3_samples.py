import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

from composer import Composer

def run_samples():
    composer = Composer()
    data_dir = Path(__file__).parent.parent / "dataset"

    with open(data_dir / "merchants_seed.json") as f:
        merchants = json.load(f)["merchants"]
        merchants_map = {m["merchant_id"]: m for m in merchants}

    with open(data_dir / "customers_seed.json") as f:
        customers = json.load(f)["customers"]
        customers_map = {c["customer_id"]: c for c in customers}

    with open(data_dir / "triggers_seed.json") as f:
        triggers = json.load(f)["triggers"]
        triggers_map = {t["id"]: t for t in triggers}

    categories_map = {}
    for cat_file in (data_dir / "categories").glob("*.json"):
        with open(cat_file) as f:
            cat_data = json.load(f)
            categories_map[cat_data["slug"]] = cat_data

    test_cases = [
        {
            "title": "Case 1: Merchant-facing | Dentists | research_digest",
            "trigger_id": "trg_001_research_digest_dentists",
        },
        {
            "title": "Case 2: Customer-facing | Dentists | recall_due (hi-en mix)",
            "trigger_id": "trg_003_recall_due_priya",
        },
        {
            "title": "Case 3: Customer-facing | Salons | wedding_package_followup",
            "trigger_id": "trg_007_bridal_followup_kavya",
        },
        {
            "title": "Case 4: Merchant-facing | Dentists | perf_dip",
            "trigger_id": "trg_004_perf_dip_bharat",
        },
        {
            "title": "Case 5: Merchant-facing | Salons | curious_ask_due",
            "trigger_id": "trg_008_curious_ask_studio11",
        }
    ]

    for tc in test_cases:
        trig = triggers_map[tc["trigger_id"]]
        merch = merchants_map[trig["merchant_id"]]
        cat_slug = merch.get("category_slug") or trig.get("payload", {}).get("category")
        cat = categories_map.get(cat_slug)
        cust = customers_map.get(trig.get("customer_id")) if trig.get("customer_id") else None

        result = composer.compose(
            category=cat,
            merchant=merch,
            trigger=trig,
            customer=cust
        )

        print("\n" + "=" * 70)
        print(f"### {tc['title']}")
        print(f"Trigger ID: {trig['id']}")
        print(f"Scope: {trig.get('scope')} | Send As: {result.send_as} | CTA: {result.cta}")
        print(f"Suppression Key: {result.suppression_key}")
        print(f"Body:\n\"{result.body}\"")
        print(f"Rationale:\n{result.rationale}")

if __name__ == "__main__":
    run_samples()
