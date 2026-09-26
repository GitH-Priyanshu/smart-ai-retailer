import os
import sys
from dotenv import load_dotenv
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

from bot import app, context_store, conversation_store, guard_layer

def test_guards():
    client = TestClient(app)

    print("=" * 70)
    print("TEST 1: Auto-reply hell — same canned text sent 3x")
    print("Expectation: send -> wait -> end")
    print("=" * 70)

    conv_auto = "conv_auto_test_1"
    canned_msg = "Thank you for contacting us! Our team will respond shortly."

    # Turn 1
    r1 = client.post("/v1/reply", json={
        "conversation_id": conv_auto,
        "merchant_id": "m_test",
        "message": canned_msg,
        "turn_number": 1
    })
    data1 = r1.json()
    print("Turn 1 response:", data1["action"], f"({data1.get('body', '')[:60]}...)")
    assert data1["action"] == "send", f"Expected send on turn 1, got {data1['action']}"

    # Turn 2
    r2 = client.post("/v1/reply", json={
        "conversation_id": conv_auto,
        "merchant_id": "m_test",
        "message": canned_msg,
        "turn_number": 2
    })
    data2 = r2.json()
    print("Turn 2 response:", data2["action"], f"(wait_seconds: {data2.get('wait_seconds')})")
    assert data2["action"] == "wait", f"Expected wait on turn 2, got {data2['action']}"

    # Turn 3
    r3 = client.post("/v1/reply", json={
        "conversation_id": conv_auto,
        "merchant_id": "m_test",
        "message": canned_msg,
        "turn_number": 3
    })
    data3 = r3.json()
    print("Turn 3 response:", data3["action"], f"(rationale: {data3.get('rationale')})")
    assert data3["action"] == "end", f"Expected end on turn 3, got {data3['action']}"
    print(">>> TEST 1 PASSED: send -> wait -> end verified successfully!\n")

    print("=" * 70)
    print("TEST 2: Intent transition — commitment phrase 'ok lets do it'")
    print("Expectation: immediate switch to ACTION mode, NO qualifying questions")
    print("=" * 70)

    conv_intent = "conv_intent_test_1"
    # Turn 1: merchant asks a question / qualifying stage
    r_qual = client.post("/v1/reply", json={
        "conversation_id": conv_intent,
        "merchant_id": "m_test",
        "message": "What is included in the package?",
        "turn_number": 1
    })
    print("Turn 1 (qualifying):", r_qual.json()["action"], f"({r_qual.json().get('body', '')[:60]}...)")

    # Turn 2: merchant commits
    commitment_msg = "Ok lets do it. Whats next?"
    r_intent = client.post("/v1/reply", json={
        "conversation_id": conv_intent,
        "merchant_id": "m_test",
        "message": commitment_msg,
        "turn_number": 2
    })
    data_intent = r_intent.json()
    print("Turn 2 (commitment):", data_intent["action"])
    body = data_intent.get("body", "")
    print(f"Body: \"{body}\"")

    body_lower = body.lower()
    qualifying_phrases = ["would you", "do you", "can you tell", "what if", "how about"]
    actioning_words = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]

    assert any(w in body_lower for w in actioning_words), "Expected actioning words in response"
    assert not any(q in body_lower for q in qualifying_phrases), "Found qualifying phrase in action mode response!"
    print(">>> TEST 2 PASSED: Switched to ACTION mode, contains actioning words, zero qualifying questions!\n")

    print("=" * 70)
    print("TEST 3: Hostile / Opt-out message — 'Stop messaging me. This is useless spam.'")
    print("Expectation: immediate 'end' or apology+exit, bypassing composer")
    print("=" * 70)

    conv_hostile = "conv_hostile_test_1"
    r_hostile = client.post("/v1/reply", json={
        "conversation_id": conv_hostile,
        "merchant_id": "m_test",
        "message": "Stop messaging me. This is useless spam.",
        "turn_number": 2
    })
    data_hostile = r_hostile.json()
    print("Hostile response:", data_hostile["action"], f"(rationale: {data_hostile.get('rationale')})")
    assert data_hostile["action"] == "end", f"Expected end on hostile message, got {data_hostile['action']}"
    print(">>> TEST 3 PASSED: Correctly ENDED immediately on hostility!\n")

    print("ALL 3 STEP 4 PRE-CHECK TESTS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_guards()
