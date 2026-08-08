"""Offline regression tests for crawler parsing and deduplication."""

from __future__ import annotations

import unittest

from bs4 import BeautifulSoup

from jd_crawler import (
    _parse_liepin_browser_card,
    _parse_list_html,
    deduplicate_jobs,
)


class LiepinBrowserCardTests(unittest.TestCase):
    def test_parse_rendered_card_keeps_url_and_city_in_identity(self) -> None:
        html = """
        <div class="job-card-pc-container">
          <a data-nick="job-detail-job-info" href="/job/123.shtml">
            <span class="ellipsis-1" title="Python Engineer">Python Engineer</span>
          </a>
          <div data-nick="job-detail-company-info"><span class="ellipsis-1">Acme</span></div>
          <span class="job-salary">20-30k</span>
          <span class="job-dq">Beijing</span>
          <span class="job-require">3-5 years</span>
          <div class="tag-list"><span>Python</span><span>FastAPI</span></div>
        </div>
        """
        card = BeautifulSoup(html, "html.parser").select_one(".job-card-pc-container")
        job = _parse_liepin_browser_card(card, "Nationwide")

        self.assertIsNotNone(job)
        assert job is not None
        self.assertEqual(job["title"], "Python Engineer")
        self.assertEqual(job["company"], "Acme")
        self.assertEqual(job["city"], "Beijing")
        self.assertEqual(job["url"], "https://www.liepin.com/job/123.shtml")
        self.assertEqual(job["skills"], ["Python", "FastAPI"])

    def test_same_title_and_company_in_different_cities_are_retained(self) -> None:
        html = """
        <section class="job-list-item"><a href="/job/1"><h3>Backend Engineer</h3></a>
          <span class="company">Acme</span><span class="job-area">Beijing</span></section>
        <section class="job-list-item"><a href="/job/2"><h3>Backend Engineer</h3></a>
          <span class="company">Acme</span><span class="job-area">Shanghai</span></section>
        """
        jobs = _parse_list_html("liepin", html, "Backend", "Nationwide")
        unique_jobs = deduplicate_jobs(jobs)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(unique_jobs), 2)
        self.assertNotEqual(unique_jobs[0]["job_id"], unique_jobs[1]["job_id"])

    def test_configured_51job_source_uses_its_selectors(self) -> None:
        html = """
        <article class="job-item"><a href="/job/100"><h3 class="jname">Data Engineer</h3></a>
          <span class="cname">Example Corp</span><span class="sal">25-35k</span>
          <span class="work-area">Shanghai</span></article>
        """
        jobs = _parse_list_html("51job", html, "Data", "Nationwide")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Data Engineer")
        self.assertEqual(jobs[0]["company"], "Example Corp")
        self.assertEqual(jobs[0]["city"], "Shanghai")
        self.assertEqual(jobs[0]["url"], "https://we.51job.com/job/100")


if __name__ == "__main__":
    unittest.main()
