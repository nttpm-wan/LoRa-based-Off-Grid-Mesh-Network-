"""Deterministic flooding and duplicate suppression for a mesh network.

This module models radio links as graph edges. It is intended to test routing
logic before connecting real LoRa hardware; it does not control an SX1276.
"""

from collections import defaultdict, deque
from itertools import combinations
from math import asin, cos, isfinite, radians, sin, sqrt

from .models import MeshNode, NetworkEvent, Packet, Position, SendResult


class MeshNetwork:
    """A graph-based simulator for the LORMesh packet-forwarding logic."""

    def __init__(self) -> None:
        self.nodes: dict[str, MeshNode] = {}
        self._links: dict[str, set[str]] = defaultdict(set)
        self.events: list[NetworkEvent] = []
        self._next_message_number = 1
        self._route_cache: dict[tuple[str, str], tuple[str, ...]] = {}

    def add_node(self, node: MeshNode) -> None:
        if not node.node_id.strip():
            raise ValueError("node_id cannot be empty")
        if node.node_id in self.nodes:
            raise ValueError(f"node already exists: {node.node_id}")
        self.nodes[node.node_id] = node

    def connect(self, first: str, second: str) -> None:
        """Add a bidirectional radio link between two known nodes."""
        self._require_node(first)
        self._require_node(second)
        if first == second:
            raise ValueError("a node cannot be linked to itself")
        if second not in self._links[first]:
            # A newly available link may provide a shorter path for a low TTL.
            self._route_cache.clear()
        self._links[first].add(second)
        self._links[second].add(first)

    def connect_within_range(self, max_range_m: float) -> tuple[tuple[str, str], ...]:
        """Connect positioned nodes whose great-circle distance is in range.

        This is a simple coverage model, not a radio propagation model. Nodes
        without GPS positions are skipped, and existing links are preserved.
        """
        if not isinstance(max_range_m, (int, float)) or isinstance(max_range_m, bool) or not isfinite(max_range_m) or max_range_m <= 0:
            raise ValueError("max_range_m must be greater than zero")

        new_links: list[tuple[str, str]] = []
        for first, second in combinations(self.nodes, 2):
            first_position = self.nodes[first].position
            second_position = self.nodes[second].position
            if first_position is None or second_position is None:
                continue
            if self._distance_m(first_position, second_position) <= max_range_m:
                if second not in self._links[first]:
                    self.connect(first, second)
                    new_links.append((first, second))
        return tuple(new_links)

    def rebuild_links_within_range(self, max_range_m: float) -> tuple[tuple[str, str], ...]:
        """Recalculate the simulated radio graph after a GPS position update."""
        if not isinstance(max_range_m, (int, float)) or isinstance(max_range_m, bool) or not isfinite(max_range_m) or max_range_m <= 0:
            raise ValueError("max_range_m must be greater than zero")
        self._links.clear()
        self._route_cache.clear()
        return self.connect_within_range(max_range_m)

    def links(self) -> tuple[tuple[str, str], ...]:
        """Return each configured bidirectional link once."""
        return tuple(
            sorted(
                (first, second)
                for first, neighbors in self._links.items()
                for second in neighbors
                if first < second
            )
        )

    @staticmethod
    def _distance_m(first: Position, second: Position) -> float:
        """Return the great-circle distance between two GPS coordinates."""
        earth_radius_m = 6_371_000
        lat1, lat2 = radians(first.latitude), radians(second.latitude)
        delta_lat = lat2 - lat1
        delta_lon = radians(second.longitude - first.longitude)
        haversine = (
            sin(delta_lat / 2) ** 2
            + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
        )
        return 2 * earth_radius_m * asin(sqrt(min(1.0, max(0.0, haversine))))

    def send_text(
        self,
        source: str,
        destination: str,
        text: str,
        *,
        ttl: int = 8,
    ) -> SendResult:
        """Send a normal message, optionally limiting the number of hops."""
        self._require_node(source)
        if destination != "ALL":
            self._require_node(destination)
            if source == destination:
                raise ValueError("source and destination must be different nodes")

        key = (source, destination)
        cached_route = self._route_cache.get(key)
        if cached_route and self._route_is_usable(cached_route, source, destination):
            return self._send(
                source,
                destination,
                text,
                ttl=ttl,
                position=self.nodes[source].position,
                route=cached_route,
            )
        if cached_route:
            self._route_cache.pop(key, None)

        result = self._send(
            source,
            destination,
            text,
            ttl=ttl,
            position=self.nodes[source].position,
        )
        if result.delivered and result.path:
            self._route_cache[key] = result.path
        return result

    def send_sos(self, source: str, *, ttl: int = 8) -> SendResult:
        """Send an SOS packet and attach the source node's latest GPS fix."""
        self._require_node(source)
        return self._send(
            source,
            "ALL",
            "SOS",
            ttl=ttl,
            position=self.nodes[source].position,
            is_sos=True,
        )

    def _send(
        self,
        source: str,
        destination: str,
        text: str,
        *,
        ttl: int,
        position: Position | None = None,
        is_sos: bool = False,
        route: tuple[str, ...] | None = None,
    ) -> SendResult:
        self._require_node(source)
        if destination != "ALL":
            self._require_node(destination)
            if destination == source:
                raise ValueError("source and destination must be different nodes")
        if not self.nodes[source].online:
            raise ValueError(f"source node is offline: {source}")
        if type(ttl) is not int or ttl < 1:
            raise ValueError("ttl must be a positive integer")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("message text cannot be empty")
        # Match the browser's maxlength, including its treatment of emoji.
        if len(text.encode("utf-16-le")) // 2 > 200:
            raise ValueError("message text must not exceed 200 characters")

        message_id = f"{source}-{self._next_message_number:04d}"
        self._next_message_number += 1
        packet = Packet(
            message_id=message_id,
            source=source,
            destination=destination,
            text=text,
            ttl=ttl,
            position=position,
            is_sos=is_sos,
        )

        # Queue entries represent a frame arriving at a node. The source marks
        # its own ID as seen first, so a cycle cannot cause it to relay itself.
        queue: deque[tuple[str, tuple[str, ...]]] = deque()
        seen = {source}
        first_path: dict[str, tuple[str, ...]] = {source: (source,)}
        transmissions = 0
        duplicate_drops = 0
        ttl_drops = 0
        self.events.append(NetworkEvent("created", source, message_id, text))

        if route is not None:
            return self._send_on_known_route(packet, route)

        for neighbor in sorted(self._links[source]):
            transmissions += 1
            queue.append((neighbor, (source, neighbor)))

        while queue:
            node_id, path = queue.popleft()
            node = self.nodes[node_id]
            if not node.online:
                self.events.append(
                    NetworkEvent("offline_drop", node_id, message_id, "node is offline")
                )
                continue
            if node_id in seen:
                duplicate_drops += 1
                self.events.append(
                    NetworkEvent("duplicate_drop", node_id, message_id, "already seen")
                )
                continue

            seen.add(node_id)
            first_path[node_id] = path
            self.events.append(NetworkEvent("received", node_id, message_id, text))

            if destination == "ALL" or node_id == destination:
                self.events.append(
                    NetworkEvent("delivered", node_id, message_id, text)
                )

            hops_used = len(path) - 1
            if hops_used >= ttl:
                ttl_drops += 1
                self.events.append(
                    NetworkEvent("ttl_drop", node_id, message_id, "hop limit reached")
                )
                continue

            for neighbor in sorted(self._links[node_id]):
                transmissions += 1
                queue.append((neighbor, path + (neighbor,)))

        delivered = len(first_path) > 1 if destination == "ALL" else destination in first_path
        path = first_path.get(destination) if destination != "ALL" else None
        self.events.append(
            NetworkEvent(
                "complete",
                source,
                message_id,
                "delivered" if delivered else "destination not reached",
            )
        )
        return SendResult(
            packet=packet,
            delivered=delivered,
            path=path,
            transmissions=transmissions,
            duplicate_drops=duplicate_drops,
            ttl_drops=ttl_drops,
            routing_mode="broadcast_flood" if destination == "ALL" else "flood_discovery",
        )

    def _send_on_known_route(self, packet: Packet, route: tuple[str, ...]) -> SendResult:
        """Forward directly on a learned path, as a small AODV-like cache."""
        transmissions = 0
        ttl_drops = 0
        seen = {packet.source}
        traversed = [packet.source]

        for hops_used, node_id in enumerate(route[1:], start=1):
            transmissions += 1
            if not self.nodes[node_id].online:
                self.events.append(
                    NetworkEvent("offline_drop", node_id, packet.message_id, "node is offline")
                )
                break
            if node_id in seen:
                self.events.append(
                    NetworkEvent("duplicate_drop", node_id, packet.message_id, "already seen")
                )
                break
            seen.add(node_id)
            traversed.append(node_id)
            self.events.append(NetworkEvent("received", node_id, packet.message_id, packet.text))
            if node_id == packet.destination:
                self.events.append(
                    NetworkEvent("delivered", node_id, packet.message_id, packet.text)
                )
                self.events.append(
                    NetworkEvent("complete", packet.source, packet.message_id, "delivered")
                )
                return SendResult(
                    packet=packet,
                    delivered=True,
                    path=tuple(traversed),
                    transmissions=transmissions,
                    duplicate_drops=0,
                    ttl_drops=0,
                    routing_mode="cached_route",
                )
            if hops_used >= packet.ttl:
                ttl_drops += 1
                self.events.append(
                    NetworkEvent("ttl_drop", node_id, packet.message_id, "hop limit reached")
                )
                break

        self.events.append(
            NetworkEvent("complete", packet.source, packet.message_id, "route failed")
        )
        return SendResult(
            packet=packet,
            delivered=False,
            path=None,
            transmissions=transmissions,
            duplicate_drops=0,
            ttl_drops=ttl_drops,
            routing_mode="cached_route",
        )

    def _route_is_usable(
        self, route: tuple[str, ...], source: str, destination: str
    ) -> bool:
        if not route or route[0] != source or route[-1] != destination:
            return False
        for first, second in zip(route, route[1:]):
            if not self.nodes[first].online or not self.nodes[second].online:
                return False
            if second not in self._links[first]:
                return False
        return True

    def _require_node(self, node_id: str) -> None:
        if not isinstance(node_id, str) or node_id not in self.nodes:
            raise ValueError(f"unknown node: {node_id}")
