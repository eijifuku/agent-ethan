import unittest

from agent_ethan.tools import arxiv_filter
from agent_ethan.tools import arxiv_keywords
from agent_ethan.tools import arxiv_summary


class ArxivKeywordFallbackTestCase(unittest.TestCase):
    def test_uses_llm_keywords_when_available(self) -> None:
        result = arxiv_keywords.fallback_keywords(
            request="any", llm_keywords="  lightgbm, time series  "
        )
        self.assertEqual(result["json"]["keywords"], "lightgbm, time series")

    def test_generates_heuristic_keywords_when_missing(self) -> None:
        result = arxiv_keywords.fallback_keywords(
            request="LightGBM for time series forecasting in retail"
        )
        keywords = result["json"]["keywords"].split(", ")
        self.assertIn("lightgbm", keywords)
        self.assertIn("time", keywords)


class ArxivSummaryFallbackTestCase(unittest.TestCase):
    def test_returns_llm_summary_if_present(self) -> None:
        result = arxiv_summary.fallback_summary(
            downloads=[],
            llm_summary="Generated report",
        )
        self.assertEqual(result["json"]["summary"], "Generated report")

    def test_builds_fallback_summary_when_missing(self) -> None:
        downloads = [
            {"id": "arXiv:1234.5678", "title": "Sample Paper", "path": "downloads/sample.pdf"}
        ]
        result = arxiv_summary.fallback_summary(downloads=downloads, llm_summary=None)
        summary = result["json"]["summary"]
        self.assertIn("Sample Paper", summary)
        self.assertIn("downloads/sample.pdf", summary)


class ArxivFilterFallbackTestCase(unittest.TestCase):
    def test_heuristic_selection_when_llm_output_invalid(self) -> None:
        search_results = [
            {
                "id": "arXiv:2303.12345",
                "title": "LightGBM Feature Engineering",
                "summary": "time series forecasting",
                "categories": ["cs.LG"],
            },
            {
                "id": "arXiv:2101.54321",
                "title": "Transformers",
                "summary": "unrelated",
                "categories": ["cs.AI"],
            },
        ]
        result = arxiv_filter.parse_selection(
            raw_text="not json",
            search_results=search_results,
            keywords="lightgbm time series",
            max_results=1,
        )
        ids = result["json"]["relevant_ids"]
        self.assertEqual(ids, ["arXiv:2303.12345"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
