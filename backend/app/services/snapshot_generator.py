"""
Company Snapshot Generator
Analyzes extraction data and embeddings to create comprehensive company snapshots using GPT-4.1-nano
Extracts 5-10 pages of detailed financial analysis from annual reports
"""
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import console_logger, job_logger


# Comprehensive financial document analysis prompt - OPTIMIZED FOR TOKEN LIMITS
FINANCIAL_ANALYSIS_PROMPT = '''Extract investment data from annual reports into JSON.

## EXTRACT THESE DATA POINTS:
1. Financials: Revenue, PAT, EBITDA, EPS, ROE, ROCE, D/E ratio, margins (5-8 year trends)
2. Balance Sheet: Assets, liabilities, equity, debt, working capital
3. Cash Flow: OCF, ICF, FCF, net change
4. Segments: Revenue by business/geography with %
5. Operations: Employees, facilities, capacity, production
6. Management: Board directors, key executives with designations
7. Contracts: Major partnerships (Baker Hughes, Saudi Aramco etc)
8. Facilities: Manufacturing sites with location/status
9. Green Energy: Solar MW, renewable %, savings
10. Subsidiaries: Name, holding %, CIN
11. Credit Rating, Share Capital, Awards
12. Risks, ESG, Dividends, Shareholding pattern

## SEARCH LOCATIONS:
- Director's Report, MD&A, Financial Statements, Notes to Accounts
- Chairman's Message, Corporate Governance, BRSR, Annexures
- Performance at a Glance, 5-year summary tables

## JSON OUTPUT STRUCTURE:
{
  "company_overview": {"company_name":"str","cin":"str|null","registered_office":"str|null","industry_sector":"str","website":"str|null","stock_info":{"bse_code":"str|null","nse_symbol":"str|null","market_cap":"str|null"},"auditor":"str|null","auditor_opinion":"str|null"},
  "financial_metrics": {"current_period":"FY2024","previous_period":"FY2023","metrics":[{"name":"Revenue","current":num,"previous":num|null,"unit":"Crores","change_percent":"str"},{"name":"Net Profit","current":num,"previous":num|null,"unit":"Crores","change_percent":"str"},{"name":"EBITDA","current":num,"previous":num|null,"unit":"Crores","change_percent":"str"},{"name":"EPS","current":num,"previous":num|null,"unit":"₹","change_percent":"str"},{"name":"ROE","current":num,"previous":num|null,"unit":"%","change_percent":"str"},{"name":"ROCE","current":num,"previous":num|null,"unit":"%","change_percent":"str"},{"name":"Debt-to-Equity","current":num,"previous":num|null,"unit":"x","change_percent":"str"},{"name":"Current Ratio","current":num,"previous":num|null,"unit":"x","change_percent":"str"}]},
  "balance_sheet_summary": {"total_assets":{"value":num,"unit":"Crores"},"total_liabilities":{"value":num,"unit":"Crores"},"shareholders_equity":{"value":num,"unit":"Crores"},"current_assets":{"value":num,"unit":"Crores"},"fixed_assets":{"value":num,"unit":"Crores"},"long_term_debt":{"value":num,"unit":"Crores"},"working_capital":{"value":num,"unit":"Crores"},"retained_earnings":{"value":num,"unit":"Crores"}},
  "cash_flow_summary": {"operating_cash_flow":{"value":num,"unit":"Crores"},"investing_cash_flow":{"value":num,"unit":"Crores"},"financing_cash_flow":{"value":num,"unit":"Crores"},"free_cash_flow":{"value":num,"unit":"Crores"},"net_change_in_cash":{"value":num,"unit":"Crores"}},
  "multi_year_trends": {"years":["FY20","FY21","FY22","FY23","FY24"],"revenue":[num],"net_profit":[num],"ebitda":[num],"eps":[num],"ebitda_margin":[num],"pat_margin":[num],"roe":[num],"unit":"Crores"},
  "business_segments": [{"name":"str","revenue":num,"revenue_percentage":num,"growth_yoy":"str|null","description":"str"}],
  "geographic_breakdown": [{"region":"str","revenue":num,"percentage":num}],
  "performance_summary": {"executive_summary":"3-4 paragraphs","recent_highlights":["8-10 items"],"management_guidance":"2-3 paragraphs","key_achievements":["list"],"strategic_priorities":["list"]},
  "operational_metrics": {"employee_count":num|null,"average_employee_age":num|null,"employee_productivity":"str|null","capacity_utilization":"str|null","production_volume":"str|null","customer_count":"str|null","facilities_count":num|null,"new_products_launched":"str|null"},
  "investment_analysis": {"capex_current_year":{"value":num,"unit":"Crores"},"capex_planned":"str","rd_investment":{"value":num|null,"unit":"Crores"},"rd_as_percentage_of_revenue":num|null,"acquisitions":["list"],"expansion_plans":"str"},
  "risk_summary": {"top_risks":["5-8 risks"],"risk_mitigation":"paragraph","contingent_liabilities":"str|null","legal_proceedings":"str|null"},
  "shareholding_pattern": {"promoter_holding":num,"institutional_holding":num,"public_holding":num,"changes_in_shareholding":"str"},
  "dividend_info": {"dividend_per_share":num|null,"dividend_yield":"str|null","payout_ratio":"str|null","dividend_history":"str"},
  "esg_highlights": {"environmental_initiatives":"str|null","social_initiatives":"str|null","governance_highlights":"str|null","sustainability_goals":"str|null"},
  "key_ratios_table": [{"metric":"str","current_year":num,"previous_year":num|null,"change":"str"}],
  "investment_considerations": {"strengths":["4-6"],"concerns":["3-5"],"valuation_note":"str"},
  "management_team": [{"name":"str","designation":"str","type":"promoter|independent|executive"}],
  "key_contracts": [{"partner_name":"str","contract_type":"str","description":"str","tenure":"str|null"}],
  "manufacturing_facilities": [{"name":"str","location":"str","status":"operational|under construction|planned","description":"str|null"}],
  "green_energy": {"solar_capacity_mw":num|null,"renewable_share":"str|null","annual_savings":"str|null","initiatives":["list"]},
  "subsidiaries": [{"name":"str","cin":"str|null","holding_percentage":num,"business_activity":"str|null"}],
  "awards_certifications": [{"title":"str","year":"str|null","category":"award|certification|recognition"}],
  "credit_rating": {"agency":"str|null","rating":"str|null","outlook":"str|null"},
  "share_capital": {"authorized_capital":"str|null","paid_up_capital":"str|null","face_value":num|null}
}

## RULES:
- Search ALL sections exhaustively before returning null
- Extract 5-8 years of trend data from tables
- Numbers as actual numbers, percentages as "15.2%"
- Write comprehensive paragraphs for summaries
'''


class SnapshotGenerator:
    """Service for generating comprehensive company snapshots using GPT-4.1-nano analysis"""
    
    def __init__(self):
        self.configured = bool(settings.OPENAI_API_KEY and 
                               settings.OPENAI_API_KEY != "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._client = None
        self.model = "gpt-4.1"  # Using GPT-4.1-nano for comprehensive extraction
    
    def _get_client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenAI client"""
        if not self.configured:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        return self._client
    
    async def generate_snapshot(
        self,
        extraction_data: Dict[str, Any] | str,
        company_name: str,
        source_url: str,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive company snapshot from extraction data.
        Uses TWO API calls to handle large documents within token limits,
        then merges the results.
        
        Args:
            extraction_data: Extracted data from PDF extraction (can be dict or raw text string)
            company_name: Company name
            source_url: BSE source URL
            project_id: Project ID for logging
            
        Returns:
            Complete snapshot data structure with comprehensive financial analysis
        """
        if not self.configured:
            console_logger.warning("⚠️ OpenAI not configured, generating basic snapshot")
            # Handle string input for basic snapshot
            if isinstance(extraction_data, str):
                extraction_data = {"complete_text": extraction_data}
            return self._generate_basic_snapshot(extraction_data, company_name)
        
        console_logger.info(f"📊 Generating AI-powered snapshot for {company_name} using split-call strategy...")
        job_logger.info(
            "Starting split-call snapshot generation",
            project_id=project_id,
            data={"company_name": company_name, "model": self.model}
        )
        
        try:
            client = self._get_client()
            
            # Get the text data
            if isinstance(extraction_data, str):
                full_text = extraction_data
            else:
                full_text = extraction_data.get("complete_text", "")
            
            # Split text into two halves for two API calls
            text_length = len(full_text)
            half_length = text_length // 2
            
            # Find a good split point (at a page boundary or paragraph)
            split_point = half_length
            # Look for page marker near midpoint
            page_marker_pos = full_text.find("PAGE", half_length - 1000, half_length + 1000)
            if page_marker_pos > 0:
                # Find start of this line
                line_start = full_text.rfind("\n", 0, page_marker_pos)
                if line_start > 0:
                    split_point = line_start
            
            first_half = full_text[:split_point]
            second_half = full_text[split_point:]
            
            # Limit each half to ~45k chars to stay within token limits
            max_chars_per_call = 45000
            if len(first_half) > max_chars_per_call:
                first_half = first_half[:max_chars_per_call] + "\n[...truncated...]"
            if len(second_half) > max_chars_per_call:
                second_half = second_half[:max_chars_per_call] + "\n[...truncated...]"
            
            console_logger.info(f"📖 Split document: Part 1 = {len(first_half)} chars, Part 2 = {len(second_half)} chars")
            
            # Build prompts for each half
            prompt1 = self._build_split_prompt(first_half, company_name, source_url, part=1, total_parts=2)
            prompt2 = self._build_split_prompt(second_half, company_name, source_url, part=2, total_parts=2)
            
            # Make two API calls sequentially (to avoid rate limits)
            console_logger.info(f"🔄 Making API call 1/2 for {company_name}...")
            response1 = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": FINANCIAL_ANALYSIS_PROMPT},
                    {"role": "user", "content": prompt1}
                ],
                max_completion_tokens=8000,
                response_format={"type": "json_object"}
            )
            snapshot1 = json.loads(response1.choices[0].message.content)
            tokens1 = response1.usage.total_tokens if response1.usage else 0
            console_logger.info(f"✅ API call 1/2 complete ({tokens1} tokens)")
            
            # Small delay between calls to avoid rate limits
            import asyncio
            await asyncio.sleep(2)
            
            console_logger.info(f"🔄 Making API call 2/2 for {company_name}...")
            response2 = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": FINANCIAL_ANALYSIS_PROMPT},
                    {"role": "user", "content": prompt2}
                ],
                max_completion_tokens=8000,
                response_format={"type": "json_object"}
            )
            snapshot2 = json.loads(response2.choices[0].message.content)
            tokens2 = response2.usage.total_tokens if response2.usage else 0
            console_logger.info(f"✅ API call 2/2 complete ({tokens2} tokens)")
            
            # Merge the two snapshots
            console_logger.info(f"🔗 Merging results from both calls...")
            merged_snapshot = self._merge_snapshots(snapshot1, snapshot2)
            
            # Enhance with metadata
            snapshot = self._enhance_snapshot(merged_snapshot, extraction_data, company_name, source_url)
            
            console_logger.info(f"✅ Comprehensive snapshot generated successfully for {company_name}")
            job_logger.info(
                "Snapshot generation completed (split-call)",
                project_id=project_id,
                data={
                    "company_name": company_name,
                    "sections_generated": len(snapshot.keys()),
                    "total_tokens": tokens1 + tokens2
                }
            )
            
            return snapshot
            
        except Exception as e:
            console_logger.error(f"❌ Snapshot generation failed: {e}")
            job_logger.error(
                "Snapshot generation failed",
                project_id=project_id,
                data={"error": str(e)}
            )
            # Re-raise exception so job can fail and be resumed
            raise
    
    def _build_split_prompt(
        self,
        text_part: str,
        company_name: str,
        source_url: str,
        part: int,
        total_parts: int
    ) -> str:
        """Build prompt for a split portion of the document"""
        return f"""Analyze PART {part} of {total_parts} of the annual report for {company_name}.

**Company:** {company_name}
**Source:** {source_url}
**Note:** This is part {part} of {total_parts}. Extract ALL data you find in this section.

**Annual Report Text (Part {part}/{total_parts}):**
{text_part}

Extract ALL available data from this part. Return the complete JSON structure with null for fields not found in this section."""
    
    def _merge_snapshots(self, snap1: Dict[str, Any], snap2: Dict[str, Any]) -> Dict[str, Any]:
        """Intelligently merge two snapshots, preferring non-null values"""
        merged = {}
        
        all_keys = set(snap1.keys()) | set(snap2.keys())
        
        for key in all_keys:
            val1 = snap1.get(key)
            val2 = snap2.get(key)
            
            # If one is None/empty, use the other
            if val1 is None or val1 == {} or val1 == []:
                merged[key] = val2 if val2 is not None else val1
            elif val2 is None or val2 == {} or val2 == []:
                merged[key] = val1
            # If both are lists, merge unique items
            elif isinstance(val1, list) and isinstance(val2, list):
                # For list of dicts, merge by checking for duplicates
                merged_list = list(val1)
                for item in val2:
                    if isinstance(item, dict):
                        # Check if similar item exists
                        exists = False
                        for existing in merged_list:
                            if isinstance(existing, dict):
                                # Compare first key-value
                                if existing.get(list(existing.keys())[0] if existing else None) == item.get(list(item.keys())[0] if item else None):
                                    exists = True
                                    break
                        if not exists:
                            merged_list.append(item)
                    elif item not in merged_list:
                        merged_list.append(item)
                merged[key] = merged_list
            # If both are dicts, recursively merge
            elif isinstance(val1, dict) and isinstance(val2, dict):
                merged[key] = self._merge_snapshots(val1, val2)
            # For strings, prefer longer/non-empty
            elif isinstance(val1, str) and isinstance(val2, str):
                merged[key] = val1 if len(val1) >= len(val2) else val2
            # For numbers, prefer non-zero
            elif isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                merged[key] = val1 if val1 != 0 else val2
            else:
                # Default to first value
                merged[key] = val1 if val1 is not None else val2
        
        return merged
    
    def _build_comprehensive_prompt(
        self,
        extraction_data: Dict[str, Any] | str,
        company_name: str,
        source_url: str
    ) -> str:
        """Build comprehensive prompt for GPT-4.1-nano snapshot generation"""
        
        # Handle string input (raw text from LlamaParse)
        if isinstance(extraction_data, str):
            # If it's raw text, use it directly in the prompt
            # Limit to ~100k chars to avoid token limits (GPT-4.1-nano has large context window)
            text_preview = extraction_data[:100000] if len(extraction_data) > 100000 else extraction_data
            if len(extraction_data) > 100000:
                text_preview += "\n\n[... text truncated for length ...]"
            
            return f"""Analyze the following COMPLETE annual report text for {company_name} and create a COMPREHENSIVE investment snapshot.

**Company Information:**
- Company Name: {company_name}
- Source: {source_url}

**CRITICAL: THOROUGH EXTRACTION REQUIRED**
The text below contains the FULL annual report. You MUST search through ALL sections to extract:

1. **MANDATORY MULTI-YEAR DATA** - Look for tables with FY25, FY24, FY23, FY22, FY21 etc.
   - Search: "Performance at a Glance", "Financial Highlights", "5-Year Summary"
   
2. **MANAGEMENT TEAM & BOARD** - Extract ALL names and designations
   - Search: "Board of Directors", "Key Managerial Personnel", "Corporate Governance"
   
3. **MANUFACTURING FACILITIES** - List all sites with locations and status
   - Search: "Manufacturing", "Site 1/2/3/4/5", "Facilities", "Plants"
   
4. **KEY CONTRACTS & PARTNERSHIPS** - Major customers mentioned
   - Search: "Baker Hughes", "Saudi Aramco", "Seqens", "contract", "partnership"
   
5. **SUBSIDIARIES** - From Form AOC-1 or Notes to Accounts
   - Search: "Subsidiary", "AOC-1", "Group Companies", "100% holding"
   
6. **GREEN ENERGY / SOLAR** - Renewable capacity in MW
   - Search: "Solar", "MW", "renewable", "green energy"
   
7. **CREDIT RATING** - Look in Director's Report
   - Search: "credit rating", "CRISIL", "ICRA", "CARE"
   
8. **SHARE CAPITAL** - Authorized and Paid-up
   - Search: "Share Capital", "Authorized", "Paid-up", "Capital Structure"
   
9. **GEOGRAPHIC BREAKDOWN** - Export vs Domestic revenue
   - Search: "Export", "Domestic", "Geographic", "country-wise"

**Complete Annual Report Text:**
{text_preview}

IMPORTANT: Extract EVERY piece of data mentioned above. Search through the ENTIRE document. If a data point exists anywhere in the text, it MUST appear in your output. Do NOT return null if data is present - search again."""
        
        # Handle dict input (structured data)
        # Extract all available data
        fiscal_year = extraction_data.get("fiscal_year", "N/A")
        revenue = extraction_data.get("revenue", "N/A")
        revenue_unit = extraction_data.get("revenue_unit", "Crores")
        net_profit = extraction_data.get("net_profit", "N/A")
        operating_profit = extraction_data.get("operating_profit", "N/A")
        eps = extraction_data.get("eps", "N/A")
        revenue_growth = extraction_data.get("revenue_growth", "N/A")
        profit_growth = extraction_data.get("profit_growth", "N/A")
        key_highlights = extraction_data.get("key_highlights", [])
        business_segments = extraction_data.get("business_segments", [])
        risk_factors = extraction_data.get("risk_factors", [])
        outlook = extraction_data.get("outlook", "")
        auditor = extraction_data.get("auditor", "")
        registered_office = extraction_data.get("registered_office", "")
        charts_data = extraction_data.get("charts_data", [])
        
        prompt = f"""Analyze the following annual report data for {company_name} and create a COMPREHENSIVE investment snapshot.

**Company Information:**
- Company Name: {company_name}
- Fiscal Year: {fiscal_year}
- Source: {source_url}
- Registered Office: {registered_office}
- Auditor: {auditor}

**Financial Data:**
- Revenue: {revenue} {revenue_unit}
- Net Profit: {net_profit}
- Operating Profit/EBITDA: {operating_profit}
- EPS: {eps}
- Revenue Growth: {revenue_growth}
- Profit Growth: {profit_growth}

**Business Segments:**
{json.dumps(business_segments, indent=2) if business_segments else "Not specified"}

**Key Highlights:**
{json.dumps(key_highlights, indent=2) if key_highlights else "Not specified"}

**Risk Factors:**
{json.dumps(risk_factors, indent=2) if risk_factors else "Not specified"}

**Management Outlook:**
{outlook if outlook else "Not specified"}

**Charts/Trend Data Found:**
{json.dumps(charts_data, indent=2) if charts_data else "None extracted"}

IMPORTANT INSTRUCTIONS:
1. Extract or calculate MULTI-YEAR TRENDS for at least 5 years (revenue, profit, margins, EPS, ROE)
2. If multi-year data is found in charts_data or highlights, use those exact values
3. If only current year data is available, estimate reasonable historical trends based on growth rates mentioned
4. Write DETAILED PARAGRAPHS for executive_summary, management_guidance sections (3-4 paragraphs each)
5. Extract ALL financial ratios and metrics available
6. Include comprehensive business segment analysis
7. Provide detailed investment considerations with actionable insights
8. Ensure all numeric values are properly formatted numbers, not strings (except percentages like "15.2%")

Create the most comprehensive analysis possible from the available data. Aim for the depth and detail expected in a professional equity research report.
"""
        return prompt
    
    def _enhance_snapshot(
        self,
        snapshot_json: Dict[str, Any],
        extraction_data: Dict[str, Any] | str,
        company_name: str,
        source_url: str
    ) -> Dict[str, Any]:
        """Enhance the GPT-generated snapshot with metadata and ensure all sections exist"""
        
        # Handle string input (raw text) - create empty dict for metadata extraction
        extraction_dict = {}
        if isinstance(extraction_data, dict):
            extraction_dict = extraction_data
        elif isinstance(extraction_data, str):
            # For string input, we can't extract structured fields, use defaults
            extraction_dict = {}
        
        # Add metadata section
        snapshot_json["metadata"] = {
            "generated_at": datetime.utcnow().isoformat(),
            "source_url": source_url,
            "report_period": extraction_dict.get("fiscal_year", "N/A"),
            "data_source": "BSE India Annual Report",
            "generator_version": "2.0",
            "model": self.model
        }
        
        # Ensure all required sections exist with defaults
        self._ensure_section(snapshot_json, "company_overview", {
            "company_name": company_name,
            "cin": None,
            "registered_office": extraction_dict.get("registered_office"),
            "industry_sector": "Financial Services",
            "website": None,
            "stock_info": {"bse_code": None, "nse_symbol": None, "market_cap": None},
            "auditor": extraction_dict.get("auditor"),
            "auditor_opinion": None
        })
        
        self._ensure_section(snapshot_json, "financial_metrics", {
            "current_period": extraction_dict.get("fiscal_year", "N/A"),
            "previous_period": None,
            "metrics": self._create_basic_metrics_list(extraction_dict)
        })
        
        self._ensure_section(snapshot_json, "balance_sheet_summary", {
            "total_assets": {"value": None, "unit": "Crores"},
            "total_liabilities": {"value": None, "unit": "Crores"},
            "shareholders_equity": {"value": None, "unit": "Crores"},
            "current_assets": {"value": None, "unit": "Crores"},
            "fixed_assets": {"value": None, "unit": "Crores"},
            "long_term_debt": {"value": None, "unit": "Crores"},
            "working_capital": {"value": None, "unit": "Crores"},
            "retained_earnings": {"value": None, "unit": "Crores"}
        })
        
        self._ensure_section(snapshot_json, "cash_flow_summary", {
            "operating_cash_flow": {"value": None, "unit": "Crores"},
            "investing_cash_flow": {"value": None, "unit": "Crores"},
            "financing_cash_flow": {"value": None, "unit": "Crores"},
            "free_cash_flow": {"value": None, "unit": "Crores"},
            "net_change_in_cash": {"value": None, "unit": "Crores"}
        })
        
        self._ensure_section(snapshot_json, "multi_year_trends", self._create_basic_trends(extraction_dict))
        
        self._ensure_section(snapshot_json, "business_segments", [])
        
        self._ensure_section(snapshot_json, "geographic_breakdown", [])
        
        self._ensure_section(snapshot_json, "performance_summary", {
            "executive_summary": snapshot_json.get("performance_summary", {}).get("executive_summary", f"{company_name} is a company operating in the financial services sector. Detailed analysis based on annual report data."),
            "recent_highlights": snapshot_json.get("performance_summary", {}).get("recent_highlights", extraction_dict.get("key_highlights", []))[:10],
            "management_guidance": snapshot_json.get("performance_summary", {}).get("management_guidance", extraction_dict.get("outlook", "")),
            "key_achievements": [],
            "strategic_priorities": []
        })
        
        self._ensure_section(snapshot_json, "operational_metrics", {
            "employee_count": None,
            "employee_productivity": None,
            "capacity_utilization": None,
            "production_volume": None,
            "customer_count": None,
            "facilities_count": None,
            "new_products_launched": None
        })
        
        self._ensure_section(snapshot_json, "investment_analysis", {
            "capex_current_year": {"value": None, "unit": "Crores"},
            "capex_planned": None,
            "rd_investment": {"value": None, "unit": "Crores"},
            "rd_as_percentage_of_revenue": None,
            "acquisitions": [],
            "expansion_plans": None
        })
        
        self._ensure_section(snapshot_json, "risk_summary", {
            "top_risks": snapshot_json.get("risk_summary", {}).get("top_risks", extraction_dict.get("risk_factors", []))[:8],
            "risk_mitigation": None,
            "contingent_liabilities": None,
            "legal_proceedings": None
        })
        
        self._ensure_section(snapshot_json, "shareholding_pattern", {
            "promoter_holding": None,
            "institutional_holding": None,
            "public_holding": None,
            "changes_in_shareholding": None
        })
        
        self._ensure_section(snapshot_json, "dividend_info", {
            "dividend_per_share": None,
            "dividend_yield": None,
            "payout_ratio": None,
            "dividend_history": None
        })
        
        self._ensure_section(snapshot_json, "esg_highlights", {
            "environmental_initiatives": None,
            "social_initiatives": None,
            "governance_highlights": None,
            "sustainability_goals": None
        })
        
        self._ensure_section(snapshot_json, "key_ratios_table", [])
        
        self._ensure_section(snapshot_json, "investment_considerations", {
            "strengths": [],
            "concerns": [],
            "valuation_note": None
        })
        
        # New sections for enhanced annual report data
        self._ensure_section(snapshot_json, "management_team", [])
        
        self._ensure_section(snapshot_json, "key_contracts", [])
        
        self._ensure_section(snapshot_json, "manufacturing_facilities", [])
        
        self._ensure_section(snapshot_json, "green_energy", {
            "solar_capacity_mw": None,
            "renewable_share": None,
            "annual_savings": None,
            "initiatives": []
        })
        
        self._ensure_section(snapshot_json, "subsidiaries", [])
        
        self._ensure_section(snapshot_json, "awards_certifications", [])
        
        self._ensure_section(snapshot_json, "credit_rating", {
            "agency": None,
            "rating": None,
            "outlook": None
        })
        
        self._ensure_section(snapshot_json, "share_capital", {
            "authorized_capital": None,
            "paid_up_capital": None,
            "face_value": None
        })
        
        # Add average_employee_age to operational_metrics if not present
        if "operational_metrics" in snapshot_json and snapshot_json["operational_metrics"]:
            if "average_employee_age" not in snapshot_json["operational_metrics"]:
                snapshot_json["operational_metrics"]["average_employee_age"] = None
        
        # Legacy compatibility - create charts_data from multi_year_trends
        trends = snapshot_json.get("multi_year_trends", {})
        snapshot_json["charts_data"] = {
            "revenue_trend": {
                "years": trends.get("years", []),
                "values": trends.get("revenue", []),
                "unit": trends.get("unit", "Crores")
            },
            "profit_trend": {
                "years": trends.get("years", []),
                "values": trends.get("net_profit", []),
                "margins": trends.get("pat_margin", [])
            },
            "ebitda_trend": {
                "years": trends.get("years", []),
                "values": trends.get("ebitda", []),
                "margins": trends.get("ebitda_margin", [])
            },
            "eps_trend": {
                "years": trends.get("years", []),
                "values": trends.get("eps", [])
            },
            "roe_trend": {
                "years": trends.get("years", []),
                "values": trends.get("roe", [])
            },
            "key_margins": {
                "periods": trends.get("years", []),
                "ebitda_margin": trends.get("ebitda_margin", []),
                "net_profit_margin": trends.get("pat_margin", [])
            }
        }
        
        return snapshot_json
    
    def _ensure_section(self, data: Dict[str, Any], key: str, default: Any):
        """Ensure a section exists in the snapshot with a default value"""
        if key not in data or data[key] is None:
            data[key] = default
    
    def _create_basic_metrics_list(self, extraction_data: Dict[str, Any] | str) -> List[Dict[str, Any]]:
        """Create basic financial metrics list from extraction data"""
        # Handle string input
        if isinstance(extraction_data, str):
            return []
        
        revenue_unit = extraction_data.get("revenue_unit", "Crores")
        metrics = []
        
        if extraction_data.get("revenue"):
            metrics.append({
                "name": "Revenue",
                "current": extraction_data["revenue"],
                "previous": None,
                "unit": revenue_unit,
                "change_percent": extraction_data.get("revenue_growth")
            })
        
        if extraction_data.get("net_profit"):
            metrics.append({
                "name": "Net Profit",
                "current": extraction_data["net_profit"],
                "previous": None,
                "unit": revenue_unit,
                "change_percent": extraction_data.get("profit_growth")
            })
        
        if extraction_data.get("operating_profit"):
            metrics.append({
                "name": "EBITDA",
                "current": extraction_data["operating_profit"],
                "previous": None,
                "unit": revenue_unit,
                "change_percent": None
            })
        
        if extraction_data.get("eps"):
            metrics.append({
                "name": "EPS",
                "current": extraction_data["eps"],
                "previous": None,
                "unit": "₹",
                "change_percent": None
            })
        
        return metrics
    
    def _create_basic_trends(self, extraction_data: Dict[str, Any] | str) -> Dict[str, Any]:
        """Create basic trends structure"""
        # Handle string input
        if isinstance(extraction_data, str):
            return {
                "years": [],
                "revenue": [],
                "net_profit": [],
                "ebitda": [],
                "eps": [],
                "ebitda_margin": [],
                "pat_margin": [],
                "roe": [],
                "unit": "Crores"
            }
        
        fiscal_year = extraction_data.get("fiscal_year", "FY2024")
        revenue = extraction_data.get("revenue")
        net_profit = extraction_data.get("net_profit")
        
        return {
            "years": [fiscal_year] if fiscal_year != "N/A" else [],
            "revenue": [revenue] if revenue else [],
            "net_profit": [net_profit] if net_profit else [],
            "ebitda": [extraction_data.get("operating_profit")] if extraction_data.get("operating_profit") else [],
            "eps": [extraction_data.get("eps")] if extraction_data.get("eps") else [],
            "ebitda_margin": [],
            "pat_margin": [],
            "roe": [],
            "unit": extraction_data.get("revenue_unit", "Crores")
        }
    
    def _generate_basic_snapshot(
        self,
        extraction_data: Dict[str, Any] | str,
        company_name: str
    ) -> Dict[str, Any]:
        """Generate a basic snapshot without GPT (fallback)"""
        # Handle string input
        if isinstance(extraction_data, str):
            extraction_data = {"complete_text": extraction_data}
        
        fiscal_year = extraction_data.get("fiscal_year", "N/A")
        
        return {
            "company_overview": {
                "company_name": company_name,
                "cin": None,
                "registered_office": extraction_data.get("registered_office"),
                "industry_sector": None,
                "website": None,
                "stock_info": {
                    "bse_code": None,
                    "nse_symbol": None,
                    "market_cap": None
                },
                "auditor": extraction_data.get("auditor"),
                "auditor_opinion": None
            },
            "financial_metrics": {
                "current_period": fiscal_year,
                "previous_period": None,
                "metrics": self._create_basic_metrics_list(extraction_data)
            },
            "multi_year_trends": self._create_basic_trends(extraction_data),
            "charts_data": {
                "revenue_trend": {
                    "years": [fiscal_year],
                    "values": [extraction_data.get("revenue")] if extraction_data.get("revenue") else [],
                    "unit": extraction_data.get("revenue_unit", "Crores")
                },
                "profit_trend": {
                    "years": [fiscal_year],
                    "values": [extraction_data.get("net_profit")] if extraction_data.get("net_profit") else [],
                    "margins": []
                },
                "key_margins": {
                    "periods": [fiscal_year],
                    "ebitda_margin": [],
                    "net_profit_margin": []
                }
            },
            "performance_summary": {
                "executive_summary": "",
                "recent_highlights": extraction_data.get("key_highlights", [])[:10],
                "management_guidance": extraction_data.get("outlook", ""),
                "key_achievements": [],
                "strategic_priorities": []
            },
            "risk_summary": {
                "top_risks": extraction_data.get("risk_factors", [])[:8],
                "risk_mitigation": None,
                "contingent_liabilities": None,
                "legal_proceedings": None
            },
            "investment_considerations": {
                "strengths": [],
                "concerns": [],
                "valuation_note": None
            },
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "report_period": fiscal_year,
                "data_source": "BSE India Annual Report",
                "generator_version": "2.0-basic"
            }
        }
    
    def is_configured(self) -> bool:
        """Check if OpenAI is configured"""
        return self.configured


# Singleton instance
snapshot_generator = SnapshotGenerator()
