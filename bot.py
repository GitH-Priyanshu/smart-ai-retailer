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
from composer import Composer
from guard_layer import GuardLayer

# Load environment variables
load_dotenv()

# App and initialization
START_TIME = time.time()
context_store = ContextStore()
conversation_store = ConversationStore()
composer = Composer()
guard_layer = GuardLayer()

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

        conv_state = conversation_store.get_or_create(conv_id, merchant_id, customer_id)
        if conv_state.get("ended"):
            continue

        # Real Gemini-powered composition (with fallback)
        composed = composer.compose(
            category=category,
            merchant=merchant,
            trigger=trigger,
            customer=customer,
            conversation_history=conv_state.get("turns", []),
            conversation_mode=conv_state.get("mode", "qualifying"),
        )

        kind = trigger.get("kind", "general")
        name = (
            customer.get("identity", {}).get("name", "there")
            if customer
            else (merchant.get("identity", {}).get("owner_first_name") or merchant.get("identity", {}).get("name", "there"))
        )

        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": composed.send_as,
            "trigger_id": trigger_id,
            "template_name": f"vera_{kind}_v1",
            "template_params": [name, kind],
            "body": composed.body,
            "cta": composed.cta,
            "suppression_key": composed.suppression_key,
            "rationale": composed.rationale,
        }
        actions.append(action)

        # Log initial outbound message as turn 1 in conversation_store
        conversation_store.record_turn(
            conversation_id=conv_id,
            role=composed.send_as,
            message=composed.body,
            turn_number=1,
            extra={"cta": composed.cta, "trigger_id": trigger_id, "rationale": composed.rationale},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"actions": actions})


@app.post("/v1/reply")
async def reply(req: ReplyRequest):
    conv_state = conversation_store.get_or_create(req.conversation_id, req.merchant_id, req.customer_id)

    # Collect prior inbound messages for repeating / auto-reply checks
    prior_inbounds = [
        t["message"]
        for t in conv_state.get("turns", [])
        if t.get("role") in ("merchant", "customer")
    ]

    # Run PRE checks (Hostile, Auto-reply, Intent transition)
    intercepted, new_mode = guard_layer.check_pre_reply(
        conversation_id=req.conversation_id,
        merchant_id=req.merchant_id,
        message=req.message,
        prior_inbounds=prior_inbounds,
    )

    # Log incoming message
    conversation_store.record_turn(
        conversation_id=req.conversation_id,
        role=req.from_role,
        message=req.message,
        turn_number=req.turn_number,
        extra={"received_at": req.received_at},
    )

    # Handle intercepted outcomes immediately (bypassing composer)
    if intercepted:
        act = intercepted.get("action")
        if act == "end":
            conversation_store.set_ended(req.conversation_id, True)
        elif act == "wait":
            conversation_store.set_wait(req.conversation_id, intercepted.get("wait_seconds", 14400))
        elif act == "send":
            conversation_store.record_turn(
                conversation_id=req.conversation_id,
                role="vera",
                message=intercepted["body"],
                extra={"action": "send", "cta": intercepted.get("cta", "open_ended"), "rationale": intercepted["rationale"]},
            )
        return JSONResponse(status_code=status.HTTP_200_OK, content=intercepted)

    # If intent transition occurred, update conversation mode to "action"
    if new_mode == "action":
        conversation_store.set_mode(req.conversation_id, "action")

    current_mode = conv_state.get("mode", "qualifying")

    merchant = context_store.get("merchant", req.merchant_id) if req.merchant_id else None
    customer = context_store.get("customer", req.customer_id) if req.customer_id else None

    # Compose reply decision via Gemini
    decision = composer.compose_reply(
        merchant=merchant,
        trigger=None,
        customer=customer,
        conversation_history=conv_state.get("turns", []),
        inbound_message=req.message,
        conversation_mode=current_mode,
    )

    # If in action mode, guarantee action=='send' and sanitize body to have action words and no qualifying questions
    if current_mode == "action":
        if decision.action != "send" or not decision.body:
            decision.action = "send"
            decision.body = "Done, here is the draft. We will proceed with the next step right away."
            decision.cta = "none"
            decision.rationale = "Merchant committed; switched immediately to concrete action step."
        else:
            decision.body = guard_layer.sanitize_action_mode_body(decision.body)

    # Record and return decision
    if decision.action == "send" and decision.body:
        conversation_store.record_turn(
            conversation_id=req.conversation_id,
            role="vera",
            message=decision.body,
            extra={"action": "send", "cta": decision.cta, "rationale": decision.rationale},
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "action": "send",
                "body": decision.body,
                "cta": decision.cta,
                "rationale": decision.rationale,
            },
        )
    elif decision.action == "wait":
        conversation_store.set_wait(req.conversation_id, decision.wait_seconds or 14400)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "action": "wait",
                "wait_seconds": decision.wait_seconds or 14400,
                "rationale": decision.rationale,
            },
        )
    else:
        conversation_store.set_ended(req.conversation_id, True)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "action": "end",
                "rationale": decision.rationale,
            },
        )


@app.get("/")
async def root():
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "service": "magicpin Vera Message Engine",
            "status": "healthy",
            "version": "1.0.0",
            "endpoints": [
                "/v1/healthz",
                "/v1/metadata",
                "/v1/context",
                "/v1/tick",
                "/v1/reply"
            ]
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
            # update this to the real date before we submit
            "submitted_at": "2026-09-26T19:30:00Z",
        },
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("bot:app", host="0.0.0.0", port=port, reload=False)
