"""Behavioral regressions found while auditing the complete simulator."""

from collections import deque
from itertools import combinations
import unittest

from lormesh import MeshNetwork, MeshNode
from lormesh.demo_system import DemoSystem
from lormesh.gps import parse_nmea_position


class RoutingRegressionTests(unittest.TestCase):
    def test_isolated_sos_reports_failure(self):
        system = DemoSystem()
        for node in "BCD":
            system.set_node_online(node, False)
        result = system.send_sos("A")
        self.assertFalse(result["delivered"])
        self.assertEqual(result["recipients"], [])
        self.assertFalse(any(e["title"] == "แจ้งเตือนปลายทาง" for e in system.state()["events"]))

    def test_routing_matches_independent_bfs_for_all_four_node_graphs(self):
        edges = list(combinations("ABCD", 2))
        for mask in range(1 << len(edges)):
            for offline_mask in range(8):
                graph = {node: set() for node in "ABCD"}
                network = MeshNetwork()
                for index, node in enumerate("ABCD"):
                    online = node == "A" or not offline_mask & (1 << (index - 1))
                    network.add_node(MeshNode(node, online=online))
                for index, (a, b) in enumerate(edges):
                    if mask & (1 << index):
                        graph[a].add(b)
                        graph[b].add(a)
                        network.connect(a, b)
                distance = {"A": 0}
                queue = deque(["A"])
                while queue:
                    for neighbor in graph[queue.popleft()]:
                        if network.nodes[neighbor].online and neighbor not in distance:
                            distance[neighbor] = min(distance[n] for n in graph[neighbor] if n in distance) + 1
                            queue.append(neighbor)
                network.send_text("A", "D", "Learn")
                for ttl in (1, 2, 3):
                    with self.subTest(graph=mask, offline=offline_mask, ttl=ttl):
                        result = network.send_text("A", "D", "Check", ttl=ttl)
                        self.assertEqual(result.delivered, distance.get("D", 99) <= ttl)
                        if result.path:
                            self.assertLessEqual(len(result.path) - 1, ttl)
                        sos = network.send_sos("A", ttl=ttl)
                        recipients = {e.node_id for e in network.events if e.message_id == sos.packet.message_id and e.kind == "delivered"}
                        expected = {n for n, d in distance.items() if 0 < d <= ttl}
                        self.assertEqual(recipients, expected)
                        self.assertEqual(sos.delivered, bool(expected))

    def test_invalid_ttl_is_rejected(self):
        network = MeshNetwork()
        network.add_node(MeshNode("A"))
        network.add_node(MeshNode("B"))
        network.connect("A", "B")
        for ttl in (0, -1, 1.5, True, "2", float("nan")):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                network.send_text("A", "B", "Check", ttl=ttl)

    def test_new_shorter_link_invalidates_learned_longer_route(self):
        network = MeshNetwork()
        for node in "ABC":
            network.add_node(MeshNode(node))
        network.connect("A", "B")
        network.connect("B", "C")
        network.send_text("A", "C", "Learn")
        network.connect("A", "C")
        result = network.send_text("A", "C", "Direct", ttl=1)
        self.assertTrue(result.delivered)
        self.assertEqual(result.path, ("A", "C"))

    def test_message_length_matches_dashboard_limit(self):
        system = DemoSystem()
        with self.assertRaises(ValueError):
            system.send_message("A", "C", "x" * 201)
        self.assertTrue(system.send_message("A", "C", "x" * 200)["delivered"])
        self.assertTrue(system.send_message("A", "C", "😀" * 100)["delivered"])
        with self.assertRaises(ValueError):
            system.send_message("A", "C", "😀" * 101)

    def test_long_running_demo_keeps_bounded_history(self):
        system = DemoSystem()
        for _ in range(600):
            self.assertEqual(system.send_message("A", "C", "Check")["recipients"], ["C"])
        self.assertLessEqual(len(system.messages), 30)
        self.assertLessEqual(len(system.events), 40)
        self.assertLessEqual(len(system.network.events), 1000)

    def test_invalid_range_does_not_erase_existing_topology(self):
        system = DemoSystem()
        links = system.network.links()
        for value in (0, -1, float("inf"), float("nan"), True, "850"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                system.network.rebuild_links_within_range(value)
            self.assertEqual(system.network.links(), links)


class GpsRegressionTests(unittest.TestCase):
    def test_malformed_coordinates_and_fix_flags_are_rejected(self):
        sentences = [
            "$GPRMC,123519,A,-1345.3600,N,10030.0600,E",
            "$GPRMC,123519,A,nan,N,10030.0600,E",
            "$GPRMC,123519,A,inf,N,10030.0600,E",
            "$GPRMC,123519,A,1e3,N,10030.0600,E",
            "$GPRMC,123519,X,1345.3600,N,10030.0600,E",
            "$GPGGA,123519,1345.3600,N,10030.0600,E,-1",
            "$GPGGA,123519,1345.3600,N,10030.0600,E,99",
            "$RMC,123519,A,1345.3600,N,10030.0600,E",
        ]
        for sentence in sentences:
            with self.subTest(sentence=sentence), self.assertRaises(ValueError):
                parse_nmea_position(sentence)

    def test_valid_checksum_and_trailing_junk(self):
        sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
        self.assertAlmostEqual(parse_nmea_position(sentence).latitude, 48.1173)
        with self.assertRaises(ValueError):
            parse_nmea_position(sentence + "junk")

    def test_no_fix_preserves_last_position_and_exposes_status(self):
        system = DemoSystem()
        before = system.network.nodes["A"].position
        state = system.set_gps_from_nmea("A", "$GPRMC,123519,V,,,,,,,230394,,,N")
        self.assertEqual(system.network.nodes["A"].position, before)
        self.assertIn("ไม่มี fix", state["nodes"][0]["gps_source"])
        result = system.send_sos("A")
        self.assertTrue(result["delivered"])
        self.assertIn("ไม่มี fix", result["gps_source"])
        self.assertTrue(any("ยังไม่มี GPS fix" in e["detail"] for e in system.state()["events"]))

    def test_moving_node_out_of_range_invalidates_learned_route(self):
        system = DemoSystem()
        system.send_message("A", "C", "Learn")
        system.set_gps_from_nmea("A", "$GPRMC,123519,A,1400.0000,N,10100.0000,E")
        self.assertFalse(system.send_message("A", "C", "Check")["delivered"])
        self.assertFalse(system.send_sos("A")["delivered"])


if __name__ == "__main__":
    unittest.main()
