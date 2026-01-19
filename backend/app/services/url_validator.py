"""
URL validation for BSE India annual reports links
"""
import re
from typing import Tuple, Optional


# BSE India annual reports URL pattern
BSE_URL_PATTERN = re.compile(
    r'^https://www\.bseindia\.com/stock-share-price/([^/]+)/([^/]+)/(\d+)/financials-annual-reports/?$',
    re.IGNORECASE
)


def validate_bse_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate if the URL is a valid BSE India annual reports URL.
    
    Args:
        url: The URL to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url:
        return False, "URL is required"
    
    if not url.startswith("https://"):
        return False, "URL must use HTTPS"
    
    if "bseindia.com" not in url.lower():
        return False, "URL must be from bseindia.com"
    
    match = BSE_URL_PATTERN.match(url.strip())
    if not match:
        return False, (
            "Invalid BSE URL format. Expected format: "
            "https://www.bseindia.com/stock-share-price/{company-name}/{symbol}/{code}/financials-annual-reports/"
        )
    
    return True, None


def extract_company_name(url: str) -> str:
    """
    Extract company name from BSE URL.
    
    Example:
        Input: https://www.bseindia.com/stock-share-price/vimta-labs-ltd/vimtalabs/524394/financials-annual-reports/
        Output: VIMTA LABS LTD
    """
    match = BSE_URL_PATTERN.match(url.strip())
    if match:
        company_slug = match.group(1)
        # Convert slug to proper name (replace hyphens with spaces, uppercase)
        return company_slug.replace("-", " ").upper()
    return "UNKNOWN COMPANY"


def extract_company_symbol(url: str) -> str:
    """
    Extract company trading symbol from BSE URL.
    
    Example:
        Input: https://www.bseindia.com/stock-share-price/vimta-labs-ltd/vimtalabs/524394/financials-annual-reports/
        Output: VIMTALABS
    """
    match = BSE_URL_PATTERN.match(url.strip())
    if match:
        return match.group(2).upper()
    return "UNKNOWN"


def extract_company_code(url: str) -> str:
    """
    Extract BSE company code from URL.
    
    Example:
        Input: https://www.bseindia.com/stock-share-price/vimta-labs-ltd/vimtalabs/524394/financials-annual-reports/
        Output: 524394
    """
    match = BSE_URL_PATTERN.match(url.strip())
    if match:
        return match.group(3)
    return ""
