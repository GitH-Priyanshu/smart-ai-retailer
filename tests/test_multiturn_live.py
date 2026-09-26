import json
import os
import sys
import time
from datetime import datetime, timezone
import httpx

BASE_URL = os.getenv("BOT_URL", "https://smart-ai-retailer-production.up.railway.app").rstrip("/")

def print_separator(title: str):
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")

def call_tick(client: httpx.Client, triggers: list) -> dict:
    url = f"{BASE_URL}/v1/tick"
    payload = {
        "now": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "available_triggers": triggers,
    }
    t0 = time.time()
    resp = client.post(url, json=payload, timeout=30.0)
    lat = (time.time() - t0) * 1000
    if resp.status_code != 200:
        print(f"TICK ERROR: HTTP {resp.status_code} - {resp.text}")
        return {}
    data = resp.json()
    return data

def call_reply(client: httpx.Client, conv_id: str, merchant_id: str, message: str, turn: int, customer_id: str = None) -> dict:
    url = f"{BASE_URL}/v1/reply"
    payload = {
        "conversation_id": conv_id,
        "merchant_id": merchant_id,
        "customer_id": customer_id,
        "from_role": "merchant",
        "message": message,
        "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "turn_number": turn,
    }
    t0 = time.time()
    resp = client.post(url, json=payload, timeout=30.0)
    lat = (time.time() - t0) * 1000
    if resp.status_code != 200:
        print(f"REPLY ERROR (Turn {turn}): HTTP {resp.status_code} - {resp.text}")
        return {"error": f"HTTP {resp.status_code}", "status_code": resp.status_code}
    data = resp.json()
    data["_latency_ms"] = lat
    return data

def run_tests():
    client = httpx.Client()
    ts = int(time.time())
    overall_pass = True

    # -------------------------------------------------------------
    # CONVERSATION A — Normal qualifying to action transition
    # -------------------------------------------------------------
    print_separator("CONVERSATION A — Qualifying to Action Transition")
    merchant_id = "m_001_drmeera_dentist_delhi"
    # Turn 1: Seed via /v1/tick or direct conversation start
    print(f"\n[Turn 1] Initial Tick Trigger...")
    tick_res = call_tick(client, ["trg_001_research_digest_dentists"])
    actions = tick_res.get("actions", [])
    if actions:
        conv_a_id = actions[0].get("conversation_id", f"conv_live_test_a_{ts}")
        turn1_body = actions[0].get("body", "")
        print(f"Bot (Turn 1): \"{turn1_body}\"")
    else:
        conv_a_id = f"conv_live_test_a_{ts}"
        turn1_body = "Dr. Meera, JIDA trial showed 3-month recall cuts caries 38% better. Want to review?"
        print(f"Bot (Turn 1 fallback): \"{turn1_body}\"")

    # Turn 2: Question
    turn2_msg = "Can you explain more about this?"
    print(f"\n[Turn 2] Merchant: \"{turn2_msg}\"")
    turn2_resp = call_reply(client, conv_a_id, merchant_id, turn2_msg, turn=2)
    print(f"Bot Action: {turn2_resp.get('action')}")
    print(f"Bot Body:   \"{turn2_resp.get('body')}\"")
    print(f"Rationale:  {turn2_resp.get('rationale')}")
    
    turn2_pass = turn2_resp.get("action") == "send" and bool(turn2_resp.get("body"))
    if not turn2_pass:
        print("[FAIL] Turn 2 expected action 'send' with follow-up body")
        overall_pass = False
    else:
        print("[PASS] Turn 2 replied with follow-up")

    # Turn 3: Intent Transition -> "Ok sounds good, let's do it"
    turn3_msg = "Ok sounds good, let's do it"
    print(f"\n[Turn 3] Merchant: \"{turn3_msg}\"")
    turn3_resp = call_reply(client, conv_a_id, merchant_id, turn3_msg, turn=3)
    print(f"Bot Action: {turn3_resp.get('action')}")
    print(f"Bot Body:   \"{turn3_resp.get('body')}\"")
    print(f"Rationale:  {turn3_resp.get('rationale')}")

    body_lower = (turn3_resp.get("body") or "").lower()
    has_qualifying_q = any(q in body_lower for q in ["would you like", "shall i", "want me to", "do you want", "are you interested"])
    turn3_pass = turn3_resp.get("action") == "send" and not has_qualifying_q
    if not turn3_pass:
        print(f"[FAIL] Turn 3 expected action 'send' with concrete next steps and NO qualifying question")
        overall_pass = False
    else:
        print("[PASS] Turn 3 transitioned to action mode without qualifying questions")

    # Turn 4: "Great, done"
    turn4_msg = "Great, done"
    print(f"\n[Turn 4] Merchant: \"{turn4_msg}\"")
    turn4_resp = call_reply(client, conv_a_id, merchant_id, turn4_msg, turn=4)
    print(f"Bot Action: {turn4_resp.get('action')}")
    print(f"Bot Body:   \"{turn4_resp.get('body')}\"")
    print(f"Rationale:  {turn4_resp.get('rationale')}")

    turn4_pass = turn4_resp.get("action") in ("send", "end")
    if not turn4_pass:
        print(f"[FAIL] Turn 4 expected action 'send' or 'end'")
        overall_pass = False
    else:
        print("[PASS] Turn 4 handled completion acknowledgment")

    # -------------------------------------------------------------
    # CONVERSATION B — Auto-reply hell
    # -------------------------------------------------------------
    print_separator("CONVERSATION B — Auto-Reply Hell")
    conv_b_id = f"conv_live_test_b_autoreply_{ts}"
    auto_msg = "Thank you for contacting us! We will respond soon."

    # Turn 2: 1st auto-reply
    print(f"\n[Turn 2] Merchant: \"{auto_msg}\"")
    b2 = call_reply(client, conv_b_id, merchant_id, auto_msg, turn=2)
    print(f"Bot Action: {b2.get('action')}")
    print(f"Bot Body:   \"{b2.get('body')}\"")
    print(f"Rationale:  {b2.get('rationale')}")
    b2_pass = b2.get("action") == "send"
    if not b2_pass:
        print(f"[FAIL] Turn 2 expected action 'send' on 1st auto-reply")
        overall_pass = False
    else:
        print("[PASS] Turn 2 correctly sent targeted follow-up on 1st auto-reply")

    # Turn 3: 2nd auto-reply
    print(f"\n[Turn 3] Merchant: \"{auto_msg}\"")
    b3 = call_reply(client, conv_b_id, merchant_id, auto_msg, turn=3)
    print(f"Bot Action: {b3.get('action')}")
    print(f"Wait Sec:   {b3.get('wait_seconds')}")
    print(f"Rationale:  {b3.get('rationale')}")
    b3_pass = b3.get("action") == "wait"
    if not b3_pass:
        print(f"[FAIL] Turn 3 expected action 'wait' on 2nd auto-reply")
        overall_pass = False
    else:
        print("[PASS] Turn 3 correctly set 'wait' on 2nd auto-reply")

    # Turn 4: 3rd auto-reply
    print(f"\n[Turn 4] Merchant: \"{auto_msg}\"")
    b4 = call_reply(client, conv_b_id, merchant_id, auto_msg, turn=4)
    print(f"Bot Action: {b4.get('action')}")
    print(f"Rationale:  {b4.get('rationale')}")
    b4_pass = b4.get("action") == "end"
    if not b4_pass:
        print(f"[FAIL] Turn 4 expected action 'end' on 3rd auto-reply")
        overall_pass = False
    else:
        print("[PASS] Turn 4 correctly ended conversation on 3rd auto-reply")

    # -------------------------------------------------------------
    # CONVERSATION C — Hostile then off-topic
    # -------------------------------------------------------------
    print_separator("CONVERSATION C — Hostile then Off-Topic")
    conv_c1_id = f"conv_live_test_c1_hostile_{ts}"
    hostile_msg = "Stop messaging me this is spam"

    print(f"\n[Part 1: Hostile Handling]")
    print(f"Merchant: \"{hostile_msg}\"")
    c1 = call_reply(client, conv_c1_id, merchant_id, hostile_msg, turn=2)
    print(f"Bot Action: {c1.get('action')}")
    print(f"Bot Body:   \"{c1.get('body')}\"")
    print(f"Rationale:  {c1.get('rationale')}")
    c1_pass = c1.get("action") == "end"
    if not c1_pass:
        print(f"[FAIL] Part 1 expected immediate action 'end'")
        overall_pass = False
    else:
        print("[PASS] Correctly ended conversation immediately on hostile input")

    # Part 2: Reset conversation, new conversation_id
    conv_c2_id = f"conv_live_test_c2_offtopic_{ts}"
    offtopic_msg = "Can you help me with my GST filing?"

    print(f"\n[Part 2: Off-Topic Handling]")
    print(f"Merchant: \"{offtopic_msg}\"")
    c2 = call_reply(client, conv_c2_id, merchant_id, offtopic_msg, turn=3)
    print(f"Bot Action: {c2.get('action')}")
    print(f"Bot Body:   \"{c2.get('body')}\"")
    print(f"Rationale:  {c2.get('rationale')}")

    # Off-topic should NOT be end; it should be send (polite decline and redirect)
    c2_pass = c2.get("action") == "send" and bool(c2.get("body"))
    if not c2_pass:
        print(f"[FAIL] Part 2 expected action 'send' (polite decline/redirect), got '{c2.get('action')}'")
        overall_pass = False
    else:
        print("[PASS] Correctly replied with polite decline / redirect, NOT a full end")

    # -------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------
    print_separator("SECTION 3 TEST SUMMARY")
    if overall_pass:
        print(">>> ALL SECTION 3 MULTI-TURN CONVERSATION TESTS PASSED <<<")
    else:
        print(">>> SECTION 3 MULTI-TURN CONVERSATION TESTS COMPLETED WITH FAILURES <<<")

if __name__ == "__main__":
    run_tests()
