from google import genai
from dotenv import load_dotenv
from app.models.schemas import ResolveResponse

load_dotenv()

client = genai.Client()

# Fake hunk data for testing — mirrors what your real parser produces
prompt = """
You are an expert at resolving Git merge conflicts.

Ours (HEAD):
def calculate_total(items):
    return sum(items)

Theirs (feature-branch):
def calculate_total(items):
    return sum(item.price for item in items)

Task: propose the single best resolution for this conflict.
"""

interaction = client.interactions.create(
    model="gemini-3.6-flash",
    input=prompt,
    response_format={
        "type": "text",
        "mime_type": "application/json",
        "schema": ResolveResponse.model_json_schema()
    }
)

# Validate + parse the raw JSON string straight into your actual response model
result = ResolveResponse.model_validate_json(interaction.output_text)
print(result)