"""Run a small three-node demonstration: A -> B -> C."""

from .models import MeshNode, Position
from .network import MeshNetwork


def main() -> None:
    network = MeshNetwork()
    network.add_node(MeshNode("A", Position(13.7563, 100.5018)))
    network.add_node(MeshNode("B", Position(13.7600, 100.5100)))
    network.add_node(MeshNode("C", Position(13.7650, 100.5200)))
    network.connect("A", "B")
    network.connect("B", "C")

    result = network.send_text("A", "C", "Need medical help", ttl=4)
    print(f"Message ID : {result.packet.message_id}")
    print(f"Delivered  : {result.delivered}")
    print(f"Route      : {' -> '.join(result.path or ())}")
    print(f"Transmits  : {result.transmissions}")

    sos = network.send_sos("A")
    print(f"SOS        : {sos.packet.text}")
    print(f"GPS        : {sos.packet.position}")
    recipients = [
        event.node_id
        for event in network.events
        if event.message_id == sos.packet.message_id and event.kind == "delivered"
    ]
    print(f"Reached    : {', '.join(recipients)}")


if __name__ == "__main__":
    main()
