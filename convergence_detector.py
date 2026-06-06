"""
=======================================================================
  ASIFAH ANALYTICS -- CONVERGENCE DETECTOR (multi-axis, live)
  v0.2.0 (Jun 6 2026) -- STEP 2: THREE-AXIS JOIN + TIERING
=======================================================================

WHAT THIS IS
  A transversal layer that reads the three live signal axes already on
  the ME backend and asks, per country: how many INDEPENDENT axes are
  lit at the same time? Agreement across axes beats one loud headline.

    Axis 1 -- KINETIC    : kinetic_activity_gatherer  (Redis: kinetic:global:latest)
                           per country: band normal/elevated/high/surge
    Axis 2 -- COMMODITY  : commodity_tracker          (Redis: commodity_tracker_cache)
                           country_summaries[id].alert_level (same band scale)
    Axis 3 -- RHETORIC   : regional BLUFs             (Redis: rhetoric:<region>:regional_bluf)
                           theatre_summary[id].level  (L0-L5 escalation)

  NOTE: no Africa regional BLUF exists yet, so African countries carry no
  rhetoric axis until that hole is filled. The join treats a missing axis
  as simply absent -- such a country can still register on the other two.

NORMALIZATION (common 0-3 intensity ladder)
    kinetic / commodity band : normal=0 elevated=1 high=2 surge=3
    rhetoric level L0-L5     : L0/L1=0  L2=1  L3=2  L4/L5=3
  An axis is "active" for a country at intensity >= 1. (Tunable.)

TIERING (the analytic claim -- count of co-active axes)
    3 active -> triple convergence    (headline tier)
    2 active -> dual convergence
    1 active -> single-axis
    0 active -> quiet (omitted from the scan list)
  Ranked by tier, then by summed intensity within tier.

WHAT THIS STEP DOES NOT DO YET
    - no "so what" prose            (Step: prose)
    - no historical baseline/delta  (Step: history)
  Output is structured data so the joins can be eyeballed against the
  caches before we build narrative on top.

NAMESPACE
  Routes under /api/cax/* -- the /api/convergence/* namespace belongs to
  convergence_registry.py (a different module). Do not mix.

USAGE FROM ME BACKEND app.py
    from convergence_detector import register_convergence_detector_endpoints
    register_convergence_detector_endpoints(app)

CONVERGENCE-NOT-PREDICTION
  Reports which signal streams are co-active. Does not forecast actions.
"""

import os
import json
import requests
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# Redis (Upstash REST) -- READ-ONLY. Never triggers a scan.
# ----------------------------------------------------------------------
_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')   or os.environ.get('UPSTASH_REDIS_REST_URL')
_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

KINETIC_CACHE_KEY   = 'kinetic:global:latest'
COMMODITY_CACHE_KEY = 'commodity_tracker_cache'
RHETORIC_BLUF_KEYS  = {
    'me':     'rhetoric:me:regional_bluf',
    'wha':    'rhetoric:wha:regional_bluf',
    'europe': 'rhetoric:europe:regional_bluf',
    'asia':   'rhetoric:asia:regional_bluf',
    # 'africa': 'rhetoric:africa:regional_bluf',   # FUTURE -- BLUF not built yet
}

DISCLAIMER = ("This is a CONVERGENCE indicator, NOT a probability of action. "
              "Co-active signal streams indicate that independent reporting axes "
              "agree; they do not predict whether or when action will occur.")


def _redis_get(key):
    """Read-only GET from Upstash REST. Returns parsed JSON or None. Never scans."""
    if not (_REDIS_URL and _REDIS_TOKEN):
        return None
    try:
        resp = requests.get(
            f"{_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_REDIS_TOKEN}"},
            timeout=6,
        )
        data = resp.json()
        if data.get("result"):
            return json.loads(data["result"])
    except Exception as e:
        print(f"[ConvergenceDetector] Redis GET {key} error: {e}")
    return None


# ----------------------------------------------------------------------
# Normalization tables
# ----------------------------------------------------------------------
BAND_INTENSITY = {'normal': 0, 'elevated': 1, 'high': 2, 'surge': 3}
RHETORIC_LEVEL_INTENSITY = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3, 5: 3}
TIER_BY_COUNT = {0: 'quiet', 1: 'single', 2: 'dual', 3: 'triple'}
TIER_RANK = {'triple': 3, 'dual': 2, 'single': 1, 'quiet': 0}

# ----------------------------------------------------------------------
# Country-id canonicalization. Commodity + rhetoric already use lowercase
# ids; kinetic uses GDELT display names. We canonicalize everything to id.
# Explicit cases where lower+underscore would NOT match the commodity ids.
# ----------------------------------------------------------------------
ID_TO_DISPLAY = {
    'usa':          'United States',
    'uae':          'United Arab Emirates',
    'drc':          'DR Congo',
    'south_korea':  'South Korea',
    'south_africa': 'South Africa',
    'saudi_arabia': 'Saudi Arabia',
    'eu':           'EU',
}
_NAME_TO_ID = {
    'United States':         'usa',
    'United Arab Emirates':  'uae',
    'DR Congo':              'drc',
}


def _kinetic_name_to_id(name):
    """GDELT display name -> canonical lowercase id."""
    if name in _NAME_TO_ID:
        return _NAME_TO_ID[name]
    return name.lower().replace(' ', '_').replace('-', '_')


def _id_to_display(cid):
    """Canonical id -> human display name."""
    return ID_TO_DISPLAY.get(cid) or cid.replace('_', ' ').title()


# ----------------------------------------------------------------------
# Per-axis readers. Each returns {country_id: {intensity, label, score, driver}}
# plus an availability flag so a cold cache is visible, never silent.
# ----------------------------------------------------------------------
def _read_kinetic():
    kin = _redis_get(KINETIC_CACHE_KEY)
    if not kin:
        return {}, False
    out = {}
    for name, c in (kin.get('countries', {}) or {}).items():
        band = c.get('band', 'normal')
        intensity = BAND_INTENSITY.get(band, 0)
        # driver = first conflict-track top event, else first event
        events = c.get('top_events', []) or []
        drv = next((e for e in events if e.get('track') == 'conflict'), events[0] if events else None)
        driver = None
        if drv:
            driver = {'label': drv.get('label'), 'articles': drv.get('articles'),
                      'source': drv.get('source')}
        out[_kinetic_name_to_id(name)] = {
            'intensity': intensity, 'label': band,
            'score': c.get('conflict_score'), 'driver': driver,
        }
    return out, True


def _read_commodity():
    com = _redis_get(COMMODITY_CACHE_KEY)
    if not com:
        return {}, False
    out = {}
    for cid, c in (com.get('country_summaries', {}) or {}).items():
        level = c.get('alert_level', 'normal')
        sigs = c.get('top_signals', []) or []
        out[cid] = {
            'intensity': BAND_INTENSITY.get(level, 0), 'label': level,
            'score': c.get('total_score'),
            'driver': sigs[0] if sigs else None,
        }
    return out, True


def _read_rhetoric():
    """Merge per-country theatre_summary across all regional BLUF caches."""
    out, availability = {}, {}
    for region, key in RHETORIC_BLUF_KEYS.items():
        bluf = _redis_get(key)
        availability[region] = bool(bluf)
        if not bluf:
            continue
        for cid, t in (bluf.get('theatre_summary', {}) or {}).items():
            level = t.get('level', 0) or 0
            out[cid] = {
                'intensity': RHETORIC_LEVEL_INTENSITY.get(level, 0),
                'label': t.get('label', ''), 'level': level,
                'score': t.get('score'), 'region': region,
                'driver': {'label': t.get('label'), 'level': level},
            }
    return out, availability


# ----------------------------------------------------------------------
# The join
# ----------------------------------------------------------------------
def build_convergence():
    kinetic,   kin_ok  = _read_kinetic()
    commodity, com_ok  = _read_commodity()
    rhetoric,  rhe_avail = _read_rhetoric()

    all_ids = set(kinetic) | set(commodity) | set(rhetoric)
    records = []
    for cid in all_ids:
        axes = {
            'kinetic':   kinetic.get(cid),
            'commodity': commodity.get(cid),
            'rhetoric':  rhetoric.get(cid),
        }
        active = [name for name, a in axes.items() if a and a.get('intensity', 0) >= 1]
        count = len(active)
        if count == 0:
            continue
        records.append({
            'country':          cid,
            'display':          _id_to_display(cid),
            'tier':             TIER_BY_COUNT[min(count, 3)],
            'active_count':     count,
            'active_axes':      active,
            'summed_intensity': sum(axes[a]['intensity'] for a in active),
            'axes':             axes,
        })

    records.sort(key=lambda r: (TIER_RANK[r['tier']], r['summed_intensity']), reverse=True)

    tier_counts = {'triple': 0, 'dual': 0, 'single': 0}
    for r in records:
        tier_counts[r['tier']] += 1

    return {
        'records':       records,
        'tier_counts':   tier_counts,
        'availability':  {'kinetic': kin_ok, 'commodity': com_ok, 'rhetoric': rhe_avail},
    }


def register_convergence_detector_endpoints(app):
    """Register the convergence-detector endpoints on the ME Flask app."""
    from flask import jsonify

    @app.route('/api/cax/scan', methods=['GET'])
    def cax_scan():
        """STEP 2: three-axis join + tiering. Structured output, no prose yet."""
        try:
            result = build_convergence()
            return jsonify({
                'success':      True,
                'version':      '0.2.0',
                'step':         '2 (three-axis join + tiering, no prose)',
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'tier_counts':  result['tier_counts'],
                'availability': result['availability'],
                'count':        len(result['records']),
                'records':      result['records'],
                'disclaimer':   DISCLAIMER,
            })
        except Exception as e:
            print(f"[ConvergenceDetector] /scan error: {e}")
            return jsonify({'success': False, 'error': str(e)[:300]}), 500

    @app.route('/api/cax/probe', methods=['GET'])
    def cax_probe():
        """Lightweight availability probe -- which caches are warm right now."""
        kin = _redis_get(KINETIC_CACHE_KEY)
        com = _redis_get(COMMODITY_CACHE_KEY)
        rhe = {r: bool(_redis_get(k)) for r, k in RHETORIC_BLUF_KEYS.items()}
        return jsonify({
            'success': True, 'version': '0.2.0',
            'redis_configured': bool(_REDIS_URL and _REDIS_TOKEN),
            'kinetic_warm':   bool(kin),
            'commodity_warm': bool(com),
            'rhetoric_warm':  rhe,
            'probed_at': datetime.now(timezone.utc).isoformat(),
        })

    print("[ConvergenceDetector] Registered: /api/cax/scan, /api/cax/probe  (v0.2.0)")
