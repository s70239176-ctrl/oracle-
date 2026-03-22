"""
utils/classifier.py
────────────────────
Lightweight claim-type classifier using keyword heuristics.
In production, swap with an OpenGradient Hub ML model via:
    client.alpha.infer(model_cid="your-classifier-cid", model_input={"text": claim})
"""

import re


CLAIM_PATTERNS = {
    "financial": [
        r"\b(stock|market|GDP|inflation|interest rate|economy|recession|crypto|bitcoin|ETF|Fed|reserve)\b",
        r"\$[\d,]+",
        r"\b\d+%\s*(growth|decline|rise|fall|increase|decrease)\b",
    ],
    "scientific": [
        r"\b(study|research|scientists|climate|vaccine|virus|gene|DNA|species|NASA|WHO)\b",
        r"\b(causes?|linked to|associated with|proven|disproven)\b",
        r"\b(temperature|emissions|carbon|fossil fuel|radiation)\b",
    ],
    "political": [
        r"\b(president|senator|congress|parliament|government|election|vote|policy|democrat|republican|legislation)\b",
        r"\b(law|bill|executive order|administration|campaign|candidate)\b",
        r"\b(war|military|sanctions|treaty|diplomacy)\b",
    ],
    "health": [
        r"\b(drug|treatment|cure|symptom|disease|hospital|FDA|CDC|clinical trial|medicine|health)\b",
        r"\b(deaths?|mortality|survival rate|diagnosis|chronic|pandemic|epidemic)\b",
    ],
    "historical": [
        r"\b(in \d{4}|century|decade|world war|historical|founded|invented|discovered|ancient)\b",
        r"\b(first|originally|historically|traditionally)\b",
    ],
}


def classify_claim_type(claim: str) -> str:
    """
    Classify the type of claim using regex pattern matching.
    Returns: financial | scientific | political | health | historical | general
    """
    claim_lower = claim.lower()
    scores = {ctype: 0 for ctype in CLAIM_PATTERNS}

    for ctype, patterns in CLAIM_PATTERNS.items():
        for pattern in patterns:
            matches = re.findall(pattern, claim_lower, re.IGNORECASE)
            scores[ctype] += len(matches)

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def get_claim_context(claim_type: str) -> str:
    """Return additional context instructions based on claim type."""
    contexts = {
        "financial": "Focus on primary financial data sources (Fed, World Bank, Bloomberg). Look for official statistics.",
        "scientific": "Prioritize peer-reviewed sources, WHO, CDC, NASA. Be cautious of preprint vs published studies.",
        "political": "Cross-reference multiple outlets with different political leanings. Focus on verifiable facts not opinions.",
        "health": "Prioritize FDA, CDC, WHO, peer-reviewed medical journals. Note date of studies.",
        "historical": "Check encyclopedias, academic sources, primary historical documents.",
        "general": "Use broad web search and cross-check at least 3 independent sources.",
    }
    return contexts.get(claim_type, contexts["general"])
