from .html_scraper import BasicHTMLScraper, IndexedHTMLScraper
from .mdx_scraper import MDXScraper
from .arxiv_html_scraper import ArxivHTMLScraper
from .arxiv_tex_scraper import ArxivTeXScraper
from .qmd_scraper import QMDScraper
from .archive_org_scraper import ArchiveOrgScraper
from .planalto_br_scraper import PlanaltoBRScraper

registry = {
    'BasicHTMLScraper': BasicHTMLScraper,
    'IndexedHTMLScraper': IndexedHTMLScraper,
    'MDXScraper': MDXScraper,
    'ArxivHTMLScraper': ArxivHTMLScraper,
    'ArxivTeXScraper': ArxivTeXScraper,
    'QMDScraper': QMDScraper,
    'ArchiveOrgScraper': ArchiveOrgScraper,
    'PlanaltoBRScraper': PlanaltoBRScraper,
}