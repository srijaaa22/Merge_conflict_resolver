from fastapi import APIRouter, Header, Response

from app.models.schemas import HistoryResponse
from app.services.resolver import clear_history, ensure_session, get_history

router = APIRouter()


@router.get("/history", response_model=HistoryResponse)
def read_history(
    response: Response,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    session_id, is_new = ensure_session(x_session_id)
    if is_new:
        response.headers["X-Session-Id"] = session_id

    entries = get_history(session_id)
    return HistoryResponse(history=entries, count=len(entries))


@router.delete("/history", response_model=None)
def delete_history(
    response: Response,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    session_id, is_new = ensure_session(x_session_id)
    if is_new:
        response.headers["X-Session-Id"] = session_id

    return {"deleted_count": clear_history(session_id)}