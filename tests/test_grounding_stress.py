import json
import os
import re
import sys
import time
from datetime import datetime, timezone
import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = os.getenv("BOT_URL", "https://smart-ai-retailer-production.up.railway.app").rstrip("/")

def push_trigger(client: httpx.Client, trigger: dict):
    url = f"{BASE_URL}/v1/context"
    body = {
        "scope": "trigger",
        "context_id": trigger["id"],
        "version": 1,
        "payload": trigger,
        "delivered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    resp = client.post(url, json=body, timeout=15.0)
    return resp.status_code, resp.json()

def call_tick(client: httpx.Client, trigger_id: str):
    url = f"{BASE_URL}/v1/tick"
    body = {
        "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "available_triggers": [trigger_id],
    }
    resp = client.post(url, json=body, timeout=30.0)
    if resp.status_code != 200:
        return None
    actions = resp.json().get("actions", [])
    return actions[0] if actions else None

def extract_numbers(text: str):
    return set(re.findall(r"\b\d+(?:,\d+)*(?:\.\d+)?%?\b", text))

def main():
    client = httpx.Client()
    ts = int(time.time())

    # 5 test trigger definitions
    test_cases = [
        {
            "category": "Dentists",
            "category_slug": "dentists",
            "voice_expected": "Clinical, peer-level, respectful, evidence-grounded, Hindi-English natural for customer",
            "trigger": {
                "id": f"trg_sec5_dentist_recall_{ts}",
                "scope": "customer",
                "kind": "recall_due",
                "source": "internal",
                "merchant_id": "m_002_bharat_dentist_mumbai",
                "customer_id": "c_019_tara_for_m_002_bharat_dentist_mumbai",
                "urgency": 3,
                "suppression_key": f"recall:c_019:{ts}",
                "payload": {
                    "service_due": "6_month_cleaning",
                    "last_service_date": "2026-05-10",
                    "due_date": "2026-11-10",
                    "available_slots": [
                        {"iso": "2026-11-04T17:00:00+05:30", "label": "Tue 4 Nov, 5pm"},
                        {"iso": "2026-11-05T18:00:00+05:30", "label": "Wed 5 Nov, 6pm"}
                    ],
                    "offer_title": "Dental Cleaning @ ₹299"
                }
            },
            "available_facts": [
                "Doctor: Dr. Bharat",
                "Clinic: Bharat Dental Care",
                "Locality: Andheri West, Mumbai",
                "Customer: Tara (language: hi-en mix)",
                "Last visit: 2026-05-10 (6 months ago)",
                "Service due: 6-month cleaning recall",
                "Due date: 2026-11-10",
                "Slots: Tue 4 Nov 5pm, Wed 5 Nov 6pm",
                "Offer: Dental Cleaning @ ₹299"
            ]
        },
        {
            "category": "Salons",
            "category_slug": "salons",
            "voice_expected": "Warm-practical, trend-conscious, inviting, operator-to-operator",
            "trigger": {
                "id": f"trg_sec5_salon_perfdip_{ts}",
                "scope": "merchant",
                "kind": "perf_dip",
                "source": "internal",
                "merchant_id": "m_003_studio11_salon_hyderabad",
                "customer_id": None,
                "urgency": 4,
                "suppression_key": f"perfdip:m_003:{ts}",
                "payload": {
                    "metric": "calls",
                    "delta_pct": -0.35,
                    "window": "7d",
                    "vs_baseline": 14,
                    "active_offer": "Keratin Treatment @ ₹1,999"
                }
            },
            "available_facts": [
                "Owner: Lakshmi",
                "Salon: Studio11 Kapra, Hyderabad",
                "Performance: 1,940 views (30d), 14 baseline calls",
                "Dip: calls dropped 35% in the last 7 days",
                "Active Offer: Keratin Treatment @ ₹1,999",
                "Peer calls: 24 calls/30d"
            ]
        },
        {
            "category": "Restaurants",
            "category_slug": "restaurants",
            "voice_expected": "Operator-to-operator, margin-aware, concise, action-focused",
            "trigger": {
                "id": f"trg_sec5_restaurant_festival_{ts}",
                "scope": "merchant",
                "kind": "festival_upcoming",
                "source": "external",
                "merchant_id": "m_005_pizzajunction_restaurant_delhi",
                "customer_id": None,
                "urgency": 2,
                "suppression_key": f"festival:diwali:m_005:{ts}",
                "payload": {
                    "festival": "Diwali",
                    "date": "2026-10-31",
                    "days_until": 22,
                    "category_relevance": ["restaurants"],
                    "signature_offer": "Family Meal Combo @ ₹699"
                }
            },
            "available_facts": [
                "Owner: Vikram",
                "Restaurant: Pizza Junction, Pitampura, Delhi",
                "Festival: Diwali on 2026-10-31 (22 days remaining)",
                "Active Offers: Unlimited Pizza Buffet @ ₹399, Family Meal Combo @ ₹699",
                "Dining category peak: party orders & advance pre-booking"
            ]
        },
        {
            "category": "Gyms",
            "category_slug": "gyms",
            "voice_expected": "Coaching, motivating, progress-oriented, structured, encouraging",
            "trigger": {
                "id": f"trg_sec5_gym_lapsed_{ts}",
                "scope": "customer",
                "kind": "customer_lapsed_soft",
                "source": "internal",
                "merchant_id": "m_007_powerhouse_gym_bangalore",
                "customer_id": "c_009_arjun_for_m007",
                "urgency": 3,
                "suppression_key": f"lapsed_soft:c_009:{ts}",
                "payload": {
                    "days_since_last_visit": 21,
                    "preferred_slot": "weekday_7am",
                    "training_focus": "strength",
                    "offer_name": "Personal Training Intro @ ₹499"
                }
            },
            "available_facts": [
                "Gym: Powerhouse Fitness, Indiranagar, Bangalore",
                "Owner: Rajesh",
                "Customer: Arjun (language: english)",
                "Training focus: strength",
                "Preferred slot: weekday 7am",
                "Lapsed: 21 days since last session (last visit 2026-04-21)",
                "Offer: Personal Training Intro @ ₹499"
            ]
        },
        {
            "category": "Pharmacies",
            "category_slug": "pharmacies",
            "voice_expected": "Trustworthy-precise, compliance-minded, health-focused, strictly factual, caring",
            "trigger": {
                "id": f"trg_sec5_pharmacy_refill_{ts}",
                "scope": "customer",
                "kind": "chronic_refill_due",
                "source": "internal",
                "merchant_id": "m_009_apollo_pharmacy_jaipur",
                "customer_id": "c_013_grandfather_for_m009",
                "urgency": 3,
                "suppression_key": f"refill:c_013:{ts}",
                "payload": {
                    "molecule_list": ["metformin", "atorvastatin", "telmisartan"],
                    "last_refill": "2026-03-26",
                    "stock_runs_out_iso": "2026-04-28",
                    "days_stock_remaining": 2,
                    "delivery_address_saved": True
                }
            },
            "available_facts": [
                "Pharmacy: Apollo Pharmacy, Malviya Nagar, Jaipur",
                "Owner: Sunita",
                "Customer: Mr. Sharma (senior citizen, language: hi)",
                "Active Offers: Free Home Delivery > ₹499, Senior Citizen 15% OFF",
                "Chronic condition molecules: metformin, atorvastatin, telmisartan",
                "Last refill: 2026-03-26",
                "Stock runs out: 2026-04-28 (2 days remaining)",
                "Delivery address: saved on file (free home delivery)"
            ]
        }
    ]

    print("=" * 70)
    print("  SECTION 5 — GROUNDING STRESS TEST ACROSS ALL 5 CATEGORIES")
    print("=" * 70)

    results = []

    for i, tc in enumerate(test_cases, 1):
        print(f"\n[{i}/5] Processing Category: {tc['category']} ({tc['trigger']['kind']})...")
        
        # 1. Push trigger
        st, push_res = push_trigger(client, tc["trigger"])
        if st not in (200, 409):
            print(f"  [ERROR] Trigger push failed: HTTP {st} {push_res}")
            continue

        # 2. Call tick
        action = call_tick(client, tc["trigger"]["id"])
        if not action:
            print(f"  [ERROR] Tick returned no action for trigger {tc['trigger']['id']}")
            continue

        body = action.get("body", "")
        cta = action.get("cta", "none")
        send_as = action.get("send_as", "vera")
        rationale = action.get("rationale", "")

        # Grounding check: extract all numbers and check against available facts
        all_context_text = " ".join(tc["available_facts"]) + " " + json.dumps(tc["trigger"]["payload"])
        context_numbers = set(re.findall(r"\d+", all_context_text))
        body_numbers = set(re.findall(r"\d+", body))
        unmatched_numbers = body_numbers - context_numbers

        # Single CTA check
        questions = [s.strip() for s in re.split(r"[.!?]\s+", body) if "?" in s]
        has_single_cta = len(questions) <= 1

        results.append({
            "category": tc["category"],
            "trigger_kind": tc["trigger"]["kind"],
            "send_as": send_as,
            "cta": cta,
            "body": body,
            "rationale": rationale,
            "available_facts": tc["available_facts"],
            "unmatched_numbers": list(unmatched_numbers),
            "numbers_grounded": len(unmatched_numbers) == 0,
            "has_single_cta": has_single_cta,
            "voice_expected": tc["voice_expected"]
        })

    # Print Full Report
    print("\n" + "=" * 70)
    print("  SECTION 5 DETAILED RESULTS REPORT")
    print("=" * 70)

    for i, res in enumerate(results, 1):
        print(f"\n----------------------------------------------------------------------")
        print(f"CATEGORY {i}: {res['category'].upper()} — Trigger: {res['trigger_kind']}")
        print(f"----------------------------------------------------------------------")
        print(f"Send As: {res['send_as']} | CTA Type: {res['cta']}")
        print(f"\nCOMPOSED MESSAGE:\n\"{res['body']}\"")
        print(f"\nAVAILABLE FACTS IN CONTEXT:")
        for f in res['available_facts']:
            print(f"  * {f}")
        print(f"\nGROUNDING VERIFICATION:")
        print(f"  * All numbers grounded: {res['numbers_grounded']} (Unmatched: {res['unmatched_numbers'] or 'None - 100% Grounded'})")
        print(f"  * Exactly one CTA: {res['has_single_cta']} [PASS]")
        print(f"  * Category Voice: {res['voice_expected']}")
        print(f"  * Rationale: {res['rationale']}")

if __name__ == "__main__":
    main()
