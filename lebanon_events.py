"""
Asifah Analytics — Lebanon Events Module v1.0.0
================================================
Fetches georeferenced conflict events from GDELT Event API v2
and serves them as map markers for the Lebanon Stability page.

GDELT Event API: api.gdeltproject.org/api/v2/geo/geo
- Free, no API key required
- Returns conflict events with lat/lon, actor names, CAMEO codes
- Goldstein Scale: -10 (most destabilizing) to +10 (most cooperative)

CAMEO codes used for filtering:
  18x = Assault (180-186)
  19x = Fight (190-196)
  20x = Use conventional military force (200-204)
  17x = Coerce (170-174) — threats/sanctions
  15x = Demonstrate/protest (150-155)

Env vars required (shared with lebanon_humanitarian.py):
  UPSTASH_REDIS_REST_URL
  UPSTASH_REDIS_REST_TOKEN
"""

import os
import json
import requests

# Oct 18 2026: the GEO API now goes through the shared gateway too
# (gdelt_get_json_probed, gateway v2.4.1+) -- same platform clock, stand-down,
# budget and cache as every DOC query. This module was the last unpaced caller.
try:
    from gdelt_gateway import gdelt_get_json_probed as _gw_json_probed
except ImportError:
    _gw_json_probed = None
    print('[Lebanon Events] gdelt_gateway < 2.4.1 or missing -- GEO fetch disabled (no direct fallback)')
from datetime import datetime, timezone, timedelta

UPSTASH_URL = os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_REST_TOKEN')

GDELT_EVENT_URL = "https://api.gdeltproject.org/api/v2/geo/geo"
EVENTS_CACHE_KEY = "lebanon_events_v1"
EVENTS_CACHE_TTL = 2 * 60 * 60  # 2 hours in seconds

# CAMEO root codes to include — conflict/military/coercion
# See: https://www.gdeltproject.org/data/documentation/CAMEO.Manual.1.1b3.pdf
CONFLICT_CAMEO_ROOTS = {
    '14': ('Protest', '#facc15', '✊'),        # Demand
    '15': ('Protest', '#facc15', '✊'),        # Demonstrate
    '17': ('Coercion', '#f97316', '⚠️'),       # Coerce
    '18': ('Assault', '#ef4444', '💥'),        # Assault
    '19': ('Armed Conflict', '#dc2626', '🔴'), # Fight
    '20': ('Military Force', '#991b1b', '🎯'), # Use conventional military force
}

# Lebanon bounding box for filtering: west, south, east, north
LEBANON_BBOX = {
    'min_lat': 33.05, 'max_lat': 34.70,
    'min_lng': 35.10, 'max_lng': 36.65
}

# Extend slightly to catch border area events (southern Lebanon / Blue Line)
LEBANON_BBOX_EXTENDED = {
    'min_lat': 32.80, 'max_lat': 34.70,
    'min_lng': 35.00, 'max_lng': 36.70
}


def _redis_get(key):
    """Get value from Upstash Redis."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f"[Lebanon Events] Redis get error: {e}")
    return None


def _redis_set(key, value, ttl_seconds=EVENTS_CACHE_TTL):
    """Set value in Upstash Redis with TTL."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        return
    try:
        payload = json.dumps(value, default=str)
        requests.post(
            f"{UPSTASH_URL}/set/{key}",
            headers={
                "Authorization": f"Bearer {UPSTASH_TOKEN}",
                "Content-Type": "application/json"
            },
            data=payload,
            params={"EX": ttl_seconds},
            timeout=5
        )
        print(f"[Lebanon Events] ✅ Cached to Redis ({len(payload)} bytes)")
    except Exception as e:
        print(f"[Lebanon Events] Redis set error: {e}")


def _is_cache_fresh(cached):
    """Check if cached data is still within TTL."""
    if not cached or 'cached_at' not in cached:
        return False
    try:
        age = (datetime.now(timezone.utc) -
               datetime.fromisoformat(cached['cached_at'])).total_seconds()
        return age < EVENTS_CACHE_TTL
    except Exception:
        return False


def _cameo_to_event_type(cameo_code):
    """Map CAMEO code to event type metadata."""
    if not cameo_code:
        return ('Unknown', '#6b7280', '❓')
    root = str(cameo_code)[:2]
    return CONFLICT_CAMEO_ROOTS.get(root, ('Activity', '#6b7280', '📌'))


def _goldstein_to_severity(goldstein):
    """Convert Goldstein scale to severity label."""
    if goldstein is None:
        return 'unknown'
    if goldstein <= -7:
        return 'critical'
    if goldstein <= -4:
        return 'high'
    if goldstein <= -1:
        return 'moderate'
    if goldstein >= 1:
        return 'cooperative'
    return 'neutral'


def fetch_gdelt_events_lebanon(days=7, force=False):
    """
    Fetch Lebanon conflict events from GDELT Event API.
    Returns list of georeferenced events for map display.
    """
    # Check cache first
    if not force:
        cached = _redis_get(EVENTS_CACHE_KEY)
        if cached and _is_cache_fresh(cached):
            print(f"[Lebanon Events] Returning cached data "
                  f"({len(cached.get('events', []))} events)")
            return cached

    print("[Lebanon Events] Fetching fresh data from GDELT Event API...")

    # Build date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    all_events = []
    _sensed, _not = 0, {}

    # Query GDELT for Lebanon-related conflict events
    # Using multiple queries to maximize coverage
    queries = [
        "Lebanon",
        "Hezbollah",
        "South Lebanon",
        "Beirut strike",
        "IDF Lebanon",
        "Khiam Lebanon",
        "Bekaa Valley",
    ]

    for query in queries:
        try:
            params = {
                'query': query,
                'mode': 'pointdata',
                'format': 'json',
                'timespan': f'{days}d',
                'maxrecords': 250,
            }
            if _gw_json_probed is None:
                break
            data, probe = _gw_json_probed(GDELT_EVENT_URL, params,
                                          label='lebanon_events/geo')
            if not probe.get('sensed'):
                print(f"[Lebanon Events] '{query}' not sensed ({probe.get('reason')}) -- "
                      f"not 'no events'")
                _not[probe.get('reason') or 'unknown'] = _not.get(probe.get('reason') or 'unknown', 0) + 1
                continue
            _sensed += 1
            features = data.get('features', []) if isinstance(data, dict) else []

            for feature in features:
                props = feature.get('properties', {})
                geom = feature.get('geometry', {})
                coords = geom.get('coordinates', [])

                if len(coords) < 2:
                    continue

                lng, lat = coords[0], coords[1]

                # Filter to Lebanon + border area bounding box
                bbox = LEBANON_BBOX_EXTENDED
                if not (bbox['min_lat'] <= lat <= bbox['max_lat'] and
                        bbox['min_lng'] <= lng <= bbox['max_lng']):
                    continue

                # Extract fields
                cameo = props.get('EventCode', props.get('ActionGeo_Type', ''))
                goldstein = props.get('GoldsteinScale')
                try:
                    goldstein = float(goldstein) if goldstein else None
                except (ValueError, TypeError):
                    goldstein = None

                # Skip highly cooperative events (goldstein > 3)
                if goldstein and goldstein > 3:
                    continue

                actor1 = props.get('Actor1Name', props.get('Actor1CountryCode', ''))
                actor2 = props.get('Actor2Name', props.get('Actor2CountryCode', ''))
                location = props.get('ActionGeo_FullName', props.get('name', ''))
                date_str = props.get('SQLDATE', props.get('date', ''))
                url = props.get('SOURCEURL', props.get('url', ''))
                mentions = props.get('NumMentions', 0)
                sources = props.get('NumSources', 0)

                # Parse date
                event_date = ''
                if date_str:
                    try:
                        if len(str(date_str)) == 8:  # YYYYMMDD
                            event_date = (f"{str(date_str)[:4]}-"
                                          f"{str(date_str)[4:6]}-"
                                          f"{str(date_str)[6:8]}")
                        else:
                            event_date = str(date_str)[:10]
                    except Exception:
                        event_date = str(date_str)

                event_type, color, icon = _cameo_to_event_type(cameo)
                severity = _goldstein_to_severity(goldstein)

                all_events.append({
                    'lat': round(lat, 4),
                    'lng': round(lng, 4),
                    'location': location,
                    'date': event_date,
                    'actor1': actor1 or 'Unknown',
                    'actor2': actor2 or 'Unknown',
                    'event_type': event_type,
                    'cameo': str(cameo),
                    'goldstein': goldstein,
                    'severity': severity,
                    'color': color,
                    'icon': icon,
                    'mentions': int(mentions) if mentions else 0,
                    'sources': int(sources) if sources else 0,
                    'url': url,
                })

            print(f"[Lebanon Events] '{query}': {len(features)} raw → "
                  f"{len(all_events)} total after filtering")

        except Exception as e:
            print(f"[Lebanon Events] Query '{query}' error: {e}")
        # (Oct 18 2026: the 0.5s sleep is gone -- the gateway owns pacing now.)

    # Absence is reported, not inferred. If NO query was sensed (throttle,
    # circuit, budget), we did not look -- so we must not cache "0 events"
    # over the last real answer. Serve the last good payload, marked stale.
    if _sensed == 0:
        print(f"[Lebanon Events] BLIND -- 0/{len(queries)} queries sensed {_not}; "
              f"keeping last good cache")
        prior = _redis_get(EVENTS_CACHE_KEY)
        if isinstance(prior, dict) and prior.get('events') is not None:
            prior = dict(prior)
            prior['stale'] = True
            prior['gdelt_sensed'] = {'sensed': 0, 'queries': len(queries), 'not_sensed': _not}
            return prior
        return {
            'success': False, 'events': [], 'total_events': 0,
            'days_analyzed': days, 'event_type_counts': {},
            'gdelt_sensed': {'sensed': 0, 'queries': len(queries), 'not_sensed': _not},
            'error': 'GDELT not sensed (no prior data to fall back on)',
            'cached_at': datetime.now(timezone.utc).isoformat(),
            'version': '1.1.0',
        }

    # Deduplicate by lat/lng/date/actor1 combination
    seen = set()
    deduped = []
    for e in all_events:
        key = (round(e['lat'], 2), round(e['lng'], 2), e['date'], e['actor1'][:10])
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    # Sort by date descending, then by severity (most negative goldstein first)
    deduped.sort(key=lambda x: (
        x['date'],
        x['goldstein'] if x['goldstein'] is not None else 0
    ), reverse=True)

    # Cap at 200 events for frontend performance
    deduped = deduped[:200]

    # Build summary stats
    event_type_counts = {}
    for e in deduped:
        event_type_counts[e['event_type']] = \
            event_type_counts.get(e['event_type'], 0) + 1

    result = {
        'success': True,
        'events': deduped,
        'total_events': len(deduped),
        'days_analyzed': days,
        'event_type_counts': event_type_counts,
        'gdelt_sensed': {'sensed': _sensed, 'queries': len(queries), 'not_sensed': _not},
        'cached_at': datetime.now(timezone.utc).isoformat(),
        'version': '1.1.0',
    }

    # Cache result
    _redis_set(EVENTS_CACHE_KEY, result)

    print(f"[Lebanon Events] ✅ Complete: {len(deduped)} events "
          f"({event_type_counts})")
    return result


def register_events_endpoints(app):
    """Register Lebanon events endpoints with the Flask app."""
    from flask import request as flask_request, jsonify, make_response

    def _cors(data, status=200):
        resp = make_response(jsonify(data), status)
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

    @app.route('/api/lebanon/events', methods=['GET'])
    def api_lebanon_events():
        """
        Lebanon conflict events from GDELT for map display.
        ?days=7 (default) — number of days to look back
        ?force=true — bypass cache
        """
        try:
            days = int(flask_request.args.get('days', 7))
            force = flask_request.args.get('force', 'false').lower() == 'true'
            days = max(1, min(days, 30))  # cap 1-30 days

            result = fetch_gdelt_events_lebanon(days=days, force=force)
            return _cors(result)

        except Exception as e:
            print(f"[Lebanon Events API] Error: {e}")
            return _cors({
                'success': False,
                'error': str(e)[:200],
                'events': [],
                'total_events': 0,
            }, 500)

    print("[Lebanon Events] ✅ Route registered: /api/lebanon/events")
