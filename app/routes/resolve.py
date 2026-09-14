from fastapi import APIRouter, HTTPException
from app.models.schemas import ResolveRequest, ResolveResponse, Strategy
from app.state import analyzed_hunks

router = APIRouter()

@router.post("/resolve", response_model = ResolveResponse)
def resolve(req: ResolveRequest):
    if req.hunk_id in analyzed_hunks:
        hunk = analyzed_hunks[req.hunk_id]
    else:
        raise HTTPException(status_code = 404, detail = "Hunk_id not found")

    if req.strategy == Strategy.OURS:
        res = ResolveResponse(
            resolution=hunk["ours"],
            reasoning="took ours as-is, no LLM resolution",
            confidence="high",
            risk_flag="low",
            strategy="took_ours"
        )
        return res

    elif req.strategy == Strategy.THEIRS:
        res = ResolveResponse(
                resolution=hunk["theirs"],
                reasoning="took theirs as-is, no LLM resolution",
                confidence="high",
                risk_flag="low",
                strategy="took_theirs"
            )
        return res
    
    elif req.strategy == Strategy.SMART:
        raise HTTPException(status_code = 501, detail = "smart strategy not implemented yet")
