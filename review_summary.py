"""Review and improve newsletter summaries using a second AI call."""
import json
import os
import requests
from ai_request import post_completion
from editorial_policy import ARABIC_EDITORIAL_POLICY

from glossary import glossary_prompt_hint

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

REVIEW_PROMPT = ARABIC_EDITORIAL_POLICY + """\nReview and correct the submitted Arabic headline and body against the original source and every editorial rule.
Return JSON with fields title_ar, body_ar, title_en, body_en, changes (array), approved (boolean). Set title_en and body_en to empty strings; generate no English summary.\n"""


def review_summary(summary: dict, category_en: str = "", article_title: str = "", article_text: str = "") -> dict:
    """Review and improve a summary. Returns corrected summary + review notes."""
    api_key = OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    prompt_parts = [
        f"Category: {category_en or 'Unknown'}",
        f"Original article title: {article_title}",
        "Original article text (verified source text):",
        article_text[:45000],
        "Review these summaries:",
        f"English Title: {summary['title_en']}",
        f"English Body: {summary['body_en']}",
        f"Arabic Title: {summary['title_ar']}",
        f"Arabic Body: {summary['body_ar']}",
    ]

    glossary_hint = glossary_prompt_hint()
    if glossary_hint:
        prompt_parts.append(glossary_hint)

    prompt_parts.append("Return corrected JSON.")
    user_prompt = "\n\n".join(prompt_parts)

    resp = post_completion(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": REVIEW_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    result = json.loads(content)

    for key in ("title_en", "body_en", "title_ar", "body_ar"):
        if key not in result:
            result[key] = summary[key]
    if "changes" not in result:
        result["changes"] = []
    if "approved" not in result:
        result["approved"] = len(result["changes"]) == 0

    return result


if __name__ == "__main__":
    test = {
        "title_en": "OpenAI says ads will be an iterative process",
        "body_en": "OpenAI's COO said the company will test ads in ChatGPT.",
        "title_ar": "OpenAI تقول إن الإعلانات ستكون عملية تكرارية",
        "body_ar": "قالت شركة OpenAI إنها ستختبر الإعلانات في ChatGPT.",
    }
    result = review_summary(test)
    print(json.dumps(result, indent=2, ensure_ascii=False))
