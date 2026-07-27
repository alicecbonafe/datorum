from .archive_org_scraper import ArchiveOrgScraper
from .arxiv_scraper import ArxivHTMLScraper, ArxivTeXScraper, BaseArxivScraper
from .base import BaseScraper, ScrapedDocument
from .html_scraper import BasicHTMLScraper, IndexedHTMLScraper
from .mdx_scraper import MDXScraper
from .planalto_br_scraper import PlanaltoBRScraper
from .qmd_scraper import QMDScraper

registry = {
    "BasicHTMLScraper": BasicHTMLScraper,
    "IndexedHTMLScraper": IndexedHTMLScraper,
    "MDXScraper": MDXScraper,
    "ArxivHTMLScraper": ArxivHTMLScraper,
    "ArxivTeXScraper": ArxivTeXScraper,
    "QMDScraper": QMDScraper,
    "ArchiveOrgScraper": ArchiveOrgScraper,
    "PlanaltoBRScraper": PlanaltoBRScraper,
}
