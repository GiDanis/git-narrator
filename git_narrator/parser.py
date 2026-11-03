"""5-tier fallback JSON parser and heuristic auto-repair for LLM outputs."""

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from git_narrator.schemas import (
    GitNarratorReport,
)

logger = logging.getLogger(__name__)


class JSONParseError(Exception):
    """Raised when all JSON parsing tiers fail."""


def extract_code_fences(text: str) -> list[str]:
    """Tier 2: Extract text inside markdown code fences."""
    pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    matches = re.findall(pattern, text, re.IGNORECASE)
    return [m.strip() for m in matches if m.strip()]


def extract_balanced_braces(text: str) -> str | None:
    """Tier 3: Extract candidate JSON object from first '{' to last '}'."""
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        return text[first_brace : last_brace + 1].strip()
    return None


def repair_truncated_json(text: str) -> str:
    """Tier 4: Auto-repair truncated JSON string using stack & heuristic auto-closing.

    Handles:
    - Unclosed strings
    - Dangling commas and colons
    - Unclosed brackets '[' and braces '{'
    - Dangling object keys
    """
    first_brace = text.find("{")
    if first_brace == -1:
        raise JSONParseError("No opening JSON brace '{' found for repair.")

    s = text[first_brace:]
    in_string = False
    escape = False
    stack: list[str] = []

    for ch in s:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch in "{[":
                stack.append(ch)
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()

    # If truncated mid-escape
    if escape:
        s = s[:-1]

    # If truncated inside an unclosed string
    if in_string:
        s += '"'

    s = s.rstrip()

    # If ended with a dangling key like: "key" without colon inside an object
    if stack and stack[-1] == "{" and re.search(r'([,{]\s*"[^"]+")\s*$', s):
        s += ": null"

    # Strip trailing commas
    while s.endswith(","):
        s = s[:-1].rstrip()

    # If ending with dangling colon, provide null value
    if s.endswith(":"):
        s += " null"

    while s.endswith(","):
        s = s[:-1].rstrip()

    # Close remaining open brackets and braces
    for item in reversed(stack):
        if item == "{":
            s += "}"
        elif item == "[":
            s += "]"

    # Clean dangling commas and colons before closing delimiters
    s = re.sub(r",\s*([\}\]])", r"\1", s)
    s = re.sub(r":\s*([\}\]])", r": null\1", s)

    return s


def parse_narrator_json(raw_text: str) -> tuple[dict[str, Any], int]:
    """Parse JSON string using a 5-tier fallback cascade.

    Returns:
        tuple[dict, tier_used]: Parsed dictionary and the tier number (1-5) used.

    Tiers:
        1. Direct json.loads
        2. Markdown code fences stripping (```json ... ```)
        3. Balanced brace extraction (first '{' to last '}')
        4. Truncated JSON heuristic repair (stack-based auto-closing)
        5. Fallback dictionary synthesized from raw text
    """
    cleaned = raw_text.strip()
    if not cleaned:
        logger.warning("Empty raw_text provided to parse_narrator_json; falling back to Tier 5.")
        return build_fallback_dict(raw_text), 5

    # Tier 1: Direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data, 1
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Tier 2: Code fence stripping
    code_blocks = extract_code_fences(raw_text)
    for block in code_blocks:
        try:
            data = json.loads(block)
            if isinstance(data, dict):
                return data, 2
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # Tier 3: Balanced brace extraction
    candidate = extract_balanced_braces(raw_text)
    if candidate:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data, 3
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    # Tier 4: Truncated JSON repair
    # Try repairing the raw_text directly or the first candidate found inside code fences
    candidates_to_repair = [raw_text]
    if code_blocks:
        candidates_to_repair.extend(code_blocks)
    if candidate:
        candidates_to_repair.append(candidate)

    for item in candidates_to_repair:
        try:
            repaired_str = repair_truncated_json(item)
            data = json.loads(repaired_str)
            if isinstance(data, dict):
                return data, 4
        except Exception:
            continue

    # Tier 5: Fallback gracefully to raw text extraction
    logger.warning("All JSON parsing tiers failed; synthesizing Tier 5 fallback report.")
    return build_fallback_dict(raw_text), 5


def extract_conventional_commit(text: str) -> str:
    """Extract a conventional commit message from raw text using regex, or generate default."""
    pattern = r"(?:feat|fix|refactor|perf|test|docs|build|chore|ci)(?:\([^)]+\))?:\s*[^\n\r]+"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(0).strip()
    return "chore: update repository changes"


def build_fallback_dict(raw_text: str) -> dict[str, Any]:
    """Tier 5: Synthesize a structural dictionary from raw/unparseable text."""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    first_line = lines[0] if lines else "Architectural analysis summary"
    headline = first_line[:120]

    commit = extract_conventional_commit(raw_text)

    # Excerpt body for narrative
    body_excerpt = "\n".join(lines[:15]) if lines else "No detailed text available."

    return {
        "executive_summary": {
            "headline": headline,
            "intent": "Automated architectural recovery from unstructured LLM output.",
            "overall_impact": "Changes detected; please verify details against the source diff.",
            "tags": ["auto-recovery", "unstructured-output"],
        },
        "architecture_narrative": {
            "before_state": "Legacy / previous state prior to changeset.",
            "after_state": body_excerpt,
            "tech_debt": "Unstructured LLM response; manual review of tech debt required.",
            "components_affected": [],
        },
        "risk_radar": [],
        "visual_flow": None,
        "review_checklist": {
            "manual_checks": [
                "Verify changeset manually as LLM output required fallback recovery.",
                "Check unit and integration test coverage.",
            ],
            "breaking_changes": [],
        },
        "conventional_commit": commit,
    }


def coerce_report_dict(data: dict[str, Any], raw_text: str) -> dict[str, Any]:
    """Ensure all required fields for GitNarratorReport exist in the dictionary."""
    fallback = build_fallback_dict(raw_text)

    # Executive summary
    exec_summary = data.get("executive_summary")
    if not isinstance(exec_summary, dict):
        data["executive_summary"] = fallback["executive_summary"]
    else:
        for k in ("headline", "intent", "overall_impact"):
            if not exec_summary.get(k):
                exec_summary[k] = fallback["executive_summary"][k]
        if not isinstance(exec_summary.get("tags"), list):
            exec_summary["tags"] = []

    # Architecture narrative
    arch_narrative = data.get("architecture_narrative")
    if not isinstance(arch_narrative, dict):
        data["architecture_narrative"] = fallback["architecture_narrative"]
    else:
        for k in ("before_state", "after_state", "tech_debt"):
            if not arch_narrative.get(k):
                arch_narrative[k] = fallback["architecture_narrative"][k]
        if not isinstance(arch_narrative.get("components_affected"), list):
            arch_narrative["components_affected"] = []

    # Review checklist
    review_checklist = data.get("review_checklist")
    if not isinstance(review_checklist, dict):
        data["review_checklist"] = fallback["review_checklist"]
    else:
        if not isinstance(review_checklist.get("manual_checks"), list):
            review_checklist["manual_checks"] = []
        if not isinstance(review_checklist.get("breaking_changes"), list):
            review_checklist["breaking_changes"] = []

    # Risk radar
    if not isinstance(data.get("risk_radar"), list):
        data["risk_radar"] = []

    # Conventional commit
    if not data.get("conventional_commit") or not isinstance(data.get("conventional_commit"), str):
        data["conventional_commit"] = fallback["conventional_commit"]

    return data


def parse_and_validate_report(raw_text: str) -> GitNarratorReport:
    """Parse raw LLM response through the 5-tier cascade and return a validated GitNarratorReport."""
    parsed_dict, tier = parse_narrator_json(raw_text)

    try:
        return GitNarratorReport.model_validate(parsed_dict)
    except ValidationError:
        logger.warning("Pydantic validation failed on tier %d output; applying coercion repair.", tier)
        repaired_dict = coerce_report_dict(parsed_dict, raw_text)
        try:
            return GitNarratorReport.model_validate(repaired_dict)
        except ValidationError as final_err:
            logger.error("Final validation error after coercion: %s. Using tier 5 fallback.", final_err)
            return GitNarratorReport.model_validate(build_fallback_dict(raw_text))
