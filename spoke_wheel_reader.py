"""
spoke_wheel_reader.py
Asifah Analytics -- SHARED MODULE (deploy byte-identical to ALL backends)
v1.0.2 -- July 25, 2026

One reader for the whole spoke-and-wheel architecture. Give it a hub and it
returns that hub's rim; give it a country list and it returns what those
countries are feeding outward.

────────────────────────────────────────────────────────────────────────────
WHY THIS LIVES ON EVERY BACKEND (and is NOT proxied to one)
────────────────────────────────────────────────────────────────────────────
The proxy pattern (commodity_proxy_africa, etc.) exists because a DATA
PRODUCER lives on one backend. Here there is no producer to proxy to -- the
producer is shared Upstash Redis, and every backend already holds the
credentials. A proxied reader would mean Europe makes an HTTP call to ME so
that ME can read a key Europe could read directly: a network hop, a timeout
risk on every BLUF build, and a single point of failure where ME going down
darkens every region's wheel panel.

So this follows the gdelt_gateway.py precedent: ONE file, byte-identical,
deployed everywhere. Proxy-don't-clone governs DATA. This is LIBRARY CODE.

────────────────────────────────────────────────────────────────────────────
THE THREE CONVENTIONS (this module's core job)
────────────────────────────────────────────────────────────────────────────
Spoke data accumulated under three different naming schemes as the
architecture grew. The fragmentation is why cross-hub reads kept coming back
empty -- the Azerbaijan `present:false` mystery, and Somalia's Turkey read
that was dead from the day it was written. Both were connected pipes
returning nothing, with nothing anywhere saying so.

  1. spoke:{hub}:{country}              -- hub-first, explicit, richest.
                                          Turkey + China wheels.
                                          (azerbaijan, armenia, greece,
                                           cyprus, kazakhstan)
  2. crosstheater:{country}:fingerprint -- canonical, hub-AGNOSTIC.
                                          What the Russia wheel reads.
                                          (ukraine, belarus, hungary, poland,
                                           greenland, kazakhstan, armenia,
                                           azerbaijan, sudan, somalia...)
  3. rhetoric:crosstheater:fingerprints -- collective dict, one slice per
     + fingerprint:{hub}:{key}            entity. What TURKEY writes as a hub.

This module reads all three and returns ONE shape. New conventions can be
added in _resolve_spoke() without touching any caller.

────────────────────────────────────────────────────────────────────────────
DISCOVERY-FIRST (the flexibility requirement)
────────────────────────────────────────────────────────────────────────────
Spokes are DISCOVERED by Redis SCAN, not declared in a hardcoded roster:

    SCAN MATCH 'spoke:*'                    -> hub AND country parsed from key
    SCAN MATCH 'crosstheater:*:fingerprint' -> country parsed; hub affinity
                                               inferred from payload shape

A new tracker that writes `spoke:china:mali` appears in the China wheel on
the next scan with ZERO code change here -- and so does the China wheel
itself, if it did not previously exist. The optional HUB_REGISTRY below only
supplies display names and polarity for spokes already found; it never gates
discovery. Adding Wagner spokes across the Sahel requires no edit to this file.

────────────────────────────────────────────────────────────────────────────
THREE STATES (absence-honesty)
────────────────────────────────────────────────────────────────────────────
  lit           -- fresh data at/above threshold. The spoke is active.
  dark          -- fresh data below threshold. The spoke is QUIET.
  not_reporting -- no key, or data older than the freshness gate. The spoke
                   is SILENT, which is a different fact entirely.

Conflating "quiet" with "silent" reads a plumbing gap as calm. That failure
mode has cost this platform real analytical accuracy three separate times
(the 0-article L0, the false russia_plug convergence note, the dead Turkey
read). A panel that renders NOT REPORTING turns the emission gap into
something visible -- the panel doubles as the build to-do list.

PUBLIC API:
    read_wheel(hub, ...)              -> one hub's rim (INBOUND)
    read_emanating(countries, ...)    -> local countries feeding foreign hubs
    discover_hubs(...)                -> every hub with at least one spoke
    build_convergence_panel(...)      -> the full panel dict for a BLUF payload

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import requests
from datetime import datetime, timezone

__version__ = '1.0.2'

# ============================================================
# CONFIG
# ============================================================
UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))

COLLECTIVE_KEY = 'rhetoric:crosstheater:fingerprints'

DEFAULT_FRESHNESS_HOURS = 24    # older than this = not_reporting (stale)
DEFAULT_LIT_THRESHOLD   = 2     # level >= this = lit
SCAN_COUNT              = 500
SCAN_MAX_PAGES          = 20    # ceiling; keyspace is small, this is paranoia

# Optional. Supplies DISPLAY NAMES and POLARITY for spokes already discovered.
# NEVER gates discovery -- an unknown spoke still surfaces, just with a
# title-cased name and node_class 'unclassified'. Node classes follow the
# taxonomy in HANDOVER_RUSSIA_WHEEL.md.
HUB_REGISTRY = {
    'russia': {
        'title': 'RUSSIA WHEEL',
        'icon': '\U0001F1F7\U0001F1FA',
        'node_classes': {
            'belarus': 'aligned_multiplier', 'ukraine': 'adversary',
            'hungary': 'axis_reversal_watch', 'azerbaijan': 'friction',
            'armenia': 'friction', 'kazakhstan': 'friction',
            'greenland': 'inbound_target', 'poland': 'inbound_target',
            'moldova': 'inbound_target', 'syria': 'ruptured',
            'sudan': 'expeditionary_client', 'libya': 'expeditionary_client',
            'venezuela': 'expeditionary_client', 'cuba': 'expeditionary_client',
            'mali': 'expeditionary_client', 'niger': 'expeditionary_client',
            'burkina_faso': 'expeditionary_client', 'car': 'expeditionary_client',
            'iran': 'peer', 'china': 'peer', 'dprk': 'peer',
        },
    },
    'turkey': {
        'title': 'TURKEY WHEEL',
        'icon': '\U0001F1F9\U0001F1F7',
        'node_classes': {
            'azerbaijan': 'aligned_multiplier', 'cyprus': 'adversary',
            'greece': 'adversary', 'armenia': 'normalisation_track',
            'syria': 'expeditionary_client', 'libya': 'expeditionary_client',
            'somalia': 'expeditionary_client', 'kazakhstan': 'turkic_affinity',
        },
    },
    'iran': {
        'title': 'IRAN WHEEL',
        'icon': '\U0001F1EE\U0001F1F7',
        'node_classes': {
            'yemen': 'proxy', 'lebanon': 'proxy', 'iraq': 'proxy', 'gaza': 'proxy',
            'syria': 'ruptured', 'oman': 'mediation', 'qatar': 'mediation',
            'azerbaijan': 'friction', 'saudi_arabia': 'friction',
            'bahrain': 'friction', 'pakistan': 'friction', 'armenia': 'friction',
            'russia': 'peer', 'china': 'peer',
        },
    },
    'china': {
        'title': 'CHINA WHEEL',
        'icon': '\U0001F1E8\U0001F1F3',
        'node_classes': {
            'kazakhstan': 'bri_corridor', 'pakistan': 'bri_corridor',
            'taiwan': 'adversary', 'russia': 'peer', 'iran': 'peer',
            'dprk': 'client',
        },
    },
    'israel': {'title': 'ISRAEL WHEEL', 'icon': '\U0001F1EE\U0001F1F1', 'node_classes': {}},
    'dprk':   {'title': 'DPRK WHEEL',   'icon': '\U0001F1F0\U0001F1F5', 'node_classes': {}},
    'us':     {'title': 'US WHEEL',     'icon': '\U0001F1FA\U0001F1F8', 'node_classes': {}},
}

# Payload fields that betray hub affinity on a hub-AGNOSTIC canonical
# fingerprint. Checked when a country writes crosstheater:{c}:fingerprint
# without saying which wheel it belongs to. Extend freely -- unknown shapes
# simply do not infer, they never crash.
_HUB_AFFINITY_HINTS = {
    'russia': ('russia_plug', 'russia_spoke', 'russia_axis', 'russia_iran_axis',
               'wagner', 'africa_corps'),
    'turkey': ('turkey_spoke', 'turkey_vector', 'turkey_axis', 'turksom'),
    'iran':   ('iran_spoke', 'iran_axis', 'proxy_activation_level',
               'unity_of_fronts_level'),
    'china':  ('china_spoke', 'china_axis', 'bri', 'belt_and_road'),
    'israel': ('israel_spoke', 'israel_somaliland'),
}


# ============================================================
# REDIS PRIMITIVES  (command-array POST -- proven across all backends)
# ============================================================
def _redis_cmd(args, timeout=8):
    """Execute one Upstash REST command. Returns the raw 'result' or None."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    if not UPSTASH_REDIS_URL.startswith('http'):
        return None
    try:
        resp = requests.post(
            UPSTASH_REDIS_URL,
            headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN},
            json=args, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.json().get('result')
    except Exception:
        return None


def _redis_alive():
    """Is Redis actually reachable?

    Load-bearing since the registry supplies an expected roster: without this
    probe, an unreachable Redis renders a full wheel of NOT REPORTING that is
    indistinguishable from a rim where nobody emits. Those are different
    problems -- one is an outage, one is a build gap -- and the panel must not
    conflate them.
    """
    return _redis_cmd(['PING'], timeout=5) is not None


def _redis_get_json(key):
    """GET + json.loads, tolerant of already-decoded values."""
    raw = _redis_cmd(['GET', key], timeout=6)
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _scan_keys(pattern, max_pages=SCAN_MAX_PAGES):
    """Cursor-paginated SCAN. Returns a list of matching key names.

    SCAN rather than KEYS: KEYS blocks the server on large keyspaces, and this
    module is called during BLUF builds. The keyspace here is small, but the
    habit is cheap and the failure mode is not.
    """
    keys, cursor, pages = [], '0', 0
    while pages < max_pages:
        res = _redis_cmd(['SCAN', cursor, 'MATCH', pattern, 'COUNT', str(SCAN_COUNT)])
        if not res or not isinstance(res, list) or len(res) < 2:
            break
        cursor = str(res[0])
        batch = res[1]
        if isinstance(batch, list):
            keys.extend(str(k) for k in batch)
        pages += 1
        if cursor == '0':
            break
    return sorted(set(keys))


# ============================================================
# HELPERS
# ============================================================
def _age_hours(ts):
    """Hours since an ISO timestamp. None when unparseable (never raises)."""
    if not ts:
        return None
    try:
        s = str(ts).replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    except Exception:
        return None


def _coerce_level(fp):
    """Coerce a level across every schema in the wild.

    Numeric `level` wins. Falls back to the alert_level string map that
    Turkey's collective slice uses (normal/elevated/high/critical -> 1-4),
    then to a handful of known level-ish fields. Returns 0, never raises.
    """
    if not isinstance(fp, dict):
        return 0
    for field in ('level', 'spoke_level', 'theatre_level', 'escalation_level'):
        v = fp.get(field)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(max(0, min(5, v)))
    alert = str(fp.get('alert_level') or fp.get('alert') or '').lower()
    mapped = {'normal': 1, 'elevated': 2, 'high': 3, 'critical': 4}.get(alert)
    if mapped is not None:
        return mapped
    return 0


_ACRONYMS = {'car': 'CAR', 'drc': 'DRC', 'uae': 'UAE', 'dprk': 'DPRK',
             'us': 'US', 'usa': 'USA', 'ksa': 'KSA', 'eu': 'EU', 'uk': 'UK'}


def _display(name):
    key = str(name).lower()
    if key in _ACRONYMS:
        return _ACRONYMS[key]
    return str(name).replace('_', ' ').replace('-', ' ').title()


def _node_class(hub, country):
    reg = HUB_REGISTRY.get(hub, {}) or {}
    return (reg.get('node_classes', {}) or {}).get(country, 'unclassified')


def _infer_hubs_from_payload(fp):
    """Which hubs does a hub-AGNOSTIC canonical fingerprint appear to serve?

    Canonical `crosstheater:{country}:fingerprint` does not name its wheel, so
    affinity is inferred from payload shape (a `russia_plug` block means this
    country is being read as a Russia spoke). Explicit `hub` / `hubs` fields
    win when present. Returns a set; empty when nothing is inferable, which is
    an honest answer rather than a guess.
    """
    hubs = set()
    if not isinstance(fp, dict):
        return hubs
    explicit = fp.get('hub')
    if isinstance(explicit, str) and explicit:
        hubs.add(explicit.lower())
    for h in (fp.get('hubs') or []):
        if isinstance(h, str):
            hubs.add(h.lower())
    touches = fp.get('hub_touches')
    if isinstance(touches, dict):
        hubs.update(str(k).lower() for k in touches)
    flat = ' '.join(str(k).lower() for k in fp.keys())
    for hub, hints in _HUB_AFFINITY_HINTS.items():
        if any(hint in flat for hint in hints):
            hubs.add(hub)
    return hubs


# ============================================================
# RESOLUTION  (the three-convention normalizer)
# ============================================================
def _extract_hub_detail(fp, hub):
    """Pull the hub-SPECIFIC sub-object out of a hub-agnostic fingerprint.

    A canonical `crosstheater:{country}:fingerprint` often carries per-hub
    blocks with their OWN level:

        somalia -> {'level': 5, 'turkey_spoke': {'level': 2, 'note': ...},
                                'russia_spoke': {'level': 1, ...}}
        sudan   -> {'level': 4, 'russia_plug':  {'level': 0, ...}}

    Without this, an emanating read reports the COUNTRY's theatre level as its
    hub-touch level -- Somalia at L5 would read as a blazing Turkey spoke when
    its actual Turkey level is 2. Wrong number, confidently displayed, which is
    worse than no number.

    Returns a merged dict (sub-object level wins) or None when no hub-specific
    block exists.
    """
    if not isinstance(fp, dict):
        return None
    candidates = ['%s_spoke' % hub, '%s_plug' % hub, '%s_axis' % hub, '%s_touch' % hub]
    if hub == 'israel':
        candidates.append('israel_somaliland')     # Somalia's naming
    for name in candidates:
        sub = fp.get(name)
        if isinstance(sub, dict) and sub:
            merged = dict(fp)
            merged['level'] = sub.get('level', 0)
            merged['hub_block'] = name
            note = sub.get('note') or sub.get('top_signal') or ''
            if note:
                merged['top_signal'] = note
            if 'active' in sub:
                merged['hub_active'] = bool(sub.get('active'))
            return merged
    return None


def _resolve_spoke(hub, country, collective=None):
    """Find (hub, country) across all three conventions. First hit wins.

    Order is by descending confidence:
      1. spoke:{hub}:{country}              -- explicit, hub-first, richest
      2. crosstheater:{country}:fingerprint -- canonical, hub-agnostic
      3. collective dict slice [country]    -- shared registry
      4. collective dict slice [hub]        -- hub self-report naming country
                                              among its lit theatres
    Returns (payload, source_label) or (None, 'absent').

    To add a fourth convention later, add a branch here. No caller changes.
    """
    fp = _redis_get_json('spoke:%s:%s' % (hub, country))
    if isinstance(fp, dict) and fp:
        return fp, 'spoke_key'

    fp = _redis_get_json('crosstheater:%s:fingerprint' % country)
    if isinstance(fp, dict) and fp:
        # Prefer the hub-specific block when the fingerprint carries one --
        # otherwise the country's theatre level masquerades as its hub level.
        detail = _extract_hub_detail(fp, hub)
        if detail is not None:
            return detail, 'canonical_hub_block'
        return fp, 'canonical'

    if collective is None:
        collective = _redis_get_json(COLLECTIVE_KEY) or {}
    if isinstance(collective, dict):
        slice_ = collective.get(country)
        if isinstance(slice_, dict) and slice_:
            return slice_, 'collective'
        # Hub self-report: Turkey's Erdogan Projection Node names the theatres
        # it is lit in. A hub declaring presence is stronger evidence than a
        # spoke inferring it.
        hub_slice = collective.get(hub)
        if isinstance(hub_slice, dict):
            lit = [str(x).lower() for x in (hub_slice.get('projection_lit_theaters') or [])]
            if country in lit:
                return ({'level': _coerce_level(hub_slice),
                         'ts': hub_slice.get('ts'),
                         'hub_declared': True,
                         'projection_band': hub_slice.get('projection_band', ''),
                         'top_signal': '%s names %s among its lit theatres'
                                       % (_display(hub), _display(country))},
                        'hub_declared')
    return None, 'absent'


def _spoke_state(fp, source, freshness_hours, lit_threshold):
    """Classify a resolved spoke as lit / dark / not_reporting.

    not_reporting covers BOTH absence and staleness, carrying a `reason` so a
    caller can tell them apart. Both mean the same thing analytically -- we do
    not currently know -- which is categorically different from 'quiet'.
    """
    if fp is None:
        return {'state': 'not_reporting', 'reason': 'absent', 'level': 0,
                'age_hours': None}
    age = _age_hours(fp.get('ts') or fp.get('timestamp') or fp.get('scanned_at'))
    level = _coerce_level(fp)
    if age is not None and age > freshness_hours:
        return {'state': 'not_reporting', 'reason': 'stale', 'level': level,
                'age_hours': round(age, 1)}
    state = 'lit' if level >= lit_threshold else 'dark'
    return {'state': state, 'reason': '', 'level': level,
            'age_hours': round(age, 1) if age is not None else None}


# ============================================================
# DISCOVERY
# ============================================================
def discover_spokes():
    """SCAN the keyspace and return {hub: set(countries)}.

    THIS is the flexibility guarantee. Nothing here is hardcoded: a tracker
    that starts writing spoke:china:mali puts Mali on the China wheel on the
    next scan, and creates the China wheel if it did not exist.

    Two passes:
      * spoke:{hub}:{country} -- hub is explicit in the key
      * crosstheater:{country}:fingerprint -- hub affinity inferred from the
        payload (see _infer_hubs_from_payload)
    """
    found = {}

    for key in _scan_keys('spoke:*'):
        parts = key.split(':')
        if len(parts) != 3:
            continue
        _, hub, country = parts
        if not hub or not country:
            continue          # guards malformed keys like 'spoke:turkey:'
        found.setdefault(hub.lower(), set()).add(country.lower())

    for key in _scan_keys('crosstheater:*:fingerprint'):
        parts = key.split(':')
        if len(parts) != 3:
            continue
        country = parts[1].lower()
        if not country:
            continue
        fp = _redis_get_json(key)
        for hub in _infer_hubs_from_payload(fp):
            if hub != country:            # a hub is not its own spoke
                found.setdefault(hub, set()).add(country)

    return found


def discover_hubs():
    """Every hub with at least one discoverable spoke, plus its spoke count."""
    spokes = discover_spokes()
    return sorted(
        ({'hub': h, 'title': (HUB_REGISTRY.get(h, {}) or {}).get('title',
                              '%s WHEEL' % _display(h).upper()),
          'icon': (HUB_REGISTRY.get(h, {}) or {}).get('icon', '\u2699\uFE0F'),
          'spoke_count': len(c)} for h, c in spokes.items()),
        key=lambda x: (-x['spoke_count'], x['hub']))


# ============================================================
# PUBLIC API
# ============================================================
def read_wheel(hub, extra_spokes=None, freshness_hours=DEFAULT_FRESHNESS_HOURS,
               lit_threshold=DEFAULT_LIT_THRESHOLD, converge_at=2):
    """INBOUND read: one hub's whole rim.

    hub           -- 'russia', 'turkey', 'iran', 'china', ...
    extra_spokes  -- optional countries to check even if discovery missed them.
                     Use for spokes known to be planned but not yet emitting:
                     they render NOT REPORTING, which is the honest state and
                     also a visible build to-do.
    converge_at   -- lit spokes required before `converged` is True.

    Never raises. On total Redis failure returns an empty wheel flagged
    unreadable rather than an empty wheel that looks quiet.
    """
    hub = str(hub).lower()
    out = {
        'hub': hub,
        'title': (HUB_REGISTRY.get(hub, {}) or {}).get('title', '%s WHEEL' % _display(hub).upper()),
        'icon': (HUB_REGISTRY.get(hub, {}) or {}).get('icon', '\u2699\uFE0F'),
        'spokes': [], 'lit_count': 0, 'dark_count': 0, 'unreported_count': 0,
        'converged': False, 'readable': True,
        'freshness_hours': freshness_hours,
    }
    try:
        if not _redis_alive():
            out['readable'] = False
            out['note'] = ('Redis unreachable this cycle -- the %s wheel cannot be read at '
                           'all. This is an OUTAGE, not a silent rim: no inference about '
                           'spoke activity should be drawn from this panel.' % _display(hub))
            return out

        # Roster = DISCOVERED  |  registry-expected  |  caller-supplied.
        #
        # Discovery is the source of truth for what EXISTS; the registry is the
        # source of truth for what SHOULD exist. A country whose canonical
        # fingerprint carries no hub-affinity marker (Poland writes one with no
        # `russia_*` field) is undiscoverable as a Russia spoke -- and would
        # silently vanish from the wheel rather than showing as a gap. Union-ing
        # the registry makes the gap visible as NOT REPORTING.
        #
        # This does NOT gate discovery: a spoke:china:mali key still creates a
        # Mali entry on the China wheel with no registry edit.
        discovered = discover_spokes().get(hub, set())
        # Peers (Iran/China/DPRK on the Russia wheel) are WHEEL-TO-WHEEL, not
        # rim spokes -- the Iran scoping note is explicit that they must not be
        # double-counted as proxies. They still appear if genuinely discovered;
        # they are simply not force-rendered as missing rim.
        _classes = (HUB_REGISTRY.get(hub, {}) or {}).get('node_classes', {}) or {}
        expected = {c for c, nc in _classes.items() if nc != 'peer'}
        roster = sorted(discovered | expected | {str(c).lower() for c in (extra_spokes or [])})
        if not roster:
            out['readable'] = False
            out['note'] = ('No spokes discoverable for the %s wheel. Either no tracker '
                           'emits for this hub yet, or Redis is unreachable -- these are '
                           'different problems and this module cannot tell them apart '
                           'from here.' % _display(hub))
            return out

        collective = _redis_get_json(COLLECTIVE_KEY) or {}
        for country in roster:
            fp, source = _resolve_spoke(hub, country, collective=collective)
            st = _spoke_state(fp, source, freshness_hours, lit_threshold)
            fp = fp or {}
            out['spokes'].append({
                'country': country,
                'display': _display(country),
                'hub': hub,
                'level': st['level'],
                'state': st['state'],
                'reason': st['reason'],
                'age_hours': st['age_hours'],
                'source': source,
                'node_class': fp.get('node_class') or _node_class(hub, country),
                'relationship': fp.get('relationship', ''),
                'direction': fp.get('direction', ''),
                'hub_declared': bool(fp.get('hub_declared')),
                'top_signal': str(fp.get('top_signal', ''))[:180],
            })

        out['lit_count'] = sum(1 for s in out['spokes'] if s['state'] == 'lit')
        out['dark_count'] = sum(1 for s in out['spokes'] if s['state'] == 'dark')
        out['unreported_count'] = sum(1 for s in out['spokes'] if s['state'] == 'not_reporting')
        out['converged'] = out['lit_count'] >= converge_at
        out['spokes'].sort(key=lambda s: (-s['level'], s['country']))

        lit_names = [s['display'] for s in out['spokes'] if s['state'] == 'lit']
        if out['converged']:
            out['headline'] = (
                '%d spokes lit simultaneously on the %s wheel (%s) -- consistent with '
                'network activation rather than single-country noise.'
                % (out['lit_count'], _display(hub), ', '.join(lit_names)))
        elif out['lit_count'] == 1:
            out['headline'] = ('One %s spoke lit (%s). A lone spoke rides up independently; '
                               'convergence fires only when two or more light at once.'
                               % (_display(hub), lit_names[0]))
        else:
            out['headline'] = ''
        out['dormant_note'] = _dormant_note(out, hub)
    except Exception as e:
        out['readable'] = False
        out['note'] = 'Wheel read failed: %s' % str(e)[:120]
    return out


def _dormant_note(wheel, hub):
    """Say which kind of nothing this is."""
    lit, dark, unrep = wheel['lit_count'], wheel['dark_count'], wheel['unreported_count']
    total = lit + dark + unrep
    if lit >= 2:
        return ''
    if unrep and unrep == total:
        return ('No %s spoke is reporting this cycle. The rim is SILENT, not quiet -- '
                'these spokes are not emitting, so absence here is a gap in coverage '
                'rather than a finding about the theatre.' % _display(hub))
    if unrep:
        return ('%d of %d %s spokes are quiet; %d are not reporting at all. Convergence '
                'fires only when two or more light at once -- and a spoke that is silent '
                'cannot contribute to that read either way.'
                % (dark, total, _display(hub), unrep))
    return ('No %s convergence this cycle. Every spoke is reporting and quiet; each rides '
            'to the regional BLUF independently, and convergence fires only when two or '
            'more light at once.' % _display(hub))


def read_emanating(countries, exclude_hubs=(), freshness_hours=DEFAULT_FRESHNESS_HOURS,
                   lit_threshold=DEFAULT_LIT_THRESHOLD, include_silent=False):
    """OUTBOUND read: which FOREIGN hubs are these countries feeding?

    This is the half that rides to the GPI. A region owns certain hubs
    (Europe owns Russia and Turkey); everything its countries emit toward
    OTHER hubs -- Baku's Iran touch, Kazakhstan's China touch, Syria's Turkey
    touch -- emanates outward and belongs in the global read, not the local one.

    exclude_hubs -- the hubs resident in this region, so they are not
                    double-counted as emanating.
    """
    exclude = {str(h).lower() for h in (exclude_hubs or [])}
    wanted = {str(c).lower() for c in (countries or [])}
    out = []
    try:
        collective = _redis_get_json(COLLECTIVE_KEY) or {}
        for hub, spokes in discover_spokes().items():
            if hub in exclude:
                continue
            for country in sorted(spokes & wanted):
                fp, source = _resolve_spoke(hub, country, collective=collective)
                st = _spoke_state(fp, source, freshness_hours, lit_threshold)
                if st['state'] == 'not_reporting' and not include_silent:
                    # EXPORT path: a gap must never ride to the GPI as signal.
                    # DISPLAY path (include_silent=True) keeps it, because a
                    # known relationship that has gone quiet is exactly what the
                    # dormant panel exists to show.
                    continue
                fp = fp or {}
                out.append({
                    'country': country, 'display': _display(country),
                    'hub': hub, 'hub_display': _display(hub),
                    'hub_icon': (HUB_REGISTRY.get(hub, {}) or {}).get('icon', '\u2699\uFE0F'),
                    'level': st['level'], 'state': st['state'],
                    'source': source,
                    'node_class': fp.get('node_class') or _node_class(hub, country),
                    'top_signal': str(fp.get('top_signal', ''))[:180],
                })
        out.sort(key=lambda x: (-x['level'], x['hub'], x['country']))
    except Exception as e:
        print('[spoke_wheel_reader] emanating read failed: %s' % str(e)[:110])
    return out


def build_convergence_panel(resident_hubs, local_countries=(), extra_spokes=None,
                            freshness_hours=DEFAULT_FRESHNESS_HOURS,
                            lit_threshold=DEFAULT_LIT_THRESHOLD, region=''):
    """The full bidirectional panel, ready to drop into a BLUF payload.

    resident_hubs   -- hubs whose wheel lives in this region.
                       Europe ['russia','turkey'] · ME ['iran'] · Asia ['china']
                       Africa [] (no resident hub -- pure emanating)
    local_countries -- this region's countries, for the emanating half.
    extra_spokes    -- {hub: [countries]} to force-render as NOT REPORTING.

    Frontends render this generically: same markup for every region and the
    GPI. Adding a region is a backend call plus one HTML paste.
    """
    extra_spokes = extra_spokes or {}
    panel = {
        'schema_version': __version__,
        'region': region,
        'resident_wheels': [],
        'emanating': [],
        'any_converged': False,
        'disclaimer': ('This is a CONVERGENCE indicator, NOT a probability of action. '
                       'Each spoke is independently sourced; the reader completes the '
                       'inference.'),
    }
    try:
        for hub in (resident_hubs or []):
            w = read_wheel(hub, extra_spokes=extra_spokes.get(hub),
                           freshness_hours=freshness_hours, lit_threshold=lit_threshold)
            panel['resident_wheels'].append(w)
            if w.get('converged'):
                panel['any_converged'] = True

        # Read WITH silent entries, then split. `emanating` is the export set
        # (rides to the GPI); `emanating_silent` is display-only, so a region
        # with every spoke quiet still renders a dormant panel instead of
        # vanishing. A card that disappears when nothing is happening cannot
        # distinguish "quiet" from "broken" for the reader either.
        _all_eman = read_emanating(
            local_countries, exclude_hubs=resident_hubs,
            freshness_hours=freshness_hours, lit_threshold=lit_threshold,
            include_silent=True)
        panel['emanating'] = [e for e in _all_eman if e['state'] != 'not_reporting']
        panel['emanating_silent'] = [e for e in _all_eman if e['state'] == 'not_reporting']

        if not resident_hubs:
            panel['subtitle'] = ('No resident hub in this region -- every wheel read here '
                                 'is outbound. Spokes feed hubs that live elsewhere.')
            lit_n = sum(1 for e in panel['emanating'] if e['state'] == 'lit')
            if lit_n >= 2:
                panel['dormant_note'] = ''
            elif panel['emanating'] or panel['emanating_silent']:
                panel['dormant_note'] = (
                    'No multi-hub convergence this cycle. Each spoke rides outward '
                    'independently; convergence fires only when two or more light at '
                    'once. Spokes listed as not reporting are silent, not quiet -- '
                    'they are not emitting, which is a coverage gap rather than a '
                    'finding about the theatre.')
            else:
                panel['dormant_note'] = (
                    'No outbound spoke relationships discoverable this cycle. Either no '
                    'tracker in this region emits hub-affinity data yet, or the '
                    'keyspace is unreadable.')
        else:
            names = ' \u00b7 '.join(_display(h) for h in resident_hubs)
            panel['subtitle'] = '%s hubbed here \u2014 inbound rim reads' % names
    except Exception as e:
        panel['error'] = str(e)[:160]
    return panel
