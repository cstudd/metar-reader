import pytest
import requests
from unittest.mock import patch, MagicMock

from app import (
    app as flask_app,
    c_to_f,
    decode_weather,
    degrees_to_compass,
    determine_flight_category,
    fetch_metar,
    knots_to_mph,
    parse_metar,
    relative_humidity,
)


# ── Helper functions ──────────────────────────────────────────────────────────

class TestDegreesToCompass:
    @pytest.mark.parametrize("deg, expected", [
        (0,   "N"),   (360, "N"),
        (45,  "NE"),  (90,  "E"),   (135, "SE"),
        (180, "S"),   (225, "SW"),  (270, "W"),  (315, "NW"),
        (22,  "NNE"), (337, "NNW"),
    ])
    def test_directions(self, deg, expected):
        assert degrees_to_compass(deg) == expected


class TestKnotsToMph:
    @pytest.mark.parametrize("kt, mph", [
        (0,   0),
        (10,  12),
        (25,  29),
        (100, 115),
    ])
    def test_conversion(self, kt, mph):
        assert knots_to_mph(kt) == mph


class TestCtoF:
    @pytest.mark.parametrize("c, f", [
        (0,    32),
        (100,  212),
        (-40,  -40),
        (20,   68),
        (-5,   23),
    ])
    def test_conversion(self, c, f):
        assert c_to_f(c) == f


class TestRelativeHumidity:
    def test_saturated(self):
        assert relative_humidity(20, 20) == 100

    def test_dry_air(self):
        assert relative_humidity(30, 0) < 30

    def test_typical_range(self):
        rh = relative_humidity(23, 12)
        assert 40 < rh < 60


class TestDecodeWeather:
    @pytest.mark.parametrize("token, expected", [
        ("RA",    "rain"),
        ("-RA",   "light rain"),
        ("+SN",   "heavy snow"),
        ("TSRA",  "thunderstorm with rain"),
        ("FZFG",  "freezing fog"),
        ("VCSH",  "nearby showers of"),
        ("+RASN", "heavy rain snow"),
        ("BR",    "mist"),
        ("HZ",    "haze"),
    ])
    def test_known_tokens(self, token, expected):
        assert decode_weather(token) == expected


class TestDetermineFlightCategory:
    def _cloud(self, cover, height_ft):
        return {"cover": cover, "height_ft": height_ft}

    def test_vfr_clear_sky(self):
        cat, _ = determine_flight_category([], 10.0)
        assert cat == "VFR"

    def test_mvfr_ceiling(self):
        cat, _ = determine_flight_category([self._cloud("BKN", 2500)], 10.0)
        assert cat == "MVFR"

    def test_mvfr_visibility(self):
        cat, _ = determine_flight_category([], 4.0)
        assert cat == "MVFR"

    def test_ifr_ceiling(self):
        cat, _ = determine_flight_category([self._cloud("OVC", 800)], 10.0)
        assert cat == "IFR"

    def test_ifr_visibility(self):
        cat, _ = determine_flight_category([], 2.0)
        assert cat == "IFR"

    def test_lifr_ceiling(self):
        cat, _ = determine_flight_category([self._cloud("OVC", 300)], 10.0)
        assert cat == "LIFR"

    def test_lifr_visibility(self):
        cat, _ = determine_flight_category([], 0.5)
        assert cat == "LIFR"

    def test_few_clouds_not_a_ceiling(self):
        # FEW is not a ceiling-defining cover; should remain VFR
        cat, _ = determine_flight_category([self._cloud("FEW", 400)], 10.0)
        assert cat == "VFR"

    def test_multiple_layers_uses_lowest_bkn(self):
        clouds = [self._cloud("FEW", 3000), self._cloud("BKN", 900)]
        cat, _ = determine_flight_category(clouds, 10.0)
        assert cat == "IFR"


# ── parse_metar ───────────────────────────────────────────────────────────────

class TestParseMETAR:
    def test_standard_vfr(self):
        raw = "METAR KORD 121552Z 27015KT 10SM FEW040 23/12 A3005 RMK AO2"
        d = parse_metar(raw)
        assert d["station"] == "KORD"
        assert d["time"] == "15:52 UTC"
        assert d["wind_compass"] == "W"
        assert d["wind_mph"] == knots_to_mph(15)
        assert d["visibility"] == "10+ miles"
        assert d["temperature_c"] == 23
        assert d["temperature_f"] == c_to_f(23)
        assert d["dewpoint_c"] == 12
        assert d["pressure_inhg"] == pytest.approx(30.05)
        assert d["flight_category"] == "VFR"
        assert d["remarks"] == "AO2"

    def test_metar_prefix_stripped(self):
        d = parse_metar("METAR KORD 121552Z 27015KT 10SM CLR 23/12 A3005")
        assert d["station"] == "KORD"

    def test_speci_prefix_stripped(self):
        d = parse_metar("SPECI KORD 121552Z 27015KT 10SM CLR 23/12 A3005")
        assert d["station"] == "KORD"

    def test_no_prefix(self):
        d = parse_metar("KORD 121552Z 27015KT 10SM CLR 23/12 A3005")
        assert d["station"] == "KORD"

    def test_raw_string_preserved(self):
        raw = "KORD 121552Z 27015KT 10SM CLR 23/12 A3005"
        assert parse_metar(raw)["raw"] == raw

    def test_auto_flag_true(self):
        d = parse_metar("METAR KBOS 121555Z AUTO 18010KT 10SM CLR 20/15 A2995")
        assert d["auto"] is True

    def test_auto_flag_absent(self):
        d = parse_metar("KORD 121552Z 27015KT 10SM CLR 23/12 A3005")
        assert d["auto"] is False

    def test_gusts_in_wind_text(self):
        raw = "KDFW 121553Z 18025G35KT 10SM SCT030 BKN060 32/18 A2995"
        d = parse_metar(raw)
        assert "gusting" in d["wind"]
        assert str(knots_to_mph(35)) in d["wind"]

    def test_variable_wind(self):
        d = parse_metar("KATL 121552Z VRB03KT 10SM CLR 25/14 A3010")
        assert d["wind_compass"] == "Variable"
        assert "variable" in d["wind"].lower()

    def test_calm_wind(self):
        d = parse_metar("KLAX 121556Z 00000KT 10SM SKC 22/10 A2998")
        assert d["wind"] == "Calm"

    def test_cavok(self):
        d = parse_metar("EGLL 121550Z 25010KT CAVOK 18/10 Q1015")
        assert d["cavok"] is True
        assert d["visibility"] == "10+ miles"
        assert d["flight_category"] == "VFR"

    def test_q_altimeter(self):
        d = parse_metar("EHAM 121555Z 24015KT 10SM FEW025 15/08 Q1010")
        assert d["pressure_mb"] == 1010
        assert d["pressure_inhg"] is not None

    def test_negative_temperatures(self):
        d = parse_metar("KORD 011552Z 31015KT 10SM OVC050 M05/M12 A3020")
        assert d["temperature_c"] == -5
        assert d["dewpoint_c"] == -12
        assert d["temperature_f"] == c_to_f(-5)

    def test_humidity_computed(self):
        d = parse_metar("KORD 121552Z 27015KT 10SM FEW040 23/12 A3005")
        assert d["humidity"] == relative_humidity(23, 12)

    def test_weather_phenomena_decoded(self):
        d = parse_metar("KJFK 121551Z 05009KT 2SM -RA BKN012 OVC025 18/16 A2990")
        assert any("rain" in w for w in d["weather"])

    def test_thunderstorm_with_cb_cloud(self):
        d = parse_metar("KDEN 121558Z 20012KT 7SM TSRA SCT035CB BKN060 28/18 A3001")
        assert any("thunderstorm" in w for w in d["weather"])
        assert any("cumulonimbus" in c["text"] for c in d["clouds"])

    def test_heavy_snow_ifr(self):
        d = parse_metar("KMSP 121554Z 33025G40KT 1SM +SN OVC010 M02/M05 A2985")
        assert any("heavy" in w and "snow" in w for w in d["weather"])
        assert d["flight_category"] == "IFR"

    def test_fog_lifr(self):
        d = parse_metar("KSFO 121556Z 24008KT 1/4SM FG OVC002 13/12 A3012")
        assert d["flight_category"] == "LIFR"
        assert d["visibility_miles"] == pytest.approx(0.25)

    def test_fractional_visibility(self):
        d = parse_metar("KBWI 121554Z 06005KT 1 1/2SM -RA OVC008 17/16 A2992")
        assert d["visibility_miles"] == pytest.approx(1.5)

    def test_multiple_cloud_layers(self):
        d = parse_metar("KBOS 121600Z 22010KT 10SM FEW015 SCT030 BKN060 18/14 A2988")
        assert len(d["clouds"]) == 3
        assert [c["cover"] for c in d["clouds"]] == ["FEW", "SCT", "BKN"]

    def test_mvfr_low_ceiling(self):
        d = parse_metar("KSEA 121556Z 27008KT 10SM BKN025 16/12 A2998")
        assert d["flight_category"] == "MVFR"

    def test_flight_category_vfr_high_ceiling(self):
        d = parse_metar("KORD 121552Z 27015KT 10SM FEW040 23/12 A3005")
        assert d["flight_category"] == "VFR"

    def test_summary_non_empty(self):
        d = parse_metar("KORD 121552Z 27015KT 10SM FEW040 23/12 A3005")
        assert d["summary"]

    def test_tcu_cloud_label(self):
        d = parse_metar("KDEN 121558Z 20012KT 10SM SCT040TCU 28/18 A3001")
        assert any("towering cumulus" in c["text"] for c in d["clouds"])


# ── fetch_metar ───────────────────────────────────────────────────────────────

class TestFetchMETAR:
    RAW = "KORD 121552Z 27015KT 10SM CLR 23/12 A3005"

    def test_calls_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.text = self.RAW
        with patch("app.requests.get", return_value=mock_resp) as mock_get:
            fetch_metar("KORD")
        mock_get.assert_called_once_with(
            "https://aviationweather.gov/api/data/metar?ids=KORD&format=raw",
            timeout=10,
        )

    def test_returns_stripped_text(self):
        mock_resp = MagicMock()
        mock_resp.text = f"  {self.RAW}  \n"
        with patch("app.requests.get", return_value=mock_resp):
            result = fetch_metar("KORD")
        assert result == self.RAW

    def test_http_error_propagates(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("app.requests.get", return_value=mock_resp):
            with pytest.raises(requests.HTTPError):
                fetch_metar("XXXX")

    def test_connection_error_propagates(self):
        with patch("app.requests.get", side_effect=requests.ConnectionError("down")):
            with pytest.raises(requests.ConnectionError):
                fetch_metar("KORD")

    def test_timeout_propagates(self):
        with patch("app.requests.get", side_effect=requests.Timeout("timed out")):
            with pytest.raises(requests.Timeout):
                fetch_metar("KORD")


# ── Flask route ───────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


class TestIndexRoute:
    RAW = "KORD 121552Z 27015KT 10SM CLR 23/12 A3005"

    def test_get_renders_form(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"<form" in resp.data

    def test_post_empty_airport_skips_fetch(self, client):
        with patch("app.fetch_metar") as mock_fetch:
            resp = client.post("/", data={"airport": ""})
        assert resp.status_code == 200
        mock_fetch.assert_not_called()

    def test_post_airport_uppercased_before_fetch(self, client):
        with patch("app.fetch_metar", return_value=self.RAW) as mock_fetch:
            client.post("/", data={"airport": "kord"})
        mock_fetch.assert_called_once_with("KORD")

    def test_post_valid_airport_shows_station(self, client):
        with patch("app.fetch_metar", return_value=self.RAW):
            resp = client.post("/", data={"airport": "KORD"})
        assert resp.status_code == 200
        assert b"KORD" in resp.data

    def test_post_empty_response_shows_error(self, client):
        with patch("app.fetch_metar", return_value=""):
            resp = client.post("/", data={"airport": "XXXX"})
        assert resp.status_code == 200
        assert b"No METAR data" in resp.data

    def test_post_request_exception_shows_error(self, client):
        with patch("app.fetch_metar", side_effect=requests.RequestException("timeout")):
            resp = client.post("/", data={"airport": "KORD"})
        assert resp.status_code == 200
        assert b"Could not connect" in resp.data

    def test_post_parse_exception_shows_error(self, client):
        with patch("app.fetch_metar", return_value="KORD 121552Z 27015KT 10SM CLR 23/12 A3005"):
            with patch("app.parse_metar", side_effect=ValueError("bad")):
                resp = client.post("/", data={"airport": "KORD"})
        assert resp.status_code == 200
        assert b"Error decoding METAR" in resp.data
