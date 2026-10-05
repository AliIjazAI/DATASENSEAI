import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


class BusinessEnrichmentAnalyzer:

    def __init__(self, job_id, jobs, logger):
        self.job_id = job_id
        self.jobs = jobs
        self.log = logger

        self.headers = {
            "User-Agent": "Mozilla/5.0"
        }

    # ------------------------
    # MAIN ENTRY
    # ------------------------
    def enrich_row(self, row):

        website = str(row.get("Website Link", "")).strip()
        shop = str(row.get("Shop Name", "")).strip()

        result = {
            "Shop Name": shop,
            "Website": website,
            "Owner Name": "",
            "Owner Title": "",
            "Email": "",
            "Phone": "",
            "Company Name": "",
            "Confidence": 0,
            "Sources": ""
        }

        try:
            self.log(self.job_id, f"Scraping: {website}")

            text = self._scrape_all_pages(website)

            emails = self._extract_emails(text)
            phones = self._extract_phones(text)
            owner = self._extract_owner(text)
            company = self._extract_company(text)

            result["Email"] = emails[0] if emails else ""
            result["Phone"] = phones[0] if phones else ""
            result["Owner Name"] = owner
            result["Company Name"] = company

            score = 0
            if owner:
                score += 40
            if emails:
                score += 20
            if phones:
                score += 20
            if company:
                score += 20

            result["Confidence"] = score
            result["Sources"] = "Website Scrape"

            return result

        except Exception as e:
            self.log(self.job_id, f"Row error: {str(e)}")
            return result

    # ------------------------
    # SCRAPING CORE
    # ------------------------
    def _scrape_all_pages(self, website):

        pages = [
            website,
            urljoin(website, "/about"),
            urljoin(website, "/contact"),
            urljoin(website, "/team"),
            urljoin(website, "/privacy"),
        ]

        text = ""

        for p in pages:
            try:
                r = requests.get(p, headers=self.headers, timeout=8)
                soup = BeautifulSoup(r.text, "html.parser")
                text += " " + soup.get_text(" ", strip=True)
            except:
                continue

        return text

    # ------------------------
    # EXTRACTION LOGIC
    # ------------------------
    def _extract_emails(self, text):
        return re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)

    def _extract_phones(self, text):
        return re.findall(r"\+?\d[\d\-\(\)\s]{8,}\d", text)

    def _extract_company(self, text):
        match = re.findall(
            r"([A-Z][A-Za-z0-9\s,&\-]{3,}(LLC|Inc|Corp|Company|Co))",
            text
        )
        return match[0][0] if match else ""

    def _extract_owner(self, text):
        patterns = [
            r"(?:owner|founder|ceo|director)\s*[:\-]?\s*([A-Z][a-z]+\s[A-Z][a-z]+)",
            r"([A-Z][a-z]+\s[A-Z][a-z]+)\s*(?:owner|founder|ceo)"
        ]

        for p in patterns:
            m = re.findall(p, text, re.IGNORECASE)
            if m:
                return m[0]

        return ""