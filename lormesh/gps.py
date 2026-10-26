"""Small parser for NMEA RMC and GGA sentences used by GPS modules."""

from re import fullmatch

from .models import Position


def parse_nmea_position(sentence: str) -> Position | None:
    """Parse an NMEA RMC/GGA sentence into decimal-degree coordinates.

    Returns ``None`` when a supported sentence reports that there is no GPS
    fix. If a checksum is present it is validated before coordinates are read.
    """
    if not isinstance(sentence, str):
        raise ValueError("NMEA sentence must be text")
    sentence = sentence.strip()
    if not sentence.startswith("$"):
        raise ValueError("NMEA sentence must start with '$'")
    if "*" in sentence:
        payload, checksum_text = sentence[1:].split("*", 1)
        if fullmatch(r"[0-9A-Fa-f]{2}", checksum_text) is None:
            raise ValueError("NMEA checksum must contain two hexadecimal digits")
        try:
            expected = int(checksum_text, 16)
        except ValueError as error:
            raise ValueError("NMEA checksum is not hexadecimal") from error
        actual = 0
        for character in payload:
            actual ^= ord(character)
        if actual != expected:
            raise ValueError("NMEA checksum does not match")
    else:
        payload = sentence[1:]

    fields = payload.split(",")
    if fullmatch(r"[A-Z]{2}(RMC|GGA)", fields[0]) is None:
        raise ValueError(f"unsupported NMEA sentence identifier: {fields[0]}")
    sentence_type = fields[0][-3:]
    if sentence_type == "RMC":
        if len(fields) < 7:
            raise ValueError("RMC sentence is missing coordinate fields")
        if fields[2] == "V":
            return None
        if fields[2] != "A":
            raise ValueError("RMC fix status must be A or V")
        latitude, north_south = fields[3], fields[4]
        longitude, east_west = fields[5], fields[6]
    elif sentence_type == "GGA":
        if len(fields) < 7:
            raise ValueError("GGA sentence is missing fix or coordinate fields")
        try:
            fix_quality = int(fields[6])
        except ValueError as error:
            raise ValueError("GGA fix quality must be an integer") from error
        if fix_quality == 0:
            return None
        if not 1 <= fix_quality <= 8:
            raise ValueError("GGA fix quality must be between 0 and 8")
        latitude, north_south = fields[2], fields[3]
        longitude, east_west = fields[4], fields[5]
    else:
        raise ValueError(f"unsupported NMEA sentence type: {sentence_type}")

    return Position(
        latitude=_to_decimal_degrees(latitude, north_south, is_latitude=True),
        longitude=_to_decimal_degrees(longitude, east_west, is_latitude=False),
    )


def _to_decimal_degrees(value: str, hemisphere: str, *, is_latitude: bool) -> float:
    if not value:
        raise ValueError("NMEA coordinate is empty")
    digits = 4 if is_latitude else 5
    if fullmatch(rf"[0-9]{{{digits}}}(?:\.[0-9]+)?", value) is None:
        raise ValueError(f"invalid NMEA coordinate: {value}")
    try:
        raw = float(value)
    except ValueError as error:
        raise ValueError(f"invalid NMEA coordinate: {value}") from error

    degrees = int(raw // 100)
    minutes = raw - degrees * 100
    if minutes >= 60 or minutes < 0:
        raise ValueError("NMEA minutes must be in the range [0, 60)")
    limit = 90 if is_latitude else 180
    if degrees > limit or (degrees == limit and minutes > 0):
        raise ValueError("NMEA coordinate exceeds the valid range")

    allowed = {"N", "S"} if is_latitude else {"E", "W"}
    if hemisphere not in allowed:
        raise ValueError(f"invalid hemisphere for coordinate: {hemisphere}")
    coordinate = degrees + minutes / 60
    if hemisphere in {"S", "W"}:
        coordinate = -coordinate
    return coordinate
