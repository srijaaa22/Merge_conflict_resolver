import json

from app.services.git_parser import analyze_repo

result = analyze_repo(r"C:\Users\srija\OneDrive\Desktop\conflict-practice")
print(json.dumps(result, indent=2))