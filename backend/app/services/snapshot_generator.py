"""
Company Snapshot Generator
Analyzes extraction data and embeddings to create comprehensive company snapshots using GPT-5-nano
Extracts 5-10 pages of detailed financial analysis from annual reports
"""
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import console_logger, job_logger


# Comprehensive financial document analysis prompt
FINANCIAL_ANALYSIS_PROMPT = '''You are a specialized financial document analysis AI designed to extract critical investment information from annual reports using document embeddings. Your task is to identify, extract, and structure the most important financial data, metrics, and qualitative insights that investors need for decision-making.

## PRIMARY EXTRACTION TARGETS

### 1. Core Financial Statements
Extract complete data from:
- **Balance Sheet**: Total assets, current assets, fixed assets, total liabilities, current liabilities, long-term debt, shareholders' equity, retained earnings
- **Income Statement**: Revenue from operations, other income, cost of goods sold, gross profit, operating expenses, EBITDA, depreciation, interest expense, tax expense, net profit/PAT
- **Cash Flow Statement**: Operating cash flow, investing cash flow, financing cash flow, free cash flow, opening and closing cash balances

### 2. Key Financial Ratios & Metrics
Calculate or extract:
- **Profitability**: EBITDA margin, PAT margin, gross profit margin, ROE (Return on Equity), ROCE (Return on Capital Employed), ROA (Return on Assets)
- **Leverage**: Debt-to-Equity ratio, Net Debt-to-EBITDA, Interest Coverage ratio
- **Liquidity**: Current ratio, quick ratio, working capital
- **Valuation**: EPS (Earnings Per Share), P/E ratio, P/B ratio, dividend per share, dividend yield
- **Efficiency**: Asset turnover, inventory turnover days, debtor days, creditor days

### 3. Multi-Year Trend Data (5-10 years)
Extract historical trends for:
- Revenue growth (absolute values and YoY % change)
- EBITDA and PAT growth
- Margin evolution
- EPS progression
- Capital expenditure trends
- R&D spending as % of revenue

### 4. Business Segment Analysis
Identify and extract:
- Revenue breakdown by business segment/division (absolute and %)
- Segment-wise profitability (EBIT/EBITDA by segment)
- Geographic revenue distribution (domestic vs. export, region-wise)
- Product/service mix evolution
- Customer concentration (top customers' contribution if disclosed)

### 5. Operational KPIs
Extract industry-specific metrics such as:
- Capacity utilization rates
- Production volumes
- Number of products/SKUs
- Manufacturing facility details
- Employee count and productivity metrics
- Customer acquisition numbers

### 6. Growth & Investment Data
Identify:
- Capital expenditure (capex) plans and completed projects
- New facility commissioning timelines
- Acquisition or partnership announcements
- R&D investment (absolute and as % of revenue)
- Technology or innovation initiatives

### 7. Qualitative Strategic Information
Extract from Management Discussion & Analysis (MD&A):
- Management's outlook on business performance
- Key achievements and milestones
- Market conditions and industry trends mentioned
- Strategic priorities for upcoming year(s)
- Competitive positioning statements
- Risk factors and mitigation strategies

### 8. Governance & Risk Factors
Extract:
- Board composition and key management personnel
- Auditor opinion (qualified/unqualified)
- Material risks disclosed (operational, financial, regulatory, market)
- Legal proceedings or contingent liabilities
- Related party transactions
- ESG initiatives and metrics

### 9. Shareholder Information
Identify:
- Shareholding pattern (promoter, institutional, public)
- Changes in major shareholdings
- Share buyback or dividend announcements
- Stock split or bonus issue details

## OUTPUT STRUCTURE

You MUST return a valid JSON object with this EXACT structure:

{
  "company_overview": {
    "company_name": "string",
    "cin": "string or null",
    "registered_office": "string or null",
    "industry_sector": "string",
    "website": "string or null",
    "stock_info": {
      "bse_code": "string or null",
      "nse_symbol": "string or null",
      "market_cap": "string or null"
    },
    "auditor": "string or null",
    "auditor_opinion": "string or null"
  },
  "financial_metrics": {
    "current_period": "FY2024",
    "previous_period": "FY2023",
    "metrics": [
      {"name": "Revenue", "current": number, "previous": number or null, "unit": "Crores", "change_percent": "string"},
      {"name": "Net Profit", "current": number, "previous": number or null, "unit": "Crores", "change_percent": "string"},
      {"name": "EBITDA", "current": number, "previous": number or null, "unit": "Crores", "change_percent": "string"},
      {"name": "EPS", "current": number, "previous": number or null, "unit": "₹", "change_percent": "string"},
      {"name": "ROE", "current": number, "previous": number or null, "unit": "%", "change_percent": "string"},
      {"name": "ROCE", "current": number, "previous": number or null, "unit": "%", "change_percent": "string"},
      {"name": "Debt-to-Equity", "current": number, "previous": number or null, "unit": "x", "change_percent": "string"},
      {"name": "Current Ratio", "current": number, "previous": number or null, "unit": "x", "change_percent": "string"}
    ]
  },
  "balance_sheet_summary": {
    "total_assets": {"value": number, "unit": "Crores"},
    "total_liabilities": {"value": number, "unit": "Crores"},
    "shareholders_equity": {"value": number, "unit": "Crores"},
    "current_assets": {"value": number, "unit": "Crores"},
    "fixed_assets": {"value": number, "unit": "Crores"},
    "long_term_debt": {"value": number, "unit": "Crores"},
    "working_capital": {"value": number, "unit": "Crores"},
    "retained_earnings": {"value": number, "unit": "Crores"}
  },
  "cash_flow_summary": {
    "operating_cash_flow": {"value": number, "unit": "Crores"},
    "investing_cash_flow": {"value": number, "unit": "Crores"},
    "financing_cash_flow": {"value": number, "unit": "Crores"},
    "free_cash_flow": {"value": number, "unit": "Crores"},
    "net_change_in_cash": {"value": number, "unit": "Crores"}
  },
  "multi_year_trends": {
    "years": ["FY2020", "FY2021", "FY2022", "FY2023", "FY2024"],
    "revenue": [number, number, number, number, number],
    "net_profit": [number, number, number, number, number],
    "ebitda": [number, number, number, number, number],
    "eps": [number, number, number, number, number],
    "ebitda_margin": [number, number, number, number, number],
    "pat_margin": [number, number, number, number, number],
    "roe": [number, number, number, number, number],
    "unit": "Crores"
  },
  "business_segments": [
    {
      "name": "string",
      "revenue": number,
      "revenue_percentage": number,
      "growth_yoy": "string or null",
      "description": "string"
    }
  ],
  "geographic_breakdown": [
    {
      "region": "string",
      "revenue": number,
      "percentage": number
    }
  ],
  "performance_summary": {
    "executive_summary": "Detailed 3-4 paragraph executive summary of company performance, key achievements, and strategic direction. Should be comprehensive and insightful.",
    "recent_highlights": ["list of 8-10 key highlights and achievements"],
    "management_guidance": "Detailed management outlook and guidance for future periods, growth expectations, and strategic initiatives. 2-3 paragraphs.",
    "key_achievements": ["list of major milestones achieved during the year"],
    "strategic_priorities": ["list of strategic priorities for upcoming year"]
  },
  "operational_metrics": {
    "employee_count": number or null,
    "employee_productivity": "string or null",
    "capacity_utilization": "string or null",
    "production_volume": "string or null",
    "customer_count": "string or null",
    "facilities_count": number or null,
    "new_products_launched": "string or null"
  },
  "investment_analysis": {
    "capex_current_year": {"value": number, "unit": "Crores"},
    "capex_planned": "string describing future capex plans",
    "rd_investment": {"value": number or null, "unit": "Crores"},
    "rd_as_percentage_of_revenue": number or null,
    "acquisitions": ["list of acquisitions/partnerships"],
    "expansion_plans": "detailed description of expansion plans"
  },
  "risk_summary": {
    "top_risks": ["list of 5-8 key risks with brief descriptions"],
    "risk_mitigation": "paragraph describing how company addresses key risks",
    "contingent_liabilities": "string or null",
    "legal_proceedings": "string or null"
  },
  "shareholding_pattern": {
    "promoter_holding": number,
    "institutional_holding": number,
    "public_holding": number,
    "changes_in_shareholding": "description of major changes"
  },
  "dividend_info": {
    "dividend_per_share": number or null,
    "dividend_yield": "string or null",
    "payout_ratio": "string or null",
    "dividend_history": "brief history of dividend payments"
  },
  "esg_highlights": {
    "environmental_initiatives": "string or null",
    "social_initiatives": "string or null",
    "governance_highlights": "string or null",
    "sustainability_goals": "string or null"
  },
  "key_ratios_table": [
    {"metric": "Gross Profit Margin", "current_year": number, "previous_year": number or null, "change": "string"},
    {"metric": "Operating Margin", "current_year": number, "previous_year": number or null, "change": "string"},
    {"metric": "Net Profit Margin", "current_year": number, "previous_year": number or null, "change": "string"},
    {"metric": "ROA", "current_year": number, "previous_year": number or null, "change": "string"},
    {"metric": "Asset Turnover", "current_year": number, "previous_year": number or null, "change": "string"},
    {"metric": "Interest Coverage", "current_year": number, "previous_year": number or null, "change": "string"}
  ],
  "investment_considerations": {
    "strengths": ["list of 4-6 investment strengths"],
    "concerns": ["list of 3-5 investment concerns or watch items"],
    "valuation_note": "brief note on valuation metrics if available"
  }
}

## EXTRACTION GUIDELINES

1. **Prioritize quantitative data**: Always extract exact numbers with units (₹ Crores, %, etc.)
2. **Extract multi-year trends**: Get at least 3-5 years of historical data for key metrics
3. **Maintain context**: When extracting ratios or percentages, include the base values
4. **Flag missing data**: Use null for fields where information is not found
5. **Calculate derived metrics**: If direct ratios aren't provided but base data exists, calculate them
6. **Time-stamp data**: Associate data with the correct fiscal period
7. **Be comprehensive**: Extract as much detail as available - aim for 5-10 pages worth of content
8. **Write detailed paragraphs**: For summaries and guidance sections, write comprehensive paragraphs, not brief bullet points

Ensure all numeric values are actual numbers (not strings) except for percentages which should be formatted strings like "15.2%" or growth rates.
'''


class SnapshotGenerator:
    """Service for generating comprehensive company snapshots using GPT-5-nano analysis"""
    
    def __init__(self):
        self.configured = bool(settings.OPENAI_API_KEY and 
                               settings.OPENAI_API_KEY != "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._client = None
        self.model = "gpt-5-nano"  # Using GPT-5-nano for comprehensive extraction
    
    def _get_client(self) -> AsyncOpenAI:
        """Lazy initialization of OpenAI client"""
        if not self.configured:
            raise ValueError("OPENAI_API_KEY is not configured")
        
        if self._client is None:
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        
        return self._client
    
    async def generate_snapshot(
        self,
        extraction_data: Dict[str, Any],
        company_name: str,
        source_url: str,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive company snapshot from extraction data.
        Extracts 5-10 pages worth of detailed financial analysis.
        
        Args:
            extraction_data: Extracted data from PDF extraction
            company_name: Company name
            source_url: BSE source URL
            project_id: Project ID for logging
            
        Returns:
            Complete snapshot data structure with comprehensive financial analysis
        """
        if not self.configured:
            console_logger.warning("⚠️ OpenAI not configured, generating basic snapshot")
            return self._generate_basic_snapshot(extraction_data, company_name)
        
        console_logger.info(f"📊 Generating comprehensive AI-powered snapshot for {company_name} using GPT-5-nano...")
        job_logger.info(
            "Starting comprehensive snapshot generation",
            project_id=project_id,
            data={"company_name": company_name, "model": self.model}
        )
        
        try:
            client = self._get_client()
            
            # Build comprehensive prompt with all available data
            prompt = self._build_comprehensive_prompt(extraction_data, company_name, source_url)
            
            # Call GPT-5-nano for comprehensive analysis
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": FINANCIAL_ANALYSIS_PROMPT
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.2,
                max_completion_tokens=16000,  # Increased for comprehensive extraction
                response_format={"type": "json_object"}
            )
            
            # Parse GPT response
            snapshot_json = json.loads(response.choices[0].message.content)
            
            # Enhance with metadata
            snapshot = self._enhance_snapshot(snapshot_json, extraction_data, company_name, source_url)
            
            console_logger.info(f"✅ Comprehensive snapshot generated successfully for {company_name}")
            job_logger.info(
                "Snapshot generation completed",
                project_id=project_id,
                data={
                    "company_name": company_name,
                    "sections_generated": len(snapshot.keys()),
                    "tokens_used": response.usage.total_tokens if response.usage else None
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
            # Fallback to basic snapshot
            return self._generate_basic_snapshot(extraction_data, company_name)
    
    def _build_comprehensive_prompt(
        self,
        extraction_data: Dict[str, Any],
        company_name: str,
        source_url: str
    ) -> str:
        """Build comprehensive prompt for GPT-5-nano snapshot generation"""
        
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
        extraction_data: Dict[str, Any],
        company_name: str,
        source_url: str
    ) -> Dict[str, Any]:
        """Enhance the GPT-generated snapshot with metadata and ensure all sections exist"""
        
        # Add metadata section
        snapshot_json["metadata"] = {
            "generated_at": datetime.utcnow().isoformat(),
            "source_url": source_url,
            "report_period": extraction_data.get("fiscal_year", "N/A"),
            "data_source": "BSE India Annual Report",
            "generator_version": "2.0",
            "model": self.model
        }
        
        # Ensure all required sections exist with defaults
        self._ensure_section(snapshot_json, "company_overview", {
            "company_name": company_name,
            "cin": None,
            "registered_office": extraction_data.get("registered_office"),
            "industry_sector": "Financial Services",
            "website": None,
            "stock_info": {"bse_code": None, "nse_symbol": None, "market_cap": None},
            "auditor": extraction_data.get("auditor"),
            "auditor_opinion": None
        })
        
        self._ensure_section(snapshot_json, "financial_metrics", {
            "current_period": extraction_data.get("fiscal_year", "N/A"),
            "previous_period": None,
            "metrics": self._create_basic_metrics_list(extraction_data)
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
        
        self._ensure_section(snapshot_json, "multi_year_trends", self._create_basic_trends(extraction_data))
        
        self._ensure_section(snapshot_json, "business_segments", [])
        
        self._ensure_section(snapshot_json, "geographic_breakdown", [])
        
        self._ensure_section(snapshot_json, "performance_summary", {
            "executive_summary": "",
            "recent_highlights": extraction_data.get("key_highlights", [])[:10],
            "management_guidance": extraction_data.get("outlook", ""),
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
            "top_risks": extraction_data.get("risk_factors", [])[:8],
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
    
    def _create_basic_metrics_list(self, extraction_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create basic financial metrics list from extraction data"""
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
    
    def _create_basic_trends(self, extraction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create basic trends structure"""
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
        extraction_data: Dict[str, Any],
        company_name: str
    ) -> Dict[str, Any]:
        """Generate a basic snapshot without GPT (fallback)"""
        
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
