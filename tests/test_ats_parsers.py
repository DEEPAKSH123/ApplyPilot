"""Unit tests for ATS parsers and edge-case contracts."""

import html
import pytest
from unittest.mock import MagicMock, patch

from applypilot.discovery.ats import (
    _scrape_greenhouse,
    _scrape_lever,
    _scrape_ashby,
    _scrape_smartrecruiters,
    detect_ats_board,
)
from applypilot.discovery.workday import workday_search


def test_greenhouse_double_encoded_html():
    """Verify Greenhouse scraper unescapes double-encoded HTML in job content."""
    fake_jobs = {
        "jobs": [
            {
                "id": 101,
                "title": "Backend Engineer",
                "location": {"name": "Bengaluru, India"},
                "absolute_url": "https://boards.greenhouse.io/test/jobs/101",
                "content": "&lt;p&gt;Looking for &amp;lt;strong&amp;gt;Golang&amp;lt;/strong&amp;gt; developer.&lt;/p&gt;",
                "updated_at": "2026-11-20T10:00:00Z",
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_jobs

    with patch("httpx.Client.get", return_value=mock_resp):
        emp = {"slug": "testcompany", "name": "TestCompany"}
        results = _scrape_greenhouse("testcompany", emp, ["bengaluru"], [], 0, [])
        assert len(results) == 1
        assert "Golang" in results[0]["full_description"]
        assert "&lt;" not in results[0]["full_description"]


def test_lever_ms_timestamp_and_eu_fallback():
    """Verify Lever scraper parses millisecond timestamps and falls back to EU endpoint on 404."""
    fake_jobs = [
        {
            "id": "lever-1",
            "text": "Senior Backend Engineer",
            "categories": {"location": "Remote"},
            "hostedUrl": "https://jobs.lever.co/test/lever-1",
            "createdAt": 1700000000000,
            "descriptionPlain": "Go, Kafka, Microservices",
        }
    ]

    mock_404 = MagicMock(status_code=404)
    mock_200 = MagicMock(status_code=200, json=lambda: fake_jobs)

    def mock_get(url):
        if "api.eu.lever.co" in url:
            return mock_200
        return mock_404

    with patch("httpx.Client.get", side_effect=mock_get):
        emp = {"slug": "testeu", "name": "TestEU"}
        results = _scrape_lever("testeu", emp, ["remote"], [], 0, [])
        assert len(results) == 1
        assert results[0]["title"] == "Senior Backend Engineer"


def test_ashby_is_listed_filter():
    """Verify Ashby scraper excludes jobs where isListed == False."""
    fake_payload = {
        "jobs": [
            {
                "id": "ashby-1",
                "title": "Backend Engineer",
                "location": "Bengaluru",
                "isListed": False,
                "publishedAt": "2026-11-20T10:00:00Z",
            },
            {
                "id": "ashby-2",
                "title": "Distributed Systems Engineer",
                "location": "Bengaluru",
                "isListed": True,
                "publishedAt": "2026-11-20T10:00:00Z",
            },
        ]
    }

    mock_resp = MagicMock(status_code=200, json=lambda: fake_payload)
    with patch("httpx.Client.get", return_value=mock_resp):
        emp = {"slug": "ashbyco", "name": "AshbyCo"}
        results = _scrape_ashby("ashbyco", emp, ["bengaluru"], [], 0, [])
        assert len(results) == 1
        assert results[0]["title"] == "Distributed Systems Engineer"


def test_workday_limit_cap_and_locale_stripping():
    """Verify workday_search caps limit at 20 and strips locale segments."""
    with patch("urllib.request.Request") as mock_req, patch("applypilot.discovery.workday._urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"total": 5, "jobPostings": []}'
        mock_url.return_value.__enter__.return_value = mock_resp

        employer = {
            "name": "Nvidia",
            "base_url": "https://nvidia.wd5.myworkdayjobs.com/en-US",
            "tenant": "nvidia",
            "site_id": "en-US/NVIDIAExternalCareerSite",
        }
        res = workday_search(employer, "backend", limit=50, offset=0)
        assert res["total"] == 5

        # Check URL requested
        call_args = mock_req.call_args[0]
        url = call_args[0]
        assert "/en-US" not in url
        assert "limit\": 20" in mock_req.call_args[1]["data"].decode()
