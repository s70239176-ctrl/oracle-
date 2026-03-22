#!/usr/bin/env python3
"""
QuantChain Verifiable Fact-Checker CLI
========================================
Usage:
    python cli/main.py "The moon landing was faked"
    python cli/main.py --file claims.txt --output results/
    python cli/main.py --interactive
    python cli/main.py "claim" --json
    python cli/main.py "claim" --model gpt4o --settlement batch
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.fact_checker import FactCheckerAgent, VerificationResult
import opengradient as og


# ─────────────────────────────────────────────
# ANSI Colors
# ─────────────────────────────────────────────

class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    PURPLE = "\033[95m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"

def c(color: str, text: str) -> str:
    return f"{color}{text}{C.RESET}"


# ─────────────────────────────────────────────
# Display Helpers
# ─────────────────────────────────────────────

VERDICT_COLORS = {
    "TRUE":         (C.GREEN,  "✅ TRUE"),
    "FALSE":        (C.RED,    "❌ FALSE"),
    "MISLEADING":   (C.YELLOW, "⚠️  MISLEADING"),
    "UNVERIFIABLE": (C.BLUE,   "❓ UNVERIFIABLE"),
}

CONFIDENCE_BAR_WIDTH = 30

def confidence_bar(score: float) -> str:
    filled = int(score * CONFIDENCE_BAR_WIDTH)
    bar = "█" * filled + "░" * (CONFIDENCE_BAR_WIDTH - filled)
    color = C.GREEN if score > 0.75 else C.YELLOW if score > 0.5 else C.RED
    return f"{color}[{bar}]{C.RESET} {score:.0%}"


def print_banner():
    print(f"""
{c(C.CYAN, C.BOLD + '╔══════════════════════════════════════════════════════╗')}
{c(C.CYAN, '║')}  {c(C.WHITE+C.BOLD, 'QuantChain')} {c(C.PURPLE, 'Verifiable Fact-Checker')}              {c(C.CYAN, '║')}
{c(C.CYAN, '║')}  {c(C.DIM, 'Powered by OpenGradient TEE · LangChain · On-Chain')}  {c(C.CYAN, '║')}
{c(C.CYAN, '╚══════════════════════════════════════════════════════╝')}
""")


def print_result(result: VerificationResult, show_proof_chain: bool = False):
    color, label = VERDICT_COLORS.get(result.verdict, (C.WHITE, result.verdict))

    print(f"\n{c(C.BOLD, '─'*58)}")
    print(f"  {c(C.DIM, 'CLAIM')}   {result.claim[:72]}{'...' if len(result.claim) > 72 else ''}")
    print(f"  {c(C.DIM, 'TYPE')}    {c(C.PURPLE, result.claim_type.upper())}")
    print(f"  {c(C.DIM, 'VERDICT')} {c(color, C.BOLD + label)}")
    print(f"  {c(C.DIM, 'CONFID.')} {confidence_bar(result.confidence)}")
    print(f"{c(C.BOLD, '─'*58)}\n")

    print(f"  {c(C.BOLD, 'Summary')}")
    print(f"  {result.summary}\n")

    if result.evidence:
        print(f"  {c(C.BOLD, 'Evidence')}")
        for i, ev in enumerate(result.evidence[:5], 1):
            source = ev.get("source") or ev.get("tool") or ev.get("oracle", "Unknown")
            stance = ev.get("stance") or ev.get("verdict", "")
            excerpt = ev.get("excerpt") or ev.get("result_preview") or ev.get("query", "")
            stance_color = C.GREEN if "support" in str(stance).lower() else C.RED if "refut" in str(stance).lower() else C.YELLOW
            print(f"  {c(C.DIM, str(i)+'.')} {c(C.CYAN, source)}", end="")
            if stance:
                print(f"  {c(stance_color, stance)}", end="")
            print(f"\n     {c(C.DIM, str(excerpt)[:80])}")
        print()

    print(f"  {c(C.BOLD, 'Cryptographic Proof')}")
    print(f"  {c(C.DIM, 'Final TX')}    {c(C.GREEN, result.final_tx_hash[:52]+'...' if len(result.final_tx_hash) > 52 else result.final_tx_hash)}")
    print(f"  {c(C.DIM, 'Chain Hash')}  {c(C.GREEN, result.composite_hash[:52]+'...')}")
    print(f"  {c(C.DIM, 'Steps')}       {len(result.proof_chain)} attested inference steps")
    print(f"  {c(C.DIM, 'Sources')}     {result.sources_checked} oracles checked")
    print(f"  {c(C.DIM, 'Model')}       {result.model_used}")
    print(f"  {c(C.DIM, 'Checked')}     {result.checked_at}")

    if show_proof_chain and result.proof_chain:
        print(f"\n  {c(C.BOLD, 'Full Proof Chain')}")
        for step in result.proof_chain:
            print(f"  {c(C.DIM, '[Step '+str(step.step)+']')} {c(C.PURPLE, step.action)}")
            print(f"     TX: {c(C.GREEN, step.tx_hash)}")
            print(f"     {c(C.DIM, step.output[:80]+'...' if len(step.output) > 80 else step.output)}")

    print(f"\n{c(C.DIM, '─'*58)}\n")


def spinner_verify(agent: FactCheckerAgent, claim: str) -> VerificationResult:
    """Show a spinner while verifying."""
    frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    i = 0
    result = None
    error = None

    import threading

    def run():
        nonlocal result, error
        try:
            result = agent.verify(claim)
        except Exception as e:
            error = e

    thread = threading.Thread(target=run)
    thread.start()

    while thread.is_alive():
        frame = frames[i % len(frames)]
        print(f"\r  {c(C.CYAN, frame)} Verifying claim via OpenGradient TEE...   ", end="", flush=True)
        i += 1
        time.sleep(0.1)

    print("\r" + " " * 60 + "\r", end="")
    thread.join()

    if error:
        raise error
    return result


# ─────────────────────────────────────────────
# Interactive Mode
# ─────────────────────────────────────────────

def interactive_mode(agent: FactCheckerAgent, output_dir: str = None):
    print_banner()
    print(f"  {c(C.DIM, 'Interactive mode. Type a claim to verify, or:')}")
    print(f"  {c(C.CYAN, '/help')} {c(C.DIM, '— show commands')}")
    print(f"  {c(C.CYAN, '/proof')} {c(C.DIM, '— toggle proof chain display')}")
    print(f"  {c(C.CYAN, '/json')} {c(C.DIM, '— toggle JSON output mode')}")
    print(f"  {c(C.CYAN, '/exit')} {c(C.DIM, '— quit')}\n")

    show_proof = False
    json_mode = False

    while True:
        try:
            claim = input(f"  {c(C.CYAN, '❯')} ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n  {c(C.DIM, 'Goodbye.')}\n")
            break

        if not claim:
            continue
        if claim == "/exit":
            print(f"\n  {c(C.DIM, 'Goodbye.')}\n")
            break
        if claim == "/proof":
            show_proof = not show_proof
            print(f"  {c(C.DIM, 'Proof chain display: ' + ('ON' if show_proof else 'OFF'))}\n")
            continue
        if claim == "/json":
            json_mode = not json_mode
            print(f"  {c(C.DIM, 'JSON mode: ' + ('ON' if json_mode else 'OFF'))}\n")
            continue
        if claim == "/help":
            print(f"\n  Commands: /proof /json /exit\n  Just type any claim to verify it.\n")
            continue

        try:
            result = spinner_verify(agent, claim)

            if json_mode:
                print(result.to_json())
            else:
                print_result(result, show_proof_chain=show_proof)

            if output_dir:
                save_result(result, output_dir)

        except Exception as e:
            print(f"\n  {c(C.RED, '✗ Error:')} {e}\n")


# ─────────────────────────────────────────────
# File Batch Mode
# ─────────────────────────────────────────────

def batch_mode(agent: FactCheckerAgent, input_file: str, output_dir: str = None, json_mode: bool = False):
    path = Path(input_file)
    if not path.exists():
        print(f"{c(C.RED, 'Error:')} File not found: {input_file}")
        sys.exit(1)

    claims = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    print(f"\n  {c(C.CYAN, f'Processing {len(claims)} claims from {input_file}...')}\n")

    results = []
    for i, claim in enumerate(claims, 1):
        print(f"  [{i}/{len(claims)}] {claim[:60]}...")
        try:
            result = spinner_verify(agent, claim)
            results.append(result)
            if json_mode:
                print(result.to_json())
            else:
                print_result(result)
            if output_dir:
                save_result(result, output_dir)
        except Exception as e:
            print(f"  {c(C.RED, '✗')} Error: {e}\n")

    # Summary
    verdicts = {r.verdict for r in results}
    print(f"\n  {c(C.BOLD, 'Batch Summary')}")
    print(f"  Processed: {len(results)}/{len(claims)}")
    for v in ["TRUE", "FALSE", "MISLEADING", "UNVERIFIABLE"]:
        count = sum(1 for r in results if r.verdict == v)
        if count:
            color, label = VERDICT_COLORS[v]
            print(f"  {c(color, label)}: {count}")


def save_result(result: VerificationResult, output_dir: str):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = result.claim[:30].replace(" ", "_").replace("/", "-")
    fname = Path(output_dir) / f"result_{ts}_{slug}.json"
    fname.write_text(result.to_json())
    print(f"  {c(C.DIM, f'Saved → {fname}')}")


# ─────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────

MODEL_MAP = {
    "claude37":  og.TEE_LLM.CLAUDE_SONNET_4_6,
    "claude35":  og.TEE_LLM.CLAUDE_HAIKU_4_5,
    "gpt4o":     og.TEE_LLM.GPT_5,
    "gemini25":  og.TEE_LLM.GEMINI_2_5_PRO,
}

SETTLEMENT_MAP = {
    "private":   og.x402SettlementMode.PRIVATE,
    "full":      og.x402SettlementMode.INDIVIDUAL_FULL,
    "batch":     og.x402SettlementMode.BATCH_HASHED,
}


def main():
    parser = argparse.ArgumentParser(
        prog="quantchain-oracle",
        description="QuantChain Verifiable Fact-Checker — TEE-attested claim verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli/main.py "The moon landing was faked"
  python cli/main.py "Inflation hit 40-year highs in 2022" --json
  python cli/main.py --interactive
  python cli/main.py --file claims.txt --output results/
  python cli/main.py "climate claim" --model gemini25 --settlement batch --proof
        """
    )

    parser.add_argument("claim", nargs="?", help="Claim or headline to verify")
    parser.add_argument("-i", "--interactive", action="store_true", help="Start interactive REPL")
    parser.add_argument("-f", "--file", help="Path to file with one claim per line")
    parser.add_argument("-o", "--output", help="Directory to save JSON results")
    parser.add_argument("--json", action="store_true", help="Output raw JSON only")
    parser.add_argument("--proof", action="store_true", help="Show full proof chain")
    parser.add_argument("--verbose", action="store_true", help="Verbose agent logging")
    parser.add_argument(
        "--model", choices=list(MODEL_MAP.keys()), default="claude37",
        help="TEE model to use (default: claude37)"
    )
    parser.add_argument(
        "--settlement", choices=list(SETTLEMENT_MAP.keys()), default="full",
        help="OpenGradient settlement mode (default: metadata)"
    )

    args = parser.parse_args()

    # Build agent
    model = MODEL_MAP[args.model]
    settlement = SETTLEMENT_MAP[args.settlement]
    agent = FactCheckerAgent(model=model, settlement=settlement, verbose=args.verbose)

    # Route
    if args.interactive:
        interactive_mode(agent, output_dir=args.output)

    elif args.file:
        print_banner()
        batch_mode(agent, args.file, output_dir=args.output, json_mode=args.json)

    elif args.claim:
        if not args.json:
            print_banner()
        try:
            result = spinner_verify(agent, args.claim)
            if args.json:
                print(result.to_json())
            else:
                print_result(result, show_proof_chain=args.proof)
            if args.output:
                save_result(result, args.output)
        except Exception as e:
            print(f"{c(C.RED, 'Error:')} {e}", file=sys.stderr)
            sys.exit(1)

    else:
        if not args.json:
            print_banner()
        print(f"  {c(C.DIM, 'No claim provided. Use --interactive or pass a claim as argument.')}")
        print(f"  {c(C.CYAN, 'Example:')} python cli/main.py \"The moon landing was faked\"\n")
        parser.print_help()


if __name__ == "__main__":
    main()
