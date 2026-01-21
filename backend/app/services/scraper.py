"""
BSE India PDF Scraper using Playwright (via subprocess for Windows compatibility)
Scrapes annual report PDFs from BSE India pages (dynamic JS-rendered content)
"""
import asyncio
import json
import os
import platform
import subprocess
import sys
import tempfile
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass

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


# Standalone scraper script that runs in a separate process
SCRAPER_SCRIPT = '''
import json
import sys
import os
import platform
import tempfile

def get_browser_args():
    if platform.system() == "Windows":
        return []
    return ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']

def scrape(url, headless, timeout):
    from playwright.sync_api import sync_playwright
    import requests
    
    result = {"success": False, "pdfs": [], "error": None}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=get_browser_args() or None,
                timeout=timeout
            )
            
            context = browser.new_context(
                accept_downloads=True,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 2)
            
            try:
                page.wait_for_selector('a[href*=".pdf"]', timeout=20000)
            except:
                page.wait_for_timeout(8000)
            
            # Extract PDF links
            pdf_info_list = page.evaluate(r"""() => {
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
                            const label = cells[0]?.innerText?.trim() || 'Year ' + year;
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
            }""")
            
            browser.close()
            
            if not pdf_info_list:
                result["error"] = "Could not find PDF download links on the page"
                return result
            
            # Download PDFs
            downloaded = []
            for pdf_info in pdf_info_list:
                try:
                    response = requests.get(
                        pdf_info["url"],
                        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                        timeout=180
                    )
                    response.raise_for_status()
                    
                    if len(response.content) >= 1024:
                        # Save to temp file and return path
                        fd, path = tempfile.mkstemp(suffix='.pdf')
                        with os.fdopen(fd, 'wb') as f:
                            f.write(response.content)
                        
                        downloaded.append({
                            "url": pdf_info["url"],
                            "year": pdf_info["year"],
                            "label": pdf_info["label"],
                            "temp_path": path,
                            "size": len(response.content)
                        })
                except Exception as e:
                    pass  # Skip failed downloads
            
            if not downloaded:
                result["error"] = "Failed to download any PDFs"
                return result
            
            result["success"] = True
            result["pdfs"] = downloaded
            return result
            
    except Exception as e:
        result["error"] = str(e)
        return result

if __name__ == "__main__":
    url = sys.argv[1]
    headless = sys.argv[2].lower() == "true"
    timeout = int(sys.argv[3])
    
    result = scrape(url, headless, timeout)
    print("__RESULT_START__")
    print(json.dumps(result))
    print("__RESULT_END__")
'''


class BSEScraper:
    """Scraper for BSE India annual reports pages using subprocess for Windows compatibility"""
    
    def __init__(self):
        self.headless = settings.PLAYWRIGHT_HEADLESS
        self.timeout = settings.PLAYWRIGHT_TIMEOUT
    
    async def scrape_latest_annual_report(
        self, 
        url: str,
        project_id: Optional[str] = None,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> ScrapeResult:
        """
        Scrape BSE India page by running Playwright in a separate subprocess.
        This completely avoids event loop conflicts on Windows.
        """
        if on_progress is None:
            on_progress = lambda x: None
        
        scraper_logger.info(
            f"Starting scrape for URL: {url}",
            project_id=project_id,
            data={"url": url}
        )
        console_logger.info(f"🔍 Starting scrape for: {url}")
        
        on_progress({"step": "scraping", "message": "Launching browser..."})
        
        # Run the subprocess scraper in a thread to avoid blocking
        try:
            result = await asyncio.to_thread(
                self._run_scraper_subprocess,
                url,
                on_progress
            )
            return result
        except Exception as e:
            console_logger.error(f"❌ Scraping error: {e}")
            return ScrapeResult(success=False, pdfs=[], error=str(e))
    
    def _run_scraper_subprocess(
        self,
        url: str,
        on_progress: Callable
    ) -> ScrapeResult:
        """Run the scraper in a subprocess (called from a thread)"""
        script_path = None
        
        try:
            # Write the scraper script to a temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
                f.write(SCRAPER_SCRIPT)
                script_path = f.name
            
            console_logger.info(f"🌐 Launching Chromium subprocess (headless={self.headless})")
            on_progress({"step": "scraping", "message": "Navigating to BSE India page..."})
            
            # Prepare creation flags for Windows
            creation_flags = 0
            if platform.system() == "Windows":
                creation_flags = subprocess.CREATE_NO_WINDOW
            
            # Run the scraper subprocess
            process = subprocess.Popen(
                [sys.executable, script_path, url, str(self.headless), str(self.timeout)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creation_flags
            )
            
            # Wait for completion with timeout
            try:
                stdout, stderr = process.communicate(timeout=300)  # 5 minute timeout
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return ScrapeResult(success=False, pdfs=[], error="Scraping timed out after 5 minutes")
            
            stdout_text = stdout.decode('utf-8', errors='replace')
            stderr_text = stderr.decode('utf-8', errors='replace')
            
            if stderr_text:
                console_logger.warning(f"Scraper stderr: {stderr_text[:500]}")
            
            # Parse result from stdout
            if "__RESULT_START__" in stdout_text and "__RESULT_END__" in stdout_text:
                start = stdout_text.index("__RESULT_START__") + len("__RESULT_START__")
                end = stdout_text.index("__RESULT_END__")
                result_json = stdout_text[start:end].strip()
                result = json.loads(result_json)
            else:
                console_logger.error(f"Scraper output: {stdout_text[:1000]}")
                return ScrapeResult(
                    success=False,
                    pdfs=[],
                    error=f"Failed to parse scraper output. Exit code: {process.returncode}"
                )
            
            if not result.get("success"):
                return ScrapeResult(
                    success=False,
                    pdfs=[],
                    error=result.get("error", "Unknown error")
                )
            
            on_progress({"step": "scraping", "message": "Loading downloaded PDFs..."})
            
            # Read PDF files from temp paths
            downloaded_pdfs = []
            for pdf_data in result.get("pdfs", []):
                temp_path = pdf_data.get("temp_path")
                if temp_path and os.path.exists(temp_path):
                    try:
                        with open(temp_path, 'rb') as f:
                            pdf_buffer = f.read()
                        
                        os.unlink(temp_path)  # Clean up temp file
                        
                        file_size_mb = len(pdf_buffer) / 1024 / 1024
                        console_logger.info(f"✅ Loaded PDF: {pdf_data['label']} ({file_size_mb:.2f} MB)")
                        
                        downloaded_pdfs.append(PDFInfo(
                            url=pdf_data["url"],
                            year=pdf_data["year"],
                            label=pdf_data["label"],
                            pdf_buffer=pdf_buffer
                        ))
                    except Exception as e:
                        console_logger.error(f"Failed to read temp PDF: {e}")
            
            if not downloaded_pdfs:
                return ScrapeResult(
                    success=False,
                    pdfs=[],
                    error="Failed to load any PDFs"
                )
            
            console_logger.info(f"✅ Successfully scraped {len(downloaded_pdfs)} PDF(s)")
            return ScrapeResult(success=True, pdfs=downloaded_pdfs)
            
        except Exception as error:
            console_logger.error(f"❌ Subprocess scraping error: {error}")
            scraper_logger.error(
                f"Scraping failed",
                project_id=None,
                data={"error": str(error), "url": url}
            )
            return ScrapeResult(success=False, pdfs=[], error=str(error))
        
        finally:
            # Clean up script file
            if script_path:
                try:
                    os.unlink(script_path)
                except:
                    pass


# Singleton instance
scraper = BSEScraper()
