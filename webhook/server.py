"""
webhook/server.py
──────────────────
Optional FastAPI webhook server for QuantChain Fact-Checker.
Allows external integrations to POST claims and receive verifiable results.

Start:
    uvicorn webhook.server:app --reload --port 8000

Endpoints:
    POST /verify              — verify a single claim
    POST /verify/batch        — verify multiple claims
    GET  /result/{result_id}  — retrieve a cached result
    GET  /health              — health check
    GET  /proof/{tx_hash}     — look up a specific proof
"""

import os
import sys
import uuid
import json
import hmac
import hashlib
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
except ImportError:
    print("Install fastapi + uvicorn: pip install fastapi uvicorn")
    sys.exit(1)

import opengradient as og
from agent.fact_checker import FactCheckerAgent, VerificationResult


# ─────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────

app = FastAPI(
    title="QuantChain Verifiable Fact-Checker API",
    description="TEE-attested claim verification powered by OpenGradient",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory result cache (use Redis in production)
result_cache: dict[str, dict] = {}
job_status: dict[str, str] = {}  # job_id → "pending" | "done" | "error"


# ─────────────────────────────────────────────
# Request / Response Models
# ─────────────────────────────────────────────

class VerifyRequest(BaseModel):
    claim: str = Field(..., min_length=5, max_length=2000, example="The moon landing was faked")
    model: str = Field("claude37", example="claude37", description="TEE model: claude37 | gpt4o | gemini25")
    settlement: str = Field("metadata", example="metadata", description="settle | metadata | batch")
    webhook_url: Optional[str] = Field(None, description="Optional callback URL for async result delivery")
    metadata: Optional[dict] = Field(None, description="Optional caller metadata (id, source, etc.)")


class BatchVerifyRequest(BaseModel):
    claims: list[str] = Field(..., min_items=1, max_items=50)
    model: str = "claude37"
    settlement: str = "metadata"
    webhook_url: Optional[str] = None


class VerifyResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[dict] = None
    message: str


class HealthResponse(BaseModel):
    status: str
    og_connected: bool
    timestamp: str
    version: str


# ─────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 webhook signature."""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


API_KEY = os.environ.get("ORACLE_API_KEY", "")

def check_api_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ─────────────────────────────────────────────
# Agent Factory
# ─────────────────────────────────────────────

MODEL_MAP = {
    "claude37": og.TEE_LLM.CLAUDE_SONNET_4_6,
    "claude35": og.TEE_LLM.CLAUDE_HAIKU_4_5,
    "gpt4o":    og.TEE_LLM.GPT_5,
    "gemini25": og.TEE_LLM.GEMINI_2_5_PRO,
}

SETTLEMENT_MAP = {
    "settle":   og.x402SettlementMode.PRIVATE,
    "metadata": og.x402SettlementMode.INDIVIDUAL_FULL,
    "batch":    og.x402SettlementMode.BATCH_HASHED,
}

def build_agent(model: str = "claude37", settlement: str = "metadata") -> FactCheckerAgent:
    return FactCheckerAgent(
        model=MODEL_MAP.get(model, og.TEE_LLM.CLAUDE_SONNET_4_6),
        settlement=SETTLEMENT_MAP.get(settlement, og.x402SettlementMode.INDIVIDUAL_FULL),
        verbose=False,
    )


# ─────────────────────────────────────────────
# Background Job Runner
# ─────────────────────────────────────────────

async def run_verification(job_id: str, claim: str, model: str, settlement: str,
                            webhook_url: Optional[str], metadata: Optional[dict]):
    job_status[job_id] = "processing"
    try:
        agent = build_agent(model, settlement)
        loop = asyncio.get_event_loop()
        result = await agent.verify_async(claim)

        result_data = result.to_dict()
        if metadata:
            result_data["caller_metadata"] = metadata
        result_data["job_id"] = job_id

        result_cache[job_id] = result_data
        job_status[job_id] = "done"

        # Fire webhook callback if provided
        if webhook_url:
            await _fire_webhook(webhook_url, result_data)

    except Exception as e:
        job_status[job_id] = "error"
        result_cache[job_id] = {"error": str(e), "job_id": job_id}


async def _fire_webhook(url: str, payload: dict):
    """POST result to webhook URL."""
    try:
        import httpx
        secret = os.environ.get("WEBHOOK_SECRET", "")
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if secret:
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-QuantChain-Signature"] = f"sha256={sig}"
        async with httpx.AsyncClient() as client:
            await client.post(url, content=body, headers=headers, timeout=10)
    except Exception as e:
        print(f"Webhook delivery failed: {e}")


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    og_ok = bool(os.environ.get("OG_PRIVATE_KEY"))
    return {
        "status": "ok",
        "og_connected": og_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
    }


@app.post("/verify", response_model=VerifyResponse)
async def verify_claim(req: VerifyRequest, background_tasks: BackgroundTasks,
                        x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)

    job_id = str(uuid.uuid4())
    job_status[job_id] = "pending"

    background_tasks.add_task(
        run_verification,
        job_id, req.claim, req.model, req.settlement, req.webhook_url, req.metadata
    )

    return {
        "job_id": job_id,
        "status": "pending",
        "result": None,
        "message": f"Verification started. Poll GET /result/{job_id} or provide webhook_url.",
    }


@app.post("/verify/sync")
async def verify_claim_sync(req: VerifyRequest, x_api_key: Optional[str] = Header(None)):
    """Synchronous verification — waits for result (use for short claims)."""
    check_api_key(x_api_key)
    try:
        agent = build_agent(req.model, req.settlement)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, agent.verify, req.claim)
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/verify/batch")
async def verify_batch(req: BatchVerifyRequest, background_tasks: BackgroundTasks,
                        x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)
    jobs = []
    for claim in req.claims:
        job_id = str(uuid.uuid4())
        job_status[job_id] = "pending"
        background_tasks.add_task(
            run_verification, job_id, claim, req.model, req.settlement, req.webhook_url, None
        )
        jobs.append({"job_id": job_id, "claim": claim[:60]})

    return {"batch_size": len(jobs), "jobs": jobs}


@app.get("/result/{job_id}")
async def get_result(job_id: str, x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)
    status = job_status.get(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    result = result_cache.get(job_id)
    return {"job_id": job_id, "status": status, "result": result}


@app.get("/proof/{tx_hash}")
async def get_proof(tx_hash: str):
    """Look up a specific TEE proof hash across cached results."""
    for result in result_cache.values():
        chain = result.get("proof_chain", [])
        for step in chain:
            if step.get("tx_hash") == tx_hash:
                return {
                    "found": True,
                    "tx_hash": tx_hash,
                    "step": step,
                    "claim": result.get("claim"),
                    "verdict": result.get("verdict"),
                    "composite_hash": result.get("composite_hash"),
                }
    return {"found": False, "tx_hash": tx_hash}


@app.get("/stats")
async def get_stats():
    """Basic usage statistics."""
    verdicts = {}
    for r in result_cache.values():
        v = r.get("verdict", "UNKNOWN")
        verdicts[v] = verdicts.get(v, 0) + 1

    return {
        "total_verified": len(result_cache),
        "verdict_breakdown": verdicts,
        "active_jobs": sum(1 for s in job_status.values() if s == "processing"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
@app.get("/")
async def root():
    return {
        "name": "QuantChain Oracle",
        "status": "live",
        "docs": "/docs",
        "endpoints": ["/verify/sync", "/verify", "/verify/batch", "/health", "/stats"]
    }