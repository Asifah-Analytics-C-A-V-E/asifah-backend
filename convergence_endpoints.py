"""
═══════════════════════════════════════════════════════════════════════
  ASIFAH ANALYTICS — CONVERGENCE REGISTRY ENDPOINTS
  v1.1.0 (May 23 2026)
═══════════════════════════════════════════════════════════════════════

HTTP-facing endpoints for convergence_registry.py. Lives on the ME
backend alongside the registry. Other regional backends (Asia, Europe,
WHA) consume these endpoints via their per-backend proxy modules.

ARCHITECTURE:
  ME backend (canonical convergence_registry.py)
    └─→ /api/convergence/<id>             — single entry
    └─→ /api/convergence/all              — full registry
    └─→ /api/convergence/by-country/<c>   — country-filtered list
    └─→ /api/convergence/by-region/<r>    — region-filtered list
    └─→ /api/convergence/by-commodity/<c> — commodity-filtered list (v1.1)

CONSUMED BY:
  - Asia backend  → convergence_proxy_asia.py
  - Europe backend → convergence_proxy_europe.py (future)
  - WHA backend   → convergence_proxy_wha.py (future)
  - GPI (lives on ME backend, reads registry directly)
  - ME BLUF (lives on ME backend, reads registry directly)

WHY SPLIT FROM REGISTRY:
  - convergence_registry.py stays as a pure-data + helpers module
  - This file owns the HTTP layer (Flask, jsonify, request handling)
  - Cleaner separation of concerns

USAGE FROM ME BACKEND app.py:
    from convergence_endpoints import register_convergence_endpoints
    register_convergence_endpoints(app)
"""

from datetime import datetime, timezone
from flask import jsonify, request

try:
    from convergence_registry import (
        CONVERGENCE_REGISTRY,
        find_convergence_by_country_commodity,
        find_convergences_for_country,
        find_convergence_by_trigger,
    )
    REGISTRY_AVAILABLE = True
except ImportError as e:
    print(f"[Convergence Endpoints] ⚠️ convergence_registry not available: {e}")
    REGISTRY_AVAILABLE = False
    CONVERGENCE_REGISTRY = []


def _serialize_entry(entry):
    """
    Strip any internal-only fields before returning over HTTP.
    Keeps the public schema clean.
    """
    if not entry:
        return None
    # Currently the registry has no truly private fields, but we use
    # this helper to enable future field-level filtering if needed.
    return dict(entry)


def register_convergence_endpoints(app):
    """
    Register convergence registry HTTP endpoints on the ME backend Flask app.
    """

    @app.route('/api/convergence/all', methods=['GET'])
    def convergence_all():
        """Return the full convergence registry."""
        if not REGISTRY_AVAILABLE:
            return jsonify({
                'success': False,
                'error':   'Registry module not loaded',
                'registry': [],
            }), 503
        try:
            entries = [_serialize_entry(e) for e in CONVERGENCE_REGISTRY]
            return jsonify({
                'success':       True,
                'count':         len(entries),
                'registry':      entries,
                # Alias for proxy backwards compatibility
                'convergences':  entries,
                'fetched_at':    datetime.now(timezone.utc).isoformat(),
                'version':       '1.1.0',
            })
        except Exception as e:
            print(f"[Convergence Endpoints] /all error: {e}")
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/convergence/<conv_id>', methods=['GET'])
    def convergence_single(conv_id):
        """Return a single convergence entry by ID."""
        if not REGISTRY_AVAILABLE:
            return jsonify({'success': False, 'error': 'Registry not loaded'}), 503
        try:
            entry = next(
                (e for e in CONVERGENCE_REGISTRY if e.get('id') == conv_id),
                None
            )
            if entry is None:
                return jsonify({
                    'success': False,
                    'error':   f'Convergence "{conv_id}" not in registry',
                    'id':      conv_id,
                }), 404
            return jsonify({
                'success':    True,
                'id':         conv_id,
                'data':       _serialize_entry(entry),
                'fetched_at': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            print(f"[Convergence Endpoints] /{conv_id} error: {e}")
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/convergence/by-country/<country>', methods=['GET'])
    def convergence_by_country(country):
        """Return all convergences relevant to a given country."""
        if not REGISTRY_AVAILABLE:
            return jsonify({'success': False, 'error': 'Registry not loaded'}), 503
        try:
            country = country.lower()
            matches = [
                _serialize_entry(e)
                for e in CONVERGENCE_REGISTRY
                if e.get('country', '').lower() == country
                or country in [r.lower() for r in (e.get('regions') or [])]
            ]
            return jsonify({
                'success':    True,
                'country':    country,
                'count':      len(matches),
                'matches':    matches,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/convergence/by-region/<region>', methods=['GET'])
    def convergence_by_region(region):
        """Return all convergences for a given trigger_region (me, asia, europe, wha)."""
        if not REGISTRY_AVAILABLE:
            return jsonify({'success': False, 'error': 'Registry not loaded'}), 503
        try:
            region = region.lower()
            matches = [
                _serialize_entry(e)
                for e in CONVERGENCE_REGISTRY
                if e.get('trigger_region', '').lower() == region
                or region in [r.lower() for r in (e.get('regions') or [])]
            ]
            return jsonify({
                'success':    True,
                'region':     region,
                'count':      len(matches),
                'matches':    matches,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

    @app.route('/api/convergence/by-commodity/<commodity>', methods=['GET'])
    def convergence_by_commodity(commodity):
        """
        Return all convergences anchored on a given commodity.

        Useful for surfacing all convergence narratives that involve, e.g.,
        diamonds, cobalt, or phosphate. Matches the registry entry's
        'commodity' field (not 'top_producers' / 'top_consumers').

        Examples:
            /api/convergence/by-commodity/diamonds  -> diamonds_sanctions_regime
            /api/convergence/by-commodity/cobalt    -> cobalt_drc_active
            /api/convergence/by-commodity/oil       -> hormuz_china_oil_dependency
        """
        if not REGISTRY_AVAILABLE:
            return jsonify({'success': False, 'error': 'Registry not loaded'}), 503
        try:
            commodity = commodity.lower()
            matches = [
                _serialize_entry(e)
                for e in CONVERGENCE_REGISTRY
                if (e.get('commodity') or '').lower() == commodity
            ]
            return jsonify({
                'success':    True,
                'commodity':  commodity,
                'count':      len(matches),
                'matches':    matches,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 500

        print("[Convergence Endpoints] ✅ Registered: "
          "/api/convergence/all, /<id>, /by-country/<c>, /by-region/<r>, /by-commodity/<c>")
