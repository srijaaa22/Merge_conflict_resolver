import logging
import re
import uuid

from dotenv import load_dotenv

from app.models.schemas import (
    Confidence,
    HistoryEntry,
    ResolutionStrategy,
    ResolveResponse,
    RiskFlag,
    Strategy,
)
from app.state import analyzed_hunks, history

load_dotenv()

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.6-flash"
_client = None

# Max lines of "ours" / "theirs" (each, separately) sent to Gemini.
# Longer sides keep their first and last MAX_HUNK_LINES // 2 lines.
# Only the prompt is trimmed: stored hunks, ours/theirs resolutions and
# MCP's raw hunk fetch always keep the full text.
MAX_HUNK_LINES = 200


class HunkNotFoundError(Exception):
    """hunk_id isn't in server storage (maps to HTTP 404)."""


class LLMUnavailableError(Exception):
    """Gemini call failed: rate limit, network, missing key, etc. (maps to HTTP 503)."""


class LLMResponseError(Exception):
    """Gemini returned output that doesn't match our schema (maps to HTTP 500)."""


def _get_client():
    """Create the Gemini client on first use, so ours/theirs never need a key or the SDK."""
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client()
    return _client


def get_hunk(hunk_id: str) -> dict:
    hunk = analyzed_hunks.get(hunk_id)
    if hunk is None:
        raise HunkNotFoundError(f"hunk_id not found: {hunk_id}")
    return hunk


def ensure_session(session_id: str | None) -> tuple[str, bool]:
    """Return (session_id, is_new). Generates a server-side UUID when none is supplied."""
    if not session_id:
        return str(uuid.uuid4()), True
    return session_id, False


def _truncate_side(text: str) -> tuple[str, int]:
    """Cap one side of a conflict at MAX_HUNK_LINES.

    Returns (text_for_prompt, lines_omitted). Text within the cap is returned
    unchanged with 0 omitted. Otherwise the first and last MAX_HUNK_LINES // 2
    lines are kept with an explicit marker in between.
    """
    lines = re.findall(r"[^\n]*\n|[^\n]+", text)
    if len(lines) <= MAX_HUNK_LINES:
        return text, 0

    keep = MAX_HUNK_LINES // 2
    omitted = len(lines) - 2 * keep
    marker = f"[... {omitted} lines omitted ...]\n"
    return "".join(lines[:keep]) + marker + "".join(lines[-keep:]), omitted


def _build_prompt(hunk: dict) -> tuple[str, int, int]:
    """Return (prompt, ours_lines_omitted, theirs_lines_omitted)."""
    # Each context line already ends in a newline, so join with "" (not "\n").
    context_before = "".join(hunk.get("context_before", []))
    context_after = "".join(hunk.get("context_after", []))

    ours, ours_omitted = _truncate_side(hunk["ours"])
    theirs, theirs_omitted = _truncate_side(hunk["theirs"])

    truncation_note = ""
    if ours_omitted or theirs_omitted:
        truncation_note = (
            "\n    NOTE: one or both sides below were too long and had their middle lines "
            "replaced by a marker like [... N lines omitted ...]. Do not guess or invent the "
            "omitted code. Keep your resolution conservative and mention the truncation in "
            "your reasoning.\n"
        )

    prompt = f"""
    You are an expert at resolving Git merge conflicts.
{truncation_note}
    File: {hunk.get("filepath", "unknown")}

    Context before the conflict:
    {context_before}

    Ours (HEAD):
    {ours}

    Theirs (branch: {hunk["branch_name"]}):
    {theirs}

    Context after the conflict:
    {context_after}

    Task: propose the single best resolution for this conflict. Commit to one resolution,
    do not present multiple options. Explain your reasoning briefly.
    """
    return prompt, ours_omitted, theirs_omitted


def build_prompt(hunk: dict) -> str:
    """Format a hunk dict into a labeled prompt for the smart resolution strategy."""
    return _build_prompt(hunk)[0]


def _resolve_with_llm(hunk: dict) -> ResolveResponse:
    prompt, ours_omitted, theirs_omitted = _build_prompt(hunk)

    try:
        interaction = _get_client().interactions.create(
            model=GEMINI_MODEL,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": ResolveResponse.model_json_schema(),
            },
        )
    except Exception as e:
        logger.error("Gemini call failed: %s", e)
        raise LLMUnavailableError("LLM service unavailable, please retry shortly") from e

    try:
        res = ResolveResponse.model_validate_json(interaction.output_text)
    except (ValueError, TypeError) as e:  # pydantic's ValidationError is a ValueError
        logger.error("Malformed Gemini output: %s", e)
        raise LLMResponseError("Malformed response from LLM") from e

    # risk_flag is a placeholder until real flagging logic exists; don't trust the model's value.
    update = {"risk_flag": RiskFlag.LOW}

    if ours_omitted or theirs_omitted:
        # The model only saw part of the conflict, so never let this look trustworthy.
        update["confidence"] = Confidence.LOW
        update["reasoning"] = (
            f"{res.reasoning}\n\n"
            f"WARNING: input was truncated before reaching the model "
            f"({ours_omitted} lines omitted from 'ours', {theirs_omitted} from 'theirs'). "
            f"This resolution is based on partial input; review it manually before using it."
        )

    return res.model_copy(update=update)


def resolve_hunk(hunk_id: str, strategy: Strategy | str, session_id: str) -> ResolveResponse:
    strategy = Strategy(strategy)  # accepts plain strings too (e.g. from MCP tools)

    hunk = get_hunk(hunk_id)

    if strategy == Strategy.OURS:
        res = ResolveResponse(
            resolution=hunk["ours"],
            reasoning="took ours as-is, no LLM resolution",
            confidence=Confidence.HIGH,
            risk_flag=RiskFlag.LOW,
            strategy=ResolutionStrategy.TOOK_OURS,
        )
    elif strategy == Strategy.THEIRS:
        res = ResolveResponse(
            resolution=hunk["theirs"],
            reasoning="took theirs as-is, no LLM resolution",
            confidence=Confidence.HIGH,
            risk_flag=RiskFlag.LOW,
            strategy=ResolutionStrategy.TOOK_THEIRS,
        )
    else:
        res = _resolve_with_llm(hunk)

    history.setdefault(session_id, []).append(HistoryEntry(hunk_id=hunk_id, result=res))
    return res


def get_history(session_id: str) -> list[HistoryEntry]:
    return history.get(session_id, [])


def clear_history(session_id: str) -> int:
    return len(history.pop(session_id, []))