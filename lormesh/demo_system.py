"""Application state for the LORMesh browser demonstration.

Users send text or SOS, nodes forward packets, and GPS/alerts appear on a local
web dashboard. Hardware behavior is represented in software for this demo.
"""

from datetime import datetime
from threading import RLock

from .models import MeshNode, Position, SendResult
from .network import MeshNetwork
from .gps import parse_nmea_position


class DemoSystem:
    """A repeatable four-node scenario for the browser UI and its tests."""

    RADIO_RANGE_M = 850

    def __init__(self) -> None:
        self._lock = RLock()
        self.connection_mode = "wifi"
        self._build_network()
        self.messages: list[dict] = []
        self.events: list[dict] = []

    def _build_network(self) -> None:
        self.network = MeshNetwork()
        self._gps_sources = {node_id: "GPS จำลอง" for node_id in "ABCD"}
        self.network.add_node(MeshNode("A", Position(13.7560, 100.5010)))
        self.network.add_node(MeshNode("B", Position(13.7600, 100.5040)))
        self.network.add_node(MeshNode("C", Position(13.7640, 100.5070)))
        # D is a backup relay: traffic can reach C via D when B is offline.
        self.network.add_node(MeshNode("D", Position(13.7600, 100.5060)))
        self.network.connect_within_range(self.RADIO_RANGE_M)

    def state(self) -> dict:
        with self._lock:
            nodes = []
            for node_id, node in self.network.nodes.items():
                position = node.position
                role = {"A": "ผู้ส่ง", "B": "รีเลย์หลัก", "C": "ผู้รับ", "D": "รีเลย์สำรอง"}[node_id]
                nodes.append(
                    {
                        "id": node_id,
                        "role": role,
                        "online": node.online,
                        "ap_ssid": f"LORMESH-NODE{node_id}",
                        "latitude": position.latitude if position else None,
                        "longitude": position.longitude if position else None,
                        "gps_source": self._gps_sources[node_id],
                    }
                )
            links = [
                {"from": first, "to": second}
                for first, second in self.network.links()
            ]
            return {
                "mode": "simulation",
                "connection_mode": self.connection_mode,
                "radio_range_m": self.RADIO_RANGE_M,
                "nodes": nodes,
                "links": links,
                "messages": list(reversed(self.messages[-30:])),
                "events": list(reversed(self.events[-40:])),
                "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }

    def set_connection_mode(self, mode: str) -> dict:
        with self._lock:
            if mode not in {"wifi", "ble"}:
                raise ValueError("connection mode must be 'wifi' or 'ble'")
            self.connection_mode = mode
            label = "Wi-Fi AP / Captive Portal" if mode == "wifi" else "BLE fallback"
            self._add_event("ช่องทางผู้ใช้", f"เปลี่ยนเป็น {label} (จำลอง)")
            return self.state()

    def set_gps_from_nmea(self, node_id: str, sentence: str) -> dict:
        with self._lock:
            if node_id not in self.network.nodes:
                raise ValueError(f"unknown node: {node_id}")
            position = parse_nmea_position(sentence)
            if position is None:
                self._gps_sources[node_id] = "NMEA ไม่มี fix · พิกัดล่าสุด"
                self._add_event("GPS parser", f"Node {node_id}: NMEA ระบุว่ายังไม่มี GPS fix", node_id=node_id)
                return self.state()
            self.network.nodes[node_id].position = position
            self._gps_sources[node_id] = "NMEA ที่ป้อน"
            self.network.rebuild_links_within_range(self.RADIO_RANGE_M)
            self._add_event(
                "GPS parser",
                f"Node {node_id}: NMEA → {position.latitude:.5f}, {position.longitude:.5f}",
                node_id=node_id,
            )
            return self.state()

    def send_message(self, source: str, destination: str, text: str) -> dict:
        with self._lock:
            result = self.network.send_text(source, destination, text, ttl=8)
            return self._record(result, kind="message")

    def send_sos(self, source: str) -> dict:
        with self._lock:
            result = self.network.send_sos(source, ttl=8)
            return self._record(result, kind="sos")

    def set_node_online(self, node_id: str, online: bool) -> dict:
        with self._lock:
            if node_id not in self.network.nodes:
                raise ValueError(f"unknown node: {node_id}")
            node = self.network.nodes[node_id]
            node.online = online
            self._add_event(
                "สถานะโหนด",
                f"Node {node_id} {'ออนไลน์' if online else 'ออฟไลน์'}",
                node_id=node_id,
            )
            return self.state()

    def reset(self) -> dict:
        with self._lock:
            self._build_network()
            self.connection_mode = "wifi"
            self.messages.clear()
            self.events.clear()
            self._add_event("ระบบพร้อม", "เริ่มสถานการณ์จำลองใหม่")
            return self.state()

    def _record(self, result: SendResult, *, kind: str) -> dict:
        packet = result.packet
        destinations = [
            event.node_id
            for event in self.network.events
            if event.message_id == packet.message_id and event.kind == "delivered"
        ]
        position = packet.position
        item = {
            "id": packet.message_id,
            "kind": kind,
            "source": packet.source,
            "destination": packet.destination,
            "text": packet.text,
            "latitude": position.latitude if position else None,
            "longitude": position.longitude if position else None,
            "gps_source": self._gps_sources[packet.source],
            "path": list(result.path) if result.path else None,
            "delivered": result.delivered,
            "recipients": destinations,
            "transmissions": result.transmissions,
            "duplicate_drops": result.duplicate_drops,
            "routing_mode": result.routing_mode,
            "time": datetime.now().astimezone().strftime("%H:%M:%S"),
        }
        self.messages.append(item)
        del self.messages[:-30]
        path_text = " → ".join(item["path"] or [packet.source])
        routing_label = {
            "flood_discovery": "Flood discovery",
            "cached_route": "AODV-like route cache",
            "broadcast_flood": "Flood broadcast",
        }.get(result.routing_mode, result.routing_mode)
        coordinate_text = self._coordinate_text(position)
        if "ไม่มี fix" in item["gps_source"]:
            coordinate_text += " (พิกัดล่าสุด ยังไม่มี GPS fix)"
        if kind == "sos":
            outcome = f"รับ SOS ที่ {', '.join(destinations)}" if result.delivered else "SOS ส่งไม่ถึงโหนดใด"
            details = f"{outcome} · พิกัด {coordinate_text} · {routing_label}"
            self._add_event("SOS", details, node_id=destinations[-1] if destinations else None)
            for recipient in destinations:
                self._add_event(
                    "แจ้งเตือนปลายทาง",
                    f"Node {recipient}: Buzzer ดัง · LED กะพริบ",
                    node_id=recipient,
                )
        elif result.delivered:
            details = f"Node {packet.destination} รับข้อความ · เส้นทาง {path_text} · {routing_label} · พิกัด {coordinate_text}"
            self._add_event("ข้อความถึงปลายทาง", details, node_id=packet.destination)
        else:
            self._add_event("ส่งไม่สำเร็จ", f"ยังไปไม่ถึง Node {packet.destination}", node_id=packet.source)
        # Retain recent diagnostics without growing memory on every poll/send.
        del self.network.events[:-1000]
        return item

    def _add_event(self, title: str, detail: str, *, node_id: str | None = None) -> None:
        self.events.append(
            {
                "title": title,
                "detail": detail,
                "node_id": node_id,
                "time": datetime.now().astimezone().strftime("%H:%M:%S"),
            }
        )
        del self.events[:-40]

    @staticmethod
    def _coordinate_text(position: Position | None) -> str:
        if position is None:
            return "ไม่มี GPS fix"
        return f"{position.latitude:.4f}, {position.longitude:.4f}"
