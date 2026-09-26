import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from context_store import ContextStore

# Load environment variables
load_dotenv()

# App and initialization
START_TIME = time.time()
context_store = ContextStore()

app = FastAPI(
    title="Vera Message Engine",
    description="Deterministic message-composition engine for magicpin merchants",
    version="1.0.0",
)


class ContextPushRequest(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


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
