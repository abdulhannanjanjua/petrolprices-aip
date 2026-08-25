import unittest

from scraper import extract_chart_series as extract_city_chart_series
from state_scraper import extract_chart_series as extract_state_chart_series


SAMPLE_HTML = """
<script>
const chartSeries = [{"name":"Sydney","data":[[1756598400000,167.4714],[1757203200000,176.95]]}];
const chartTitle = "Sydney";
</script>
"""


class PetrolChartParserTests(unittest.TestCase):
    def test_city_parser_extracts_and_rounds_prices(self):
        result = extract_city_chart_series(SAMPLE_HTML, "Sydney", "Sydney")
        self.assertEqual(result["Sydney"].tolist(), [167.5, 177.0])
        self.assertEqual(
            result["week_ending"].dt.strftime("%Y-%m-%d").tolist(),
            ["2025-08-31", "2025-09-07"],
        )

    def test_state_parser_uses_requested_output_column(self):
        html = SAMPLE_HTML.replace("Sydney", "NSW State Average")
        result = extract_state_chart_series(html, "NSW State Average", "NSW")
        self.assertEqual(result["NSW"].tolist(), [167.5, 177.0])

    def test_parser_rejects_missing_chart_data(self):
        with self.assertRaisesRegex(ValueError, "chartSeries"):
            extract_city_chart_series("<html></html>", "Sydney", "Sydney")


if __name__ == "__main__":
    unittest.main()
