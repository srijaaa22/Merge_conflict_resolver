from fastapi import APIRouter, HTTPException, Header, Response
from app.models.schemas import ResolveRequest, ResolveResponse, Strategy, HistoryEntry
from app.state import analyzed_hunks, history
from google import genai
from dotenv import load_dotenv
from pydantic import ValidationError
import uuid

load_dotenv()

router = APIRouter()

client = genai.Client()

def build_prompt(hunk: dict) -> str:
    """Format a hunk dict into a labeled prompt for the smart resolution strategy."""
    context_before = "\n".join(hunk.get("context_before", []))
    context_after = "\n".join(hunk.get("context_after", []))

    return f"""
You are an expert at resolving Git merge conflicts.

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

@router.post("/resolve", response_model=ResolveResponse)
def resolve(req: ResolveRequest, response: Response, x_session_id: str | None = Header(default=None, alias="X-Session-Id")):
    if x_session_id is None:
        session_id = str(uuid.uuid4())
        response.headers["X-Session-Id"] = session_id
    else:
        session_id = x_session_id

    if req.hunk_id not in analyzed_hunks:
        raise HTTPException(status_code=404, detail="hunk_id not found")

    hunk = analyzed_hunks[req.hunk_id]

    if req.strategy == Strategy.OURS:
        res = ResolveResponse(
            resolution=hunk["ours"],
            reasoning="took ours as-is, no LLM resolution",
            confidence="high",
            risk_flag="low",
            strategy="took_ours"
        )

    elif req.strategy == Strategy.THEIRS:
        res = ResolveResponse(
            resolution=hunk["theirs"],
            reasoning="took theirs as-is, no LLM resolution",
            confidence="high",
            risk_flag="low",
            strategy="took_theirs"
        )

    elif req.strategy == Strategy.SMART:
        prompt = build_prompt(hunk)

        try:
            interaction = client.interactions.create(
                model="gemini-3.6-flash",
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": ResolveResponse.model_json_schema()
                }
            )
        except Exception as e:
            # Covers rate limits, network errors, timeouts, etc. from the Gemini call itself
            print(f"GEMINI CALL FAILED: {e}")
            raise HTTPException(
                status_code=503,
                detail="LLM service unavailable, please retry shortly"
            )

        try:
            res = ResolveResponse.model_validate_json(interaction.output_text)
        except ValidationError:
            # Model returned output that doesn't match our schema
            raise HTTPException(
                status_code=500,
                detail="Malformed response from LLM"
            )

    if session_id not in history:
        history[session_id] = []
    history[session_id].append(HistoryEntry(hunk_id=req.hunk_id, result=res))

    return res