"""
=======================================================================
  ASIFAH ANALYTICS -- CONVERGENCE DETECTOR (multi-axis, live)
  v0.1.0 (Jun 6 2026) -- STEP 1: READ-PROBE ONLY (no scoring yet)
=======================================================================

WHAT THIS IS
  A transversal layer that reads the three live signal axes already on
  the ME backend and asks, per country: are multiple INDEPENDENT axes
  lit at the same time? Convergence across axes beats one loud headline.

    Axis 1 -- KINETIC    : kinetic_activity_gatherer  (Redis: kinetic:global:latest)
    Axis 2 -- COMMODITY  : commodity_tracker          (Redis: commodity_tracker_cache)
    Axis 3 -- RHETORIC   : rhetoric trackers          (wired in Step 2)

WHY A READ-PROBE FIRST
  The three axes speak three different country vocabularies:
      kinetic   -> GDELT display names  ("United States", "DR Congo")
      commodity -> lowercase ids        ("usa", "drc")
      rhetoric  -> lowercase ids        ("us", "lebanon")
  Before we score anything, we DUMP what each cache actually contains and
  show which country names reconcile and which don't. No silent-empty
  readers scoring against air. (This step does NOT compute convergence.)

NAMESPACE
  Routes live under /api/cax/* on purpose -- the /api/convergence/*
  namespace is owned by convergence_registry.py (a different module: a
  curated knowledge base of commodity-geopolitics linkages). Do not mix.

USAGE FROM ME BACKEND app.py
    from convergence_detector import register_convergence_detector_endpoints
    register_convergence_detector_endpoints(app)

CONVERGENCE-NOT-PREDICTION
  This module reports which signal streams are co-active and how that
  compares to the recent past. It does not forecast actions.
"""

import os
import json
import requests
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# Redis (Upstash REST) -- READ-ONLY. Never triggers a scan.
# Matches the env-var names used by commodity_tracker / the gatherer on
# the ME backend, with a fallback to the REST-prefixed variants.
# ----------------------------------------------------------------------
_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

KINETIC_CACHE_KEY   = 'kinetic:global:latest'
COMMODITY_CACHE_KEY = 'commodity_tracker_cache'


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
# Draft name-reconciliation map: commodity/rhetoric id  ->  kinetic name.
# Most ids title-case cleanly (iran -> Iran). These are the exceptions.
# The probe reports residual mismatches so we can grow this map honestly.
# ----------------------------------------------------------------------
ID_TO_KINETIC_NAME = {
    'usa':          'United States',
    'uae':          'United Arab Emirates',
    'drc':          'DR Congo',
    'south_korea':  'South Korea',
    'south_africa': 'South Africa',
    'saudi_arabia': 'Saudi Arabia',
    'eu':           None,   # supranational -- no single kinetic country
}


def _id_to_kinetic_name(cid):
    """Best-effort map a lowercase country id to a kinetic display name."""
    if cid in ID_TO_KINETIC_NAME:
        return ID_TO_KINETIC_NAME[cid]
    return cid.replace('_', ' ').title()


def _summarize_kinetic(kin):
    """Pull a compact, schema-tolerant summary of the kinetic cache."""
    if not kin:
        return {'present': False}
    countries = kin.get('countries', {}) or {}
    non_normal = {
        c: b.get('band')
        for c, b in countries.items()
        if b.get('band') and b.get('band') != 'normal'
    }
    return {
        'present':       True,
        'generated_at':  kin.get('generated_at'),
        'from_cache':    kin.get('from_cache'),
        'total_events':  kin.get('total_events'),
        'country_count': len(countries),
        'countries_hot': kin.get('countries_hot'),
        'non_normal':    dict(sorted(non_normal.items(),
                                     key=lambda kv: countries[kv[0]].get('conflict_score', 0),
                                     reverse=True)),
        'name_sample':   list(countries.keys())[:12],
    }


def _summarize_commodity(com):
    """
    Schema-tolerant summary of the commodity cache. We don't assume the
    exact nesting -- we report the top-level keys and try the most likely
    per-commodity paths, recording which one actually carried alert_levels.
    """
    if not com:
        return {'present': False}
    out = {
        'present':       True,
        'cached_at':     com.get('cached_at'),
        'top_level_keys': list(com.keys()),
        'alert_levels':  {},
        'path_used':     None,
    }
    # Candidate locations for the per-commodity summaries, most-likely first.
    candidates = [
        ('commodities', com.get('commodities')),
        ('summaries',   com.get('summaries')),
        ('root',        com),
    ]
    for path_name, blob in candidates:
        if not isinstance(blob, dict):
            continue
        found = {}
        for cid, cdata in blob.items():
            if isinstance(cdata, dict) and 'alert_level' in cdata:
                found[cid] = cdata.get('alert_level')
        if found:
            out['alert_levels'] = found
            out['path_used'] = path_name
            break
    return out


def register_convergence_detector_endpoints(app):
    """Register the convergence-detector probe endpoints on the ME Flask app."""

    @app.route('/api/cax/probe', methods=['GET'])
    def cax_probe():
        """
        STEP 1 read-probe. Dumps what the kinetic + commodity caches contain
        and how their country vocabularies reconcile. No scoring.
        """
        from flask import jsonify

        # --- Axis 1: kinetic (read-only) ---
        kin = _redis_get(KINETIC_CACHE_KEY)
        kin_summary = _summarize_kinetic(kin)
        kin_names = set((kin or {}).get('countries', {}).keys())

        # --- Axis 2: commodity (read-only cache + static exposure config) ---
        com = _redis_get(COMMODITY_CACHE_KEY)
        com_summary = _summarize_commodity(com)

        exposure_ids, exposure_err = [], None
        try:
            from commodity_tracker import COUNTRY_COMMODITY_EXPOSURE
            exposure_ids = list(COUNTRY_COMMODITY_EXPOSURE.keys())
        except Exception as e:
            exposure_err = str(e)[:200]

        # --- Name reconciliation (the integration risk made visible) ---
        matched, unmatched = [], []
        for cid in sorted(exposure_ids):
            mapped = _id_to_kinetic_name(cid)
            if mapped is None:
                continue
            (matched if mapped in kin_names else unmatched).append(f"{cid} -> {mapped}")

        return jsonify({
            'success':       True,
            'step':          '1 (read-probe, no scoring)',
            'version':       '0.1.0',
            'probed_at':     datetime.now(timezone.utc).isoformat(),
            'redis_configured': bool(_REDIS_URL and _REDIS_TOKEN),
            'kinetic':       kin_summary,
            'commodity':     com_summary,
            'exposure': {
                'country_count': len(exposure_ids),
                'import_error':  exposure_err,
                'country_ids':   sorted(exposure_ids),
            },
            'name_reconciliation': {
                'note': 'commodity country-ids checked against kinetic display-names',
                'matched_count':   len(matched),
                'unmatched_count': len(unmatched),
                'unmatched':       unmatched,   # these need alias entries before we join
            },
            'rhetoric': {'present': False, 'note': 'wired in Step 2'},
        })

    print("[ConvergenceDetector] Registered: /api/cax/probe  (v0.1.0 read-probe)")
