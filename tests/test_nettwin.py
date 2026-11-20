from ipaddress import IPv4Address
import unittest

from fastapi.testclient import TestClient

from nettwin.engine import Forwarding, Snapshot, compare
from nettwin.examples import scenario
from nettwin.web import app


def demo(name, drill=False):
    config = scenario(name)
    return compare(config["baseline"], config["candidate"], config["policies"], drill)


class NetTwinTests(unittest.TestCase):
    def test_withdrawal_removes_both_equal_cost_paths(self):
        report = demo("withdraw", drill=True)
        self.assertFalse(report["passed"])
        route, isolation, lab = report["policies"]
        self.assertEqual(route["before"]["path_count"], 2)
        self.assertEqual(route["after"]["path_count"], 0)
        self.assertEqual(route["outcome"], "regression")
        self.assertTrue(isolation["after"]["pass"])
        self.assertTrue(lab["after"]["pass"])
        self.assertTrue(all(route["name"] not in row["violations"] for row in report["failures"]))

    def test_higher_cost_removes_ecmp_and_risk_surfaces_under_outage(self):
        report = demo("cost", drill=True)
        route = report["policies"][0]
        self.assertTrue(report["passed"])
        self.assertEqual(route["after"]["cost"], 20)
        self.assertEqual(route["after"]["paths"], [["Access", "West", "Core"]])
        self.assertEqual(route["outcome"], "changed")
        failures = {frozenset(row["link"]): row["violations"] for row in report["failures"]}
        self.assertIn(route["name"], failures[frozenset(("Access", "West"))])
        self.assertNotIn(route["name"], failures[frozenset(("Access", "East"))])

    def test_isolation_violation(self):
        report = demo("isolation")
        policy = report["policies"][1]
        self.assertEqual(policy["outcome"], "regression")
        self.assertEqual(policy["after"]["path_count"], 2)

    def test_every_equal_cost_path_must_pass_waypoint(self):
        config = scenario("unchanged")
        config["policies"][0]["via"] = "East"
        report = compare(config["baseline"], config["candidate"], config["policies"])
        route = report["policies"][0]["after"]
        self.assertEqual((route["paths_via"], route["path_count"]), (1, 2))
        self.assertFalse(route["pass"])

    def test_longest_reachable_prefix(self):
        config = scenario()["baseline"]
        config["prefixes"]["Core"] = ["10.0.0.0/8"]
        config["prefixes"]["Lab"] = ["10.20.0.0/24"]
        target = IPv4Address("10.20.0.8")
        split = Forwarding(Snapshot.parse(config))
        self.assertEqual(split.routes("Access", target)["prefix"], "10.0.0.0/8")
        config["links"].append({"a": "Access", "b": "Guest", "cost": 99})
        connected = Forwarding(Snapshot.parse(config))
        self.assertEqual(connected.routes("Access", target)["prefix"], "10.20.0.0/24")

    def test_api_serves_workshop_and_rejects_invalid_snapshots(self):
        with TestClient(app) as client:
            self.assertIn("Before the switch.", client.get("/").text)
            self.assertEqual(client.get("/static/app.js").status_code, 200)
            config = client.get("/api/scenarios/cost").json()
            self.assertTrue(client.post("/api/compare", json=config).json()["passed"])
            config["policies"][0]["source"] = []
            self.assertEqual(client.post("/api/compare", json=config).status_code, 422)
            self.assertEqual(client.post("/api/compare", content=" " * 65_537).status_code, 413)
