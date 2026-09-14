from fastapi import APIRouter, HTTPException, Header, Response
from app.models.schemas import ResolveRequest, ResolveResponse, Strategy, HistoryEntry
from app.state import analyzed_hunks, history
import uuid

router = APIRouter()

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
        raise HTTPException(status_code=501, detail="smart strategy not implemented yet")

    if session_id not in history:
        history[session_id] = []
    history[session_id].append(HistoryEntry(hunk_id=req.hunk_id, result=res))

    return res