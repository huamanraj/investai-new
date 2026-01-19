"""
Company Snapshot Generator
Analyzes extraction data and embeddings to create comprehensive company snapshots using GPT
"""
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logging import console_logger, job_logger


class SnapshotGenerator:
    """Service for generating company snapshots using GPT analysis"""
    
    def __init__(self):
        self.configured = bool(settings.OPENAI_API_KEY and 
                               settings.OPENAI_API_KEY != "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._client = None
        self.model = "gpt-4o-mini"
    
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
        
        Args:
            extraction_data: Extracted data from LlamaExtract
            company_name: Company name
            source_url: BSE source URL
            project_id: Project ID for logging
            
        Returns:
            Complete snapshot data structure
        """
        if not self.configured:
            console_logger.warning("⚠️ OpenAI not configured, generating basic snapshot")
            return self._generate_basic_snapshot(extraction_data, company_name)
        
        console_logger.info(f"📊 Generating AI-powered snapshot for {company_name}...")
        job_logger.info(
            "Starting snapshot generation",
            project_id=project_id,
            data={"company_name": company_name}
        )
        
        try:
            client = self._get_client()
            
            # Build prompt for GPT
            prompt = self._build_snapshot_prompt(extraction_data, company_name, source_url)
            
            # Call GPT to analyze and structure the data
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": """You are a financial analyst creating structured company snapshots for investors.
                        
Your task is to analyze the provided financial data and create a comprehensive JSON snapshot that includes:
1. Company overview (basic info, sector, stock details)
2. Key financial metrics with YoY comparison
3. Performance highlights and achievements
4. Management guidance and outlook
5. Chart-ready data (revenue trends, profit trends, margins)

Return ONLY valid JSON without any markdown formatting or explanations."""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,
                max_tokens=3000,
                response_format={"type": "json_object"}
            )
            
            # Parse GPT response
            snapshot_json = json.loads(response.choices[0].message.content)
            
            # Enhance with metadata
            snapshot = self._enhance_snapshot(snapshot_json, extraction_data, company_name, source_url)
            
            console_logger.info(f"✅ Snapshot generated successfully for {company_name}")
            job_logger.info(
                "Snapshot generation completed",
                project_id=project_id,
                data={"company_name": company_name}
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
    
    def _build_snapshot_prompt(
        self,
        extraction_data: Dict[str, Any],
        company_name: str,
        source_url: str
    ) -> str:
        """Build the prompt for GPT snapshot generation"""
        
        # Extract key data
        fiscal_year = extraction_data.get("fiscal_year", "N/A")
        revenue = extraction_data.get("revenue", "N/A")
        revenue_unit = extraction_data.get("revenue_unit", "")
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
        
        prompt = f"""Create a comprehensive company snapshot for {company_name} based on this financial data:

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
{json.dumps(business_segments, indent=2)}

**Key Highlights:**
{json.dumps(key_highlights, indent=2)}

**Risk Factors:**
{json.dumps(risk_factors[:3], indent=2) if risk_factors else "None provided"}

**Management Outlook:**
{outlook}

Create a JSON response with this EXACT structure:

{{
  "company_overview": {{
    "company_name": "{company_name}",
    "cin": "Extract if available or null",
    "registered_office": "{registered_office}",
    "industry_sector": "Determine from context",
    "website": "Extract if available or null",
    "stock_info": {{
      "bse_code": "Extract from URL or null",
      "nse_symbol": "null",
      "market_cap": "null"
    }}
  }},
  "financial_metrics": {{
    "current_period": "{fiscal_year}",
    "previous_period": "Calculate previous year",
    "metrics": [
      {{"name": "Revenue", "current": {revenue if revenue != "N/A" else "null"}, "previous": null, "unit": "{revenue_unit}", "change_percent": "{revenue_growth}"}},
      {{"name": "Net Profit", "current": {net_profit if net_profit != "N/A" else "null"}, "previous": null, "unit": "{revenue_unit}", "change_percent": "{profit_growth}"}},
      {{"name": "EBITDA", "current": {operating_profit if operating_profit != "N/A" else "null"}, "previous": null, "unit": "{revenue_unit}", "change_percent": null}},
      {{"name": "EPS", "current": {eps if eps != "N/A" else "null"}, "previous": null, "unit": "₹", "change_percent": null}}
    ]
  }},
  "performance_summary": {{
    "recent_highlights": {json.dumps(key_highlights[:4] if key_highlights else ["Strong financial performance", "Continued business growth"])},
    "management_guidance": "{outlook[:300] if outlook else 'Not available'}",
    "business_segments": {json.dumps(business_segments)}
  }},
  "charts_data": {{
    "revenue_trend": {{
      "years": [Calculate last 3-5 years if possible, else just current],
      "values": [Revenue values],
      "unit": "{revenue_unit}"
    }},
    "profit_trend": {{
      "years": [Same as revenue],
      "values": [Profit values],
      "margins": [Calculate profit margins if possible]
    }},
    "key_margins": {{
      "periods": ["{fiscal_year}"],
      "ebitda_margin": [Calculate from operating profit/revenue if possible],
      "net_profit_margin": [Calculate from net profit/revenue if possible]
    }}
  }},
  "risk_summary": {{
    "top_risks": {json.dumps(risk_factors[:3] if risk_factors else ["Market risks", "Regulatory risks"])}
  }}
}}

Ensure all numeric values are actual numbers (not strings). Use null for missing data.
Be intelligent in extracting and inferring information from the provided data.
"""
        return prompt
    
    def _enhance_snapshot(
        self,
        snapshot_json: Dict[str, Any],
        extraction_data: Dict[str, Any],
        company_name: str,
        source_url: str
    ) -> Dict[str, Any]:
        """Enhance the GPT-generated snapshot with metadata"""
        
        # Add metadata section
        snapshot_json["metadata"] = {
            "generated_at": datetime.utcnow().isoformat(),
            "source_url": source_url,
            "report_period": extraction_data.get("fiscal_year", "N/A"),
            "data_source": "BSE India Annual Report",
            "generator_version": "1.0"
        }
        
        # Ensure all required sections exist
        if "company_overview" not in snapshot_json:
            snapshot_json["company_overview"] = {
                "company_name": company_name,
                "cin": None,
                "registered_office": extraction_data.get("registered_office"),
                "industry_sector": "Financial Services",
                "website": None,
                "stock_info": {}
            }
        
        if "financial_metrics" not in snapshot_json:
            snapshot_json["financial_metrics"] = self._create_basic_metrics(extraction_data)
        
        if "performance_summary" not in snapshot_json:
            snapshot_json["performance_summary"] = {
                "recent_highlights": extraction_data.get("key_highlights", [])[:4],
                "management_guidance": extraction_data.get("outlook", ""),
                "business_segments": extraction_data.get("business_segments", [])
            }
        
        if "charts_data" not in snapshot_json:
            snapshot_json["charts_data"] = self._create_basic_charts(extraction_data)
        
        if "risk_summary" not in snapshot_json:
            snapshot_json["risk_summary"] = {
                "top_risks": extraction_data.get("risk_factors", [])[:3]
            }
        
        return snapshot_json
    
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
                }
            },
            "financial_metrics": self._create_basic_metrics(extraction_data),
            "performance_summary": {
                "recent_highlights": extraction_data.get("key_highlights", [])[:4],
                "management_guidance": extraction_data.get("outlook", ""),
                "business_segments": extraction_data.get("business_segments", [])
            },
            "charts_data": self._create_basic_charts(extraction_data),
            "risk_summary": {
                "top_risks": extraction_data.get("risk_factors", [])[:3]
            },
            "metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "report_period": fiscal_year,
                "data_source": "BSE India Annual Report",
                "generator_version": "1.0-basic"
            }
        }
    
    def _create_basic_metrics(self, extraction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create basic financial metrics structure"""
        
        fiscal_year = extraction_data.get("fiscal_year", "N/A")
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
        
        return {
            "current_period": fiscal_year,
            "previous_period": None,
            "metrics": metrics
        }
    
    def _create_basic_charts(self, extraction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create basic chart data structure"""
        
        fiscal_year = extraction_data.get("fiscal_year", "N/A")
        revenue = extraction_data.get("revenue")
        net_profit = extraction_data.get("net_profit")
        revenue_unit = extraction_data.get("revenue_unit", "Crores")
        
        charts = {
            "revenue_trend": {
                "years": [fiscal_year],
                "values": [revenue] if revenue else [],
                "unit": revenue_unit
            },
            "profit_trend": {
                "years": [fiscal_year],
                "values": [net_profit] if net_profit else [],
                "margins": []
            },
            "key_margins": {
                "periods": [fiscal_year],
                "ebitda_margin": [],
                "net_profit_margin": []
            }
        }
        
        # Calculate margins if possible
        if revenue and net_profit:
            try:
                profit_margin = (float(net_profit) / float(revenue)) * 100
                charts["key_margins"]["net_profit_margin"] = [round(profit_margin, 2)]
                charts["profit_trend"]["margins"] = [round(profit_margin, 2)]
            except (ValueError, ZeroDivisionError):
                pass
        
        if revenue and extraction_data.get("operating_profit"):
            try:
                ebitda_margin = (float(extraction_data["operating_profit"]) / float(revenue)) * 100
                charts["key_margins"]["ebitda_margin"] = [round(ebitda_margin, 2)]
            except (ValueError, ZeroDivisionError):
                pass
        
        return charts
    
    def is_configured(self) -> bool:
        """Check if OpenAI is configured"""
        return self.configured


# Singleton instance
snapshot_generator = SnapshotGenerator()
