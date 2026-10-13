"""Generate newsletter-style summaries using OpenAI API."""
import json
import os
import requests
from ai_request import post_completion
from editorial_policy import ARABIC_EDITORIAL_POLICY

from glossary import glossary_prompt_hint


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

SYSTEM_PROMPT = ARABIC_EDITORIAL_POLICY + """\nWrite a faithful Arabic news brief.
Return JSON with fields title_ar, body_ar, title_en, body_en. Set title_en and body_en to empty strings; generate no English summary.\n"""

UNIVERSITIES_PROMPT = """EXTRA REQUIREMENTS FOR CATEGORY = Universities:
- English title should name the university or say "Researchers at <full university name> ...".
- Arabic title should name the university explicitly, for example: "باحثون من جامعة ... يطوّرون ..." or "جامعة ... تكشف ...".
- The body must include, when available:
  1. full university name
  2. the specific research achievement or study result
  3. lab, research group, department, named researcher, or partner organization
  4. concrete outcome or real-world application
  5. key numbers, benchmark results, publication venue, funding, or dates
- Avoid vague phrasing such as "researchers developed a new AI system" unless the article truly offers nothing more specific."""


def _build_user_prompt(article_title: str, article_text: str, category_en: str) -> str:
    prompt_parts = [
        "Write a newsletter entry for this article.",
        f"Category: {category_en}",
        "Write one Arabic paragraph, aiming for 90-120 words within the 40-170 word slide allowance, without adding facts. Leave the English fields empty.",
    ]

    # The shared policy governs all categories.

    glossary_hint = glossary_prompt_hint()
    if glossary_hint:
        prompt_parts.append(glossary_hint)

    prompt_parts.extend([
        f"Original title: {article_title}",
        "Original article text:",
        article_text[:45000],
        'Return JSON: {"title_en": "...", "body_en": "...", "title_ar": "...", "body_ar": "..."}',
    ])
    return "\n\n".join(prompt_parts)


def write_summary(article_title: str, article_text: str, category_en: str) -> dict:
    """Generate EN and AR summaries for an article."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    user_prompt = _build_user_prompt(article_title, article_text, category_en)

    resp = post_completion(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def detect_category(article_title: str, article_text: str) -> tuple:
    """Auto-detect category. Returns (en, ar)."""
    text = (article_title + " " + article_text[:1000]).lower()

    scores = {"Companies": 0, "Governments": 0, "Universities": 0, "Studies": 0}

    company_kw = [
        "startup", "ceo", "cto", "cfo", "launches", "unveils", "announces", "revenue",
        "acquisition", "acquires", "product", "platform", "app", "service", "funding",
        "ipo", "stock", "valuation", "billion", "million", "series a", "series b",
        "venture", "profit", "quarterly", "earnings", "shares", "market cap",
        "company", "corporation", "inc.", "corp.", "ltd.", "llc",
        "openai", "google", "meta", "microsoft", "apple", "amazon", "nvidia",
        "anthropic", "tesla", "samsung", "intel", "amd", "qualcomm",
    ]
    gov_kw = [
        "government", "administration", "federal", "regulation", "policy",
        "president", "minister", "law", "legislation", "executive order",
        "bill", "agency", "state", "parliament", "senate", "congress",
        "eu", "compliance", "ban", "restrict", "mandate", "oversight",
        "white house", "pentagon", "regulatory", "antitrust",
    ]
    uni_kw = [
        "university", "universities", "researcher", "researchers", "professor", "academic",
        "study", "paper", "phd", "campus", "research", "lab", "laboratory",
        "journal", "peer-reviewed", "findings", "experiment", "dataset",
        "published", "scientists", "doctoral", "faculty", "college", "school of",
        "research team", "mit", "stanford", "oxford", "cambridge",
    ]
    study_kw = [
        "organization", "foundation", "institute", "non-profit", "association",
        "united nations", "who", "unesco", "oecd", "ieee", "consortium",
        "alliance", "summit", "forum", "treaty", "standard", "ngo",
        "un ", "world bank", "imf",
    ]

    for kw in company_kw:
        if kw in text:
            scores["Companies"] += 1
    for kw in gov_kw:
        if kw in text:
            scores["Governments"] += 2
    for kw in uni_kw:
        if kw in text:
            scores["Universities"] += 2
    for kw in study_kw:
        if kw in text:
            scores["Studies"] += 2

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        best = "Companies"

    ar_map = {"Companies": "شركات", "Governments": "حكومات", "Universities": "جامعات", "Studies": "دراسات"}
    return (best, ar_map[best])


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        result = write_summary(sys.argv[1], sys.argv[2], "Companies")
        print(json.dumps(result, indent=2, ensure_ascii=False))
