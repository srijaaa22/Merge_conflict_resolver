from fastapi import APIRouter, HTTPException
from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.git_parser import analyze_repo, InvalidRepoError, GitCommandError

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    try:
        return analyze_repo(req.repo_path)
    except InvalidRepoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except GitCommandError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Unexpected error while analyzing repo")