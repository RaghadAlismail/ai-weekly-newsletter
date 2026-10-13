"""Bounded copy repair followed by explicit source-fidelity approval."""
import re

def copy_problems(result):
    title = str(result.get("title_ar", "")).strip()
    body = str(result.get("body_ar", "")).strip()
    problems = []
    if not title or len(title) > 110 or re.search("[A-Za-z]", title):
        problems.append("Arabic headline must be Arabic-only and at most 110 characters")
    if not body or not 40 <= len(body.split()) <= 170:
        problems.append("Arabic summary must contain 40-170 words")
    return problems

def validate_copy(result, category, title, text, review, fact_check):
    result = review(result, category, title, text)
    for attempt in range(3):
        if copy_problems(result) and attempt:
            result = review(result, category, title, text)
        result = fact_check(result, text)
        result["body_ar"] = " ".join(str(result.get("body_ar", "")).split())
        if result.get("approved") is True and not copy_problems(result):
            return result
    if result.get("approved") is not True:
        raise ValueError("Source-fidelity check still needs attention after automatic correction. Review the original source.")
    raise ValueError("Arabic copy still fails the headline or length checks after automatic correction.")
