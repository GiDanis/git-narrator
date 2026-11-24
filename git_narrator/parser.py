"""5-tier fallback JSON parser and heuristic auto-repair for LLM outputs."""

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from git_narrator.schemas import (
    ComponentMutation,
    GitNarratorReport,
    RiskRadarItem,
    VisualFlow,
    infer_blast_radius,
)

logger = logging.getLogger(__name__)


class JSONParseError(Exception):
    """Raised when all JSON parsing tiers fail."""


def extract_code_fences(text: str) -> list[str]:
    """Tier 2: Extract JSON candidates from markdown code fences."""
    candidates: list[str] = []

    # First check an outer ```json ... ``` fence wrapping the entire response (resilient to ``` inside strings)
    outer_match = re.search(r"```(?:json)?\s*\n([\s\S]*)\n\s*```\s*$", text.strip(), re.IGNORECASE)
    if outer_match:
        inner = outer_match.group(1).strip()
        if inner.startswith("{"):
            candidates.append(inner)

    pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    matches = re.findall(pattern, text, re.IGNORECASE)
    for m in matches:
        stripped = m.strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

    return candidates


def extract_balanced_braces(text: str) -> str | None:
    """Tier 3: Extract the first top-level balanced JSON object while respecting strings."""
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(text)):
        ch = text[idx]
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
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1].strip()

    # Fallback to outermost braces if balanced scan did not close cleanly
    last_brace = text.rfind("}")
    if last_brace > start:
        return text[start : last_brace + 1].strip()
    return None


def repair_truncated_json(text: str) -> str:
    """Tier 4: Auto-repair truncated JSON string using stack & heuristic auto-closing.

    Handles:
    - Unclosed strings and trailing escapes
    - Partial literals (true, false, null) and incomplete numbers
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
            elif (ch == "}" and stack and stack[-1] == "{") or (ch == "]" and stack and stack[-1] == "["):
                stack.pop()

    # If truncated mid-escape
    if escape:
        s = s[:-1]

    # If truncated inside an unclosed string
    if in_string:
        s += '"'

    s = s.rstrip()

    # If truncated inside a bare literal (e.g., ': tru', ': nul', ': fal') or trailing dot/minus
    partial_literal = re.search(r"([:\[,]\s*)(tr?u?e?|fa?l?s?e?|nu?l?l?|-|\d+\.)$", s)
    if partial_literal and not re.search(r"^(true|false|null|\d+)$", partial_literal.group(2)):
        s = s[: partial_literal.start(2)] + "null"

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
    candidates_to_repair = [raw_text, *code_blocks]
    if candidate:
        candidates_to_repair.append(candidate)

    for item in candidates_to_repair:
        try:
            repaired_str = repair_truncated_json(item)
            data = json.loads(repaired_str)
            if isinstance(data, dict):
                return data, 4
        except (JSONParseError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            logger.debug("Tier 4 JSON repair candidate failed: %s", exc)

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
    lines = [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip() and not line.strip().startswith("```")
    ]
    first_line = lines[0] if lines else "Architectural analysis summary"
    headline = first_line[:120]
    commit = extract_conventional_commit(raw_text)
    body_excerpt = "\n".join(lines[:15]) if lines else "No detailed text available."

    return {
        "executive_summary": {
            "headline": headline,
            "intent": "Automated architectural recovery from unstructured LLM output.",
            "overall_impact": "Changes detected; please verify details against the source diff.",
            "blast_radius": "MEDIUM",
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


def _coerce_valid_items(raw_items: Any, model_cls: type[RiskRadarItem] | type[ComponentMutation]) -> list[dict[str, Any]]:
    """Validate list entries individually so one malformed entry never nukes the whole list."""
    if not isinstance(raw_items, list):
        return []
    valid: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            validated = model_cls.model_validate(item)
            valid.append(validated.model_dump())
        except ValidationError:
            continue
    return valid


def coerce_report_dict(data: dict[str, Any], raw_text: str) -> dict[str, Any]:
    """Ensure all required fields for GitNarratorReport exist and invalid nested items are cleaned."""
    fallback = build_fallback_dict(raw_text)

    # Executive summary
    exec_summary = data.get("executive_summary")
    if not isinstance(exec_summary, dict):
        data["executive_summary"] = fallback["executive_summary"]
    else:
        for k in ("headline", "intent", "overall_impact"):
            if not exec_summary.get(k):
                exec_summary[k] = fallback["executive_summary"][k]
        if not exec_summary.get("blast_radius"):
            exec_summary["blast_radius"] = infer_blast_radius(str(exec_summary["overall_impact"])).value
        if not isinstance(exec_summary.get("tags"), list):
            exec_summary["tags"] = []
        else:
            exec_summary["tags"] = [str(t) for t in exec_summary["tags"] if t]

    # Architecture narrative
    arch_narrative = data.get("architecture_narrative")
    if not isinstance(arch_narrative, dict):
        data["architecture_narrative"] = fallback["architecture_narrative"]
    else:
        for k in ("before_state", "after_state", "tech_debt"):
            if not arch_narrative.get(k):
                arch_narrative[k] = fallback["architecture_narrative"][k]
        arch_narrative["components_affected"] = _coerce_valid_items(
            arch_narrative.get("components_affected"), ComponentMutation
        )

    # Visual flow
    vf = data.get("visual_flow")
    if isinstance(vf, dict):
        try:
            data["visual_flow"] = VisualFlow.model_validate(vf).model_dump()
        except ValidationError:
            data["visual_flow"] = None
    elif vf is not None:
        data["visual_flow"] = None

    # Review checklist
    review_checklist = data.get("review_checklist")
    if not isinstance(review_checklist, dict):
        data["review_checklist"] = fallback["review_checklist"]
    else:
        checks = review_checklist.get("manual_checks")
        breaks = review_checklist.get("breaking_changes")
        review_checklist["manual_checks"] = [str(x) for x in checks] if isinstance(checks, list) else []
        review_checklist["breaking_changes"] = [str(x) for x in breaks] if isinstance(breaks, list) else []

    # Risk radar — validate item-by-item so 1 bad entry doesn't discard the entire report
    data["risk_radar"] = _coerce_valid_items(data.get("risk_radar"), RiskRadarItem)

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
