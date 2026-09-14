from fastapi import APIRouter, HTTPException
from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.resolver import analyze_repo
from app.state import analyzed_hunks

router = APIRouter()

@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    try:
        res = analyze_repo(req.repo_path)
        for file in res["conflicted_files"]:
            for hunk in file["hunks"]:
                analyzed_hunks[hunk["hunk_id"]] = hunk

        #print(analyzed_hunks)
        return res

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))