import copy
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = os.getenv("BOT_URL", "https://smart-ai-retailer-production.up.railway.app").rstrip("/")

def main():
    root = Path(__file__).resolve().parent.parent
    seed_file = root / "dataset" / "merchants_seed.json"
    with open(seed_file, encoding="utf-8") as f:
        data = json.load(f)
        meera_v1 = next(m for m in data["merchants"] if m["merchant_id"] == "m_001_drmeera_dentist_delhi")

    client = httpx.Client()

    print("=" * 65)
    print("  SECTION 4 — ADAPTIVE INJECTION TEST")
    print("=" * 65)
    print(f"Target URL: {BASE_URL}")

    # -------------------------------------------------------------
    # Step 1: Push merchant context at baseline version
    # -------------------------------------------------------------
    print("\n--- STEP 1: PUSH MERCHANT AT BASELINE VERSION ---")
    p1 = {
        "scope": "merchant",
        "context_id": "m_001_drmeera_dentist_delhi",
        "version": 1,
        "payload": meera_v1,
        "delivered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    r1 = client.post(f"{BASE_URL}/v1/context", json=p1, timeout=15.0)
    current_v = 1
    if r1.status_code == 409:
        current_v = r1.json().get("current_version", 1)
        print(f"Merchant already exists at version {current_v}")
    else:
        print(f"Push v1 Status: {r1.status_code} ({r1.json().get('reason', 'accepted')})")
    print(f"Baseline views: {meera_v1['performance']['views']}, calls: {meera_v1['performance']['calls']}")

    # -------------------------------------------------------------
    # Step 2: Fire /v1/tick and save initial message
    # -------------------------------------------------------------
    print("\n--- STEP 2: FIRE /v1/tick (BASELINE TRIGGER) ---")
    t1_resp = client.post(f"{BASE_URL}/v1/tick", json={
        "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "available_triggers": ["trg_001_research_digest_dentists"]
    }, timeout=30.0)
    
    t1_data = t1_resp.json()
    actions1 = t1_data.get("actions", [])
    if not actions1:
        print("[FAIL] No actions returned for baseline tick!")
        return
    
    msg1 = actions1[0].get("body", "")
    print(f"Message 1 (v1 baseline):")
    print(f"\"{msg1}\"")

    # -------------------------------------------------------------
    # Step 3: Push SAME merchant at updated version with CHANGED data
    # -------------------------------------------------------------
    next_v = current_v + 1
    print(f"\n--- STEP 3: PUSH SAME MERCHANT AT VERSION {next_v} (CHANGED DATA) ---")
    meera_v2 = copy.deepcopy(meera_v1)
    # Higher views, lower calls, new competitor signal
    meera_v2["performance"]["views"] = 6200
    meera_v2["performance"]["calls"] = 4
    if "competitor_opened_nearby: true" not in meera_v2.get("signals", []):
        meera_v2["signals"].append("competitor_opened_nearby: true")

    p2 = {
        "scope": "merchant",
        "context_id": "m_001_drmeera_dentist_delhi",
        "version": next_v,
        "payload": meera_v2,
        "delivered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    r2 = client.post(f"{BASE_URL}/v1/context", json=p2, timeout=15.0)
    print(f"Push v{next_v} Status: {r2.status_code} ({r2.json()})")
    print(f"Updated views: {meera_v2['performance']['views']}, calls: {meera_v2['performance']['calls']}")
    print(f"Signals: {meera_v2['signals']}")
    
    if r2.status_code != 200:
        print(f"[FAIL] Expected HTTP 200 on v{next_v} push, got {r2.status_code}")
        return

    # -------------------------------------------------------------
    # Step 4: Push a NEW trigger that didn't exist before
    # -------------------------------------------------------------
    print("\n--- STEP 4: PUSH NEW TRIGGER (competitor_opened) ---")
    new_trigger_id = f"trg_adaptive_competitor_clove_{int(time.time())}"
    new_trigger_payload = {
        "id": new_trigger_id,
        "scope": "merchant",
        "kind": "competitor_opened",
        "source": "external",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "urgency": 4,
        "suppression_key": f"competitor:m_001:clove_delhi_{int(time.time())}",
        "payload": {
            "competitor_name": "Clove Dental",
            "distance_meters": 350,
            "launch_offer": "Free dental consultation + 20% off scaling",
            "category": "dentists"
        }
    }

    pt = {
        "scope": "trigger",
        "context_id": new_trigger_id,
        "version": 1,
        "payload": new_trigger_payload,
        "delivered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    rt = client.post(f"{BASE_URL}/v1/context", json=pt, timeout=15.0)
    print(f"New Trigger Push Status: {rt.status_code} ({rt.json()})")

    if rt.status_code != 200:
        print(f"[FAIL] Expected HTTP 200 on trigger push, got {rt.status_code}")
        return

    # -------------------------------------------------------------
    # Step 5: Fire /v1/tick again with the new trigger
    # -------------------------------------------------------------
    print("\n--- STEP 5: FIRE /v1/tick WITH NEW TRIGGER ---")
    t2_resp = client.post(f"{BASE_URL}/v1/tick", json={
        "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "available_triggers": [new_trigger_id]
    }, timeout=30.0)

    t2_data = t2_resp.json()
    actions2 = t2_data.get("actions", [])
    if not actions2:
        print(f"[FAIL] No actions returned for new trigger tick! Response: {t2_data}")
        return

    msg2 = actions2[0].get("body", "")
    print(f"Message 2 (adaptive injection):")
    print(f"\"{msg2}\"")

    # -------------------------------------------------------------
    # Step 6: Compare the two messages side by side
    # -------------------------------------------------------------
    print("\n" + "=" * 65)
    print("  STEP 6: SIDE-BY-SIDE COMPARISON")
    print("=" * 65)
    print(f"\n[Message 1 - Baseline (trg_001 Research Digest)]:\n\"{msg1}\"")
    print(f"\n[Message 2 - Adaptive Injection (New Competitor + v2 Context)]:\n\"{msg2}\"")

    # Verification checks
    used_competitor_name = "clove" in msg2.lower()
    used_distance_or_offer = "350" in msg2 or "consultation" in msg2.lower() or "scaling" in msg2.lower() or "competitor" in msg2.lower()
    different_from_m1 = msg1.strip() != msg2.strip()

    print("\n--- VALIDATION ---")
    print(f"  Messages are distinct: {different_from_m1} {'[PASS]' if different_from_m1 else '[FAIL]'}")
    print(f"  Uses new competitor data: {used_competitor_name} {'[PASS]' if used_competitor_name else '[FAIL]'}")
    print(f"  Grounded in new context: {used_distance_or_offer} {'[PASS]' if used_distance_or_offer else '[FAIL]'}")

    if different_from_m1 and (used_competitor_name or used_distance_or_offer):
        print("\n>>> SECTION 4 ADAPTIVE INJECTION TEST: ALL PASSED <<<")
    else:
        print("\n>>> SECTION 4 ADAPTIVE INJECTION TEST: FAILED <<<")

if __name__ == "__main__":
    main()
