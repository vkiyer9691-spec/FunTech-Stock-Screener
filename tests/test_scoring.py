import unittest

from app import canslim_c_growth


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


if __name__ == "__main__":
    unittest.main()
