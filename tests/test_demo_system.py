import unittest

from lormesh.demo_system import DemoSystem


class DemoSystemTests(unittest.TestCase):
    def test_primary_path_matches_project_flow(self) -> None:
        system = DemoSystem()

        result = system.send_message("A", "C", "Need help")

        self.assertTrue(result["delivered"])
        self.assertEqual(result["path"], ["A", "B", "C"])
        self.assertEqual(result["recipients"], ["C"])
        self.assertIsNotNone(result["latitude"])

    def test_backup_relay_routes_around_failed_node(self) -> None:
        system = DemoSystem()
        system.set_node_online("B", False)

        result = system.send_message("A", "C", "Need help")

        self.assertTrue(result["delivered"])
        self.assertEqual(result["path"], ["A", "D", "C"])

    def test_sos_broadcast_reaches_online_nodes_and_attaches_gps(self) -> None:
        system = DemoSystem()

        result = system.send_sos("A")
        state = system.state()

        self.assertTrue(result["delivered"])
        self.assertEqual(set(result["recipients"]), {"B", "C", "D"})
        self.assertEqual(result["text"], "SOS")
        self.assertEqual((result["latitude"], result["longitude"]), (13.756, 100.501))
        self.assertTrue(any(event["title"] == "แจ้งเตือนปลายทาง" for event in state["events"]))

    def test_connection_mode_and_nmea_gps_are_exposed_to_dashboard(self) -> None:
        system = DemoSystem()

        system.set_connection_mode("ble")
        state = system.set_gps_from_nmea(
            "A", "$GPRMC,123519,A,1345.3600,N,10030.0600,E,0.0,0.0,230394,,,A"
        )

        self.assertEqual(state["connection_mode"], "ble")
        node_a = next(node for node in state["nodes"] if node["id"] == "A")
        self.assertAlmostEqual(node_a["latitude"], 13.756)
        self.assertAlmostEqual(node_a["longitude"], 100.501)

    def test_reset_restores_nodes_and_clears_history(self) -> None:
        system = DemoSystem()
        system.send_message("A", "C", "Need help")
        system.set_node_online("B", False)

        state = system.reset()

        self.assertTrue(all(node["online"] for node in state["nodes"]))
        self.assertEqual(state["messages"], [])
        self.assertEqual(state["links"], [
            {"from": "A", "to": "B"},
            {"from": "A", "to": "D"},
            {"from": "B", "to": "C"},
            {"from": "B", "to": "D"},
            {"from": "C", "to": "D"},
        ])


if __name__ == "__main__":
    unittest.main()
