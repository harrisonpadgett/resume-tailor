import re
import requests
from bs4 import BeautifulSoup
import trafilatura
import tldextract
from loguru import logger
from urllib.parse import urlparse

class JobScraper:
    @staticmethod
    def get_job_info(url_or_text, gemini_model=None) -> (str, str, str):
        if not url_or_text.startswith('http'):
            return "CustomJob", "Manual", url_or_text
        
        logger.info(f"Scraping Job Description from: {url_or_text}")
        
        ext = tldextract.extract(url_or_text)
        url_path = urlparse(url_or_text).path
        path_segments = [p for p in url_path.split('/') if p]
        
        PLATFORM_EXTRACTORS = {
            'greenhouse': lambda ext, seg: seg[0] if seg else ext.subdomain,
            'lever': lambda ext, seg: seg[0] if seg else ext.subdomain,
            'myworkdayjobs': lambda ext, seg: ext.subdomain.split('.')[0],
            'myworkdaysite': lambda ext, seg: seg[1] if len(seg) > 1 else ext.subdomain,
            'smartrecruiters': lambda ext, seg: seg[0] if seg else ext.subdomain,
            'ashbyhq': lambda ext, seg: seg[0] if seg else ext.subdomain,
            'bamboohr': lambda ext, seg: ext.subdomain.split('.')[0],
            'eightfold': lambda ext, seg: ext.subdomain.split('.')[0],
            'icims': lambda ext, seg: ext.subdomain.replace('careers-', '').replace('careers', '').split('.')[0],
        }
        
        extractor = PLATFORM_EXTRACTORS.get(ext.domain)
        if extractor:
            company_name = extractor(ext, path_segments)
        elif ext.subdomain in ('careers', 'jobs', 'boards', 'career', 'www', ''):
            company_name = ext.domain
        else:
            company_name = ext.subdomain.split('.')[0]
        
        company_name = re.sub(r'^wd\d+$', '', company_name)
        company_name = company_name.replace('_', ' ').replace('-', ' ').strip()
        company_name = company_name.title() if company_name else ext.domain.capitalize()

        try:
            downloaded = trafilatura.fetch_url(url_or_text)
            job_title = "TailoredJob"
            if downloaded:
                meta = trafilatura.extract_metadata(downloaded)
                if meta and meta.title:
                    job_title = re.sub(r' - | \| | Careers at .*', '', meta.title).split(' - ')[0]
                    job_title = "".join([c for c in job_title if c.isalnum() or c in (' ', '-')]).strip()
            
            text = trafilatura.extract(downloaded, include_comments=False, include_tables=True, no_fallback=False) if downloaded else None
            
            if not text:
                logger.info("Trafilatura failed, falling back to requests+BeautifulSoup...")
                try:
                    response = requests.get(url_or_text, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, 'html.parser')
                        for s in soup(["script", "style", "nav", "footer", "header", "head", "noscript", "meta", "svg", "iframe", "aside"]): 
                            s.decompose()
                        text = ' '.join(soup.get_text(separator=' ').split())
                        text = re.sub(r'<[^>]+>', '', text)
                        if job_title == "TailoredJob" and soup.title:
                            job_title = soup.title.string or "TailoredJob"
                    else:
                        logger.info(f"BeautifulSoup got HTTP {response.status_code}, skipping.")
                except Exception as bs_err:
                    logger.warning(f"BeautifulSoup fallback failed: {bs_err}")

            if not text:
                logger.info("Static scrapers failed (likely bot-protected). Launching headless browser via Playwright...")
                try:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
                        ctx = browser.new_context(user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')
                        page = ctx.new_page()
                        page.goto(url_or_text, wait_until='domcontentloaded', timeout=60000)
                        page.wait_for_timeout(8000)
                        
                        if job_title == "TailoredJob":
                            page_title = page.title()
                            if page_title and "moment" not in page_title.lower():
                                job_title = re.sub(r' - | \| | Careers at .*| in .*', '', page_title).split(' - ')[0]
                                job_title = "".join([c for c in job_title if c.isalnum() or c in (' ', '-')]).strip()
                        
                        text = page.inner_text('body')
                        text = ' '.join(text.split())
                        text = re.sub(r'<[^>]+>', '', text)
                        browser.close()
                        logger.success(f"Playwright extracted {len(text)} chars successfully.")
                except Exception as pw_err:
                    logger.warning(f"Playwright fallback failed: {pw_err}")

            if not text:
                logger.error("All extraction methods failed for URL.")
                return company_name, job_title, None

            if company_name in ["Jobs", "Careers", "Board"] and gemini_model:
                extraction_prompt = f"Extract ONLY the company name from this text. No other text:\n\n{text[:500]}"
                comp_res = gemini_model.models.generate_content(model='gemini-2.0-flash-lite', contents=extraction_prompt)
                company_name = comp_res.text.strip()

            return company_name, job_title, text
        except Exception as e:
            logger.error(f"Error scraping URL: {e}")
            return company_name or "TailoredJob", "Manual", None
