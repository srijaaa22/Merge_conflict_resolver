from fastapi import APIRouter, HTTPException
from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.resolver import analyze_repo

router = APIRouter()

@router.post("/analyze", response_model = AnalyzeResponse)
def analyze(req : AnalyzeRequest):
    try:
        return analyze_repo(req.repo_path)
    except Exception as e:
        raise HTTPException(status_code = 400, detail = str(e))