"""
BSE India PDF Scraper using Playwright (Sync API for Windows compatibility)
Scrapes annual report PDFs from BSE India pages (dynamic JS-rendered content)
"""
import asyncio
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright, Browser as SyncBrowser, Page as SyncPage

from app.core.config import settings
from app.core.logging import scraper_logger, console_logger


@dataclass
class PDFInfo:
    """Information about a scraped PDF"""
    url: str
    year: int
    label: str
    pdf_buffer: Optional[bytes] = None


@dataclass
class ScrapeResult:
    """Result of scraping operation"""
    success: bool
    pdfs: List[PDFInfo]
    error: Optional[str] = None


class BSEScraper:
    """Scraper for BSE India annual reports pages using sync Playwright"""
    
    def __init__(self):
        self.headless = settings.PLAYWRIGHT_HEADLESS
        self.timeout = settings.PLAYWRIGHT_TIMEOUT
        self.executor = ThreadPoolExecutor(max_workers=2)
    
    async def scrape_latest_annual_report(
        self, 
        url: str,
        project_id: Optional[str] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> ScrapeResult:
        """
        Scrape BSE India page using sync Playwright in a thread pool.
        This avoids Windows asyncio subprocess issues.
        """
        if on_progress is None:
            on_progress = lambda x: None
        
        # Run the sync scraper in a thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor,
            self._scrape_sync,
            url,
            project_id,
            on_progress
        )
        return result
    
    def _scrape_sync(
        self,
        url: str,
        project_id: Optional[str],
        on_progress: Callable
    ) -> ScrapeResult:
        """Synchronous scraping using sync Playwright API"""
        scraper_logger.info(
            f"Starting scrape for URL: {url}",
            project_id=project_id,
            data={"url": url}
        )
        console_logger.info(f"🔍 Starting scrape for: {url}")
        
        on_progress({"step": "scraping", "message": "Launching browser..."})
        
        try:
            with sync_playwright() as p:
                # Launch browser
                browser = p.chromium.launch(
                    headless=self.headless,
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                
                # Create context
                context = browser.new_context(
                    accept_downloads=True,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                page = context.new_page()
                
                on_progress({"step": "scraping", "message": "Navigating to BSE India page..."})
                scraper_logger.info("Navigating to page", project_id=project_id)
                
                # Navigate
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                on_progress({"step": "scraping", "message": "Waiting for annual reports..."})
                
                # Wait for PDF links
                try:
                    page.wait_for_selector('a[href*=".pdf"]', timeout=20000)
                    console_logger.info("✅ Found PDF links on page")
                except Exception:
                    console_logger.warning("⚠️ PDF links not found quickly, waiting more...")
                    page.wait_for_timeout(8000)
                
                on_progress({"step": "scraping", "message": "Finding latest annual report..."})
                
                # Extract PDF links
                pdf_info_list = self._extract_pdf_links_sync(page)
                
                if not pdf_info_list:
                    browser.close()
                    return ScrapeResult(
                        success=False,
                        pdfs=[],
                        error="Could not find PDF download links on the page"
                    )
                
                unique_years = list(set(p["year"] for p in pdf_info_list))
                console_logger.info(f"📥 Found {len(pdf_info_list)} PDF(s) from years: {unique_years}")
                
                # Download PDFs
                downloaded_pdfs = []
                
                for i, pdf_info in enumerate(pdf_info_list):
                    console_logger.info(f"📥 [{i+1}/{len(pdf_info_list)}] Downloading: {pdf_info['label']}")
                    
                    on_progress({
                        "step": "downloading",
                        "message": f"Downloading PDF {i+1}/{len(pdf_info_list)}: {pdf_info['label']}..."
                    })
                    
                    try:
                        pdf_buffer = self._download_pdf_sync(context, pdf_info["url"])
                        
                        if pdf_buffer:
                            file_size_mb = len(pdf_buffer) / 1024 / 1024
                            console_logger.info(f"✅ Downloaded: {file_size_mb:.2f} MB")
                            
                            downloaded_pdfs.append(PDFInfo(
                                url=pdf_info["url"],
                                year=pdf_info["year"],
                                label=pdf_info["label"],
                                pdf_buffer=pdf_buffer
                            ))
                    
                    except Exception as e:
                        console_logger.error(f"❌ Failed to download {pdf_info['label']}: {e}")
                
                browser.close()
                
                if not downloaded_pdfs:
                    return ScrapeResult(
                        success=False,
                        pdfs=[],
                        error="Failed to download any PDFs"
                    )
                
                console_logger.info(f"✅ Successfully downloaded {len(downloaded_pdfs)} PDF(s)")
                return ScrapeResult(success=True, pdfs=downloaded_pdfs)
        
        except Exception as error:
            console_logger.error(f"❌ Scraping error: {error}")
            scraper_logger.error(
                f"Scraping failed",
                project_id=project_id,
                data={"error": str(error), "url": url}
            )
            return ScrapeResult(success=False, pdfs=[], error=str(error))
    
    def _extract_pdf_links_sync(self, page: SyncPage) -> List[Dict[str, Any]]:
        """Extract PDF links from page"""
        pdf_info_list = page.evaluate('''() => {
            const pdfLinks = Array.from(document.querySelectorAll('a[href*=".pdf"]'));
            const annualReportData = [];
            
            pdfLinks.forEach(link => {
                const href = link.href;
                const row = link.closest('tr');
                
                if (row) {
                    const text = row.innerText;
                    const isAnnualReport = href.includes('AttachHis') || href.includes('AnnualReport');
                    const yearMatch = text.match(/20(\\d{2})/);
                    
                    if (isAnnualReport && yearMatch) {
                        const year = parseInt('20' + yearMatch[1]);
                        const cells = row.querySelectorAll('td');
                        const label = cells[0]?.innerText?.trim() || `Year ${year}`;
                        
                        annualReportData.push({url: href, year: year, label: label});
                    }
                }
            });
            
            if (annualReportData.length === 0 && pdfLinks.length > 0) {
                const firstLink = pdfLinks[0];
                const row = firstLink.closest('tr');
                return [{
                    url: firstLink.href,
                    year: 0,
                    label: row ? row.querySelector('td')?.innerText?.trim() : 'unknown'
                }];
            }
            
            const uniqueYears = [...new Set(annualReportData.map(d => d.year))].sort((a, b) => b - a);
            const latestYear = uniqueYears[0];
            const filteredReports = annualReportData.filter(d => d.year === latestYear);
            
            return filteredReports.length > 0 ? [filteredReports[0]] : [];
        }''')
        
        return pdf_info_list or []
    
    def _download_pdf_sync(self, context, pdf_url: str) -> Optional[bytes]:
        """Download PDF synchronously using requests"""
        import requests
        
        try:
            console_logger.info(f"📥 Downloading PDF from: {pdf_url}")
            
            # Download PDF using requests (simpler and more reliable)
            response = requests.get(
                pdf_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                },
                timeout=180
            )
            
            response.raise_for_status()
            
            pdf_buffer = response.content
            
            if not pdf_buffer or len(pdf_buffer) < 1024:
                raise Exception("Downloaded file is too small or empty")
            
            return pdf_buffer
        
        except Exception as e:
            console_logger.error(f"❌ Download failed: {e}")
            raise e


# Singleton instance
scraper = BSEScraper()
