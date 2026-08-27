import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from digest import is_weekday_ist, rank_universes, render_html

IST = ZoneInfo("Asia/Kolkata")


class DigestTests(unittest.TestCase):
    def test_weekend_skip(self):
        saturday = datetime(2026, 8, 29, 8, 30, tzinfo=IST)
        monday = datetime(2026, 8, 31, 8, 30, tzinfo=IST)
        self.assertFalse(is_weekday_ist(saturday))
        self.assertTrue(is_weekday_ist(monday))

    def test_rank_top_n_per_universe(self):
        df = pd.DataFrame([
            {"Ticker": "AAA.NS", "Total Score": 9.1, "Fundamental Score": 8, "Technical Score": 9, "Relative Strength Score": 7, "Sector": "Tech"},
            {"Ticker": "BBB.NS", "Total Score": 8.2, "Fundamental Score": 7, "Technical Score": 8, "Relative Strength Score": 6, "Sector": "Banks"},
            {"Ticker": "CCC.NS", "Total Score": 7.0, "Fundamental Score": 6, "Technical Score": 7, "Relative Strength Score": 5, "Sector": "Auto"},
            {"Ticker": "DDD.NS", "Total Score": 9.9, "Fundamental Score": 9, "Technical Score": 9, "Relative Strength Score": 9, "Sector": "IT"},
        ])
        universe_map = {
            "Nifty 50": ["AAA.NS", "BBB.NS", "CCC.NS"],
            "Nifty Next 50": ["DDD.NS", "CCC.NS"],
        }
        sections = rank_universes(df, universe_map, top_n=2)
        nifty = next(s for s in sections if s["universe"] == "Nifty 50")
        self.assertEqual([r["Ticker"] for r in nifty["rows"]], ["AAA.NS", "BBB.NS"])
        nxt = next(s for s in sections if s["universe"] == "Nifty Next 50")
        self.assertEqual(nxt["rows"][0]["Ticker"], "DDD.NS")

    def test_html_contains_universes(self):
        sections = [{
            "universe": "Nifty 50",
            "tickers_scanned": 50,
            "rows": [{
                "Ticker": "RELIANCE.NS",
                "Total Score": 8.5,
                "Fundamental Score": 7.1,
                "Technical Score": 8.0,
                "Relative Strength Score": 6.2,
                "Sector": "Energy",
            }],
        }]
        html = render_html(sections, datetime(2026, 8, 27, 8, 30, tzinfo=IST), 10)
        self.assertIn("Nifty 50", html)
        self.assertIn("RELIANCE.NS", html)
        self.assertIn("FunTech morning picks", html)
        self.assertIn("not a stock recommendation", html.lower())
        self.assertIn("consult your financial advisor", html.lower())
        self.assertIn("user-selected settings and weightages", html.lower())


if __name__ == "__main__":
    unittest.main()
