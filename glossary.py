"""SDAIA Data & AI glossary helpers for newsletter terminology.

The generator loads the bundled official SDAIA Data and AI Glossary (2nd
edition) by default. A small local fallback is retained only for cases where the
official JSON is missing or unparseable, so translation prompts and QA remain
linked to SDAIA Data & AI terminology.
"""
import json
import os
import re
from functools import lru_cache


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCES_DIR = os.path.join(SCRIPT_DIR, "..", "references")
GLOSSARY_NAME = "SDAIA Data & AI glossary / معجم البيانات والذكاء الاصطناعي"
APPROVED_GLOSSARY_PATH = os.path.join(REFERENCES_DIR, "approved-glossary-ar.json")
BUNDLED_OFFICIAL_GLOSSARY_PATH = os.path.join(
    REFERENCES_DIR, "sdaia-data-ai-glossary-official.json"
)
DEFAULT_APPROVED_GLOSSARY_PATH = (
    os.environ.get("SDAIA_DATA_AI_GLOSSARY_PATH")
    or os.environ.get("APPROVED_GLOSSARY_AR_PATH")
    or (
        APPROVED_GLOSSARY_PATH
        if os.path.exists(APPROVED_GLOSSARY_PATH)
        else BUNDLED_OFFICIAL_GLOSSARY_PATH
    )
)
FALLBACK_GLOSSARY_PATH = os.path.join(REFERENCES_DIR, "sdaia-data-ai-glossary-fallback.json")
EXAMPLE_GLOSSARY_PATH = os.path.join(REFERENCES_DIR, "approved-glossary-ar.example.json")

PROMPT_PRIORITY_TERMS = [
    "data",
    "artificial intelligence (AI)",
    "machine learning (ML)",
    "generative artificial intelligence (GenAI)",
    "generative AI",
    "large language model (LLM)",
    "foundation model",
    "prompt engineering",
    "model",
    "algorithm",
    "metadata",
    "personal data",
    "privacy",
]


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _dedupe(items):
    seen = set()
    ordered = []
    for item in items:
        clean = item.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def _dedupe_paths(candidates):
    seen = set()
    ordered = []
    for path, source in candidates:
        if not path:
            continue
        absolute = os.path.abspath(path)
        if absolute in seen:
            continue
        seen.add(absolute)
        ordered.append((path, source))
    return ordered


def _official_candidates(path: str = None):
    if path:
        return [(path, "official")]

    env_path = os.environ.get("SDAIA_DATA_AI_GLOSSARY_PATH") or os.environ.get(
        "APPROVED_GLOSSARY_AR_PATH"
    )
    return _dedupe_paths(
        [
            (env_path, "official-env"),
            (APPROVED_GLOSSARY_PATH, "official-approved"),
            (BUNDLED_OFFICIAL_GLOSSARY_PATH, "official"),
        ]
    )


def _term_aliases(term: str) -> set:
    if not isinstance(term, str) or not term.strip():
        return set()

    normalized = term.casefold().replace("&", "and")
    aliases = {normalized.strip()}
    aliases.add(re.sub(r"\s*\([^)]*\)", "", normalized).strip())
    for part in re.split(r"\s*/\s*", normalized):
        aliases.add(part.strip())
        aliases.add(re.sub(r"\s*\([^)]*\)", "", part).strip())
    return {alias for alias in aliases if alias}


def _prioritized_entries(entries):
    prioritized = []
    used = set()

    for priority in PROMPT_PRIORITY_TERMS:
        priority_aliases = _term_aliases(priority)
        for index, entry in enumerate(entries):
            if index in used:
                continue
            if priority_aliases & _term_aliases(entry.get("term_en", "")):
                prioritized.append(entry)
                used.add(index)
                break

    prioritized.extend(entry for index, entry in enumerate(entries) if index not in used)
    return prioritized


def _normalize_entry(entry):
    if not isinstance(entry, dict):
        return None

    canonical = (
        entry.get("canonical_ar")
        or entry.get("canonical")
        or entry.get("preferred")
        or entry.get("target")
    )
    if not isinstance(canonical, str) or not canonical.strip():
        return None

    term_en = (
        entry.get("term_en")
        or entry.get("canonical_en")
        or entry.get("english")
        or entry.get("source_en")
        or entry.get("term")
        or ""
    )

    variants = []
    for key in ("variants", "match", "matches", "aliases", "source", "sources", "replace"):
        variants.extend(_as_list(entry.get(key)))

    canonical = canonical.strip()
    variants = [variant for variant in _dedupe(variants) if variant != canonical]
    normalized = {"canonical_ar": canonical, "variants": variants}
    if isinstance(term_en, str) and term_en.strip():
        normalized["term_en"] = term_en.strip()
    if isinstance(entry.get("note"), str) and entry["note"].strip():
        normalized["note"] = entry["note"].strip()
    return normalized


def _entries_from_mapping(mapping):
    entries = []
    for source, target in mapping.items():
        if source == "meta":
            continue
        if isinstance(source, str) and isinstance(target, str) and source.strip() and target.strip():
            entries.append({"canonical_ar": target.strip(), "term_en": source.strip(), "variants": [source.strip()]})
    return entries


def _extract_entries(data):
    if isinstance(data, list):
        return [_normalize_entry(entry) for entry in data]

    if isinstance(data, dict):
        if isinstance(data.get("entries"), list):
            return [_normalize_entry(entry) for entry in data["entries"]]

        replacements = data.get("replacements")
        if isinstance(replacements, dict):
            return _entries_from_mapping(replacements)
        if isinstance(replacements, list):
            return [_normalize_entry(entry) for entry in replacements]

        return _entries_from_mapping(data)

    return []


def _empty_result(path: str, *, source: str = "none", reason: str = "not_found") -> dict:
    return {
        "enabled": False,
        "official": False,
        "source": source,
        "path": os.path.abspath(path),
        "fallback_path": os.path.abspath(FALLBACK_GLOSSARY_PATH),
        "entries": [],
        "reason": reason,
    }


def _load_glossary_file(path: str, *, source: str, require_official: bool) -> dict:
    glossary_path = os.path.abspath(path)
    result = _empty_result(glossary_path, source=source)

    if not os.path.exists(glossary_path):
        return result

    try:
        with open(glossary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        result["reason"] = f"invalid_json:{e}"
        return result

    meta = data.get("meta", {}) if isinstance(data, dict) else {}
    official = bool(meta.get("official", not require_official))
    result["official"] = official
    if require_official and not official:
        result["reason"] = "not_official"
        return result

    entries = [entry for entry in _extract_entries(data) if entry]
    if not entries:
        result["reason"] = "no_entries"
        return result

    result["entries"] = entries
    result["enabled"] = True
    result["reason"] = "loaded"
    return result


@lru_cache(maxsize=8)
def load_approved_glossary(path: str = None) -> dict:
    """Load SDAIA glossary terms.

    Lookup order:
    1. Official JSON at `path`, `SDAIA_DATA_AI_GLOSSARY_PATH`, or
       `APPROVED_GLOSSARY_AR_PATH`.
    2. Official JSON at references/approved-glossary-ar.json when present.
    3. Bundled official SDAIA JSON extracted from the 2nd edition PDF.
    4. Local fallback references/sdaia-data-ai-glossary-fallback.json.

    The fallback is intentionally small and non-authoritative, and should only
    be used if the official bundled/exported glossary is unavailable.
    """
    official_results = []
    candidates = _official_candidates(path)
    for official_path, source in candidates:
        official = _load_glossary_file(official_path, source=source, require_official=True)
        official_results.append(official)
        if official.get("enabled"):
            return official

    fallback = _load_glossary_file(
        FALLBACK_GLOSSARY_PATH, source="fallback", require_official=False
    )
    if fallback.get("enabled"):
        fallback["official_candidates"] = [result["path"] for result in official_results]
        fallback["official_reason"] = "; ".join(
            f"{os.path.basename(result['path'])}:{result.get('reason', 'not_found')}"
            for result in official_results
        )
        return fallback

    if official_results:
        official_results[-1]["fallback_reason"] = fallback.get("reason", "not_found")
        return official_results[-1]

    empty = _empty_result(DEFAULT_APPROVED_GLOSSARY_PATH, source="official")
    empty["fallback_reason"] = fallback.get("reason", "not_found")
    return empty


def glossary_prompt_hint(max_entries: int = 20) -> str:
    """Return a compact terminology QA hint for the active SDAIA glossary."""
    glossary = load_approved_glossary()
    if not glossary["enabled"]:
        return ""

    source_label = "official" if glossary.get("official") else "fallback core"
    lines = [
        f"SDAIA Data & AI glossary QA ({GLOSSARY_NAME}) — {source_label} terms loaded from {glossary['path']}.",
        "Apply these terms when translating AI/data concepts, and before returning JSON perform a terminology QA pass so English and Arabic use the same concept consistently:",
    ]
    for entry in _prioritized_entries(glossary["entries"])[:max_entries]:
        canonical = entry["canonical_ar"]
        term_en = entry.get("term_en", "")
        variants = entry.get("variants", [])[:4]
        label = f"{term_en} → {canonical}" if term_en else canonical
        if variants:
            lines.append(f'- {label} (replace Arabic variants such as: {", ".join(variants)})')
        else:
            lines.append(f"- {label}")
    return "\n".join(lines)


def normalize_arabic_text(text: str, glossary: dict = None) -> str:
    """Normalize Arabic terminology using the active SDAIA glossary."""
    if not text:
        return text

    glossary = glossary or load_approved_glossary()
    if not glossary.get("enabled"):
        return text

    normalized = text
    for entry in glossary["entries"]:
        canonical = entry["canonical_ar"]
        for variant in sorted(entry.get("variants", []), key=len, reverse=True):
            # Avoid replacing English glossary labels inside product names such as OpenAI.
            if not any("\u0600" <= ch <= "\u06FF" for ch in variant):
                continue
            normalized = normalized.replace(variant, canonical)
    return normalized


def apply_glossary(summary: dict, glossary_override: dict = None) -> tuple:
    """Apply SDAIA glossary normalization to newsletter Arabic fields."""
    glossary = glossary_override or load_approved_glossary()
    normalized = dict(summary)
    changes = []

    if not glossary.get("enabled"):
        return normalized, changes

    for field in ("title_ar", "body_ar"):
        original = normalized.get(field, "")
        updated = normalize_arabic_text(original, glossary)
        if updated != original:
            normalized[field] = updated
            changes.append(field)

    return normalized, changes


__all__ = [
    "DEFAULT_APPROVED_GLOSSARY_PATH",
    "EXAMPLE_GLOSSARY_PATH",
    "FALLBACK_GLOSSARY_PATH",
    "GLOSSARY_NAME",
    "APPROVED_GLOSSARY_PATH",
    "BUNDLED_OFFICIAL_GLOSSARY_PATH",
    "apply_glossary",
    "glossary_prompt_hint",
    "load_approved_glossary",
    "normalize_arabic_text",
]
