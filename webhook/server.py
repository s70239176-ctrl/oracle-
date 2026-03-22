"""
webhook/server.py
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

try:
    import redis
    _redis_url = os.environ.get('REDIS_URL')
    _redis = redis.from_url(_redis_url, decode_responses=True) if _redis_url else None
except ImportError:
    _redis = None

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError:
    print("Install fastapi + uvicorn: pip install fastapi uvicorn")
    sys.exit(1)

import opengradient as og
from agent.fact_checker import FactCheckerAgent, VerificationResult

app = FastAPI(
    title="QuantChain Verifiable Fact-Checker API",
    description="TEE-attested claim verification powered by OpenGradient",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_public = Path(__file__).parent.parent / "public"
if _public.exists():
    app.mount("/static", StaticFiles(directory=str(_public)), name="static")

@app.get("/")
async def root():
    index = _public / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"name": "QuantChain Oracle", "docs": "/docs", "health": "/health"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_mem_cache: dict[str, dict] = {}
_mem_status: dict[str, str] = {}

def cache_set(key, value, prefix="result"):
    if _redis:
        _redis.setex(f"qc:{prefix}:{key}", 86400, json.dumps(value))
    else:
        _mem_cache[key] = value

def cache_get(key, prefix="result"):
    if _redis:
        raw = _redis.get(f"qc:{prefix}:{key}")
        return json.loads(raw) if raw else None
    return _mem_cache.get(key)

def cache_keys(prefix="result"):
    if _redis:
        return [k.split(":")[-1] for k in _redis.keys(f"qc:{prefix}:*")]
    return list(_mem_cache.keys())

def status_set(job_id, status):
    if _redis:
        _redis.setex(f"qc:status:{job_id}", 86400, status)
    else:
        _mem_status[job_id] = status

def status_get(job_id):
    if _redis:
        return _redis.get(f"qc:status:{job_id}")
    return _mem_status.get(job_id)

class VerifyRequest(BaseModel):
    claim: str = Field(..., min_length=5, max_length=2000)
    model: str = Field("claude37")
    settlement: str = Field("full")
    webhook_url: Optional[str] = None
    metadata: Optional[dict] = None

class BatchVerifyRequest(BaseModel):
    claims: list[str] = Field(..., min_items=1, max_items=50)
    model: str = "claude37"
    settlement: str = "full"
    webhook_url: Optional[str] = None

API_KEY = os.environ.get("ORACLE_API_KEY", "")

def check_api_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

MODEL_MAP = {
    "claude37": og.TEE_LLM.CLAUDE_SONNET_4_6,
    "claude35": og.TEE_LLM.CLAUDE_HAIKU_4_5,
    "gpt5":     og.TEE_LLM.GPT_5,
    "gemini25": og.TEE_LLM.GEMINI_2_5_PRO,
}

SETTLEMENT_MAP = {
    "private":  og.x402SettlementMode.PRIVATE,
    "full":     og.x402SettlementMode.INDIVIDUAL_FULL,
    "batch":    og.x402SettlementMode.BATCH_HASHED,
}

def build_agent(model="claude37", settlement="full"):
    return FactCheckerAgent(
        model=MODEL_MAP.get(model, og.TEE_LLM.CLAUDE_SONNET_4_6),
        settlement=SETTLEMENT_MAP.get(settlement, og.x402SettlementMode.INDIVIDUAL_FULL),
        verbose=False,
    )

async def run_verification(job_id, claim, model, settlement, webhook_url, metadata):
    status_set(job_id, "processing")
    try:
        agent = build_agent(model, settlement)
        result = await agent.verify_async(claim)
        result_data = result.to_dict()
        if metadata:
            result_data["caller_metadata"] = metadata
        result_data["job_id"] = job_id
        cache_set(job_id, result_data)
        status_set(job_id, "done")
        if webhook_url:
            await _fire_webhook(webhook_url, result_data)
    except Exception as e:
        status_set(job_id, "error")
        cache_set(job_id, {"error": str(e), "job_id": job_id})

async def _fire_webhook(url, payload):
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

@app.get("/health")
async def health():
    og_ok = bool(os.environ.get("OG_PRIVATE_KEY"))
    return {"status": "ok", "og_connected": og_ok, "timestamp": datetime.now(timezone.utc).isoformat(), "version": "1.0.0"}

@app.post("/verify")
async def verify_claim(req: VerifyRequest, background_tasks: BackgroundTasks, x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)
    job_id = str(uuid.uuid4())
    status_set(job_id, "pending")
    background_tasks.add_task(run_verification, job_id, req.claim, req.model, req.settlement, req.webhook_url, req.metadata)
    return {"job_id": job_id, "status": "pending", "message": f"Poll GET /result/{job_id}"}

@app.post("/verify/sync")
async def verify_claim_sync(req: VerifyRequest, x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)
    try:
        agent = build_agent(req.model, req.settlement)
        result = await agent.verify_async(req.claim)
        result_data = result.to_dict()
        job_id = str(uuid.uuid4())
        result_data["job_id"] = job_id
        cache_set(job_id, result_data)
        status_set(job_id, "done")
        return result_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify/batch")
async def verify_batch(req: BatchVerifyRequest, background_tasks: BackgroundTasks, x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)
    jobs = []
    for claim in req.claims:
        job_id = str(uuid.uuid4())
        status_set(job_id, "pending")
        background_tasks.add_task(run_verification, job_id, claim, req.model, req.settlement, req.webhook_url, None)
        jobs.append({"job_id": job_id, "claim": claim[:60]})
    return {"batch_size": len(jobs), "jobs": jobs}

@app.get("/result/{job_id}")
async def get_result(job_id: str, x_api_key: Optional[str] = Header(None)):
    check_api_key(x_api_key)
    status = status_get(job_id)
    if not status:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"job_id": job_id, "status": status, "result": cache_get(job_id)}

@app.get("/proof/{tx_hash}")
async def get_proof(tx_hash: str):
    for k in cache_keys("result"):
        result = cache_get(k)
        if not result:
            continue
        for step in result.get("proof_chain", []):
            if step.get("tx_hash") == tx_hash:
                return {"found": True, "tx_hash": tx_hash, "step": step, "claim": result.get("claim"), "verdict": result.get("verdict")}
    return {"found": False, "tx_hash": tx_hash}

@app.get("/stats")
async def get_stats():
    keys = cache_keys("result")
    verdicts = {}
    for k in keys:
        r = cache_get(k)
        if r:
            v = r.get("verdict", "UNKNOWN")
            verdicts[v] = verdicts.get(v, 0) + 1
    return {"total_verified": len(keys), "verdict_breakdown": verdicts, "storage": "redis" if _redis else "in-memory", "timestamp": datetime.now(timezone.utc).isoformat()}
