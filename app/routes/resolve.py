from fastapi import APIRouter, HTTPException, Header, Response

from app.models.schemas import ResolveRequest, ResolveResponse
from app.services.resolver import (
    HunkNotFoundError,
    LLMResponseError,
    LLMUnavailableError,
    ensure_session,
    resolve_hunk,
)

router = APIRouter()


@router.post("/resolve", response_model=ResolveResponse)
def resolve(
    req: ResolveRequest,
    response: Response,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
):
    session_id, is_new = ensure_session(x_session_id)
    if is_new:
        response.headers["X-Session-Id"] = session_id

    try:
        return resolve_hunk(req.hunk_id, req.strategy, session_id)
    except HunkNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e), headers={"Retry-After": "30"})
    except LLMResponseError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Unexpected error while resolving hunk")