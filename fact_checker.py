"""Fact-check newsletter summaries against source article."""
import json
import os
import requests

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

FACT_CHECK_PROMPT = """You are a strict fact-checker for a professional AI newsletter. Your ONLY job is to verify factual accuracy and source fidelity.

Compare the generated summaries against the original source article. Check for:

1. **Dates**: Every date, quarter, year must match the source exactly. If source says Q4 2025, summary must NOT say Q4 2026.
2. **Numbers**: All numbers, percentages, financial figures, measurements must match exactly.
3. **Company names**: Must be spelled correctly and refer to the right entity.
4. **Product names**: Must match the source exactly.
5. **Financial figures**: Revenue, growth rates, valuations must match source.
6. **Claims**: No fabricated details. Every claim in the summary must be explicitly present in the source article.
7. **Attributions**: Quotes and statements must be attributed to the correct person/entity.
8. **No external context**: Do not allow nationality, job title, organization description, political/economic interpretation, implications, or background context unless the source explicitly states it.
9. **Arabic opening/key sentence**: The first Arabic sentence must start with a direct past-tense verb, immediately identify the source-supported actor/entity as Arabic Name (English Name), include nationality only when source-supported, and state the main event without opinion, analysis, prediction, hype, or marketing language.
10. **Arabic closing sentence**: The final Arabic sentence must close with source-supported availability/launch timing, next step/future plan, limitation/current phase, direct objective, or another factual source-supported detail. Remove unsupported predictions, broad conclusions, future effects, political/economic analysis, or phrases such as "وقد يغيّر"، "ومن المتوقع"، "ما يعكس"، "في خطوة تؤكد".

Rules:
- If you find ANY factual error, correct it and list the change.
- Do NOT change style, tone, or structure — only fix factual errors.
- Preserve the newsletter body length requirement after any correction: English body and Arabic body should ideally be 90-120 words, with a 50-word tolerance around the ideal range (hard range: 40-170 words). If you edit a body, prefer moving it toward 90-120 without adding unsupported facts.
- If everything is accurate, return approved=true with no changes.
- Be extremely precise. Even small discrepancies matter.
- Enforce the Arabic editorial rule that the article may not add information beyond the source. If something is not explicitly in the source, remove it.
- Enforce the source-only Arabic opening and closing rules without adding unsupported nationality, conclusions, or future implications.

Focus on real factual/source-fidelity errors: wrong dates, wrong numbers, wrong product names, fabricated claims, unsupported context, or misattributed quotes.

Return JSON:
{
  "title_en": "corrected or original",
  "body_en": "corrected or original", 
  "title_ar": "corrected or original",
  "body_ar": "corrected or original",
  "factual_issues": ["list of issues found, empty if none"],
  "approved": true/false
}"""


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

    resp = requests.post(
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
            "temperature": 0.1,
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
