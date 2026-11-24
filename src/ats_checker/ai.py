"""Optional Claude review of resume bullets (``ats check --ai``).

Only the extracted bullet text is sent, never the PDF or contact details.
"""

from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-opus-5-5"
MAX_BULLETS = 40

SYSTEM = """You are a senior software engineering hiring manager reviewing resume bullets.
For each bullet, identify concrete weaknesses (e.g. "no metric", "vague scope", "no tech named",
"passive", "too long", "jargon", "unclear impact") and propose a rewrite that keeps every claim
truthful: never invent numbers or technologies. Where a metric is missing, use a clearly marked
placeholder like [X%] or [N users] for the candidate to fill in. Skip bullets that are already
strong by returning an empty issues list and the original text as the suggestion.
Also give a 2-3 sentence overall summary of the resume's bullet quality."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "issues": {"type": "array", "items": {"type": "string"}},
                    "suggestion": {"type": "string"},
                },
                "required": ["original", "issues", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "bullets"],
    "additionalProperties": False,
}


def review_bullets(bullets: list[dict], *, jd_title: str | None = None, model: str | None = None) -> dict:
    model = model or os.environ.get("ATS_AI_MODEL") or DEFAULT_MODEL
    try:
        import anthropic
    except ImportError:
        return {"error": "AI review needs the optional extra: uv tool install 'ats-checker[ai]' (or uv sync --extra ai)."}
    if not bullets:
        return {"error": "No bullets found to review."}

    lines = "\n".join(f"- [{b['role'][:60]}] {b['bullet']}" for b in bullets[:MAX_BULLETS])
    target = f"The candidate is targeting: {jd_title}.\n\n" if jd_title else ""
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            # On a safety decline, let the API re-run the request on its recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": f"{target}Review these resume bullets (role in brackets):\n{lines}"}],
        )
    except anthropic.AuthenticationError:
        return {"error": "Claude API authentication failed. Set ANTHROPIC_API_KEY or run `ant auth login`."}
    except anthropic.RateLimitError:
        return {"error": "Claude API rate limit hit; try again in a minute."}
    except anthropic.APIStatusError as e:
        return {"error": f"Claude API error {e.status_code}: {e.message}"}
    except anthropic.APIConnectionError:
        return {"error": "Couldn't reach the Claude API (network error)."}

    if response.stop_reason == "refusal":
        return {"error": "The model declined to review these bullets."}
    if response.stop_reason == "max_tokens":
        return {"error": "AI review was cut off (too many bullets); try a shorter resume."}
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"error": "AI review returned malformed output."}
    data["bullets"] = [b for b in data.get("bullets", []) if b.get("issues")]
    data["model"] = response.model
    return data
