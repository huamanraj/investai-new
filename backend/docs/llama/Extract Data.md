Given complex files like financial reports, contracts, invoices etc, Llama Extract allows you to make use of an LLM to extract the information relevant to you, in a structured format.

In this example, we'll be using [LlamaExtract](https://docs.cloud.llamaindex.ai/llamaextract/getting_started?utm_campaign=extract&utm_medium=recipe) to extract structured data from an SEC filing (specifically, the filing by Nvidia for fiscal year 2025).

On top of simple data extraction, we'll ask our extraction agent to provide citations and reasoning for each extracted field. This allows us to:
- Confirm  the accuracy of the extracted field
- Understand the reasoning behind why the LLM extracted a given piece of information
- This last point allows us an opportunity to adjust the system prompt or field descriptions and improve on results where needed.

The example we go through below is also replicable within Llama Cloud as well, where you will also be able to pick between a number of pre-defined schemas, instead of building your own.

```python
!pip install llama-cloud-services
```

## Connect to Llama Cloud

To get started, make sure you provide your [Llama Cloud](https://cloud.llamaindex.ai?utm_campaign=extract&utm_medium=recipe) API key.

```python
import os
from getpass import getpass

if "LLAMA_CLOUD_API_KEY" not in os.environ:
  os.environ["LLAMA_CLOUD_API_KEY"] = getpass("Enter your Llama Cloud API Key: ")
```

## Extract Data with Llama Extract Agent

```python
from llama_cloud_services import LlamaExtract

# Optionally, provide your project id, if not, it will use the 'Default' project
llama_extract = LlamaExtract()
```

### Provide Your Custom Schema

When using LlamaExtract via the API, you provide your own schema that describes what you want extracted from files and data provided to your agent. Here, we are essentially building an SEC filings extraction agent.

```python
from pydantic import BaseModel, Field
from enum import Enum

class FilingType(str, Enum):
    ten_k = '10 K'
    ten_q = '10-Q'
    ten_ka = '10-K/A'
    ten_qa = '10-Q/A'

class FinancialReport(BaseModel):
    company_name: str = Field(description="The name of the company")
    description: str = Field(description="Short description of the filing and what it contains")
    filing_type: FilingType = Field(description="Type of SEC filing")
    filing_date: str = Field(description="Date when filing was submitted to SEC")
    fiscal_year: int = Field(description="Fiscal year")
    unit: str = Field(description="Unit of financial figures (thousands, millions, etc.)")
    revenue: int = Field(description="Total revenue for period")
```

### Set Up Citations and Reasoning

Optionally, we can set the `ExtractConfig` to extract citations for each field the agent extracts. These cications will cite the specific pages and sections of the file from which a given field was extractedd.

By setting `use_reasoning` to True, we also ask the agent to do an additional reasoning step, explaining why a given field was extracted.

```python
from llama_cloud import ExtractConfig, ExtractMode

config = ExtractConfig(use_reasoning=True,
                       cite_sources=True,
                       extraction_mode=ExtractMode.MULTIMODAL)
```

```python
agent = llama_extract.create_agent(name="filing-parser", data_schema=FinancialReport, config=config)
```

### Demo Time - Download a PDF and Extract Data with Citations

```python
import requests

url = 'https://raw.githubusercontent.com/run-llama/llama_cloud_services/refs/heads/main/examples/extract/data/sec_filings/nvda_10k.pdf'

response = requests.get(url)

if response.status_code == 200:
    with open('/content/nvda_10k.pdf', 'wb') as f:
        f.write(response.content)
    print("PDF downloaded successfully.")
else:
    print(f"Failed to download. Status code: {response.status_code}")

```

```python
filing_info = agent.extract("/content/nvda_10k.pdf")
filing_info.data
```
```
{'company_name': 'NVIDIA Corporation',
'description': "The filing provides a detailed overview of NVIDIA's business as a full-stack computing infrastructure company, discusses various technologies including digital avatars and autonomous vehicles, outlines numerous risk factors affecting operations such as supply chain issues and geopolitical tensions, and describes employee stock purchase plans and related compliance requirements.",
'filing_type': '10 K',
'filing_date': 'February 26, 2025',
'fiscal_year': 2025,
'unit': 'millions',
'revenue': 130497}
```

### Inspect Citations and Reasoning

```python
filing_info.extraction_metadata
```
```
{'field_metadata': {'company_name': {'reasoning': 'VERBATIM EXTRACTION',
    'citation': [{'page': 1, 'matching_text': 'NVIDIA CORPORATION'},
    {'page': 2, 'matching_text': 'NVIDIA Corporation'},
    {'page': 3,
      'matching_text': 'All references to "NVIDIA," "we," "us," "our," or the "Company" mean NVIDIA Corporation and its subsidiaries.'},
    {'page': 35,
      'matching_text': 'Comparison of 5 Year Cumulative Total Return* Among NVIDIA Corporation'},
    {'page': 49,
      'matching_text': 'To the Board of Directors and Shareholders of NVIDIA Corporation'},
    {'page': 90, 'matching_text': 'NVIDIA Corporation'},
    {'page': 119,
      'matching_text': '*"Company"* means NVIDIA Corporation, a Delaware corporation.'},
    {'page': 126,
      'matching_text': 'Annual Report on Form 10-K of NVIDIA Corporation'}]},
  'filing_type': {'reasoning': "VERBATIM EXTRACTION from multiple sources confirming the filing type as '10 K'.",
    'citation': [{'page': 1, 'matching_text': 'FORM 10-K'},
    {'page': 2, 'matching_text': 'Item 16. | Form 10-K Summary'},
    {'page': 3,
      'matching_text': 'This Annual Report on Form 10-K contains forward-looking statements...'},
    {'page': 13, 'matching_text': 'this Annual Report on Form 10-K'},
    {'page': 15, 'matching_text': 'this Annual Report on Form 10-K'},
    {'page': 32,
      'matching_text': 'Annual Report on Form 10-K, which information is hereby incorporated by reference.'},
    {'page': 36, 'matching_text': 'this Annual Report on Form 10-K'},
    {'page': 43,
      'matching_text': 'Annual Report on Form 10-K for additional information'},
    {'page': 45, 'matching_text': 'Annual Report on Form 10-K'},
    {'page': 46, 'matching_text': 'this Annual Report on Form 10-K'},
    {'page': 62, 'matching_text': 'Annual Report on Form 10-K'},
    {'page': 83,
      'matching_text': 'Restated Certificate of Incorporation | 10-K'},
    {'page': 84, 'matching_text': 'Item 16. Form 10-K Summary'},
    {'page': 126, 'matching_text': 'which appears in this Form 10-K'},
    {'page': 127, 'matching_text': 'Annual Report on Form 10-K'},
    {'page': 128, 'matching_text': 'Annual Report on Form 10-K'},
    {'page': 129, 'matching_text': "The Company's Annual Report on Form 10-K"},
    {'page': 130,
      'matching_text': "The Company's Annual Report on Form 10-K for the year ended January 26, 2025"}]},
  'fiscal_year': {'reasoning': 'The fiscal year ended January 26, 2025, indicates the fiscal year is 2025. Additionally, multiple references throughout the text confirm the fiscal year 2025 in various contexts.',
    'citation': [{'page': 1,
      'matching_text': 'For the fiscal year ended January 26, 2025'},
    {'page': 6,
      'matching_text': 'In fiscal year 2025, we launched the NVIDIA Blackwell architecture'},
    {'page': 12, 'matching_text': 'fiscal year 2025'},
    {'page': 17,
      'matching_text': 'our gross margins in the second quarter of fiscal year 2025 were negatively impacted'},
    {'page': 20,
      'matching_text': 'we generated 53% of our revenue in fiscal year 2025 from sales outside the United States.'},
    {'page': 23,
      'matching_text': 'For fiscal year 2025, an indirect customer which primarily purchases our products through system integrators...'},
    {'page': 33,
      'matching_text': 'In fiscal year 2025, we repurchased 310 million shares of our common stock for $34.0 billion.'},
    {'page': 37,
      'matching_text': 'Our Data Center revenue in China grew in fiscal year 2025.'},
    {'page': 44,
      'matching_text': 'Cash provided by operating activities increased in fiscal year 2025 compared to fiscal year 2024'},
    {'page': 57,
      'matching_text': 'Fiscal years 2025, 2024 and 2023 were all 52-week years.'},
    {'page': 65,
      'matching_text': 'Beginning in the second quarter of fiscal year 2025'},
    {'page': 69, 'matching_text': 'In the fourth quarter of fiscal year 2025'},
    {'page': 78,
      'matching_text': 'Depreciation and amortization expense attributable to our Compute and Networking segment for fiscal years 2025'},
    {'page': 129, 'matching_text': 'for the year ended January 26, 2025'}]},
  'description': {'reasoning': 'The extracted data combines multiple descriptions from the source text, ensuring no duplication while maintaining the order and context of the information. Each section of the filing is summarized to reflect the key points without losing the essence of the original text.',
    'citation': [{'page': 4,
      'matching_text': 'NVIDIA is now a full-stack computing infrastructure company with data-center-scale offerings that are reshaping industry.'},
    {'page': 8,
      'matching_text': 'a suite of technologies that help developers bring digital avatars to life with generative Al...autonomous vehicles, or AV, and electric vehicles, or EV, is revolutionizing the transportation industry...Our worldwide sales and marketing strategy is key to achieving our objective of providing markets with our high-performance and efficient computing platforms and software.'},
    {'page': 14, 'matching_text': 'Risk Factors Summary'},
    {'page': 16,
      'matching_text': 'Risks Related to Demand, Supply, and Manufacturing\n\nLong manufacturing lead times and uncertain supply and component availability...'},
    {'page': 18,
      'matching_text': 'cryptocurrency mining, on demand for our products. Volatility in the cryptocurrency market, including new compute technologies...'},
    {'page': 21,
      'matching_text': 'supply-chain attacks or other business disruptions. We cannot guarantee that third parties and infrastructure in our supply chain...'},
    {'page': 22,
      'matching_text': 'We are monitoring the impact of the geopolitical conflict in and around Israel on our operations... Climate change may have a long-term impact on our business.'},
    {'page': 25,
      'matching_text': 'We are subject to complex laws, rules, regulations, and political and other actions, including restrictions on the export of our products, which may adversely impact our business.'},
    {'page': 28,
      'matching_text': 'Our competitive position has been harmed by the existing export controls, and our competitive position and future results may be further harmed'},
    {'page': 29,
      'matching_text': 'restrictions imposed by the Chinese government on the duration of gaming activities and access to games may adversely affect our Gaming revenue'},
    {'page': 29,
      'matching_text': 'our business depends on our ability to receive consistent and reliable supply from our overseas partners, especially in Taiwan and South Korea'},
    {'page': 29,
      'matching_text': 'Increased scrutiny from shareholders, regulators and others regarding our corporate sustainability practices could result in additional costs'},
    {'page': 29,
      'matching_text': 'Concerns relating to the responsible use of new and evolving technologies, such as Al, in our products and services may result in reputational or financial harm'},
    {'page': 31,
      'matching_text': 'Data protection laws around the world are quickly changing and may be interpreted and applied in an increasingly stringent fashion...'}]},
  'filing_date': {'reasoning': 'The filing date is consistently mentioned as February 26, 2025 across multiple entries, making it the most reliable date for the filing.',
    'citation': [{'page': 51, 'matching_text': 'February 26, 2025'},
    {'page': 86, 'matching_text': 'on February 26, 2025.'},
    {'page': 87, 'matching_text': 'February 26, 2025'},
    {'page': 126, 'matching_text': 'our report dated February 26, 2025'},
    {'page': 127, 'matching_text': 'Date: February 26, 2025'},
    {'page': 128, 'matching_text': 'Date: February 26, 2025'},
    {'page': 129, 'matching_text': 'Date: February 26, 2025'},
    {'page': 130, 'matching_text': 'Date: February 26, 2025'}]},
  'unit': {'reasoning': "The unit of financial figures is explicitly mentioned multiple times in the text as 'millions', including in table headers and notes. This is confirmed by various citations from pages 38, 42, 43, 52, 53, 54, 56, 65, 71, 72, 73, 75, 77, 79, 80, and 82.",
    'citation': [{'page': 38,
      'matching_text': '($ in millions, except per share data)'},
    {'page': 42, 'matching_text': '($ in millions)'},
    {'page': 43, 'matching_text': '($ in millions)'},
    {'page': 52, 'matching_text': '(In millions, except per share data)'},
    {'page': 53,
      'matching_text': 'Consolidated Statements of Comprehensive Income (In millions)'},
    {'page': 54,
      'matching_text': 'Consolidated Balance Sheets (In millions, except par value)'},
    {'page': 55, 'matching_text': '(In millions, except per share data)'},
    {'page': 56,
      'matching_text': 'Consolidated Statements of Cash Flows (In millions)'},
    {'page': 65,
      'matching_text': 'Year Ended<br/>Jan 26, 2025<br/>(In millions, except per share data)'},
    {'page': 71, 'matching_text': '(In millions) | (In millions)'},
    {'page': 72, 'matching_text': '(In millions)'}]},
  'revenue': {'reasoning': 'The total revenue for fiscal year 2025 is extracted from multiple sources within the text, all confirming the same figure of $130,497 million. The revenue recognized for fiscal year 2025 is also noted as $4,607 million, which is a separate figure. However, the primary focus is on the total revenue figure, which is consistently cited.',
    'citation': [{'page': 38,
      'matching_text': 'Revenue for fiscal year 2025 was $130.5 billion'},
    {'page': 41,
      'matching_text': 'Total                | $ 130,497    | $ | 60,922'},
    {'page': 52, 'matching_text': 'Revenue | $ 130,497'},
    {'page': 78,
      'matching_text': 'Revenue | $ 116,193 | $ 14,304 | $ - | $ 130,497'},
    {'page': 79, 'matching_text': 'Total revenue | $ 130,497'},
    {'page': 80, 'matching_text': 'Total revenue              | $ 130,497'}]}},
  'usage': {'num_pages_extracted': 130,
  'num_document_tokens': 105932,
  'num_output_tokens': 31306}}
```

## What's Next?

In this example, we built an Extraction Agent that is capable of citing it's sources from the document it's extracting data from, and reasoning about its reponse. To further customize and improve on the results, you can also try to customize the `system_prompt` in the `ExtractConfig`.

#### Learn More

- [LlamaExtract Documentation](https://docs.cloud.llamaindex.ai/llamaextract/getting_started)
- [Example Notebooks](https://github.com/run-llama/llama_cloud_services/tree/main/examples/extract) 


In this walk-through, we'll take a look at not only extracting structured information from unstructured documents, but also coming up with the schema in the first place. LlamaExtract allows you to define extraction schemas via the SDK and the UI, but it also allows you to make use of an LLM to generate a schema for you.

This works by providing either a simple prompt describing the data you want to extract, providing an example file which you want to extract data from, or both.

## Generating a Schema with an Example and/or Prompt

When creating an extraction agent you have the option to provide: 
- A file
- A short prompt

You don't have to provide both, but to use the schema generation functionality, you need to provide at least one of these two.

In this example, we'll be generating a schema for menus, and our aim is to extract not only the listed menu items, but also allergens and dietary restrictions, which may appear very differently from menu to menu. 

We start with the prompt `Extract menu items with their allergens and dietary restriction information` as well as an image of the menu:

  ![](img/generate-schema.png)

## Editing the Generated Schema

Once a schema is generated, you will have the option to make some final edits by changing field names, descriptions, whether they are required or not, or even deleting and adding fields. In this example, we're not interested in the `category` or `portion_size` fields, so we can delete them:

  ![](img/edit-schema.png)

## Publish Configuration and Run Extraction

Finally, you can publish the extraction agent configuration and run an extraction job. In this example, our extraction results end up being the following: 

  ![](img/extracted-results.png)