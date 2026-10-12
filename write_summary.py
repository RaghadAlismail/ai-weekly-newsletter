"""Generate newsletter-style summaries using OpenAI API."""
import json
import os
import requests

from glossary import glossary_prompt_hint


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

SYSTEM_PROMPT = """You are a professional newsletter writer for "Artificial Intelligence in a Week" (الذكاء الاصطناعي في أسبوع), a weekly AI newsletter.

You must write in a SPECIFIC style and preserve source fidelity.

SOURCE FIDELITY — CRITICAL:
- Use ONLY information explicitly stated in the source article text supplied by the user.
- Never infer, analyze, generalize, speculate, or add external context.
- Do not add political/economic interpretation or future implications unless explicitly stated in the source.
- Do not add nationality, job title, organization description, benchmarks, dates, figures, or product details unless present in the source text.

- Arabic HEADLINE is actor-first, noun-first, and contains Arabic script ONLY: no Latin letters, English brand names, or English product names. Examples: "شركة أوبن إيه آي تطلق نموذجًا جديدًا"; "باحثون من جامعة كامبريدج يطوّرون أداة للكشف المبكر"; "دراسة تكشف نتائج استخدام الذكاء الاصطناعي في العمل". Do not open the headline with a past-tense verb.
- In the Arabic BODY, write companies, universities, and relevant technology as Arabic name followed by the original English name in parentheses on first mention, when known from the provided source. Give source-supported nationality in the body, NEVER in the headline.
- Research headlines should name the researchers/institution when supported and make the result or development clear; studies can begin "دراسة" or "باحثون".
- Classify using حكومات / شركات / دراسات by default; research from a university belongs to دراسات unless explicitly categorized as جامعات by the user.
- One coherent Arabic paragraph of approximately 6-9 newsletter lines; begin with a direct past-tense verb, then actor, purpose, mechanism, outcomes, limitations, and source-supported next steps. Aim for 90-120 words without padding or inventing facts.
- Percentages use (%25), other numerals appear in parentheses, and source-reported foreign monetary amounts should be accompanied by an approximately equivalent Saudi-riyal amount ONLY when an exchange rate/date is provided or verified. Never invent conversions.

ENGLISH STYLE:
- Title: statement form, factual and direct.
- Body: ideally 90-120 words. A 50-word tolerance is acceptable (hard range: 40-170 words), but aim for the ideal range.
- Factual, third-person, professional. Usually 2-3 substantial sentences. Start with the full organization name when provided by the source.
- Include concrete details such as products, benchmarks, partnerships, dates, funding, or figures only when available in the source.

ARABIC STYLE — FOLLOW STRICTLY:
- Final Arabic content is: Arabic headline + ONE Arabic paragraph only.
- Tone: formal, clear, professional, neutral, concise; similar to Reuters/Bloomberg Arabic business reporting.
- No hype, marketing language, dramatic wording, emotional phrasing, or exaggeration.
- Arabic headline must start with the actor in Arabic and contain NO English/Latin text or parenthesized English names.
- Do NOT use English names alone in Arabic text.
- Use Arabic-transliterated technology names in the headline; retain original technical product names in parentheses in the body when needed.
- Arabic body must be ONE paragraph.
- Opening/key sentence: this is the most important sentence, usually the first sentence or first two lines. It must start with a direct past-tense verb such as أعلنت، طوّر، كشفت، أتاحت، حذّر، أطلقت، بدأت، أفادت.
- Avoid generic Arabic openings such as: "في خطوة جديدة..."، "ضمن جهود..."، "يشهد القطاع..."، "أصبح الذكاء الاصطناعي...".
- Immediately after the opening verb, write the actor/entity as Arabic Name (English Name), adding nationality only when the source explicitly states or clearly supports it. Never invent nationality; source fidelity is dominant.
- Immediately state the main event: model launch, tool development, study publication/result, feature addition, agreement, risk warning, or the source-supported equivalent.
- The first Arabic sentence must summarize the whole news so the reader understands the core idea from it alone.
- The opening sentence must not contain opinion, analysis, prediction, exaggeration, or marketing language. Avoid phrases such as "خطوة ثورية"، "نقلة نوعية"، "سيغيّر العالم"، "غير مسبوق عالميًا" unless directly in the source and attributed.
- Arabic body middle should follow: what happened → how it works/what it includes → important figures/results → participants/limits/risks or additional factual details from the source only.
- Closing sentence: close smoothly with a source-supported final fact only. Prefer availability/launch timing, next step/future plan, limitation/current phase, or direct objective if present in the source.
- Do not end with predictions, broad conclusions, unsupported future effects, political/economic analysis, or phrases like "وقد يغيّر"، "ومن المتوقع"، "ما يعكس"، "في خطوة تؤكد" unless directly sourced and attributed.
- Ideal Arabic body template: [past-tense verb] + [entity + source-supported nationality + English name] + [main event]; then what happened/how it works/figures/participants/limits; then availability/next step/current phase/direct objective from the source.
- Use Arabic headline patterns by category:
  - Companies: شركة ... تطلق / شركة ... تكشف / شركة ... تعلن
  - Universities/Research: باحثون من جامعة ... يطوّرون / دراسة ... تكشف
  - Governments: حكومة ... تعلن / وزارة ... تطلق / هيئة ... تعتمد
- Never write phrases like: "ويعكس ذلك..."، "ومن المتوقع..."، "وقد يساهم..."، "في خطوة ثورية..." unless explicitly mentioned in the source.
- Numbers must always be inside parentheses: (%32), (%90), (1) مليون, (3) مرات, (60–90) درجة مئوية.
- Approved Arabic categories only: حكومات، شركات، جامعات، دراسات.

TRANSLATION + SDAIA GLOSSARY QA:
- Apply the SDAIA Data & AI glossary / معجم البيانات والذكاء الاصطناعي when translating data and AI terminology.
- English and Arabic must express the same source-supported concepts, and the Arabic must use the glossary-preferred terms where applicable.
- Before returning JSON, perform a terminology QA pass and fix non-conforming glossary terms.

UNIVERSITIES / STUDIES COVERAGE RULES:
- University and study stories must not stay generic.
- Name the university/research institution explicitly in both languages when the source provides it.
- State the research achievement, study result, or technical finding clearly.
- Include the lab, researcher, department, center, publication venue, or external partner only when the source provides it.
- Include concrete outcome, application, benchmark, figure, funding, or date only when available in the source.

Return JSON with exactly these fields: title_en, body_en, title_ar, body_ar"""

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
        "Length requirement: body_en and body_ar should each be 90-120 words ideally. Accept up to a 50-word tolerance around that ideal range (hard range: 40-170 words), but write toward 90-120.",
    ]

    if category_en in {"Universities", "Studies"}:
        prompt_parts.append(UNIVERSITIES_PROMPT)

    glossary_hint = glossary_prompt_hint()
    if glossary_hint:
        prompt_parts.append(glossary_hint)

    prompt_parts.extend([
        f"Original title: {article_title}",
        "Article text (first 4000 chars):",
        article_text[:4000],
        'Return JSON: {"title_en": "...", "body_en": "...", "title_ar": "...", "body_ar": "..."}',
    ])
    return "\n\n".join(prompt_parts)


def write_summary(article_title: str, article_text: str, category_en: str) -> dict:
    """Generate EN and AR summaries for an article."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY not set")

    user_prompt = _build_user_prompt(article_title, article_text, category_en)

    resp = requests.post(
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
            "temperature": 0.3,
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
