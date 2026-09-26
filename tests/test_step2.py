import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from bot import app, context_store, conversation_store

def test_step2():
    context_store.clear()
    conversation_store.clear()

    client = TestClient(app)

    # 1. Push category
    cat_payload = {"slug": "dentists", "voice": {"tone": "peer_clinical"}}
    r = client.post("/v1/context", json={
        "scope": "category", "context_id": "dentists", "version": 1, "payload": cat_payload
    })
    assert r.status_code == 200, r.text

    # 2. Push merchant
    merch_payload = {
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera"}
    }
    r = client.post("/v1/context", json={
        "scope": "merchant", "context_id": "m_001_drmeera_dentist_delhi", "version": 1, "payload": merch_payload
    })
    assert r.status_code == 200, r.text

    # 3. Push trigger
    trig_payload = {
        "id": "trg_001_research_digest_dentists",
        "scope": "merchant",
        "kind": "research_digest",
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "urgency": 2,
        "suppression_key": "research:dentists:2026-W17"
    }
    r = client.post("/v1/context", json={
        "scope": "trigger", "context_id": "trg_001_research_digest_dentists", "version": 1, "payload": trig_payload
    })
    assert r.status_code == 200, r.text

    # 4. Call /v1/tick
    r = client.post("/v1/tick", json={
        "now": "2026-09-26T19:45:00Z",
        "available_triggers": ["trg_001_research_digest_dentists"]
    })
    assert r.status_code == 200, r.text
    data = r.json()
    print("Tick response actions count:", len(data["actions"]))
    assert len(data["actions"]) == 1
    action = data["actions"][0]
    print("Tick action:", action)
    assert action["merchant_id"] == "m_001_drmeera_dentist_delhi"
    assert action["send_as"] == "vera"
    assert action["body"] == "[STUB] Hi Meera, trigger=research_digest"
    conv_id = action["conversation_id"]

    # Confirm 1 turn logged so far in conversation_store
    turns = conversation_store.get_turns(conv_id)
    print("Turns after tick:", len(turns))
    assert len(turns) == 1
    assert turns[0]["role"] == "vera"

    # 5. Call /v1/reply on that conversation_id
    r = client.post("/v1/reply", json={
        "conversation_id": conv_id,
        "merchant_id": "m_001_drmeera_dentist_delhi",
        "customer_id": None,
        "from_role": "merchant",
        "message": "Tell me more about this trial",
        "received_at": "2026-09-26T19:46:00Z",
        "turn_number": 2
    })
    assert r.status_code == 200, r.text
    reply_data = r.json()
    print("Reply response:", reply_data)
    assert reply_data["action"] == "send"
    assert reply_data["body"] == "[STUB reply]"

    # 6. Confirm conversation_store now has 2 turns logged
    turns = conversation_store.get_turns(conv_id)
    print("Turns after reply:", len(turns))
    for t in turns:
        print("  Turn:", t)
    assert len(turns) == 2
    assert turns[0]["role"] == "vera"
    assert turns[1]["role"] == "merchant"
    assert turns[1]["message"] == "Tell me more about this trial"

    print("\nALL STEP 2 CHECKS PASSED!")

if __name__ == "__main__":
    test_step2()
