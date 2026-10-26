import unittest

from lormesh.gps import parse_nmea_position
from lormesh.models import Position


class NmeaParserTests(unittest.TestCase):
    def test_parses_rmc_coordinates_to_decimal_degrees(self) -> None:
        position = parse_nmea_position(
            "$GPRMC,123519,A,1345.3600,N,10030.0600,E,0.0,0.0,230394,,,A"
        )

        self.assertAlmostEqual(position.latitude, 13.756)
        self.assertAlmostEqual(position.longitude, 100.501)

    def test_parses_gga_southern_and_western_hemispheres(self) -> None:
        position = parse_nmea_position(
            "$GNGGA,123519,3450.0000,S,05822.5000,W,1,08,0.9,10.0,M,0.0,M,,"
        )

        self.assertAlmostEqual(position.latitude, -34.8333333, places=6)
        self.assertAlmostEqual(position.longitude, -58.375)

    def test_returns_none_when_sentence_has_no_fix(self) -> None:
        self.assertIsNone(
            parse_nmea_position("$GPRMC,123519,V,,,,,,,230394,,,N")
        )
        self.assertIsNone(
            parse_nmea_position("$GPGGA,123519,,,,,0,00,99.9,,,,,,")
        )

    def test_rejects_invalid_checksum(self) -> None:
        with self.assertRaisesRegex(ValueError, "checksum"):
            parse_nmea_position("$GPRMC,123519,A,1345.3600,N,10030.0600,E*00")

    def test_rejects_invalid_minute_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "minutes"):
            parse_nmea_position("$GPRMC,123519,A,1360.0000,N,10030.0000,E")


if __name__ == "__main__":
    unittest.main()
