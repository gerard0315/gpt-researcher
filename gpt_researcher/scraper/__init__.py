from .beautiful_soup.beautiful_soup import BeautifulSoupScraper
from .web_base_loader.web_base_loader import WebBaseLoaderScraper
from .arxiv.arxiv import ArxivScraper
from .pymupdf.pymupdf import PyMuPDFScraper
from .browser.browser import BrowserScraper
from .browser.nodriver_scraper import NoDriverScraper
from .tavily_extract.tavily_extract import TavilyExtract
from .firecrawl.firecrawl import FireCrawl
from .scrape_do.scrape_do import ScrapeDoScraper
from .firecrawl_scrape_do_random.firecrawl_scrape_do_random import (
    FirecrawlScrapeDoRandom,
)
from .scraper import Scraper

__all__ = [
    "BeautifulSoupScraper",
    "WebBaseLoaderScraper",
    "ArxivScraper",
    "PyMuPDFScraper",
    "BrowserScraper",
    "NoDriverScraper",
    "TavilyExtract",
    "ScrapeDoScraper",
    "FirecrawlScrapeDoRandom",
    "Scraper",
    "FireCrawl",
]
