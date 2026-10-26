"""Data models used by the LORMesh simulator."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """Latitude and longitude reported by a node's GPS receiver."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")


@dataclass
class MeshNode:
    """One simulated mesh device. Links are configured by MeshNetwork."""

    node_id: str
    position: Position | None = None
    online: bool = True


@dataclass(frozen=True)
class Packet:
    """An application message carried by the mesh."""

    message_id: str
    source: str
    destination: str
    text: str
    ttl: int
    position: Position | None = None
    is_sos: bool = False


@dataclass(frozen=True)
class SendResult:
    """Observable outcome and counters for one simulated transmission."""

    packet: Packet
    delivered: bool
    path: tuple[str, ...] | None
    transmissions: int
    duplicate_drops: int
    ttl_drops: int
    routing_mode: str = "flood_discovery"


@dataclass(frozen=True)
class NetworkEvent:
    """A compact event suitable for printing or later showing in a UI."""

    kind: str
    node_id: str
    message_id: str
    detail: str
