"""Fact-check newsletter summaries against source article."""
import json
import os
import requests
from ai_request import post_completion
from editorial_policy import ARABIC_EDITORIAL_POLICY

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

FACT_CHECK_PROMPT = ARABIC_EDITORIAL_POLICY + """\nCheck every fact in the Arabic headline and paragraph against the original source. Correct mismatches or unsupported claims. Report approved=true only if the returned corrected Arabic copy is fully source-supported; otherwise approved=false and list remaining factual issues.
Return JSON with fields title_ar, body_ar, title_en, body_en, factual_issues (array), approved (boolean). Set title_en and body_en to empty strings; generate no English summary.\n"""


def fact_check(summary: dict, article_text: str) -> dict:
    """Fact-check summaries against source article. Returns corrected summary."""
    api_key = OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    user_prompt = f"""ORIGINAL ARTICLE TEXT (source of truth):
{article_text[:45000]}

---

GENERATED SUMMARIES TO FACT-CHECK:

English Title: {summary['title_en']}
English Body: {summary['body_en']}

Arabic Title: {summary['title_ar']}
Arabic Body: {summary['body_ar']}

Compare every fact in the summaries against the original article. Return corrected JSON."""

    resp = post_completion(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": FACT_CHECK_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    result = json.loads(content)

    # Ensure all fields present
    for key in ("title_en", "body_en", "title_ar", "body_ar"):
        if key not in result:
            result[key] = summary[key]
    if "factual_issues" not in result:
        result["factual_issues"] = []
    if "approved" not in result:
        result["approved"] = len(result["factual_issues"]) == 0

    return result


if __name__ == "__main__":
    test_summary = {
        "title_en": "OpenAI reports Q4 2026 revenue growth",
        "body_en": "OpenAI reported strong Q4 2026 results.",
        "title_ar": "شركة (أوبن إيه آي) تعلن نتائج الربع الرابع 2026",
        "body_ar": "أعلنت شركة أوبن إيه آي نتائج الربع الرابع 2026.",
    }
    test_article = "OpenAI reported strong Q4 2025 revenue growth of 35%."
    result = fact_check(test_summary, test_article)
    print(json.dumps(result, indent=2, ensure_ascii=False))
