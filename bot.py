import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from context_store import ContextStore
from conversation_store import ConversationStore

# Load environment variables
load_dotenv()

# App and initialization
START_TIME = time.time()
context_store = ContextStore()
conversation_store = ConversationStore()

app = FastAPI(
    title="Vera Message Engine",
    description="Deterministic message-composition engine for magicpin merchants",
    version="1.0.0",
)


# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------

class ContextPushRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class TickRequest(BaseModel):
    now: Optional[str] = None
    available_triggers: List[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str = "merchant"
    message: str
    received_at: Optional[str] = None
    turn_number: Optional[int] = None


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------

@app.post("/v1/context")
async def push_context(req: ContextPushRequest):
    success, status_code, resp_data = context_store.push(
        scope=req.scope,
        context_id=req.context_id,
        version=req.version,
        payload=req.payload,
        delivered_at=req.delivered_at,
    )
    return JSONResponse(status_code=status_code, content=resp_data)


@app.post("/v1/tick")
async def tick(req: TickRequest):
    actions = []
    seen_convs = set()

    for trigger_id in req.available_triggers:
        if len(actions) >= 20:
            break

        trigger = context_store.get("trigger", trigger_id)
        if not trigger:
            continue

        merchant_id = trigger.get("merchant_id")
        if not merchant_id:
            continue

        merchant = context_store.get("merchant", merchant_id)
        if not merchant:
            continue

        category_slug = merchant.get("category_slug") or trigger.get("payload", {}).get("category")
        category = context_store.get("category", category_slug) if category_slug else None

        customer_id = trigger.get("customer_id")
        customer = context_store.get("customer", customer_id) if customer_id else None

        is_customer_facing = trigger.get("scope") == "customer" and customer_id is not None
        send_as = "merchant_on_behalf" if is_customer_facing else "vera"

        # Unique conversation ID
        if customer_id:
            conv_id = f"conv_{merchant_id}_{customer_id}_{trigger_id}"
        else:
            conv_id = f"conv_{merchant_id}_{trigger_id}"

        # Ensure only one action per (merchant_id, conversation_id) per tick
        conv_key = (merchant_id, conv_id)
        if conv_key in seen_convs:
            continue
        seen_convs.add(conv_key)

        # Name for greeting
        if is_customer_facing and customer:
            name = customer.get("identity", {}).get("name", "there")
        else:
            identity = merchant.get("identity", {})
            name = identity.get("owner_first_name") or identity.get("name", "there")

        kind = trigger.get("kind", "general")
        body = f"[STUB] Hi {name}, trigger={kind}"
        cta = "open_ended"
        suppression_key = trigger.get("suppression_key") or f"suppress:{merchant_id}:{trigger_id}"
        rationale = f"Stub action for trigger {trigger_id} on merchant {merchant_id}"

        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": send_as,
            "trigger_id": trigger_id,
            "template_name": "stub_template",
            "template_params": [name, kind],
            "body": body,
            "cta": cta,
            "suppression_key": suppression_key,
            "rationale": rationale,
        }
        actions.append(action)

        # Log initial outbound message as turn 1 in conversation_store
        conversation_store.get_or_create(conv_id, merchant_id, customer_id)
        conversation_store.record_turn(
            conversation_id=conv_id,
            role=send_as,
            message=body,
            turn_number=1,
            extra={"cta": cta, "trigger_id": trigger_id, "rationale": rationale},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"actions": actions})


@app.post("/v1/reply")
async def reply(req: ReplyRequest):
    # Log inbound turn
    conversation_store.get_or_create(req.conversation_id, req.merchant_id, req.customer_id)
    conversation_store.record_turn(
        conversation_id=req.conversation_id,
        role=req.from_role,
        message=req.message,
        turn_number=req.turn_number,
        extra={"received_at": req.received_at},
    )

    # Stub response per Step 2
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "action": "send",
            "body": "[STUB reply]",
            "cta": "open_ended",
            "rationale": "stub",
        },
    )


@app.get("/v1/healthz")
async def healthz():
    uptime = int(time.time() - START_TIME)
    counts = context_store.get_counts()
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "uptime_seconds": uptime,
            "contexts_loaded": counts,
        },
    )


@app.get("/v1/metadata")
async def metadata():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "team_name": os.getenv("TEAM_NAME", "Team Vera"),
            "team_members": ["Priyanshu Saklani"],
            "model": "gemini-2.5-flash-lite",
            "approach": (
                "Deterministic message-composition engine with single-prompt "
                "kind-aware framing, strict factual grounding, and pre/post guards"
            ),
            "contact_email": os.getenv("CONTACT_EMAIL", "priyanshu@example.com"),
            "version": "1.0.0",
            "submitted_at": "2026-09-26T19:30:00Z",
        },
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
