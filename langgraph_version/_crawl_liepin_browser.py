"""Run the reusable Liepin browser crawler from the command line.

Usage:
    python _crawl_liepin_browser.py [keyword ...]
"""

from __future__ import annotations

import logging
import sys

from config import CRAWLER_CONFIG
from jd_crawler import crawl_liepin_browser, mark_premium_jobs, save_jobs


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    keywords = sys.argv[1:] or CRAWLER_CONFIG["keywords"]
    city = CRAWLER_CONFIG["default_city"]
    jobs = mark_premium_jobs(crawl_liepin_browser(keywords, city))
    if not jobs:
        raise SystemExit("No Liepin jobs were collected.")

    saved_path = save_jobs(jobs, tag="liepin_browser")
    print(f"Collected {len(jobs)} jobs: {saved_path}")


if __name__ == "__main__":
    main()
