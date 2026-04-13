"""
QuantChain Verifiable Fact-Checker Agent
=========================================
Uses OpenGradient TEE inference + LangChain tool calls to verify claims
with full cryptographic attestation of every reasoning step.

Compatible with opengradient >= 0.8.0
"""

import os
import json
import asyncio
import hashlib
import time
from datetime import datetime, timezone
from dataclasses import dataclass, asdict

import opengradient as og

from utils.sources import query_decentralized_sources
from utils.classifier import classify_claim_type


# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

@dataclass
class ProofStep:
    step: int
    action: str
    input: str
    output: str
    tx_hash: str
    timestamp: str
    model: str


@dataclass
class VerificationResult:
    claim: str
    verdict: str          # TRUE / FALSE / MISLEADING / UNVERIFIABLE
    confidence: float
    summary: str
    evidence: list
    proof_chain: list
    final_tx_hash: str
    composite_hash: str
    claim_type: str
    sources_checked: int
    checked_at: str
    model_used: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ─────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are QuantChain's Verifiable Fact-Checker — a rigorous, impartial AI oracle.

Verify claims by analysing the evidence provided and reasoning step-by-step.

Always output a JSON object with exactly these fields:
{
  "verdict": "TRUE" | "FALSE" | "MISLEADING" | "UNVERIFIABLE",
  "confidence": <float 0.0-1.0>,
  "summary": "<2-3 sentence plain-English explanation>",
  "evidence": [
    {"source": "<name>", "supports": true|false|null, "excerpt": "<key finding>"}
  ],
  "reasoning": "<step-by-step chain of thought>"
}

Output ONLY valid JSON — no preamble, no markdown fences."""


# ─────────────────────────────────────────────
# Core Agent
# ─────────────────────────────────────────────

class FactCheckerAgent:
    def __init__(
        self,
        model: og.TEE_LLM = og.TEE_LLM.CLAUDE_SONNET_4_6,
        settlement: og.x402SettlementMode = og.x402SettlementMode.INDIVIDUAL_FULL,
        verbose: bool = False,
    ):
        pk = os.environ.get("OG_PRIVATE_KEY")
        if not pk:
            raise EnvironmentError(
                "OG_PRIVATE_KEY not set. Get test tokens at https://faucet.opengradient.ai"
            )
        # v0.8.0 API: og.LLM instead of og.Client
        self.llm = og.LLM(private_key=pk)
        self.llm.ensure_opg_approval()
        self.model = model
        self.settlement = settlement
        self.verbose = verbose
        self.proof_chain: list[ProofStep] = []
        self._step = 0

    # ── TEE-attested async inference ─────────────────────────────
    async def _attested_call(self, action: str, user_prompt: str) -> tuple[str, str]:
        self._step += 1
        if self.verbose:
            print(f"  [Step {self._step}] {action}...")

        response = await self.llm.chat(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=1000,
            x402_settlement_mode=self.settlement,
        )

        # chat_output is a dict with a "content" key
        output = ""
        if isinstance(response.chat_output, dict):
            output = response.chat_output.get("content", "")
        elif isinstance(response.chat_output, str):
            output = response.chat_output

        tx_hash = getattr(response, "payment_hash", None) or (
            "mock-" + hashlib.sha256(user_prompt.encode()).hexdigest()[:16]
        )

        step = ProofStep(
            step=self._step,
            action=action,
            input=user_prompt[:200] + ("..." if len(user_prompt) > 200 else ""),
            output=output[:300] + ("..." if len(output) > 300 else ""),
            tx_hash=tx_hash,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=str(self.model),
        )
        self.proof_chain.append(step)
        return output, tx_hash

    # ── Gather evidence via oracle tools (sync wrappers) ─────────
    def _gather_evidence(self, claim: str, claim_type: str) -> list[dict]:
        evidence = []
        tool_queries = [
            ("web",       claim),
            ("news",      claim),
            ("factdb",    claim),
        ]
        if claim_type in ("financial", "scientific"):
            tool_queries.append(("stats", claim))
        tool_queries.append(("sentiment", claim))

        for source_type, query in tool_queries:
            try:
                result = query_decentralized_sources(query, source_type=source_type)
                if isinstance(result, list):
                    for item in result:
                        item["_source_type"] = source_type
                    evidence.extend(result[:2])
                elif isinstance(result, dict):
                    result["_source_type"] = source_type
                    evidence.append(result)
            except Exception as e:
                if self.verbose:
                    print(f"  Tool error ({source_type}): {e}")
        return evidence

    # ── Composite hash ────────────────────────────────────────────
    def _composite_hash(self) -> str:
        combined = "".join(s.tx_hash for s in self.proof_chain)
        return "0x" + hashlib.sha256(combined.encode()).hexdigest()

    # ── Main async pipeline ───────────────────────────────────────
    async def _verify_async(self, claim: str) -> VerificationResult:
        self.proof_chain = []
        self._step = 0
        start = time.time()

        if self.verbose:
            print(f"\n{'─'*58}")
            print(f"  QuantChain Fact-Checker")
            print(f"  Claim: {claim[:72]}...")
            print(f"{'─'*58}")

        # 1 — Classify
        claim_type = classify_claim_type(claim)
        if self.verbose:
            print(f"  Claim type: {claim_type}")

        # 2 — Gather decentralized evidence
        if self.verbose:
            print("  Gathering oracle evidence...")
        evidence = self._gather_evidence(claim, claim_type)

        # 3 — TEE reasoning synthesis
        synthesis_prompt = f"""Claim: "{claim}"
Claim type: {claim_type}

Evidence from {len(evidence)} oracle sources:
{json.dumps(evidence[:6], indent=2)}

Synthesise all evidence and output a JSON verdict."""

        synthesis_out, synthesis_tx = await self._attested_call(
            "TEE Reasoning Synthesis", synthesis_prompt
        )

        # 4 — TEE confidence calibration
        calibration_prompt = f"""Previous verdict draft:
{synthesis_out[:600]}

Calibrate confidence (0.0-1.0) based on source agreement, evidence quality,
and claim specificity. Return the updated JSON with calibrated confidence."""

        calibrated_out, calibration_tx = await self._attested_call(
            "TEE Confidence Calibration", calibration_prompt
        )

        verdict_data = self._parse_verdict(calibrated_out or synthesis_out)
        composite = self._composite_hash()
        elapsed = time.time() - start

        if self.verbose:
            print(f"\n  ✓ Done in {elapsed:.1f}s")
            print(f"  Verdict: {verdict_data.get('verdict')} ({float(verdict_data.get('confidence', 0.5)):.0%})")
            print(f"  Proof:   {composite[:40]}...")

        return VerificationResult(
            claim=claim,
            verdict=verdict_data.get("verdict", "UNVERIFIABLE"),
            confidence=float(verdict_data.get("confidence", 0.5)),
            summary=verdict_data.get("summary", "Unable to determine verdict."),
            evidence=verdict_data.get("evidence", evidence[:4]),
            proof_chain=self.proof_chain,
            final_tx_hash=calibration_tx or synthesis_tx,
            composite_hash=composite,
            claim_type=claim_type,
            sources_checked=len(evidence) + 2,
            checked_at=datetime.now(timezone.utc).isoformat(),
            model_used=str(self.model),
        )

    # ── Public sync entry point ───────────────────────────────────
    def verify(self, claim: str) -> VerificationResult:
        """Synchronous wrapper — runs the async pipeline in an event loop."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside an async context (e.g. FastAPI)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._verify_async(claim))
                    return future.result()
            else:
                return loop.run_until_complete(self._verify_async(claim))
        except RuntimeError:
            return asyncio.run(self._verify_async(claim))

    # ── Also expose async directly for FastAPI ───────────────────
    async def verify_async(self, claim: str) -> VerificationResult:
        return await self._verify_async(claim)

    # ── JSON parser ───────────────────────────────────────────────
    def _parse_verdict(self, raw: str) -> dict:
        try:
            clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
            return json.loads(clean)
        except Exception:
            verdict = "UNVERIFIABLE"
            for v in ["TRUE", "FALSE", "MISLEADING"]:
                if v in raw.upper():
                    verdict = v
                    break
            return {
                "verdict": verdict,
                "confidence": 0.5,
                "summary": raw[:300] if raw else "Parse error — raw output in proof chain.",
                "evidence": [],
            }
