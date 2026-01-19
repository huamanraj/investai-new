# Company Snapshot JSON Structure

## Overview

The company snapshot is a comprehensive, AI-generated summary of a company's financial status, generated automatically during project processing. It's stored in the `company_snapshots` table and optimized for frontend rendering.

## Complete JSON Schema

```json
{
  "company_overview": {
    "company_name": "Tata Consultancy Services Ltd",
    "cin": "L22210MH1995PLC084781",
    "registered_office": "9th Floor, Nirmal Building, Nariman Point, Mumbai - 400021",
    "industry_sector": "Information Technology",
    "website": "https://www.tcs.com",
    "stock_info": {
      "bse_code": "532540",
      "nse_symbol": "TCS",
      "market_cap": "₹ 14,50,000 Cr"
    }
  },
  
  "financial_metrics": {
    "current_period": "FY 2024-25",
    "previous_period": "FY 2023-24",
    "metrics": [
      {
        "name": "Revenue",
        "current": 245000,
        "previous": 213000,
        "unit": "Crores",
        "change_percent": "+15.0%"
      },
      {
        "name": "Net Profit",
        "current": 42000,
        "previous": 38000,
        "unit": "Crores",
        "change_percent": "+10.5%"
      },
      {
        "name": "EBITDA",
        "current": 65000,
        "previous": 58000,
        "unit": "Crores",
        "change_percent": "+12.1%"
      },
      {
        "name": "EPS",
        "current": 115.5,
        "previous": 104.2,
        "unit": "₹",
        "change_percent": "+10.8%"
      },
      {
        "name": "Total Assets",
        "current": 185000,
        "previous": 165000,
        "unit": "Crores",
        "change_percent": "+12.1%"
      },
      {
        "name": "Dividend per Share",
        "current": 73,
        "previous": 67,
        "unit": "₹",
        "change_percent": "+9.0%"
      }
    ]
  },
  
  "performance_summary": {
    "recent_highlights": [
      "Achieved record revenue of ₹2,45,000 Crores with 15% YoY growth",
      "Won 15 large transformation deals worth over $100M each",
      "Expanded presence in North America with new delivery centers",
      "Recognized as Top Employer in 42 countries"
    ],
    "management_guidance": "Management expects continued growth momentum driven by cloud transformation, AI/ML adoption, and digital initiatives across all verticals. Focus remains on improving operational efficiency and expanding client relationships.",
    "business_segments": [
      "Banking, Financial Services and Insurance (BFSI)",
      "Retail and Consumer Business",
      "Communications and Media",
      "Technology and Services",
      "Life Sciences and Healthcare"
    ]
  },
  
  "charts_data": {
    "revenue_trend": {
      "years": ["FY 2021-22", "FY 2022-23", "FY 2023-24", "FY 2024-25"],
      "values": [185000, 198000, 213000, 245000],
      "unit": "Crores"
    },
    "profit_trend": {
      "years": ["FY 2021-22", "FY 2022-23", "FY 2023-24", "FY 2024-25"],
      "values": [32000, 35000, 38000, 42000],
      "margins": [17.3, 17.7, 17.8, 17.1]
    },
    "key_margins": {
      "periods": ["FY 2021-22", "FY 2022-23", "FY 2023-24", "FY 2024-25"],
      "ebitda_margin": [28.5, 28.9, 27.2, 26.5],
      "net_profit_margin": [17.3, 17.7, 17.8, 17.1],
      "operating_margin": [25.2, 25.8, 24.5, 24.1]
    },
    "asset_distribution": {
      "categories": ["Current Assets", "Non-Current Assets"],
      "values": [95000, 90000],
      "unit": "Crores"
    }
  },
  
  "risk_summary": {
    "top_risks": [
      "Foreign exchange rate fluctuations may impact revenue and profitability",
      "Increased competition in the IT services sector affecting pricing and margins",
      "Regulatory changes in key markets may impact operations and compliance costs"
    ]
  },
  
  "metadata": {
    "generated_at": "2026-01-19T10:30:00Z",
    "source_url": "https://www.bseindia.com/...",
    "report_period": "FY 2024-25",
    "data_source": "BSE India Annual Report",
    "generator_version": "1.0"
  }
}
```

## Field Descriptions

### company_overview
- **company_name**: Official company name
- **cin**: Corporate Identification Number (may be null if not extracted)
- **registered_office**: Complete registered office address
- **industry_sector**: Primary industry/sector
- **website**: Company website URL (may be null)
- **stock_info.bse_code**: BSE stock code
- **stock_info.nse_symbol**: NSE symbol (may be null)
- **stock_info.market_cap**: Market capitalization (may be null for real-time data)

### financial_metrics
- **current_period**: Current fiscal year (e.g., "FY 2024-25")
- **previous_period**: Previous fiscal year for comparison (may be null if single year)
- **metrics**: Array of key financial indicators
  - Each metric has: name, current value, previous value, unit, change_percent
  - Common metrics: Revenue, Net Profit, EBITDA, EPS, Total Assets, Dividend

### performance_summary
- **recent_highlights**: 3-4 bullet points of major achievements, initiatives, awards
- **management_guidance**: Summary of future outlook and strategic plans (max 300 chars)
- **business_segments**: Array of major business divisions/verticals

### charts_data
Provides arrays ready for charting libraries (Chart.js, Recharts, etc.):

- **revenue_trend**: Multi-year revenue progression
  - `years`: Array of fiscal year labels
  - `values`: Corresponding revenue values
  - `unit`: Currency unit (Crores, Lakhs, etc.)

- **profit_trend**: Multi-year profit progression with margins
  - `years`: Fiscal year labels
  - `values`: Net profit values
  - `margins`: Net profit margin percentages (for dual-axis charts)

- **key_margins**: Margin analysis over time
  - `periods`: Fiscal year labels
  - `ebitda_margin`: EBITDA margins (%)
  - `net_profit_margin`: Net profit margins (%)
  - `operating_margin`: Operating margins (%) [optional]

- **asset_distribution**: Asset breakdown (optional)
  - `categories`: Asset type labels
  - `values`: Corresponding values
  - `unit`: Currency unit

### risk_summary
- **top_risks**: Top 3 risk factors extracted from annual report

### metadata
- **generated_at**: ISO timestamp of snapshot generation
- **source_url**: BSE India source URL
- **report_period**: Fiscal year of the report
- **data_source**: Always "BSE India Annual Report"
- **generator_version**: Version of snapshot generator (for tracking changes)

## Usage in Frontend

### React Example with Chart.js

```tsx
import { Line, Bar, Doughnut } from 'react-chartjs-2';

function CompanySnapshot({ projectId }) {
  const [snapshot, setSnapshot] = useState(null);
  
  useEffect(() => {
    fetch(`/api/projects/${projectId}/snapshot`)
      .then(res => res.json())
      .then(data => setSnapshot(data.snapshot));
  }, [projectId]);
  
  if (!snapshot) return <div>Loading snapshot...</div>;
  
  const { company_overview, financial_metrics, charts_data } = snapshot;
  
  // Revenue Trend Chart
  const revenueChartData = {
    labels: charts_data.revenue_trend.years,
    datasets: [{
      label: `Revenue (${charts_data.revenue_trend.unit})`,
      data: charts_data.revenue_trend.values,
      borderColor: '#1E3A8A',
      backgroundColor: 'rgba(30, 58, 138, 0.1)'
    }]
  };
  
  return (
    <div className="company-snapshot">
      {/* Header */}
      <header>
        <h1>{company_overview.company_name}</h1>
        <p>{snapshot.metadata.report_period}</p>
      </header>
      
      {/* Financial Metrics Grid */}
      <div className="metrics-grid">
        {financial_metrics.metrics.map(metric => (
          <div key={metric.name} className="metric-card">
            <h3>{metric.name}</h3>
            <p className="value">
              {metric.unit} {metric.current?.toLocaleString()}
            </p>
            <p className={metric.change_percent?.startsWith('+') ? 'positive' : 'negative'}>
              {metric.change_percent}
            </p>
          </div>
        ))}
      </div>
      
      {/* Charts */}
      <div className="charts-section">
        <div className="chart">
          <h3>Revenue Trend</h3>
          <Line data={revenueChartData} />
        </div>
        
        <div className="chart">
          <h3>Profit Trend</h3>
          <Line data={{
            labels: charts_data.profit_trend.years,
            datasets: [
              {
                label: 'Net Profit',
                data: charts_data.profit_trend.values,
                yAxisID: 'y'
              },
              {
                label: 'Profit Margin (%)',
                data: charts_data.profit_trend.margins,
                yAxisID: 'y1'
              }
            ]
          }} />
        </div>
      </div>
      
      {/* Performance Highlights */}
      <div className="highlights">
        <h2>Recent Highlights</h2>
        <ul>
          {snapshot.performance_summary.recent_highlights.map((h, i) => (
            <li key={i}>{h}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
```

### API Call Example

```bash
curl http://localhost:8000/api/projects/{project_id}/snapshot
```

**Response:**
```json
{
  "project_id": "uuid",
  "company_name": "TCS",
  "snapshot": { /* full snapshot JSON */ },
  "generated_at": "2026-01-19T10:30:00Z",
  "updated_at": "2026-01-19T10:30:00Z",
  "version": 1
}
```

## Generation Process

1. **Extraction**: LlamaExtract pulls structured data from PDF
2. **Analysis**: GPT-4o-mini analyzes the extraction data
3. **Structuring**: GPT creates JSON matching the schema above
4. **Enhancement**: System adds metadata and validates structure
5. **Storage**: Saved to `company_snapshots` table
6. **Serving**: Available via `/api/projects/{id}/snapshot`

## Notes

- If OpenAI is not configured, a basic snapshot is generated using only extraction data
- Multi-year trend data depends on having multiple annual reports (currently single year)
- All numeric values are stored as numbers (not strings) for easy charting
- `null` values indicate missing/unavailable data
- Snapshot is versioned and can be regenerated
