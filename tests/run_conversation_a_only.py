import json
import os
import sys
import time
from datetime import datetime, timezone
import httpx

BASE_URL = os.getenv("BOT_URL", "https://smart-ai-retailer-production.up.railway.app").rstrip("/")

def main():
    client = httpx.Client()
    merchant_id = "m_001_drmeera_dentist_delhi"

    print("=== RUNNING CONVERSATION A ONLY AGAINST LIVE RAILWAY ===")
    
    # Turn 1: /v1/tick
    print("\n[Turn 1] Calling /v1/tick with trg_001_research_digest_dentists...")
    tick_resp = client.post(f"{BASE_URL}/v1/tick", json={
        "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "available_triggers": ["trg_001_research_digest_dentists"]
    }, timeout=30.0)
    
    if tick_resp.status_code != 200:
        print(f"Error on tick: {tick_resp.status_code} {tick_resp.text}")
        return

    actions = tick_resp.json().get("actions", [])
    if not actions:
        print("No actions returned from tick!")
        return

    conv_id = actions[0]["conversation_id"]
    turn1_body = actions[0]["body"]
    print(f"Conversation ID: {conv_id}")
    print(f"Bot (Turn 1): \"{turn1_body}\"")

    # Turn 2: Follow-up question
    turn2_msg = "Can you explain more about this?"
    print(f"\n[Turn 2] Merchant: \"{turn2_msg}\"")
    t2_resp = client.post(f"{BASE_URL}/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "from_role": "merchant",
        "message": turn2_msg,
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "turn_number": 2
    }, timeout=30.0)

    if t2_resp.status_code != 200:
        print(f"Error on reply: {t2_resp.status_code} {t2_resp.text}")
        return

    t2_data = t2_resp.json()
    print(f"Bot Action: {t2_data.get('action')}")
    print(f"Bot Body:   \"{t2_data.get('body')}\"")
    print(f"Rationale:  {t2_data.get('rationale')}")

    # Turn 3: "Ok sounds good, let's do it"
    turn3_msg = "Ok sounds good, let's do it"
    print(f"\n[Turn 3] Merchant: \"{turn3_msg}\"")
    t3_resp = client.post(f"{BASE_URL}/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "from_role": "merchant",
        "message": turn3_msg,
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "turn_number": 3
    }, timeout=30.0)
    t3_data = t3_resp.json()
    print(f"Bot Action: {t3_data.get('action')}")
    print(f"Bot Body:   \"{t3_data.get('body')}\"")

    # Turn 4: "Great, done"
    turn4_msg = "Great, done"
    print(f"\n[Turn 4] Merchant: \"{turn4_msg}\"")
    t4_resp = client.post(f"{BASE_URL}/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "from_role": "merchant",
        "message": turn4_msg,
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "turn_number": 4
    }, timeout=30.0)
    t4_data = t4_resp.json()
    print(f"Bot Action: {t4_data.get('action')}")
    print(f"Bot Body:   \"{t4_data.get('body')}\"")

if __name__ == "__main__":
    main()
