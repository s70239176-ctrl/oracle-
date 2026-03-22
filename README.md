# QuantChain Verifiable Fact-Checker / Oracle Agent

> TEE-attested claim verification powered by **OpenGradient SDK** + **LangChain** + on-chain cryptographic proofs.

Every reasoning step, tool call, and inference is verified inside a **Trusted Execution Environment (TEE)** and produces an on-chain transaction hash — giving you a complete, tamper-proof audit trail for any claim you verify.

---

## Architecture

```
Claim Input
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  FactCheckerAgent                                   │
│                                                     │
│  1. classify_claim_type()  ← heuristic / ML model  │
│  2. LangChain ReAct Agent  ← multi-tool reasoning  │
│     ├── web_search()       ← Brave / SerpAPI        │
│     ├── news_oracle()      ← NewsAPI / GDELT        │
│     ├── fact_database()    ← Snopes / PolitiFact    │
│     ├── statistical_oracle() ← World Bank / FRED   │
│     └── sentiment_classifier() ← bias detection   │
│  3. TEE Reasoning Synthesis ← OpenGradient TEE     │
│  4. TEE Confidence Calibration ← OpenGradient TEE  │
└─────────────────────────────────────────────────────┘
    │
    ▼
VerificationResult
    ├── verdict: TRUE / FALSE / MISLEADING / UNVERIFIABLE
    ├── confidence: 0.0 – 1.0
    ├── summary: plain-English explanation
    ├── evidence: list of sources + stances
    ├── proof_chain: list of attested inference steps
    │     └── each step: { action, tx_hash, timestamp, model }
    ├── composite_hash: SHA-256 of all step hashes
    └── final_tx_hash: OpenGradient on-chain proof
```

---

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/quantchain-oracle.git
cd quantchain-oracle

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your OG_PRIVATE_KEY
```

Get your OpenGradient private key + free test tokens:
- Wallet: any Ethereum-compatible wallet
- Testnet tokens: https://faucet.opengradient.ai

---

## CLI Usage

### Single claim
```bash
python cli/main.py "The moon landing was faked"
```

### With JSON output
```bash
python cli/main.py "Global warming is a hoax" --json
```

### With full proof chain
```bash
python cli/main.py "Vaccines cause autism" --proof
```

### Choose model and settlement mode
```bash
python cli/main.py "claim" --model gpt4o --settlement batch
```

### Interactive REPL
```bash
python cli/main.py --interactive
```

### Batch verify from file
```bash
python cli/main.py --file tests/sample_claims.txt --output results/
```

### All options
```
usage: quantchain-oracle [-h] [--interactive] [--file FILE] [--output OUTPUT]
                          [--json] [--proof] [--verbose]
                          [--model {claude37,claude35,gpt4o,gemini25}]
                          [--settlement {settle,metadata,batch}]
                          [claim]

Options:
  claim                    Claim or headline to verify
  -i, --interactive        Start interactive REPL
  -f, --file FILE          File with one claim per line
  -o, --output OUTPUT      Directory to save JSON results
  --json                   Output raw JSON only
  --proof                  Show full proof chain
  --verbose                Verbose agent logging
  --model MODEL            TEE model (default: claude37)
  --settlement SETTLEMENT  Settlement mode (default: metadata)
```

---

## Webhook Server

Start the API server:
```bash
uvicorn webhook.server:app --reload --port 8000
```

Interactive API docs at: http://localhost:8000/docs

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/verify` | Async verification (returns job_id) |
| `POST` | `/verify/sync` | Synchronous verification |
| `POST` | `/verify/batch` | Batch verify up to 50 claims |
| `GET`  | `/result/{job_id}` | Poll for async result |
| `GET`  | `/proof/{tx_hash}` | Look up a specific TEE proof |
| `GET`  | `/stats` | Usage statistics |
| `GET`  | `/health` | Health check |

### Example: Verify a claim via API

```bash
# Start verification (async)
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "5G networks cause cancer",
    "model": "claude37",
    "settlement": "metadata",
    "webhook_url": "https://your-app.com/webhook"
  }'

# Response:
# {"job_id": "abc-123", "status": "pending", ...}

# Poll for result
curl http://localhost:8000/result/abc-123
```

### Example: Synchronous verification

```bash
curl -X POST http://localhost:8000/verify/sync \
  -H "Content-Type: application/json" \
  -d '{"claim": "Bitcoin uses more energy than Argentina"}'
```

### Webhook Payload (callback)

When a `webhook_url` is provided, QuantChain will POST the result:

```json
{
  "claim": "...",
  "verdict": "FALSE",
  "confidence": 0.91,
  "summary": "...",
  "evidence": [...],
  "proof_chain": [
    {
      "step": 1,
      "action": "TEE Reasoning Synthesis",
      "tx_hash": "0x7b3c...4f12",
      "timestamp": "2025-03-22T10:00:00Z",
      "model": "claude-3-7-sonnet"
    }
  ],
  "composite_hash": "0xabc...def",
  "final_tx_hash": "0x7b3c...4f12"
}
```

Verify webhook authenticity with HMAC-SHA256:
```python
import hmac, hashlib

def verify_signature(payload: bytes, header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header)
```

---

## Python SDK Usage

```python
from agent.fact_checker import FactCheckerAgent
import opengradient as og

agent = FactCheckerAgent(
    model=og.TEE_LLM.CLAUDE_3_7_SONNET,
    settlement=og.x402SettlementMode.SETTLE_METADATA,
    verbose=True,
)

result = agent.verify("The Amazon produces 20% of Earth's oxygen")

print(result.verdict)          # FALSE
print(result.confidence)       # 0.88
print(result.summary)          # Plain-English explanation
print(result.composite_hash)   # 0xabc...def (tamper-proof)

# Each step in the proof chain
for step in result.proof_chain:
    print(step.action, step.tx_hash)

# Export to JSON
print(result.to_json())
```

---

## Settlement Modes

| Mode | Privacy | Transparency | Cost |
|------|---------|--------------|------|
| `settle` | Maximum (hashes only) | Minimal | Medium |
| `metadata` | Balanced | Full input/output | Higher |
| `batch` | Balanced | Full input/output | Lowest |

---

## Enabling Real Sources

Set `USE_REAL_SOURCES=true` in `.env` and add API keys:

```env
USE_REAL_SOURCES=true
BRAVE_API_KEY=your_brave_key      # https://api.search.brave.com
NEWS_API_KEY=your_newsapi_key     # https://newsapi.org
```

---

## Project Structure

```
quantchain-oracle/
├── agent/
│   └── fact_checker.py     # Core FactCheckerAgent + data models
├── cli/
│   └── main.py             # Rich CLI with interactive mode
├── webhook/
│   └── server.py           # FastAPI webhook server
├── utils/
│   ├── sources.py          # Decentralized oracle/source layer
│   └── classifier.py       # Claim type classifier
├── tests/
│   └── sample_claims.txt   # Test claims for batch mode
├── requirements.txt
├── .env.example
└── README.md
```

---

## License

MIT — QuantChain / OpenGradient SDK
