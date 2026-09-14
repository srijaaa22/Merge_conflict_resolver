from fastapi import APIRouter, Header, Response
import uuid

from app.state import history
from app.models.schemas import HistoryResponse, HistoryEntry

router = APIRouter()

@router.get("/history", response_model=HistoryResponse)
def get_history(response: Response, x_session_id: str | None = Header(default=None, alias="X-Session-Id")):
    if x_session_id is None:
        session_id = str(uuid.uuid4())
        response.headers["X-Session-Id"] = session_id
    else:
        session_id = x_session_id

    session_history = history.get(session_id, [])

    return HistoryResponse(
        history=session_history,
        count=len(session_history)
    )

@router.delete("/history", response_model=None)
def delete_history(response: Response, x_session_id: str | None = Header(default=None, alias="X-Session-Id")):
    if x_session_id is None:
        session_id = str(uuid.uuid4())
        response.headers["X-Session-Id"] = session_id
        return {"deleted_count": 0}
    
    session_id = x_session_id
    deleted_count = len(history.get(session_id, []))
    history.pop(session_id, None)

    return {"deleted_count": deleted_count}