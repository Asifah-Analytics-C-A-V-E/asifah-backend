"""
Asifah Analytics -- ME Actor Matrix v3.0.0
November 1, 2026

Replaces the v2 "multi-actor threat matrix" (/api/threat-matrix/<target>), which
was a seventh keyword scanner speaking in "strike probability %". v3 is a
READER: it scans nothing. Every cell is a directed pair (actor -> target) whose
level comes from the rhetoric trackers that already run, corroborate and gate
their own reads.

HOW A CELL IS READ
  1. Trackers are read through me_regional_bluf._read_all_trackers() -- the same
     reader the regional BLUF uses (live -> fallback key -> last-known-good), so
     the matrix and the BLUF can never disagree about what a tracker said.
  2. Each pair names its SOURCES: (tracker, match tokens, exclude tokens). A
     tracker vector matches when one of its name tokens is a match token and
     none is an exclude token (e.g. Israel's tracker: 'outbound' vectors feed
     Israel -> X, 'inbound' vectors feed X -> Israel).
  3. Cell level = highest matched vector level, CAPPED at that tracker's own
     theatre level. The theatre level is the gated, corroborated figure (L5
     reservation contract, 2+ source rule); a vector may not out-shout its own
     tracker.
  4. No tracker -> 'unread'. Tracker present but no vector matched -> 'not
     sensed'. Neither is ever shown as L0.

v3.1.0 (Nov 1 2026, after the first live /debug):
  - The Israel and Lebanon trackers expose no directional vectors (Israel: only
    government_formation / gaza_framework_gates; Lebanon: framework_gates), so every
    Israel pair read 'not sensed'. The Israel CARD (/api/israel-threat, the 6x6
    incoming/outgoing panel Rachel keeps) already carries those directions as
    keyword %. v3.1 reads it as a second source type: ('card:israel', 'path').
    Card % -> level: <10 L0, <25 L1, <45 L2, <65 L3, else L4. Capped at L4 -- a
    keyword count never asserts L5 (L5 assertion rule).
  - Gulf trackers' real names wired in: Saudi kinetic_inbound, UAE kinetic_inbound,
    Qatar gas_infrastructure -> Iran -> Gulf; Qatar base_posture -> Iran -> US forces.
  - New pairs: Iran -> Iraq (Iraq tracker iran_iraq), Israel -> Gaza, Hamas -> Israel.
  - Known tracker-side gap: the Iran tracker scores israel_iran and us_iran at 0
    while its theatre reads L5 -- tracker tuning, not matrix. (Fixed in Iran
    tracker v1.9.0: those buckets now carry inbound pressure.)

v3.2.0 (Nov 1 2026): Yemen tracker v2.2.0 emits corroborated, target-split vectors
  (maritime, strike_israel/saudi/uae/us, inbound_israel/us/saudi). Wired with
  all-token matches ('strike+israel'). Saudi 'kinetic_inbound' REMOVED from
  Iran -> Gulf: the live Yemen read attributes this autumn's strikes on Saudi
  Arabia to the Houthis (strike_saudi L5, 8 outlets). New pairs: Houthis -> US
  forces, Houthis -> UAE, US -> Houthis, Saudi-led coalition -> Houthis.

The vector names differ tracker to tracker. /api/threat-matrix-v3/debug lists
every tracker's vectors and which pair each one fed, so the token lists can be
tuned from what the trackers actually emit instead of from guesses.

ENDPOINTS
  /api/threat-matrix-v3               all pairs + headline + So What lines
  /api/threat-matrix-v3?actor=iran    pairs where iran is actor or target (for a country card)
  /api/threat-matrix-v3/debug         tracker vectors -> pair matching

Cost: Redis reads only (~12 trackers), cached 15 min. No external fetch, ever.
"""

import json
import re
import time
from datetime import datetime, timezone

MATRIX_VERSION = '3.2.0'
CACHE_KEY = 'threat_matrix_v3:latest'
PREV_KEY = 'threat_matrix_v3:previous_levels'
CACHE_SEC = 15 * 60

# Platform ladder words (severity_canon). Colours are the page's job (window.AsifahLadder).
LADDER = {0: 'Monitoring', 1: 'Rhetoric', 2: 'Warning', 3: 'Confrontation',
          4: 'Coercion', 5: 'Active Conflict', 6: 'Red Line Breached'}

# ----------------------------------------------------------------------------
# PAIRS -- the Nov 2026 board. 'keys' are the country/actor ids a card filter
# (?actor=) matches on. 'sources' = [(tracker, match_tokens, exclude_tokens)].
# ----------------------------------------------------------------------------
def _P(pid, actor, a_flag, target, t_flag, keys, sources, note=''):
    return {'id': pid, 'actor': actor, 'actor_flag': a_flag, 'target': target,
            'target_flag': t_flag, 'keys': keys, 'sources': sources, 'note': note}


ISR, LEB, IRN, USA, YEM, SYR, IRQ, SAU, EGY, TUR, GULF, SEA = (
    '🇮🇱', '🇱🇧', '🇮🇷', '🇺🇸', '🇾🇪', '🇸🇾', '🇮🇶', '🇸🇦', '🇪🇬', '🇹🇷', '🌐', '🚢')

PAIRS = [
    _P('israel>lebanon', 'Israel', ISR, 'Lebanon / Hizballah', LEB, ['israel', 'lebanon', 'hezbollah'],
       [('lebanon', ['israel', 'israeli', 'idf'], []),
        ('israel', ['lebanon', 'hezbollah', 'hizballah', 'northern'], ['inbound']),
        ('card:israel', 'outgoing_operations.vs_lebanon', None)]),
    _P('hizballah>israel', 'Hizballah', LEB, 'Israel', ISR, ['israel', 'lebanon', 'hezbollah'],
       [('israel', ['lebanon', 'hezbollah', 'hizballah', 'northern'], ['outbound']),
        ('lebanon', ['hezbollah', 'hizballah', 'resistance'], []),
        ('card:israel', 'incoming_threats.hezbollah', None)]),
    _P('israel>iran', 'Israel', ISR, 'Iran', IRN, ['israel', 'iran'],
       [('iran', ['israel', 'israeli', 'zionist'], []),
        ('israel', ['iran', 'iranian'], ['inbound']),
        ('card:israel', 'outgoing_operations.vs_iran', None)]),
    _P('iran>israel', 'Iran', IRN, 'Israel', ISR, ['israel', 'iran'],
       [('israel', ['iran', 'iranian'], ['outbound']),
        ('iran', ['retaliation', 'retaliate', 'response'], []),
        ('card:israel', 'incoming_threats.iran_direct', None)]),
    _P('us>iran', 'United States', USA, 'Iran', IRN, ['iran'],
       [('iran', ['us', 'usa', 'american', 'america', 'washington', 'trump', 'centcom'], [])]),
    _P('iran>us_forces', 'Iran & partners', IRN, 'US forces / Gulf bases', USA, ['iran', 'iraq'],
       [('iran', ['hormuz', 'bases', 'proxy', 'proxies'], []),
        ('iraq', ['us', 'american', 'coalition', 'bases'], []),
        ('qatar', ['base'], [])]),
    _P('iran>gulf', 'Iran', IRN, 'Gulf states', GULF, ['iran', 'saudi_arabia', 'uae', 'qatar', 'oman', 'bahrain', 'kuwait'],
       [('saudi_arabia', ['iran', 'iranian'], []), ('uae', ['iran', 'iranian', 'kinetic'], []),
        ('qatar', ['iran', 'iranian', 'gas'], []), ('oman', ['iran', 'iranian', 'hormuz'], [])],
       note='UAE "kinetic inbound" is read as Iran-led; Saudi inbound strikes are attributed to the Houthis by the Yemen tracker.'),
    _P('houthis>shipping', 'Houthis', YEM, 'Red Sea shipping / Suez', SEA, ['yemen', 'houthis', 'egypt'],
       [('yemen', ['maritime', 'shipping', 'mandeb'], []),
        ('egypt', ['suez'], [])]),
    _P('houthis>israel', 'Houthis', YEM, 'Israel', ISR, ['yemen', 'houthis', 'israel'],
       [('yemen', ['strike+israel'], []),
        ('israel', ['yemen', 'houthi', 'houthis'], ['outbound']),
        ('card:israel', 'incoming_threats.houthis', None)]),
    _P('israel>houthis', 'Israel', ISR, 'Houthis', YEM, ['yemen', 'houthis', 'israel'],
       [('israel', ['yemen', 'houthi', 'houthis'], ['inbound']),
        ('yemen', ['inbound+israel'], []),
        ('card:israel', 'outgoing_operations.vs_houthis', None)]),
    _P('us>houthis', 'United States', USA, 'Houthis', YEM, ['yemen', 'houthis'],
       [('yemen', ['inbound+us'], [])]),
    _P('coalition>houthis', 'Saudi-led coalition', SAU, 'Houthis', YEM, ['yemen', 'houthis', 'saudi_arabia'],
       [('yemen', ['inbound+saudi'], [])]),
    _P('houthis>us_forces', 'Houthis', YEM, 'US forces / ships', USA, ['yemen', 'houthis'],
       [('yemen', ['strike+us'], [])]),
    _P('houthis>uae', 'Houthis', YEM, 'UAE', '🇦🇪', ['yemen', 'houthis', 'uae'],
       [('yemen', ['strike+uae'], [])]),
    _P('houthis>saudi', 'Houthis', YEM, 'Saudi Arabia', SAU, ['yemen', 'houthis', 'saudi_arabia'],
       [('saudi_arabia', ['houthi', 'houthis', 'yemen'], []),
        ('yemen', ['strike+saudi'], [])]),
    _P('israel>syria', 'Israel', ISR, 'Syria', SYR, ['israel', 'syria'],
       [('syria', ['israel', 'israeli', 'idf', 'golan'], []),
        ('israel', ['syria', 'syrian'], ['inbound']),
        ('card:israel', 'outgoing_operations.vs_syria', None)]),
    _P('israel>gaza', 'Israel', ISR, 'Gaza', '🇵🇸', ['israel'],
       [('card:israel', 'outgoing_operations.vs_gaza', None)]),
    _P('hamas>israel', 'Hamas', '🇵🇸', 'Israel', ISR, ['israel'],
       [('card:israel', 'incoming_threats.hamas', None)]),
    _P('iran>iraq', 'Iran', IRN, 'Iraq (influence & proxies)', IRQ, ['iran', 'iraq'],
       [('iraq', ['iran'], [])]),
    _P('turkey>syria', 'Türkiye', TUR, 'Syria (north / SDF)', SYR, ['syria'],
       [('syria', ['turkey', 'turkish', 'turkiye'], [])],
       note='Türkiye\'s own tracker lives on the Europe backend; this cell reads the Syria tracker only.'),
    _P('militias>us', 'Iraqi armed factions', IRQ, 'US forces in Iraq / Syria', USA, ['iraq'],
       [('iraq', ['pmf', 'militia', 'militias', 'hashd', 'kataib', 'factions'], [])]),
    _P('sudan>egypt', 'Sudan war', '🇸🇩', 'Egypt (southern flank)', EGY, ['egypt'],
       [('egypt', ['southern'], [])]),
    _P('gaza>egypt', 'Gaza / Israel border', ISR, 'Egypt (eastern flank)', EGY, ['egypt', 'israel'],
       [('egypt', ['eastern'], [])]),
]

CARD_ALIASES = {'hezbollah': 'lebanon', 'houthis': 'yemen', 'saudi': 'saudi_arabia'}


def _now():
    return datetime.now(timezone.utc)


def _tokens(name):
    return set(t for t in re.split(r'[^a-z0-9]+', str(name).lower()) if t)


def _match(vector_name, match, exclude):
    """Any match item hits. An item written 'a+b' needs ALL of its tokens (v3.2:
    'strike+israel' must not fire on 'inbound_israel')."""
    tk = _tokens(vector_name)
    if tk & set(exclude or []):
        return False
    for m in match:
        parts = m.split('+')
        if all(p in tk for p in parts):
            return True
    return False


# ----------------------------------------------------------------------------
# TRACKER READ (shared with the regional BLUF)
# ----------------------------------------------------------------------------
def _bluf():
    import me_regional_bluf as b
    return b


def read_trackers():
    """-> {theatre: {'threat': int, 'freshness': str, 'vectors': {name: level}, 'so_what': str,
                     'scanned_at': str}}, missing list"""
    b = _bluf()
    results, missing, _stale = b._read_all_trackers()
    out = {}
    for th, n in results.items():
        raw = n.get('raw') or {}
        vecs = {}
        for k, v in (b._extract_vector_levels(raw) or {}).items():
            if b._is_multiplier_vector(k):
                continue
            lvl = v
            if isinstance(v, str):
                try:
                    import severity_canon as _canon
                    lvl = _canon.to_platform('rhetoric_band', v.strip().lower())
                except Exception:
                    lvl = None
            if isinstance(lvl, (int, float)) and not isinstance(lvl, bool):
                vecs[k] = max(0, min(6, int(lvl)))
        sw = n.get('so_what') or {}
        out[th] = {
            'threat': int((n.get('levels') or {}).get('threat') or 0),
            'freshness': n.get('freshness', 'live'),
            'vectors': vecs,
            'so_what': (sw.get('factor') if isinstance(sw, dict) else str(sw)) or '',
            'scanned_at': n.get('scanned_at', ''),
        }
    return out, list(missing)


# ----------------------------------------------------------------------------
# CARD SOURCES (v3.1) -- the ME page's own country cards, cached by app.py
# under threat:<target>. Keyword %, so capped at L4.
# ----------------------------------------------------------------------------
CARD_STALE_HOURS = 48


def pct_to_level(p):
    p = float(p or 0)
    return 0 if p < 10 else 1 if p < 25 else 2 if p < 45 else 3 if p < 65 else 4


def read_cards(redis_get, names=('israel',)):
    out = {}
    for n in names:
        try:
            c = redis_get(f'threat:{n}')
        except Exception:
            c = None
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except ValueError:
                c = None
        if isinstance(c, dict):
            fresh = 'live'
            try:
                age = (_now() - datetime.fromisoformat(str(c.get('cached_at')).replace('Z', '+00:00'))).total_seconds()
                if age > CARD_STALE_HOURS * 3600:
                    fresh = 'stale'
            except Exception:
                pass
            out[n] = {'data': c, 'freshness': fresh}
    return out


def _dig(d, path):
    for k in path.split('.'):
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# ----------------------------------------------------------------------------
# CELL + MATRIX
# ----------------------------------------------------------------------------
def read_pair(pair, trackers, cards=None):
    best = None
    tried, unread = [], []
    for th, match, exclude in pair['sources']:
        if th.startswith('card:'):
            name = th.split(':', 1)[1]
            card = (cards or {}).get(name)
            if not card:
                unread.append(f'{name} card')
                continue
            node = _dig(card['data'], match)
            if not isinstance(node, dict) or node.get('probability') is None:
                tried.append(f'{name} card')
                continue
            tried.append(f'{name} card')
            pct = float(node.get('probability') or 0)
            lvl = pct_to_level(pct)
            cand = {'level': lvl, 'raw_level': lvl, 'tracker': f'{name} card', 'vector': f"{match.split('.')[-1]} ({pct:.0f}%)",
                    'capped': False, 'freshness': card['freshness'], 'tracker_so_what': '', 'kind': 'card'}
            if best is None or cand['level'] > best['level']:
                best = cand
            continue
        t = trackers.get(th)
        if not t:
            unread.append(th)
            continue
        tried.append(th)
        for vname, vlvl in t['vectors'].items():
            if not _match(vname, match, exclude):
                continue
            capped = min(vlvl, t['threat'])
            cand = {'level': capped, 'raw_level': vlvl, 'tracker': th, 'vector': vname,
                    'capped': capped < vlvl, 'freshness': t['freshness'],
                    'tracker_so_what': t['so_what'], 'kind': 'tracker'}
            if best is None or cand['level'] > best['level']:
                best = cand
    cell = {k: pair[k] for k in ('id', 'actor', 'actor_flag', 'target', 'target_flag', 'keys', 'note')}
    if best:
        cell.update(state='read', level=best['level'], word=LADDER[best['level']], source=best)
    elif tried:
        cell.update(state='not_sensed', level=None, word='Not sensed',
                    source={'trackers_read': tried, 'reason': 'no matching vector in the tracker output'})
    else:
        cell.update(state='unread', level=None, word='Unread',
                    source={'trackers_missing': unread})
    return cell


def build_lines(cells, prev):
    lines = []
    read = [c for c in cells if c['state'] == 'read']
    by = {c['id']: c for c in cells}
    if read:
        top = max(c['level'] for c in read)
        tops = [c for c in read if c['level'] == top]
        if top >= 3:
            names = '; '.join(f"{c['actor']} → {c['target']}" for c in tops[:3])
            lines.append(f"Highest pressure: {names} at L{top} {LADDER[top]}.")
        else:
            lines.append(f"No directed pair above L{top} {LADDER[top]} -- pressure is rhetorical, not yet confrontational.")
    a, b = by.get('israel>iran'), by.get('us>iran')
    if a and b and a['state'] == b['state'] == 'read' and a['level'] >= 3 and b['level'] >= 3:
        lines.append("Israeli and US pressure on Iran are both at Confrontation or above -- the coordinated-pressure "
                     "pattern that preceded the 2026 strikes. Watch Iran → Israel and Iran → US forces for the reply.")
    for x, y in [('israel>lebanon', 'hizballah>israel'), ('israel>iran', 'iran>israel'),
                 ('houthis>israel', 'israel>houthis'), ('israel>syria', None)]:
        cx, cy = by.get(x), by.get(y) if y else None
        if cx and cy and cx['state'] == cy['state'] == 'read' and cx['level'] >= 3 and cy['level'] <= 1:
            lines.append(f"One-way pressure: {cx['actor']} → {cx['target']} at L{cx['level']} while "
                         f"{cy['actor']} → {cy['target']} sits at L{cy['level']} -- absorbing, or holding fire.")
    moved = []
    for c in read:
        p = (prev or {}).get(c['id'])
        if isinstance(p, int) and c['level'] - p >= 2:
            moved.append(f"{c['actor']} → {c['target']} (L{p}→L{c['level']})")
    if moved:
        lines.append('Sharp moves since the last read: ' + '; '.join(moved[:3]) + '.')
    gaps = [c for c in cells if c['state'] != 'read']
    if gaps:
        lines.append(f"{len(gaps)} of {len(cells)} pairs not read this cycle "
                     f"({', '.join(c['actor'] + ' → ' + c['target'] for c in gaps[:3])}"
                     f"{'…' if len(gaps) > 3 else ''}) -- shown as gaps, not as calm.")
    return lines


def build_matrix(redis_get, redis_set):
    trackers, missing = read_trackers()
    cards = read_cards(redis_get)
    cells = [read_pair(p, trackers, cards) for p in PAIRS]
    prev = redis_get(PREV_KEY) or {}
    if isinstance(prev, str):
        try:
            prev = json.loads(prev)
        except ValueError:
            prev = {}
    for c in cells:
        p = prev.get(c['id'])
        c['previous_level'] = p if isinstance(p, int) else None
        c['delta'] = (c['level'] - p) if (c['state'] == 'read' and isinstance(p, int)) else None
    read = [c for c in cells if c['state'] == 'read']
    head = max(read, key=lambda c: c['level']) if read else None
    payload = {
        'success': True, 'version': MATRIX_VERSION, 'built_at': _now().isoformat(),
        'headline': ({'pair': f"{head['actor']} → {head['target']}", 'level': head['level'],
                      'word': head['word']} if head else None),
        'pairs': cells,
        'lines': build_lines(cells, prev),
        'trackers_read': sorted(trackers), 'trackers_missing': sorted(missing),
        'stale_trackers': sorted(t for t, v in trackers.items() if v['freshness'] != 'live'),
        'cards_read': sorted(cards),
        'method': ('Each pair reads the rhetoric tracker(s) that watch it, plus the Israel card\'s incoming/outgoing '
                   'panel; the cell takes the highest reading. Tracker vectors are capped at their tracker\'s '
                   'corroborated level; card percentages convert to levels and are capped at L4. Nothing here is '
                   'scanned separately. Unread and not-sensed pairs are shown as gaps, never as L0.'),
    }
    redis_set(PREV_KEY, {c['id']: c['level'] for c in read})
    return payload, trackers


def filter_for_actor(payload, actor):
    a = CARD_ALIASES.get(actor, actor)
    pairs = [c for c in payload.get('pairs', []) if a in c['keys'] or actor in c['keys']]
    out = dict(payload)
    out['pairs'] = pairs
    out['actor'] = a
    read = [c for c in pairs if c['state'] == 'read']
    head = max(read, key=lambda c: c['level']) if read else None
    out['headline'] = ({'pair': f"{head['actor']} → {head['target']}", 'level': head['level'],
                        'word': head['word']} if head else None)
    # Lines about THIS card's pairs -- the region-wide lines belong to the regional panel.
    out['lines'] = build_lines(pairs, {c['id']: c.get('previous_level') for c in pairs}) if pairs else []
    return out


# ----------------------------------------------------------------------------
# FLASK
# ----------------------------------------------------------------------------
def register_threat_matrix_v3(app, redis_client=None):
    from flask import jsonify, request

    def rget(k):
        if not redis_client:
            return None
        try:
            v = redis_client.get(k)
            return json.loads(v) if v else None
        except Exception:
            return None

    def rset(k, v, ttl=7 * 86400):
        if not redis_client:
            return
        try:
            redis_client.setex(k, ttl, json.dumps(v, default=str))
        except Exception:
            pass

    _mem = {'payload': None, 'at': 0}

    def current():
        cached = rget(CACHE_KEY)
        if cached and time.time() - cached.get('_at', 0) < CACHE_SEC:
            return cached
        if _mem['payload'] and time.time() - _mem['at'] < CACHE_SEC:
            return _mem['payload']
        payload, _ = build_matrix(rget, rset)
        payload['_at'] = time.time()
        rset(CACHE_KEY, payload, ttl=CACHE_SEC * 4)
        _mem.update(payload=payload, at=time.time())
        return payload

    def api_matrix():
        try:
            data = current()
            actor = (request.args.get('actor') or '').strip().lower()
            return jsonify(filter_for_actor(data, actor) if actor else data)
        except Exception as e:
            return jsonify({'success': False, 'version': MATRIX_VERSION, 'state': 'unread',
                            'error': f'{type(e).__name__}: {str(e)[:200]}', 'pairs': []}), 200

    def api_debug():
        try:
            trackers, missing = read_trackers()
        except Exception as e:
            return jsonify({'error': f'{type(e).__name__}: {e}'}), 200
        rows = {}
        for th, t in trackers.items():
            feeds = {}
            for vname in t['vectors']:
                feeds[vname] = [p['id'] for p in PAIRS for (src, m, x) in p['sources']
                                if src == th and _match(vname, m, x)]
            rows[th] = {'theatre_level': t['threat'], 'freshness': t['freshness'],
                        'vectors': t['vectors'], 'vector_feeds_pairs': feeds,
                        'unused_vectors': sorted(k for k, v in feeds.items() if not v)}
        cards = read_cards(rget)
        card_rows = {n: {'freshness': c['freshness'],
                         'paths': {s[1]: (_dig(c['data'], s[1]) or {}).get('probability')
                                   for p in PAIRS for s in p['sources'] if s[0] == f'card:{n}'}}
                     for n, c in cards.items()}
        return jsonify({'version': MATRIX_VERSION, 'trackers': rows, 'cards': card_rows, 'missing': missing,
                        'pairs_by_source': {p['id']: [s[0] for s in p['sources']] for p in PAIRS}})

    app.add_url_rule('/api/threat-matrix-v3', 'threat_matrix_v3', api_matrix, methods=['GET'])
    app.add_url_rule('/api/threat-matrix-v3/debug', 'threat_matrix_v3_debug', api_debug, methods=['GET'])
    print(f"[Matrix v3] ✅ /api/threat-matrix-v3 (+ /debug) -- {len(PAIRS)} pairs, reader only")
