"""Tests for the ERA Braking Curves tool (SUBSET-026 ch.3.13) — golden values
from the v5.1 workbook port (regression guard for the package split)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from era_bct import Scenario, run, V_lim, AD_UIC, t_bbu, S41_speed_inacc, ceiling_speed_margin

# Golden values from the monolithic era_bct.py (run with the default scenario)
LAMBDA_SUMMARY = {
    "V_linespeed": 160,
    "perturbation": 4135.35815370764,
    "indication": 4135.35815370764,
    "permitted": 3356.833709263195,
    "warning": 3267.944820374306,
    "sbi": 3179.055931485417,
    "ebi": 2428.122598152084,
}
GAMMA_SUMMARY = {
    "perturbation": 3169.5320549286416,
    "permitted": 2769.5320549286416,
    "warning": 2319.133862229663,
    "sbi": 2230.2449733407743,
    "ebi": 2016.9116400074408,
}


class TestBrakeModel(unittest.TestCase):
    def test_v_lim(self):
        self.assertAlmostEqual(V_lim(100), 16.85 * 100 ** 0.428, places=12)

    def test_ad_uic_below_vlim(self):
        self.assertAlmostEqual(AD_UIC(90, 0), 0.0075 * 90 + 0.076, places=12)

    def test_t_bbu_passenger(self):
        self.assertAlmostEqual(t_bbu(400, "Passenger in P"), 2.3 + 0.17 * 16, places=12)

    def test_s41_speed_inacc(self):
        self.assertEqual(S41_speed_inacc(0), 2.0)
        self.assertEqual(S41_speed_inacc(500), 12.0)
        self.assertAlmostEqual(S41_speed_inacc(30 + 47), 3.0, places=12)

    def test_ceiling_margin(self):
        self.assertEqual(ceiling_speed_margin(50, 110, 210, 7.5, 15.0), 7.5)
        self.assertEqual(ceiling_speed_margin(300, 110, 210, 7.5, 15.0), 15.0)


class TestGoldenRuns(unittest.TestCase):
    def test_lambda_default(self):
        res = run(Scenario.default())
        self.assertIsNone(res.aborted)
        for k, v in LAMBDA_SUMMARY.items():
            self.assertAlmostEqual(res.summary[k], v, places=9, msg=k)

    def test_gamma_default(self):
        sc = Scenario.default()
        sc.train.train_type = "gamma"
        res = run(sc)
        self.assertIsNone(res.aborted)
        for k, v in GAMMA_SUMMARY.items():
            self.assertAlmostEqual(res.summary[k], v, places=9, msg=k)

    def test_scenario_json_roundtrip(self):
        sc = Scenario.default()
        d = sc.to_dict()
        sc2 = Scenario.from_dict(d)
        self.assertEqual(sc2.train.brake_position, sc.train.brake_position)
        self.assertEqual(sc2.gamma_brake.ebcl, sc.gamma_brake.ebcl)
        self.assertEqual(sc2.gamma_brake.kdry_by_ebcl[4]["comb1"][0], 0.75)


if __name__ == "__main__":
    unittest.main()
