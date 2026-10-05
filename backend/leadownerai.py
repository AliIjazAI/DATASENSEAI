import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager


HEADERS = {"User-Agent": "Mozilla/5.0"}

COMMON_PATHS = [
    "/", "/about", "/about-us", "/contact",
    "/contact-us", "/team", "/privacy", "/privacy-policy"
]

# =========================
# DRIVER FIX
# =========================
def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

# =========================
# FETCH
# =========================
def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        return r.text if r.status_code == 200 else ""
    except:
        return ""

# =========================
# FAST CRAWL
# =========================
def crawl_site(base_url):
    pages = []

    for p in COMMON_PATHS:
        url = urljoin(base_url, p)
        html = fetch(url)
        if html:
            pages.append(html)

    return pages

# =========================
# SELENIUM LIVE CRAWL (FIXED)
# =========================
def crawl_site_live(url):
    driver = create_driver()
    pages = []

    try:
        driver.get(url)
        time.sleep(3)

        pages.append(driver.page_source)

        links = driver.find_elements(By.TAG_NAME, "a")

        keywords = ["about", "contact", "team", "privacy"]

        for l in links:
            try:
                href = l.get_attribute("href")
                if not href:
                    continue

                if any(k in href.lower() for k in keywords):
                    driver.get(href)
                    time.sleep(2)
                    pages.append(driver.page_source)

            except:
                continue

    except Exception as e:
        print("Selenium error:", e)

    finally:
        driver.quit()

    return pages

# =========================
# EXTRACT COMPANY
# =========================
def extract_company(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.title.text.strip() if soup.title else None

# =========================
# CONTACTS
# =========================
def extract_contacts(text):
    emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    phones = re.findall(r"\+?\d[\d\s\-\(\)]{7,}\d", text)

    return {
        "emails": list(set(emails)),
        "phones": list(set(phones))
    }

# =========================
# LEGAL NAME
# =========================
def extract_legal(text):
    pattern = r"[A-Z][A-Za-z0-9&,. ]+\s(LLC|Inc|Corp|Ltd|Co)"
    m = re.search(pattern, text)
    return m.group(0) if m else None

# =========================
# MAIN PROCESS
# =========================
def process_url(url):

    pages = crawl_site(url)
    mode = "fast"

    if not pages:
        pages = crawl_site_live(url)
        mode = "live"

    all_text = BeautifulSoup(
        "".join(pages),
        "html.parser"
    ).get_text(" ", strip=True)

    company = extract_company(pages[0]) if pages else None
    legal = extract_legal(all_text)
    contacts = extract_contacts(all_text)

    return {
        "url": url,
        "company": company,
        "legal": legal,
        "emails": contacts["emails"],
        "phones": contacts["phones"],
        "mode": mode
    }

# =========================
# STREAM FIXED (IMPORTANT)
# =========================
def stream_process(urls):
    total = len(urls)

    for i, url in enumerate(urls, 1):

        try:
            result = process_url(url)

            yield {
                "type": "progress",
                "current": i,
                "total": total
            }

            yield {
                "type": "data",
                "row": result
            }

        except Exception as e:

            yield {
                "type": "error",
                "message": str(e),
                "url": url
            }

    yield {"type": "done"}