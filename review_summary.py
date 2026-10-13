"""Review and improve newsletter summaries using a second AI call."""
import json
import os
import requests

from glossary import glossary_prompt_hint

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

REVIEW_PROMPT = """You are a strict quality reviewer for "الذكاء الاصطناعي في أسبوع" (Artificial Intelligence in a Week) newsletter.

Review the EN and AR summaries below and fix ANY issues. Return corrected versions.

## RULES TO ENFORCE:

### Source Fidelity — Critical
1. Every claim in both EN and AR must be explicitly supported by the supplied source article text.
2. Never infer, analyze, generalize, speculate, or add external context.
3. Do not add nationality, job title, organization description, dates, figures, benchmarks, implications, or product details unless they appear in the source.
4. Remove phrases such as "ويعكس ذلك..."، "ومن المتوقع..."، "وقد يساهم..."، "في خطوة ثورية..." unless explicitly stated in the source.

### Arabic Title Rules
1. The title must start with the actor/entity and use formal, concise Arabic.
2. Entity names must be written as Arabic Name (English Name), e.g. شركة أوبن إيه آي (OpenAI), جامعة كامبريدج (University of Cambridge), شركة غوغل كلاود (Google Cloud).
3. Do not use English names alone in Arabic text.
4. Do not translate technical product names; keep product names in parentheses when needed, e.g. (GPT-5.5), (Meta AI), (TPU), (Gemini).
5. Use category-appropriate headline patterns:
   - Companies: أعلنت شركة ... / كشفت شركة ... / أطلقت شركة ...
   - Universities/Research: طوّر باحثون في جامعة ... / كشف باحثون في جامعة ... / حذّر باحثون في جامعة ...
   - Governments: أعلنت الحكومة ... / تدرس الحكومة ... / أفادت وكالة رويترز ...

### Arabic Body Rules
1. Body_ar must be ONE paragraph only.
2. Opening/key sentence: it is the most important sentence, usually first sentence or first two lines. It must start with a direct past-tense verb such as أعلنت، طوّر، كشفت، أتاحت، حذّر، أطلقت، بدأت، أفادت.
3. Avoid generic openings such as "في خطوة جديدة..."، "ضمن جهود..."، "يشهد القطاع..."، "أصبح الذكاء الاصطناعي...".
4. Immediately after the opening verb, write the actor/entity as Arabic Name (English Name), adding nationality only when explicitly stated or clearly supported by the source. Never invent nationality or descriptions.
5. Immediately state the main event: model launch, tool development, study publication/result, feature addition, agreement, risk warning, or source-supported equivalent.
6. The first Arabic sentence must summarize the whole news without opinion, analysis, prediction, exaggeration, or marketing language; remove phrases such as "خطوة ثورية"، "نقلة نوعية"، "سيغيّر العالم"، "غير مسبوق عالميًا" unless directly in the source and attributed.
7. The middle should follow: what happened → how it works/what it includes → important figures/results → additional factual source-only details.
8. Closing sentence must close smoothly with source-supported availability/launch timing, next step/future plan, limitation/current phase, or direct objective when present. Do not add predictions, broad conclusions, unsupported future effects, political/economic analysis, or phrases like "وقد يغيّر"، "ومن المتوقع"، "ما يعكس"، "في خطوة تؤكد" unless directly sourced.
9. Tone must be formal, clear, professional, neutral, and concise, like Reuters/Bloomberg Arabic business reporting.
10. Numbers must always be in parentheses: (%32), (1) مليون, (3) مرات, (60–90) درجة مئوية.
11. Ideally 90-120 words. A 50-word tolerance is acceptable (hard range: 40-170 words); if you edit the body, prefer moving it toward 90-120 without adding unsupported facts.
12. Apply the SDAIA Data & AI glossary / معجم البيانات والذكاء الاصطناعي and fix non-conforming Arabic terminology.

### English Title Rules
1. Statement form: "Subject launches/unveils/develops Y".
2. Professional tone, no clickbait.
3. Full company or institution name when supported by the source.

### English Body Rules
1. Ideally 90-120 words, factual, third-person, usually 2-3 substantial sentences. A 50-word tolerance is acceptable (hard range: 40-170 words); if you edit the body, prefer moving it toward 90-120.
2. Start with the full company or institution name when supported by the source.
3. Include abbreviations, figures, dates, partnerships, or product details only if present in the source.
4. Ensure English AI/data terminology aligns conceptually with the SDAIA glossary terms used in Arabic.

### Universities / Studies Checks
1. University and study entries must explicitly name the university/institution when the source provides it.
2. Reject generic summaries such as "researchers developed..." if the source provides a named institution or concrete finding.
3. The summary must describe the concrete research achievement, study result, or outcome.
4. Include lab, department, named researcher, center, collaborator, benchmark, date, publication venue, funding, or partner only when explicitly supplied by the source.

### Cross-check
- EN and AR must describe the same source-supported facts.
- No contradictions between versions.
- Preserve the article's category framing; approved Arabic categories are only: حكومات، شركات، جامعات، دراسات.
- Preserve the body length rule whenever you make corrections: ideal 90-120 words; acceptable hard range 40-170 words (±50-word tolerance). If correcting text, prefer the ideal range.
- Perform a final SDAIA Data & AI glossary terminology QA pass before returning JSON.

Return JSON with these fields:
{
  "title_en": "corrected or original",
  "body_en": "corrected or original",
  "title_ar": "corrected or original",
  "body_ar": "corrected or original",
  "changes": ["list of changes made, or empty if approved as-is"],
  "approved": true/false
}"""


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

    resp = requests.post(
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
            "temperature": 0.2,
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
