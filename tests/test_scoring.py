import unittest

import pandas as pd

from app import (
    canslim_a_growth,
    canslim_c_growth,
    compute_fundamental_score,
    fifty_two_week_high,
    up_volume_exceeds_down,
)


class ScoringCTests(unittest.TestCase):
    def test_c_prefers_quarterly_eps_over_annual_yahoo(self):
        info = {
            "earningsGrowth": 0.35,
            "quarterly_eps_yoy": -0.27,
            "quarterly_ni_yoy": -0.26,
        }
        self.assertAlmostEqual(canslim_c_growth(info), -0.27)
        self.assertFalse(canslim_c_growth(info) > 0.15)

    def test_c_falls_back_to_net_income(self):
        info = {"quarterly_ni_yoy": 0.20, "earningsGrowth": 0.01}
        self.assertAlmostEqual(canslim_c_growth(info), 0.20)

    def test_c_missing_is_none(self):
        self.assertIsNone(canslim_c_growth({"earningsGrowth": 0.40}))


class ScoringATests(unittest.TestCase):
    def test_a_uses_quarterly_revenue_not_yahoo(self):
        info = {"quarterly_rev_yoy": 0.05, "revenueGrowth": 0.40}
        self.assertAlmostEqual(canslim_a_growth(info), 0.05)
        self.assertFalse(canslim_a_growth(info) > 0.10)

    def test_a_missing_is_none(self):
        self.assertIsNone(canslim_a_growth({"revenueGrowth": 0.50}))


class ScoringNTests(unittest.TestCase):
    def test_n4_takes_max_of_yahoo_and_daily_high(self):
        daily = pd.DataFrame({"High": [100.0] * 10 + [150.0], "Close": [100.0] * 11})
        self.assertEqual(fifty_two_week_high({"fiftyTwoWeekHigh": 120.0}, daily), 150.0)
        self.assertEqual(fifty_two_week_high({"fiftyTwoWeekHigh": 180.0}, daily), 180.0)


class ScoringSTests(unittest.TestCase):
    def test_s3_up_volume_beats_down(self):
        close = [10 + i for i in range(12)] + [21 - i for i in range(10)]
        vol_up = [100] * 12
        vol_down = [10] * 10
        daily = pd.DataFrame({"Close": close, "Volume": vol_up + vol_down})
        self.assertTrue(up_volume_exceeds_down(daily, 20))

    def test_s3_skip_without_volume(self):
        daily = pd.DataFrame({"Close": list(range(30))})
        self.assertIsNone(up_volume_exceeds_down(daily, 20))


class ScoringLTests(unittest.TestCase):
    def test_l_beats_nifty_and_skips_missing_sector(self):
        n = 80
        stock = pd.DataFrame({"Close": [100.0] * (n - 1) + [130.0], "High": [100.0] * n, "Volume": [1] * n})
        bench = pd.DataFrame({"Close": [100.0] * n})
        info = {"quarterly_eps_yoy": 0.20, "quarterly_rev_yoy": 0.20, "heldPercentInstitutions": 0.40}
        _, _, raw = compute_fundamental_score(info, stock, bench, sector_avg_ret=None)
        self.assertTrue(raw["L"])
        self.assertIsNone(raw["Ls"])
        _, _, raw2 = compute_fundamental_score(info, stock, bench, sector_avg_ret=5.0)
        self.assertTrue(raw2["Ls"])


if __name__ == "__main__":
    unittest.main()
