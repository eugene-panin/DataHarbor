"""Base utilities for all DataHarbor extractors."""
import re
from urllib.parse import parse_qs, unquote, urlparse


def extract_clean_website(raw_url: str | None) -> str | None:
    """Unquotes redirect parameters, strips tracking query parameters, sanitizes unicode spaces, and normalizes target domain links."""
    if not raw_url:
        return None
    url = str(raw_url).replace("\u200b", "").replace("\ufeff", "").replace("\xa0", "").strip()
    if "redirect?" in url or "u=" in url:
        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if qs.get("u"):
                url = unquote(qs["u"][0])
        except Exception:
            pass
    if url:
        url = url.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
        
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower().strip()
            netloc = netloc.removeprefix("www.")
            path = parsed.path.rstrip("/").strip()
            url = f"https://{netloc}{path}"
        except Exception:
            pass
    return url.strip() if url else None

def compute_lead_score(rating_str: str | None, review_count: int, min_project_size: str | None) -> int:
    """Computes a lead quality score (1-100) based on agency metrics."""
    score = 50
    try:
        if rating_str:
            rating_num = float(re.sub(r"[^\d.]", "", rating_str))
            if rating_num >= 4.8:
                score += 20
            elif rating_num >= 4.5:
                score += 10

        if review_count > 30:
            score += 15
        elif review_count > 10:
            score += 10

        if min_project_size:
            if "50,000" in min_project_size or "100,000" in min_project_size:
                score += 15
            elif "10,000" in min_project_size or "25,000" in min_project_size:
                score += 10
    except Exception:
        pass
    return min(score, 100)
