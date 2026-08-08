"""Run the reusable Zhilian browser crawler from the command line.

Usage:
    python _crawl_zhilian_browser.py [keyword ...]
"""

from __future__ import annotations

import logging
import sys

from config import CRAWLER_CONFIG
from jd_crawler import crawl_zhilian_browser, mark_premium_jobs, save_jobs


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    keywords = sys.argv[1:] or CRAWLER_CONFIG["keywords"]
    city = CRAWLER_CONFIG["default_city"]
    jobs = mark_premium_jobs(crawl_zhilian_browser(keywords, city))
    if not jobs:
        raise SystemExit("No Zhilian jobs were collected.")

    saved_path = save_jobs(jobs, tag="zhilian_browser")
    print(f"Collected {len(jobs)} jobs: {saved_path}")


if __name__ == "__main__":
    main()
