import re
import requests
from bs4 import BeautifulSoup, Comment
import trafilatura
import tldextract
from loguru import logger
from urllib.parse import urlparse

_JOB_SIGNALS = [
    "responsibilities", "qualifications", "requirements", "experience",
    "about the role", "what you'll do", "who you are", "nice to have",
    "preferred qualifications", "minimum qualifications", "equal opportunity",
    "benefits", "compensation", "salary", "apply now", "about us",
    "years of experience", "bachelor", "degree", "full-time", "part-time",
    "job description", "role overview", "team overview",
]

_JUNK_PHRASES = [
    "enable cookies", "cookie policy", "cookie consent", "interaction data",
    "we use cookies", "cookies are used", "accept all cookies",
    "javascript is required", "enable javascript", "browser does not support",
    "access denied", "403 forbidden", "you have been blocked",
    "please verify you are a human", "captcha", "one moment",
    "checking your browser", "ray id", "cloudflare",
    "sign in to continue", "log in to view", "create an account",
    "page not found", "404 error", "this page isn't available",
    "request unsuccessful", "incapsula",
]

# Shared across BeautifulSoup and Playwright extraction tiers
_JOB_SELECTORS = [
    '[data-automation="jobDescription"]',
    '[class*="job-description"]', '[class*="jobDescription"]',
    '[class*="job-details"]', '[class*="jobDetails"]',
    '[class*="posting-requirements"]',
    '[id*="job-description"]', '[id*="jobDescription"]',
    '[id*="job-details"]', '[id*="jobDetails"]',
    'article[class*="job"]',
    '[class*="description-content"]',
    '[class*="posting-page"]',
    'main',
    '[role="main"]',
]

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _content_quality_score(text: str) -> float:
    """Score extracted text 0–100 for likelihood of being a real job description."""
    if not text:
        return 0.0

    lower = text.lower()
    score = 0.0

    n = len(text)
    if n < 200:
        score += 0
    elif n < 500:
        score += 5
    elif n < 1500:
        score += 15
    elif n < 5000:
        score += 25
    else:
        score += 35

    signal_hits = sum(1 for s in _JOB_SIGNALS if s in lower)
    score += min(signal_hits * 5, 40)

    head = lower[:600]
    tail = lower[-400:] if len(lower) > 400 else ""
    junk_hits = sum(1 for j in _JUNK_PHRASES if j in head or j in tail)
    score -= junk_hits * 15

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) > 5:
        score += (len(set(lines)) / len(lines)) * 15
    else:
        score += 5

    bullet_count = len(re.findall(r'(?m)^[\s]*[\-•●◦▪\*]\s', text))
    bullet_count += len(re.findall(r'(?m)^[\s]*\d+[\.\)]\s', text))
    if bullet_count >= 3:
        score += 10

    return max(0.0, min(100.0, score))


def _is_usable(text: str, min_score: float = 30.0) -> bool:
    if not text:
        return False
    score = _content_quality_score(text)
    logger.debug(f"  Quality score: {score:.1f}/100 | Length: {len(text)} chars")
    return score >= min_score


def _extract_beautifulsoup(url: str) -> str | None:
    logger.info("[Tier 2] Attempting requests + BeautifulSoup extraction...")
    try:
        resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=20, allow_redirects=True)
        logger.debug(f"[Tier 2] HTTP {resp.status_code} | Content-Length: {len(resp.content)}")

        if resp.status_code != 200:
            logger.warning(f"[Tier 2] Non-200 response: {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "head",
                         "noscript", "meta", "svg", "iframe", "aside", "form"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()
        for el in soup.find_all(attrs={"style": re.compile(r"display\s*:\s*none", re.I)}):
            el.decompose()
        for el in soup.find_all(attrs={"hidden": True}):
            el.decompose()
        for el in soup.find_all(attrs={"aria-hidden": "true"}):
            el.decompose()

        for selector in _JOB_SELECTORS:
            container = soup.select_one(selector)
            if container:
                candidate = " ".join(container.get_text(separator=" ").split())
                if _is_usable(candidate, min_score=25):
                    logger.success(f"[Tier 2] BS4 targeted selector '{selector}' extracted {len(candidate)} chars.")
                    return candidate

        text = " ".join(soup.get_text(separator=" ").split())
        logger.info(f"[Tier 2] BS4 full-body extracted {len(text)} chars.")
        return text if text else None

    except Exception as e:
        logger.warning(f"[Tier 2] BeautifulSoup error: {e}")
        return None


def _extract_playwright(url: str) -> str | None:
    logger.info("[Tier 3] Launching headless Chromium via Playwright...")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,eot,ico}", lambda r: r.abort())
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            _dismiss_cookie_banners(page)
            page.wait_for_timeout(3000)

            best_text = None
            best_score = 0

            for selector in _JOB_SELECTORS:
                try:
                    el = page.query_selector(selector)
                    if el:
                        candidate = " ".join(el.inner_text().split())
                        s = _content_quality_score(candidate)
                        if s > best_score:
                            best_score = s
                            best_text = candidate
                            logger.debug(f"[Tier 3] Selector '{selector}' scored {s:.1f} ({len(candidate)} chars)")
                except Exception:
                    continue

            if _is_usable(best_text, min_score=30):
                browser.close()
                logger.success(f"[Tier 3] Playwright targeted extraction: {len(best_text)} chars (score {best_score:.1f}).")
                return best_text

            text = " ".join(page.inner_text("body").split())
            browser.close()
            logger.info(f"[Tier 3] Playwright full-body extracted {len(text)} chars.")
            return text if text else None

    except Exception as e:
        logger.warning(f"[Tier 3] Playwright error: {e}")
        return None


def _dismiss_cookie_banners(page):
    COOKIE_SELECTORS = [
        'button:has-text("Accept")', 'button:has-text("Accept All")',
        'button:has-text("Accept Cookies")', 'button:has-text("I Accept")',
        'button:has-text("Got it")', 'button:has-text("OK")',
        'button:has-text("Agree")', 'button:has-text("Allow")',
        'button:has-text("Allow All")', 'button:has-text("Continue")',
        'button:has-text("Dismiss")', 'button:has-text("Close")',
        '[id*="cookie"] button', '[class*="cookie"] button',
        '[id*="consent"] button', '[class*="consent"] button',
        '[id*="gdpr"] button', '[class*="gdpr"] button',
        '[class*="banner"] button[class*="accept"]',
        '[id*="onetrust"] button#onetrust-accept-btn-handler',
    ]
    for selector in COOKIE_SELECTORS:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                logger.debug(f"[Tier 3] Dismissed cookie banner via '{selector}'")
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue


def _extract_title_from_html(html: str) -> str:
    title = "TailoredJob"
    try:
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            title = re.sub(r" - | \| | Careers at .*", "", meta.title).split(" - ")[0]
            title = "".join(c for c in title if c.isalnum() or c in (" ", "-")).strip()
    except Exception:
        pass
    return title


def _extract_title_from_page(page) -> str:
    try:
        page_title = page.title()
        if page_title and "moment" not in page_title.lower():
            title = re.sub(r" - | \| | Careers at .*| in .*", "", page_title).split(" - ")[0]
            return "".join(c for c in title if c.isalnum() or c in (" ", "-")).strip()
    except Exception:
        pass
    return "TailoredJob"


class JobScraper:
    @staticmethod
    def get_job_info(url_or_text: str) -> tuple[str, str, str | None]:
        if not url_or_text.startswith("http"):
            return "CustomJob", "Manual", url_or_text

        logger.info(f"Scraping Job Description from: {url_or_text}")

        ext = tldextract.extract(url_or_text)
        url_path = urlparse(url_or_text).path
        path_segments = [p for p in url_path.split("/") if p]

        PLATFORM_EXTRACTORS = {
            "greenhouse": lambda ext, seg: seg[0] if seg else ext.subdomain,
            "lever": lambda ext, seg: seg[0] if seg else ext.subdomain,
            "myworkdayjobs": lambda ext, seg: ext.subdomain.split(".")[0],
            "myworkdaysite": lambda ext, seg: seg[1] if len(seg) > 1 else ext.subdomain,
            "smartrecruiters": lambda ext, seg: seg[0] if seg else ext.subdomain,
            "ashbyhq": lambda ext, seg: seg[0] if seg else ext.subdomain,
            "bamboohr": lambda ext, seg: ext.subdomain.split(".")[0],
            "eightfold": lambda ext, seg: ext.subdomain.split(".")[0],
            "icims": lambda ext, seg: ext.subdomain.replace("careers-", "").replace("careers", "").split(".")[0],
        }

        extractor_fn = PLATFORM_EXTRACTORS.get(ext.domain)
        if extractor_fn:
            company_name = extractor_fn(ext, path_segments)
        elif ext.subdomain in ("careers", "jobs", "boards", "career", "www", ""):
            company_name = ext.domain
        else:
            company_name = ext.subdomain.split(".")[0]

        company_name = re.sub(r"^wd\d+$", "", company_name)
        company_name = company_name.replace("_", " ").replace("-", " ").strip()
        company_name = company_name.title() if company_name else ext.domain.capitalize()

        job_title = "TailoredJob"
        raw_html = None
        try:
            raw_html = trafilatura.fetch_url(url_or_text)
            if raw_html:
                job_title = _extract_title_from_html(raw_html)
        except Exception:
            pass

        ACCEPT_THRESHOLD = 50
        candidates: list[tuple[str, str, float]] = []

        # Tier 1: Trafilatura
        if raw_html:
            logger.info("[Tier 1] Attempting trafilatura extraction...")
            try:
                t1 = trafilatura.extract(raw_html, include_comments=False, include_tables=True,
                                         no_fallback=True, favor_precision=True)
                if not _is_usable(t1):
                    t1_alt = trafilatura.extract(raw_html, include_comments=False, include_tables=True,
                                                 no_fallback=False, favor_recall=True)
                    if t1_alt and _content_quality_score(t1_alt) > _content_quality_score(t1 or ""):
                        t1 = t1_alt
            except Exception as e:
                logger.warning(f"[Tier 1] trafilatura error: {e}")
                t1 = None

            if t1:
                s1 = _content_quality_score(t1)
                candidates.append(("trafilatura", t1, s1))
                logger.info(f"[Tier 1] trafilatura: {len(t1)} chars, score {s1:.1f}")
                if s1 >= ACCEPT_THRESHOLD:
                    logger.success("[Tier 1] High-confidence result accepted.")
                    return company_name, job_title, t1
            else:
                logger.warning("[Tier 1] trafilatura produced no usable text.")

        # Tier 2: Requests + BeautifulSoup
        t2 = _extract_beautifulsoup(url_or_text)
        if t2:
            s2 = _content_quality_score(t2)
            candidates.append(("beautifulsoup", t2, s2))
            logger.info(f"[Tier 2] BeautifulSoup: {len(t2)} chars, score {s2:.1f}")
            if s2 >= ACCEPT_THRESHOLD:
                logger.success("[Tier 2] High-confidence result accepted.")
                return company_name, job_title, t2
        else:
            logger.warning("[Tier 2] BeautifulSoup produced no usable text.")

        # Tier 3: Playwright
        t3 = _extract_playwright(url_or_text)
        if t3:
            s3 = _content_quality_score(t3)
            candidates.append(("playwright", t3, s3))
            logger.info(f"[Tier 3] Playwright: {len(t3)} chars, score {s3:.1f}")
            if s3 >= ACCEPT_THRESHOLD:
                logger.success("[Tier 3] High-confidence result accepted.")
                return company_name, job_title, t3
        else:
            logger.warning("[Tier 3] Playwright produced no usable text.")

        if candidates:
            candidates.sort(key=lambda c: c[2], reverse=True)
            winner_engine, winner_text, winner_score = candidates[0]
            logger.info(f"No engine hit threshold ({ACCEPT_THRESHOLD}). Best: {winner_engine} (score {winner_score:.1f})")
            if winner_score >= 15:
                logger.warning(f"Accepting low-confidence result from {winner_engine}.")
                return company_name, job_title, winner_text
            logger.error(f"Best candidate scored only {winner_score:.1f} — likely not a real job description.")

        logger.error("All extraction methods failed for this URL.")
        return company_name, job_title, None
