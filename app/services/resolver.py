import logging
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


def get_hunk(hunk_id : str) -> dict:
    hunk = analyzed_hunks.get(hunk_id)
    if hunk is None:
        raise HunkNotFoundError(f"hunk_id not found: {hunk_id}")
    return hunk


def ensure_session(session_id: str | None) -> tuple[str, bool]:
    """Return (session_id, is_new). Generates a server-side UUID when none is supplied."""
    if not session_id:
        return str(uuid.uuid4()), True
    return session_id, False


def build_prompt(hunk: dict) -> str:
    """Format a hunk dict into a labeled prompt for the smart resolution strategy."""
    # Each context line already ends in a newline, so join with "" (not "\n").
    context_before = "".join(hunk.get("context_before", []))
    context_after = "".join(hunk.get("context_after", []))

    return f"""
    You are an expert at resolving Git merge conflicts.

    File: {hunk.get("filepath", "unknown")}

    Context before the conflict:
    {context_before}

    Ours (HEAD):
    {hunk["ours"]}

    Theirs (branch: {hunk["branch_name"]}):
    {hunk["theirs"]}

    Context after the conflict:
    {context_after}

    Task: propose the single best resolution for this conflict. Commit to one resolution,
    do not present multiple options. Explain your reasoning briefly.
    """


def _resolve_with_llm(hunk: dict) -> ResolveResponse:
    prompt = build_prompt(hunk)

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
    return res.model_copy(update={"risk_flag": RiskFlag.LOW})


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