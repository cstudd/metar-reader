import math
import re
from datetime import datetime, timezone

import requests
from flask import Flask, render_template, request

app = Flask(__name__)

WEATHER_PHENOMENA = {
    'DZ', 'RA', 'SN', 'SG', 'IC', 'PL', 'GR', 'GS', 'UP',
    'BR', 'FG', 'FU', 'VA', 'DU', 'SA', 'HZ', 'PY',
    'PO', 'SQ', 'FC', 'SS', 'DS',
}
WEATHER_DESCRIPTORS = {'MI', 'BC', 'PR', 'DR', 'BL', 'SH', 'TS', 'FZ'}

PHENOMENON_LABELS = {
    'DZ': 'drizzle', 'RA': 'rain', 'SN': 'snow', 'SG': 'snow grains',
    'IC': 'ice crystals', 'PL': 'ice pellets', 'GR': 'hail', 'GS': 'small hail',
    'UP': 'unknown precipitation',
    'BR': 'mist', 'FG': 'fog', 'FU': 'smoke', 'VA': 'volcanic ash',
    'DU': 'dust', 'SA': 'sand', 'HZ': 'haze', 'PY': 'spray',
    'PO': 'dust whirls', 'SQ': 'squalls', 'FC': 'funnel cloud/tornado',
    'SS': 'sandstorm', 'DS': 'duststorm',
}
DESCRIPTOR_LABELS = {
    'MI': 'shallow', 'BC': 'patchy', 'PR': 'partial', 'DR': 'low drifting',
    'BL': 'blowing', 'SH': 'showers of', 'TS': 'thunderstorm with',
    'FZ': 'freezing',
}
SKY_CONDITIONS = {
    'SKC': 'Clear skies', 'CLR': 'Clear skies', 'NSC': 'No significant clouds',
    'NCD': 'No clouds detected',
    'FEW': 'A few clouds',    'SCT': 'Scattered clouds',
    'BKN': 'Broken cloud cover', 'OVC': 'Overcast', 'VV': 'Sky obscured',
}
COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
           'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def degrees_to_compass(deg):
    return COMPASS[round(deg / 22.5) % 16]


def knots_to_mph(kt):
    return round(kt * 1.15078)


def c_to_f(c):
    return round(c * 9 / 5 + 32)


def relative_humidity(temp_c, dew_c):
    rh = 100 * math.exp(
        (17.625 * dew_c / (243.04 + dew_c)) - (17.625 * temp_c / (243.04 + temp_c))
    )
    return round(rh)


def is_weather_token(token):
    t = token.lstrip('+-')
    if t.startswith('VC'):
        t = t[2:]
    if not t or len(t) % 2 != 0:
        return False
    codes = [t[i:i + 2] for i in range(0, len(t), 2)]
    return all(c in WEATHER_PHENOMENA or c in WEATHER_DESCRIPTORS for c in codes)


def decode_weather(token):
    t = token
    parts = []

    if t.startswith('+'):
        parts.append('heavy')
        t = t[1:]
    elif t.startswith('-'):
        parts.append('light')
        t = t[1:]

    if t.startswith('VC'):
        parts.append('nearby')
        t = t[2:]

    codes = [t[i:i + 2] for i in range(0, len(t), 2)]
    for code in codes:
        if code in DESCRIPTOR_LABELS:
            parts.append(DESCRIPTOR_LABELS[code])
        elif code in PHENOMENON_LABELS:
            parts.append(PHENOMENON_LABELS[code])
        else:
            parts.append(code)

    return ' '.join(parts)


def parse_temp_token(t):
    if t.startswith('M'):
        return -int(t[1:])
    return int(t)


def determine_flight_category(clouds, vis_miles):
    ceiling = None
    for c in clouds:
        if c['cover'] in ('BKN', 'OVC', 'VV') and c['height_ft'] is not None:
            if ceiling is None or c['height_ft'] < ceiling:
                ceiling = c['height_ft']

    if (ceiling is not None and ceiling < 500) or vis_miles < 1:
        return 'LIFR', 'Low IFR'
    if (ceiling is not None and ceiling < 1000) or vis_miles < 3:
        return 'IFR', 'IFR'
    if (ceiling is not None and ceiling < 3000) or vis_miles < 5:
        return 'MVFR', 'Marginal VFR'
    return 'VFR', 'VFR'


def build_summary(data):
    parts = []

    weather = data.get('weather', [])
    clouds = data.get('clouds', [])

    if weather:
        parts.append(', '.join(weather).capitalize())

    if clouds:
        dominant = clouds[-1]
        cover = dominant['cover']
        if cover in ('SKC', 'CLR', 'NSC', 'NCD'):
            parts.append('clear skies')
        elif cover == 'OVC':
            parts.append('overcast skies')
        elif cover == 'BKN':
            parts.append('mostly cloudy')
        elif cover == 'SCT':
            parts.append('partly cloudy')
        elif cover == 'FEW':
            parts.append('mostly clear with a few clouds')
        elif cover == 'VV':
            parts.append('sky obscured')

    temp_f = data.get('temperature_f')
    temp_c = data.get('temperature_c')
    if temp_f is not None:
        parts.append(f'{temp_f}°F ({temp_c}°C)')

    wind = data.get('wind')
    if wind:
        parts.append(f'wind {wind}')

    vis = data.get('visibility')
    if vis:
        parts.append(f'visibility {vis}')

    return '. '.join(p.capitalize() for p in parts) + '.' if parts else ''


def parse_metar(raw):
    data = {
        'raw': raw, 'station': None, 'time': None, 'auto': False,
        'wind': None, 'wind_mph': None, 'wind_compass': None,
        'visibility': None, 'visibility_miles': 10.0,
        'weather': [], 'clouds': [],
        'temperature_c': None, 'temperature_f': None,
        'dewpoint_c': None, 'dewpoint_f': None,
        'humidity': None,
        'pressure_inhg': None, 'pressure_mb': None,
        'remarks': None,
        'flight_category': 'VFR', 'flight_category_label': 'VFR',
        'summary': '',
        'cavok': False,
    }

    tokens = raw.strip().split()
    if tokens and tokens[0] in ('METAR', 'SPECI'):
        tokens = tokens[1:]

    idx = 0

    # Station
    if idx < len(tokens):
        data['station'] = tokens[idx]
        idx += 1

    # Date/time
    if idx < len(tokens) and re.match(r'^\d{6}Z$', tokens[idx]):
        t = tokens[idx]
        hour, minute = int(t[2:4]), int(t[4:6])
        data['time'] = f'{hour:02d}:{minute:02d} UTC'
        idx += 1

    # AUTO / COR
    if idx < len(tokens) and tokens[idx] in ('AUTO', 'COR'):
        data['auto'] = tokens[idx] == 'AUTO'
        idx += 1

    # Wind
    if idx < len(tokens):
        m = re.match(r'^(VRB|\d{3})(\d{2,3})(G(\d{2,3}))?KT$', tokens[idx])
        if m:
            direction, speed_kt = m.group(1), int(m.group(2))
            gust_kt = int(m.group(4)) if m.group(4) else None
            speed_mph = knots_to_mph(speed_kt)

            if direction == 'VRB':
                dir_text = 'from a variable direction'
                data['wind_compass'] = 'Variable'
            else:
                deg = int(direction)
                compass = degrees_to_compass(deg)
                dir_text = f'from the {compass} ({deg}°)'
                data['wind_compass'] = compass

            if speed_mph == 0:
                data['wind'] = 'Calm'
            else:
                wind_text = f'{speed_mph} mph {dir_text}'
                if gust_kt:
                    wind_text += f', gusting to {knots_to_mph(gust_kt)} mph'
                data['wind'] = wind_text

            data['wind_mph'] = speed_mph
            idx += 1

    # Variable wind dir (e.g. 350V040)
    if idx < len(tokens) and re.match(r'^\d{3}V\d{3}$', tokens[idx]):
        idx += 1

    # CAVOK
    if idx < len(tokens) and tokens[idx] == 'CAVOK':
        data['cavok'] = True
        data['visibility'] = '10+ miles'
        data['visibility_miles'] = 10.0
        data['clouds'] = [{'text': 'Clear skies', 'cover': 'CLR', 'height_ft': None}]
        idx += 1

    # Visibility (SM)
    if not data['cavok'] and idx < len(tokens):
        m = re.match(r'^(M)?(\d+(?:/\d+)?)SM$', tokens[idx])
        if m:
            less_than = m.group(1) == 'M'
            vis_str = m.group(2)
            if '/' in vis_str:
                num, den = vis_str.split('/')
                vis_float = int(num) / int(den)
            else:
                vis_float = float(vis_str)
            prefix = 'Less than ' if less_than else ''
            if vis_float >= 10:
                data['visibility'] = f'{prefix}10+ miles'
            elif vis_float == 1:
                data['visibility'] = f'{prefix}1 mile'
            else:
                data['visibility'] = f'{prefix}{vis_str} miles'
            data['visibility_miles'] = vis_float
            idx += 1
        # whole number + fraction (e.g. "1 1/2SM")
        elif re.match(r'^\d+$', tokens[idx]) and idx + 1 < len(tokens):
            m2 = re.match(r'^(\d+)/(\d+)SM$', tokens[idx + 1])
            if m2:
                vis_float = int(tokens[idx]) + int(m2.group(1)) / int(m2.group(2))
                data['visibility'] = f'{vis_float:.2g} miles'
                data['visibility_miles'] = vis_float
                idx += 2

    # Skip runway visual range (R\d\d...)
    while idx < len(tokens) and re.match(r'^R\d{2}[LCR]?/', tokens[idx]):
        idx += 1

    # Weather phenomena
    weather_list = []
    while idx < len(tokens) and is_weather_token(tokens[idx]):
        weather_list.append(decode_weather(tokens[idx]))
        idx += 1
    data['weather'] = weather_list

    # Sky conditions
    clouds = []
    while idx < len(tokens):
        m = re.match(r'^(SKC|CLR|NSC|NCD|FEW|SCT|BKN|OVC|VV)(\d{3})?(CB|TCU)?$', tokens[idx])
        if m:
            cover, height_str, cloud_type = m.group(1), m.group(2), m.group(3)
            cover_text = SKY_CONDITIONS.get(cover, cover)
            height_ft = int(height_str) * 100 if height_str else None

            if height_ft is not None:
                cloud_text = f'{cover_text} at {height_ft:,} ft'
            else:
                cloud_text = cover_text

            if cloud_type == 'CB':
                cloud_text += ' (cumulonimbus — thunderstorm clouds)'
            elif cloud_type == 'TCU':
                cloud_text += ' (towering cumulus)'

            clouds.append({'text': cloud_text, 'cover': cover, 'height_ft': height_ft})
            idx += 1
        else:
            break

    if not data['cavok']:
        data['clouds'] = clouds

    # Temperature / dew point
    if idx < len(tokens):
        m = re.match(r'^(M?\d+)/(M?\d+)$', tokens[idx])
        if m:
            temp_c = parse_temp_token(m.group(1))
            dew_c = parse_temp_token(m.group(2))
            data['temperature_c'] = temp_c
            data['temperature_f'] = c_to_f(temp_c)
            data['dewpoint_c'] = dew_c
            data['dewpoint_f'] = c_to_f(dew_c)
            data['humidity'] = relative_humidity(temp_c, dew_c)
            idx += 1

    # Altimeter
    if idx < len(tokens):
        m = re.match(r'^A(\d{4})$', tokens[idx])
        if m:
            inhg = int(m.group(1)) / 100
            data['pressure_inhg'] = inhg
            data['pressure_mb'] = round(inhg * 33.8639)
            idx += 1
        else:
            m = re.match(r'^Q(\d{4})$', tokens[idx])
            if m:
                mb = int(m.group(1))
                data['pressure_mb'] = mb
                data['pressure_inhg'] = round(mb / 33.8639, 2)
                idx += 1

    # Remarks
    if idx < len(tokens) and tokens[idx] == 'RMK':
        data['remarks'] = ' '.join(tokens[idx + 1:])

    # Flight category
    data['flight_category'], data['flight_category_label'] = determine_flight_category(
        data['clouds'], data['visibility_miles']
    )

    data['summary'] = build_summary(data)
    return data


def fetch_metar(airport_code):
    url = f'https://aviationweather.gov/api/data/metar?ids={airport_code}&format=raw'
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.text.strip()


@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    airport = ''

    if request.method == 'POST':
        airport = request.form.get('airport', '').strip().upper()
        if airport:
            try:
                raw = fetch_metar(airport)
                if raw:
                    result = parse_metar(raw)
                else:
                    error = f'No METAR data found for "{airport}". Check the airport code and try again.'
            except requests.RequestException as e:
                error = f'Could not connect to weather service: {e}'
            except Exception as e:
                error = f'Error decoding METAR: {e}'

    return render_template('index.html', result=result, error=error, airport=airport)


if __name__ == '__main__':
    app.run(debug=True)
