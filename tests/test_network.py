import unittest

from lormesh import MeshNetwork, MeshNode, Position


def make_line_network() -> MeshNetwork:
    network = MeshNetwork()
    for node_id in ("A", "B", "C"):
        network.add_node(MeshNode(node_id))
    network.connect("A", "B")
    network.connect("B", "C")
    return network


class MeshNetworkTests(unittest.TestCase):
    def test_nodes_in_range_form_a_multihop_path(self) -> None:
        network = MeshNetwork()
        network.add_node(MeshNode("A", Position(0, 0)))
        network.add_node(MeshNode("B", Position(0, 0.004)))
        network.add_node(MeshNode("C", Position(0, 0.008)))

        links = network.connect_within_range(500)
        result = network.send_text("A", "C", "Help", ttl=2)

        self.assertEqual(links, (("A", "B"), ("B", "C")))
        self.assertTrue(result.delivered)
        self.assertEqual(result.path, ("A", "B", "C"))

    def test_range_model_skips_nodes_without_gps(self) -> None:
        network = MeshNetwork()
        network.add_node(MeshNode("A", Position(0, 0)))
        network.add_node(MeshNode("B"))

        self.assertEqual(network.connect_within_range(1000), ())

    def test_message_reaches_destination_through_relay(self) -> None:
        network = make_line_network()

        result = network.send_text("A", "C", "Help", ttl=2)

        self.assertTrue(result.delivered)
        self.assertEqual(result.path, ("A", "B", "C"))
        self.assertEqual(result.packet.text, "Help")

    def test_ttl_prevents_delivery_beyond_hop_limit(self) -> None:
        network = make_line_network()

        result = network.send_text("A", "C", "Help", ttl=1)

        self.assertFalse(result.delivered)
        self.assertIsNone(result.path)
        self.assertGreaterEqual(result.ttl_drops, 1)

    def test_learned_route_forwards_directly_on_next_message(self) -> None:
        network = make_line_network()

        first = network.send_text("A", "C", "First")
        second = network.send_text("A", "C", "Second")

        self.assertEqual(first.routing_mode, "flood_discovery")
        self.assertEqual(second.routing_mode, "cached_route")
        self.assertEqual(second.path, ("A", "B", "C"))
        self.assertEqual(second.transmissions, 2)

    def test_failed_learned_route_falls_back_to_flood_discovery(self) -> None:
        network = MeshNetwork()
        for node_id in ("A", "B", "C", "D"):
            network.add_node(MeshNode(node_id))
        for first, second in (("A", "B"), ("B", "C"), ("A", "D"), ("D", "C")):
            network.connect(first, second)

        network.send_text("A", "C", "First")
        network.nodes["B"].online = False
        result = network.send_text("A", "C", "Second")

        self.assertTrue(result.delivered)
        self.assertEqual(result.routing_mode, "flood_discovery")
        self.assertEqual(result.path, ("A", "D", "C"))

    def test_cycle_suppresses_duplicate_packets(self) -> None:
        network = MeshNetwork()
        for node_id in ("A", "B", "C", "D"):
            network.add_node(MeshNode(node_id))
        for first, second in (("A", "B"), ("B", "C"), ("C", "A"),
                              ("B", "D"), ("C", "D")):
            network.connect(first, second)

        result = network.send_text("A", "D", "Check-in", ttl=6)

        self.assertTrue(result.delivered)
        self.assertGreater(result.duplicate_drops, 0)
        delivered_events = [
            event for event in network.events
            if event.message_id == result.packet.message_id
            and event.kind == "delivered"
            and event.node_id == "D"
        ]
        self.assertEqual(len(delivered_events), 1)

    def test_offline_relay_blocks_path(self) -> None:
        network = make_line_network()
        network.nodes["B"].online = False

        result = network.send_text("A", "C", "Help")

        self.assertFalse(result.delivered)

    def test_sos_carries_source_position_and_broadcasts(self) -> None:
        network = MeshNetwork()
        network.add_node(MeshNode("A", Position(13.75, 100.5)))
        network.add_node(MeshNode("B"))
        network.add_node(MeshNode("C"))
        network.connect("A", "B")
        network.connect("B", "C")

        result = network.send_sos("A")

        self.assertTrue(result.packet.is_sos)
        self.assertEqual(result.packet.position, Position(13.75, 100.5))
        recipients = {
            event.node_id for event in network.events
            if event.message_id == result.packet.message_id
            and event.kind == "delivered"
        }
        self.assertEqual(recipients, {"B", "C"})

    def test_invalid_gps_coordinates_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Position(100, 0)


if __name__ == "__main__":
    unittest.main()
