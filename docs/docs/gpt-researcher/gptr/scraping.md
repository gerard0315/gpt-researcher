# Scraping Options

GPT Researcher now offers various methods for web scraping: static scraping with BeautifulSoup, dynamic scraping with Selenium, and high-scale API scraping with Tavily Extract, FireCrawl, and Scrape.do. This document explains how to switch between these methods and the benefits of each approach.

## Configuring Scraping Method

You can choose your preferred scraping method by setting the `SCRAPER` environment variable:

1. For BeautifulSoup (static scraping):
   ```
   export SCRAPER="bs"
   ```

2. For dynamic browser scraping, either with Selenium:
   ```
   export SCRAPER="browser"
   ```
   Or with NoDriver (ZenDriver):
   ```
   export SCRAPER="nodriver"
   pip install zendriver
   ```

3. For **production** use cases, you can set the scraper to `tavily_extract`, `firecrawl`, `scrape_do`, or `firecrawl_scrape_do_random`. [Tavily](https://tavily.com) allows you to scrape sites at scale without the hassle of setting up proxies, managing cookies, or dealing with CAPTCHAs. Please note that you need to have a Tavily account and [API key](https://app.tavily.com) to use this option. To learn more about Tavily Extract [see here](https://docs.tavily.com/docs/python-sdk/tavily-extract/getting-started).
    Make sure to first install the pip package `tavily-python`. Then:
   ```
   export SCRAPER="tavily_extract"
   ```
   [FireCrawl](https://firecrawl.dev) is also allows you to scrape sites at scale. FireCrawl also provides open source code to self hosted server which provided better scrape quality compared to BeautifulSoup by passing markdown version of the scraped sites to LLMs. You will needs to have FireCrawl account (official service) to get API key or you needs self host URL and API key (if you set for your self host server) to use this option.
   Make sure to install the pip package `firecrawl-py`. Then:
   ```bash
   export SCRAPER="firecrawl"
   ```
   [Scrape.do](https://scrape.do) also supports rendered scraping and markdown output through a simple HTTP API. Set:
   ```bash
   export SCRAPER="scrape_do"
   export SCRAPE_DO_API_KEY="<your-scrape-do-api-key>"
   ```
   For random load distribution across 2 Firecrawl keys + 1 Scrape.do key:
   ```bash
   export SCRAPER="firecrawl_scrape_do_random"
   export FIRECRAWL_API_KEY="<firecrawl-key-1>,<firecrawl-key-2>"
   export SCRAPE_DO_API_KEY="<your-scrape-do-api-key>"
   ```

Note: If not set, GPT Researcher will default to BeautifulSoup for scraping.

## Scraping Methods Explained

### BeautifulSoup (Static Scraping)

When `SCRAPER="bs"`, GPT Researcher uses BeautifulSoup for static scraping. This method:

- Sends a single HTTP request to fetch the page content
- Parses the static HTML content
- Extracts text and data from the parsed HTML

Benefits:
- Faster and more lightweight
- Doesn't require additional setup
- Works well for simple, static websites

Limitations:
- Cannot handle dynamic content loaded by JavaScript
- May miss content that requires user interaction to display

### Selenium (Browser Scraping)

When `SCRAPER="browser"`, GPT Researcher uses Selenium for dynamic scraping. This method:

- Opens a real browser instance (Chrome by default)
- Loads the page and executes JavaScript
- Waits for dynamic content to load
- Extracts text and data from the fully rendered page

Benefits:
- Can scrape dynamically loaded content
- Simulates real user interactions (scrolling, clicking, etc.)
- Works well for complex, JavaScript-heavy websites

Limitations:
- Slower than static scraping
- Requires more system resources
- Requires additional setup (Selenium and WebDriver installation)

### NoDriver (Browser Scraping)

Alternative to Selenium for potentially better performance.

Setup:
```bash
pip install zendriver
```

### Tavily Extract (Recommended for Production)

When `SCRAPER="tavily_extract"`, GPT Researcher uses Tavily's Extract API for web scraping. This method:

- Uses Tavily's robust infrastructure to handle web scraping at scale
- Automatically handles CAPTCHAs, JavaScript rendering, and anti-bot measures
- Provides clean, structured content extraction

Benefits:
- Production-ready and highly reliable
- No need to manage proxies or handle rate limiting
- Excellent success rate on most websites
- Handles both static and dynamic content
- Built-in content cleaning and formatting
- Fast response times through Tavily's distributed infrastructure

Setup:
1. Create a Tavily account at [app.tavily.com](https://app.tavily.com)
2. Get your API key from the dashboard
3. Install the Tavily Python SDK:
   ```bash
   pip install tavily-python
   ```
4. Set your Tavily API key:
   ```bash
   export TAVILY_API_KEY="your-api-key"
   ```

Usage Considerations:
- Requires a Tavily API key and account
- API calls are metered based on your Tavily plan
- Best for production environments where reliability is crucial
- Ideal for businesses and applications that need consistent scraping results

### FireCrawl (Recommended for Production)
When `SCRAPER="firecrawl"`, GPT Researcher uses FireCrawl Scrape API for web scraping in markdown format. This method:

- Uses FireCrawl's robust infrastructure to handle web scraping at scale
- Or uses self-hosted FireCrawl server.
- Automatically handles CAPTCHAs, JavaScript rendering, and anti-bot measures
- Provides clean, structured content extraction in markdown format.

Benefits:
- Production-ready and highly reliable
- No need to manage proxies or handle rate limiting
- Excellent success rate on most websites
- Handles both static and dynamic content
- Built-in content cleaning and formatting
- Fast response times through FireCrawl's distributed infrastructure
- Ease of setup with FireCrawl self-hosted

Setup (official service by FireCrawl):
1. Create a FireCrawl account at [firecrawl.dev/app](https://www.firecrawl.dev/app)
2. Get your API key from the dashboard
3. Install the FireCrawl Python SDK:
   ```bash
   pip install firecrawl-py
   ```
4. Set your FireCrawl API key:
   ```bash
   export FIRECRAWL_API_KEY=<your-firecrawl-api>
   ```
Setup (with self-hosted server):
1. Host your FireCrawl. Read their [self-hosted guidelines](https://docs.firecrawl.dev/contributing/self-host) or [run locally guidelines](https://docs.firecrawl.dev/contributing/guide)
2. Get your server URL and API key (if you set it).
3. Install the FireCrawl Python SDK:
   ```bash
   pip install firecrawl-py
   ```
4. Set your FireCrawl API key:
   ```bash
   export FIRECRAWL_API_KEY=<your-firecrawl-api>
   ```

Note: `FIRECRAWL_API_KEY` can be empty if you not setup authentication for your self host server (`FIRECRAWL_API_KEY=""`).
There will be some difference between their cloud service and open source service. To understand differences between FireCrawl option read [here](https://docs.firecrawl.dev/contributing/open-source-or-cloud).

Usage Considerations:
- Requires a FireCrawl API key and account or self-hosted server
- API calls are metered based on your FireCrawl plan (it can be basically free with self-hosted FireCrawl method)
- Best for production environments where reliability is crucial (for their cloud service)
- Ideal for businesses and applications that need consistent scraping results
- Need robust scraping option for personal use

### Scrape.do (Production API Scraper)
When `SCRAPER="scrape_do"`, GPT Researcher uses the Scrape.do API for scraping. This method:

- Calls Scrape.do's hosted endpoint (`https://api.scrape.do/`)
- Supports rendered scraping (`render=true`) for JS-heavy pages
- Supports markdown output (`output=markdown`) for LLM-friendly content

Setup:
1. Create an account at [scrape.do](https://scrape.do)
2. Get your API key
3. Set environment variables:
   ```bash
   export SCRAPER="scrape_do"
   export SCRAPE_DO_API_KEY="<your-scrape-do-api-key>"
   ```
4. Optional tuning:
   ```bash
   export SCRAPE_DO_OUTPUT="markdown"   # default
   export SCRAPE_DO_RENDER="true"       # enable browser rendering
   export SCRAPE_DO_SUPER="false"       # optional premium mode
   export SCRAPE_DO_GEO_CODE="us"       # optional geo routing
   export SCRAPE_DO_TIMEOUT="40"        # request timeout seconds
   ```

### Firecrawl + Scrape.do Random Pool
When `SCRAPER="firecrawl_scrape_do_random"`, GPT Researcher builds a request pool from your configured keys and randomly routes each scrape request across pool slots.

- Each key is one slot in the random pool
- Example: 2 Firecrawl keys + 1 Scrape.do key => 3 randomized slots
- If one slot fails or returns empty content, it tries the next slot

Setup:
```bash
export SCRAPER="firecrawl_scrape_do_random"
export FIRECRAWL_API_KEY="<firecrawl-key-1>,<firecrawl-key-2>"
export SCRAPE_DO_API_KEY="<your-scrape-do-api-key>"
```

## Additional Setup for Selenium

If you choose to use Selenium (SCRAPER="browser"), you'll need to:

1. Install the Selenium package:
   ```
   pip install selenium
   ```

2. Download the appropriate WebDriver for your browser:
   - For Chrome: [ChromeDriver](https://sites.google.com/a/chromium.org/chromedriver/downloads)
   - For Firefox: [GeckoDriver](https://github.com/mozilla/geckodriver/releases)
   - For Safari: Built-in, no download required

   Ensure the WebDriver is in your system's PATH.

## Choosing the Right Method

- Use BeautifulSoup (static) for:
  - Simple websites with mostly static content
  - Scenarios where speed is a priority
  - When you don't need to interact with the page

- Use Selenium (dynamic) for:
  - Websites with content loaded via JavaScript
  - Sites that require scrolling or clicking to load more content
  - When you need to simulate user interactions

## Troubleshooting

- If Selenium fails to start, ensure you have the correct WebDriver installed and it's in your system's PATH.
- If you encounter an `ImportError` related to Selenium, make sure you've installed the Selenium package.
- If the scraper misses expected content, try switching between static and dynamic scraping to see which works better for your target website.

Remember, the choice between static and dynamic scraping can significantly impact the quality and completeness of the data GPT Researcher can gather. Choose the method that best suits your research needs and the websites you're targeting.
