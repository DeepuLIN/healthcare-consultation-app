import os
from fastapi import FastAPI, Depends
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel
from fastapi_clerk_auth import (
    ClerkConfig,
    ClerkHTTPBearer,
    HTTPAuthorizationCredentials,
)
from openai import OpenAI

gemini_url = "https://generativelanguage.googleapis.com/v1beta/openai/"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")

app = FastAPI()

clerk_config = ClerkConfig(jwks_url=CLERK_JWKS_URL)
clerk_guard = ClerkHTTPBearer(clerk_config)


class Visit(BaseModel):
    patient_name: str
    date_of_visit: str
    notes: str


system_prompt = """
You are provided with notes written by a doctor from a patient's visit.
Your job is to summarize the visit for the doctor and provide an email.

Return valid Markdown only.

Reply with exactly these three Markdown sections:

### Summary of visit for the doctor's records

### Next steps for the doctor

### Draft of email to patient in patient-friendly language

Rules:
- Keep the headings exactly as written.
- Put a blank line after each heading.
- Use bullet points under the first two sections.
- Write the email as normal paragraphs.
- Do not include [DONE].
"""


def user_prompt_for(visit: Visit) -> str:
    return f"""Create the summary, next steps and draft email for:

Patient Name: {visit.patient_name}
Date of Visit: {visit.date_of_visit}

Notes:
{visit.notes}
"""


@app.get("/api/health", response_class=PlainTextResponse)
def health():
    return "API is running"


@app.post("/api")
def consultation_summary(
    visit: Visit,
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard),
):
    if not GOOGLE_API_KEY:
        return {"error": "GOOGLE_API_KEY is missing"}

    user_id = creds.decoded["sub"]
    print("Authenticated user:", user_id)

    client = OpenAI(
        base_url=gemini_url,
        api_key=GOOGLE_API_KEY,
        timeout=30,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt_for(visit)},
    ]

    stream = client.chat.completions.create(
        model="gemini-2.5-flash",
        messages=messages,
        stream=True,
    )

    def event_stream():
        for chunk in stream:
            if not chunk.choices:
                continue

            text = chunk.choices[0].delta.content

            if text:
                for line in text.splitlines():
                    yield f"data: {line}\n"
                yield "\n"

        yield "data: [DONE]\n\n"

       

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )