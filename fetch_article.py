"""Fetch and extract article content from a URL."""
import html as html_lib
import os
import re
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse

import requests
from PIL import Image

from image_fallback import generate_article_fallback_image
from manual_gate import mark_manual_required

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")

MIN_TEXT_LENGTH = 200
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"}
BOT_CHALLENGE_MARKERS = (
    "checking your connection",
    "just a quick check",
    "prevent automated abuse",
    "request whitelisting",
    "having problems? contact support",
    "too many requests",
)


def _canonicalize_url(url: str) -> str:
    """Normalize URLs so source links and lookups stay stable."""
    raw = (url or "").strip()
    if not raw:
        return raw
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw

    parsed = urlparse(raw)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ]
    netloc = parsed.netloc.lower().replace("www.", "")

    if netloc.endswith("techxplore.com"):
        netloc = "techxplore.com"

    cleaned = parsed._replace(
        scheme="https",
        netloc=netloc,
        query=urlencode(query_items, doseq=True),
        fragment="",
    )
    return urlunparse(cleaned)


def _same_article_url(left: str, right: str) -> bool:
    return _canonicalize_url(left) == _canonicalize_url(right)


def _is_bot_challenge(content: str, title: str = "") -> bool:
    text = html_lib.unescape(f"{title}\n{content or ''}").lower()
    return any(marker in text for marker in BOT_CHALLENGE_MARKERS)


def _clean_result_title(title: str, domain: str = "") -> str:
    title = html_lib.unescape((title or "").strip())
    title = re.sub(r"\s*[-|]\s*(tech xplore|techxplore|phys\.org|science x(?: network)?)\s*$", "", title, flags=re.IGNORECASE)
    if _is_bot_challenge("", title):
        return ""
    if domain == "techxplore.com" and title.lower() == "tech xplore - technology and engineering news":
        return ""
    return title.strip()


def _clean_search_description(text: str) -> str:
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"Citation:.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"retrieved\s+\d+\s+\w+\s+\d+\s+from\s+https?://\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"DOI:\s*\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -")
    return text.strip()


def _extract_meta(html: str) -> dict:
    """Extract OG meta tags from HTML."""
    meta = {"title": "", "image_url": ""}
    og_img = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)', html)
    if og_img:
        meta["image_url"] = html_lib.unescape(og_img.group(1).strip())
    og_title = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)', html)
    if og_title:
        meta["title"] = html_lib.unescape(og_title.group(1).strip())
    else:
        title_tag = re.search(r'<title[^>]*>([^<]+)</title>', html)
        if title_tag:
            meta["title"] = html_lib.unescape(title_tag.group(1).strip())
    return meta


def _extract_text_newspaper(url: str, html: str) -> tuple:
    """Extract text using newspaper3k. Returns (text, title, image_url)."""
    try:
        from newspaper import Article
        article = Article(url)
        article.download(input_html=html)
        article.parse()
        return article.text, article.title, article.top_image
    except Exception:
        return "", "", ""


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping fallback."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_lib.unescape(re.sub(r'\s+', ' ', text).strip())
    return text[:5000]


def _fetch_with_requests(url: str) -> tuple:
    """Tier 1: Simple requests fetch. Returns (html, error). Error includes 'DNS' flag for unreachable domains."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.text, None
    except requests.exceptions.ConnectionError as e:
        return None, f"DNS_OR_CONNECTION:{e}"
    except requests.exceptions.HTTPError as e:
        if hasattr(e, 'response') and e.response is not None and len(e.response.text) > 100:
            return e.response.text, f"HTTP_{e.response.status_code}"
        return None, str(e)
    except Exception as e:
        return None, str(e)


def _title_from_url(url: str) -> str:
    """Extract a human-readable title from the URL slug as last resort."""
    path = urlparse(url).path.rstrip('/')
    slug = path.split('/')[-1]
    slug = re.sub(r'\.(html?|php)$', '', slug, flags=re.IGNORECASE)
    slug = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', slug)
    slug = re.sub(r'^\d{4}-\d{2}-', '', slug)
    slug = re.sub(r'-[a-f0-9]{8,}$', '', slug)
    slug = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', slug)
    title = slug.replace('-', ' ').strip().title()
    return title if len(title) > 10 else ""


def _fetch_with_scrapling(url: str) -> tuple:
    """Tier 2: Scrapling Fetcher (better headers, anti-bot evasion). Returns (html, error)."""
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get(url)
        if page.status == 200:
            return page.html_content, None
        return None, f"Status {page.status}"
    except Exception as e:
        return None, str(e)


def _fetch_with_scrapling_stealth(url: str) -> tuple:
    """Tier 3: Scrapling StealthyFetcher (real browser, bypasses Cloudflare etc). Returns (html, error)."""
    try:
        from scrapling.fetchers import StealthyFetcher
        page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
        if page.status == 200:
            return page.html_content, None
        return None, f"Status {page.status}"
    except Exception as e:
        return None, str(e)


def _extract_with_scrapling(url: str, html: str = None) -> str:
    """Use scrapling's parser to extract article text from already-fetched HTML or URL."""
    try:
        from scrapling.fetchers import Fetcher
        if html:
            from scrapling.parser import Adaptor
            page = Adaptor(html, url=url)
        else:
            page = Fetcher.get(url)

        for selector in ['article', '.article-body', '.post-content', '.entry-content',
                         '[data-component="text-block"]', '.story-body', '.article-content']:
            elements = page.css(selector)
            if elements:
                text = elements[0].text
                if text and len(text) > MIN_TEXT_LENGTH:
                    return text

        paras = page.css('p')
        text = ' '.join(p.text.strip() for p in paras if p.text and len(p.text.strip()) > 30)
        if len(text) > MIN_TEXT_LENGTH:
            return text
    except Exception as e:
        print(f"  Scrapling extraction failed: {e}")
    return ""


def _fetch_from_archive(url: str) -> tuple:
    """Tier 4: Try archive.org Wayback Machine. Returns (text, title, image_url)."""
    try:
        check = requests.get(
            f"https://archive.org/wayback/available?url={url}",
            timeout=10
        )
        data = check.json()
        snapshot = data.get("archived_snapshots", {}).get("closest", {})
        archive_url = snapshot.get("url", "")

        if not archive_url:
            return "", "", ""

        print(f"  Found archive snapshot: {archive_url[:80]}...")
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        resp = requests.get(archive_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return "", "", ""

        html = resp.text
        meta = _extract_meta(html)

        text_np, title_np, img_np = _extract_text_newspaper(url, html)
        if text_np and len(text_np) > MIN_TEXT_LENGTH:
            return text_np, title_np or meta["title"], img_np or meta["image_url"]

        scrapling_text = _extract_with_scrapling(url, html)
        if len(scrapling_text) > MIN_TEXT_LENGTH:
            return scrapling_text, meta["title"], meta["image_url"]

        paras = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
        clean = []
        for p in paras:
            t = re.sub(r'<[^>]+>', '', p).strip()
            if len(t) > 40 and not any(skip in t.lower() for skip in ['copyright', 'cookie', 'subscribe', 'sign in', 'log in']):
                clean.append(t)
        text = ' '.join(clean)
        if len(text) > MIN_TEXT_LENGTH:
            return text, meta["title"], meta["image_url"]

        return "", meta["title"], meta["image_url"]
    except Exception as e:
        print(f"  Archive.org failed: {e}")
        return "", "", ""


def _decode_search_result_url(url: str) -> str:
    if not url:
        return url
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return url


def _search_duckduckgo(query: str, count: int = 5) -> list:
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        if resp.status_code != 200:
            return []

        results = []
        block_pattern = re.compile(
            r'<div class="result results_links[\s\S]*?<div class="clear"></div>\s*</div>\s*</div>',
            re.IGNORECASE,
        )
        for block_match in block_pattern.finditer(resp.text):
            block = block_match.group(0)
            link_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
            if not link_match:
                continue
            snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
            if not snippet_match:
                snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</div>', block, re.IGNORECASE | re.DOTALL)

            raw_url = _decode_search_result_url(link_match.group(1))
            title = _clean_search_description(link_match.group(2))
            description = _clean_search_description(snippet_match.group(1) if snippet_match else "")
            if raw_url and (title or description):
                results.append({"url": raw_url, "title": title, "description": description})
            if len(results) >= count:
                break
        return results
    except Exception:
        return []


def _search_brave(query: str, count: int = 5) -> list:
    if not query.strip():
        return []
    if BRAVE_SEARCH_API_KEY:
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": BRAVE_SEARCH_API_KEY},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json().get("web", {}).get("results", [])
        except Exception:
            pass
    return _search_duckduckgo(query, count=count)


def _pick_search_candidate(results: list, target_url: str, preferred_domain: str = "") -> dict:
    target = _canonicalize_url(target_url)
    target_path = urlparse(target).path
    target_slug = target_path.rstrip('/').split('/')[-1]
    best = None
    best_score = -1

    for result in results:
        result_url = _canonicalize_url(result.get("url", ""))
        if not result_url:
            continue
        score = 0
        result_domain = urlparse(result_url).netloc.replace("www.", "")
        result_path = urlparse(result_url).path
        if _same_article_url(result_url, target):
            score += 100
        if result_domain == preferred_domain:
            score += 25
        if result_path == target_path:
            score += 50
        if target_slug and target_slug in result_path:
            score += 10
        if score > best_score:
            best = result
            best_score = score

    return best if best_score > 0 else {}


def _techxplore_search_fallback(url: str) -> dict:
    canonical_url = _canonicalize_url(url)
    title_hint = _title_from_url(canonical_url)
    queries = [
        f'"{canonical_url}"',
        f'site:techxplore.com "{title_hint}"' if title_hint else "",
        f'site:techxplore.com {title_hint}' if title_hint else "",
        f'Tech Xplore {title_hint}' if title_hint else "",
    ]

    for query in queries:
        if not query:
            continue
        results = _search_brave(query, count=5)
        candidate = _pick_search_candidate(results, canonical_url, preferred_domain="techxplore.com")
        if not candidate:
            continue

        candidate_url = _canonicalize_url(candidate.get("url", "")) or canonical_url
        title = _clean_result_title(candidate.get("title", ""), "techxplore.com") or title_hint
        description = _clean_search_description(candidate.get("description", ""))
        if not title and not description:
            continue

        pieces = []
        if title:
            pieces.append(f"Title: {title}")
        if description:
            pieces.append(description)

        return {
            "title": title,
            "text": "\n\n".join(pieces).strip(),
            "resolved_url": candidate_url if urlparse(candidate_url).netloc.replace("www.", "") == "techxplore.com" else canonical_url,
        }

    return {}


def _search_and_enrich(url: str, title: str) -> dict:
    """Tier 5: Search the web for corroborating snippets/alternate copies only.

    Title-only AI reconstruction is deliberately disabled: search snippets are
    marked non-publishable by the caller and must be replaced with verified
    manual source text before a newsletter can be generated.
    """
    try:
        domain = urlparse(url).netloc.replace("www.", "")
        canonical_url = _canonicalize_url(url)
        search_queries = [
            f'"{canonical_url}"',
            f'site:{domain} {title[:80]}' if domain and title else "",
            title[:100],
            f"site:archive.org {title[:60]}",
        ]

        collected_text = []

        for query in search_queries:
            if not query:
                continue
            results = _search_brave(query, count=3)
            for r in results:
                desc = _clean_search_description(r.get("description", ""))
                result_url = r.get("url", "")
                if desc and len(desc) > 50:
                    if _same_article_url(result_url, canonical_url):
                        collected_text.insert(0, desc)
                    else:
                        collected_text.append(desc)

                if result_url and result_url != url and not any(pw in result_url for pw in ['wsj.com', 'ft.com', 'nytimes.com', 'bloomberg.com']):
                    result_domain = urlparse(result_url).netloc.replace("www.", "")
                    if result_domain == "techxplore.com":
                        continue
                    try:
                        resp2 = requests.get(result_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                        if resp2.status_code == 200:
                            text_np, _, _ = _extract_text_newspaper(result_url, resp2.text)
                            if text_np and len(text_np) > 200:
                                collected_text.append(text_np[:2000])
                                break
                    except Exception:
                        pass

        if collected_text:
            full_text = f"Title: {title}\n\n" + "\n\n".join(collected_text)
            if len(full_text) > MIN_TEXT_LENGTH:
                print(f"  ✅ Enriched from web search ({len(full_text)} chars)")
                return {"text": full_text, "mode": "search"}

        return {"text": "", "mode": ""}
    except Exception as e:
        print(f"  Web search enrichment failed: {e}")
        return {"text": "", "mode": ""}


def fetch_article(url: str) -> dict:
    """Fetch article with fallback handling and source integrity checks."""
    canonical_url = _canonicalize_url(url)
    domain = urlparse(canonical_url).netloc.replace("www.", "")
    result = {
        "url": canonical_url,
        "resolved_url": canonical_url,
        "title": "",
        "text": "",
        "image_url": "",
        "source_name": domain,
        "fetch_warnings": [],
        "manual_review_required": False,
        "manual_input_required": False,
        "unreliable_extraction": False,
        "publishable": True,
        "manual_required_fields": [],
        "manual_required_reasons": [],
        "manual_required_reason": "",
        "content_source": "direct",
    }

    html = None
    text = ""
    dns_blocked = False
    source_blocked = False

    html, err = _fetch_with_requests(canonical_url)
    if err and err.startswith("DNS_OR_CONNECTION:"):
        dns_blocked = True
        print(f"  ⚠️ Domain unreachable (DNS/connection blocked). Skipping to archive.org...")

    if html and _is_bot_challenge(html):
        source_blocked = True
        html = None
        mark_manual_required(
            result,
            f"{domain} returned a bot-check page instead of article content.",
            content_source="blocked",
            warning=f"{domain} returned a bot-check page instead of article content.",
        )
        print(f"  ⚠️ Source returned a bot-check page.")

    if html:
        meta = _extract_meta(html)
        result["title"] = _clean_result_title(meta["title"], domain)
        result["image_url"] = meta["image_url"]

        text_np, title_np, img_np = _extract_text_newspaper(canonical_url, html)
        if text_np and len(text_np) > MIN_TEXT_LENGTH:
            text = text_np
        cleaned_title_np = _clean_result_title(title_np, domain)
        if cleaned_title_np and not result["title"]:
            result["title"] = cleaned_title_np
        if img_np and not result["image_url"]:
            result["image_url"] = img_np

        if len(text) < MIN_TEXT_LENGTH:
            print(f"  Tier 1 text too short ({len(text)} chars), trying scrapling parser...")
            scrapling_text = _extract_with_scrapling(canonical_url, html)
            if len(scrapling_text) > len(text):
                text = scrapling_text

    if len(text) < MIN_TEXT_LENGTH and not dns_blocked and not source_blocked:
        print(f"  Tier 1 failed or insufficient. Trying scrapling Fetcher...")
        html2, err2 = _fetch_with_scrapling(canonical_url)
        if html2 and not _is_bot_challenge(html2):
            if not html:
                html = html2
                meta = _extract_meta(html2)
                if not result["title"]:
                    result["title"] = _clean_result_title(meta["title"], domain)
                if not result["image_url"]:
                    result["image_url"] = meta["image_url"]

            scrapling_text = _extract_with_scrapling(canonical_url, html2)
            if len(scrapling_text) > len(text):
                text = scrapling_text

            if len(text) < MIN_TEXT_LENGTH:
                text_np, title_np, img_np = _extract_text_newspaper(canonical_url, html2)
                if text_np and len(text_np) > len(text):
                    text = text_np
                cleaned_title_np = _clean_result_title(title_np, domain)
                if cleaned_title_np and not result["title"]:
                    result["title"] = cleaned_title_np
                if img_np and not result["image_url"]:
                    result["image_url"] = img_np
        else:
            print(f"  Scrapling Fetcher failed: {err2}")

    if len(text) < MIN_TEXT_LENGTH and not dns_blocked and not source_blocked:
        print(f"  Tier 2 insufficient ({len(text)} chars). Trying StealthyFetcher (headless browser)...")
        html3, err3 = _fetch_with_scrapling_stealth(canonical_url)
        if html3 and not _is_bot_challenge(html3):
            if not html:
                html = html3
                meta = _extract_meta(html3)
                if not result["title"]:
                    result["title"] = _clean_result_title(meta["title"], domain)
                if not result["image_url"]:
                    result["image_url"] = meta["image_url"]

            scrapling_text = _extract_with_scrapling(canonical_url, html3)
            if len(scrapling_text) > len(text):
                text = scrapling_text
        else:
            print(f"  StealthyFetcher failed: {err3}")

    if not result["title"]:
        url_title = _title_from_url(canonical_url)
        if url_title:
            result["title"] = url_title

    if len(text) < MIN_TEXT_LENGTH:
        print(f"  Tier 3 insufficient. Trying archive.org cache...")
        archive_text, archive_title, archive_img = _fetch_from_archive(canonical_url)
        if len(archive_text) > len(text):
            text = archive_text
            mark_manual_required(
                result,
                "Used archive.org cache because direct article extraction was unavailable or insufficient.",
                content_source="archive",
                warning="Used archive.org cache; provide verified source text manually before publishing.",
            )
        archive_title = _clean_result_title(archive_title, domain)
        if archive_title and not result["title"]:
            result["title"] = archive_title
        if archive_img and not result["image_url"]:
            result["image_url"] = archive_img

    if domain == "techxplore.com" and len(text) < MIN_TEXT_LENGTH:
        print(f"  Tech Xplore requires source-specific fallback...")
        techxplore_fallback = _techxplore_search_fallback(canonical_url)
        if techxplore_fallback.get("text") and len(techxplore_fallback["text"]) > len(text):
            text = techxplore_fallback["text"]
            result["title"] = techxplore_fallback.get("title") or result["title"]
            result["resolved_url"] = techxplore_fallback.get("resolved_url") or result["resolved_url"]
            mark_manual_required(
                result,
                "Used Tech Xplore search fallback because direct extraction was blocked.",
                content_source="search",
                warning="Used Tech Xplore search fallback because direct extraction was blocked; verified manual input is required before publishing.",
            )

    noise_patterns = [
        r'(?im)^.*copyright\s+\d{4}.*$',
        r'(?im)^.*all rights reserved.*$',
        r'(?im)^.*subscribe\s+(now|today|to).*$',
        r'(?im)^.*sign\s+in\s+to\s+(continue|read).*$',
        r'(?im)^.*cookie\s+(policy|settings|preferences).*$',
        r'(?im)^.*terms\s+of\s+(use|service).*$',
        r'(?im)^.*dow\s+jones\s+reprints.*$',
        r'(?im)^.*save\s+up\s+to\s+\$\d+.*$',
    ]
    useful_text = text
    for pat in noise_patterns:
        useful_text = re.sub(pat, '', useful_text)
    useful_text = re.sub(r'\s+', ' ', useful_text).strip()
    if len(useful_text) < 500:
        title_hint = result["title"] if result["title"] and not _is_bot_challenge("", result["title"]) else _title_from_url(canonical_url)
        print(f"  Text insufficient ({len(useful_text)} useful chars). Trying web search enrichment for: {title_hint[:60]}...")
        search_result = _search_and_enrich(canonical_url, title_hint)
        search_text = search_result.get("text", "")
        if len(search_text) > len(text):
            text = search_text
            result["content_source"] = search_result.get("mode", result["content_source"] or "search")
            if result["content_source"] == "search":
                mark_manual_required(
                    result,
                    "Used search snippets or alternate search results because source extraction was limited.",
                    content_source="search",
                    warning="Used search fallback because source extraction was limited; verified manual input is required before publishing.",
                )

    if len(text) < MIN_TEXT_LENGTH and html and not _is_bot_challenge(html, result["title"]):
        print(f"  Falling back to HTML stripping...")
        text = _strip_html(html)
        mark_manual_required(
            result,
            "Used raw HTML stripping after structured article extraction failed; extracted text may include unrelated page content.",
            content_source="html_strip",
            warning="Used HTML stripping fallback; provide verified article body/source text manually before publishing.",
        )

    if not result["title"]:
        result["title"] = _title_from_url(canonical_url)

    result["text"] = text
    if not text or len(text) < MIN_TEXT_LENGTH:
        print(f"  WARNING: Could not extract sufficient text from {canonical_url} ({len(text)} chars)")
        mark_manual_required(
            result,
            f"Could not extract sufficient article body text ({len(text)} chars; minimum {MIN_TEXT_LENGTH}).",
            content_source=result.get("content_source") or "insufficient_text",
            warning="Could not extract sufficient article body text; manual input is required before publishing.",
        )

    return result


def download_image(image_url: str, output_path: str, article_title: str = "") -> bool:
    """Download image from URL to local path. Falls back to generated art or placeholder if needed."""
    try:
        if os.path.exists(output_path):
            os.remove(output_path)
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(image_url, headers=headers, timeout=15)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)

        valid_image = False
        width = height = 0
        try:
            with Image.open(output_path) as img:
                img.load()
                if img.format and img.format.upper() not in ('BMP', 'GIF', 'JPEG', 'PNG', 'TIFF', 'WMF'):
                    print(f"  Converting {img.format} → JPEG for PowerPoint compatibility")
                    rgb_img = img.convert('RGB')
                    jpeg_path = output_path.rsplit('.', 1)[0] + '.jpg'
                    rgb_img.save(jpeg_path, 'JPEG', quality=90)
                    rgb_img.close()
                    os.replace(jpeg_path, output_path)
            with Image.open(output_path) as img:
                img.load()
                width, height = img.size
                valid_image = width > 0 and height > 0
        except Exception:
            valid_image = False

        file_size = os.path.getsize(output_path)

        if not valid_image or file_size < 20480 or width < 300 or height < 300:
            print(f"  Low quality image ({file_size}B, {width}x{height}). Trying generated fallback image...")
            if article_title and generate_image_gemini(article_title, output_path):
                return True
            if os.path.exists(output_path):
                os.remove(output_path)
            return False

        return True
    except Exception as e:
        print(f"Error downloading image {image_url}: {e}")
        if article_title:
            print(f"  Trying generated fallback image...")
            return generate_image_gemini(article_title, output_path)
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        return False


def generate_image_gemini(title: str, output_path: str) -> bool:
    """Backward-compatible wrapper for article image fallback generation."""
    return generate_article_fallback_image(title, output_path)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) > 1:
        result = fetch_article(sys.argv[1])
        print(json.dumps(result, indent=2, ensure_ascii=False))
