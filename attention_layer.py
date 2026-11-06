"""
Asifah Analytics -- ATTENTION LAYER  (ME backend)
v1.0.0  (Nov 5 2026)

WHAT IT IS
  Everything that measures what people are SAYING or BETTING, as opposed to
  what is HAPPENING, read side by side for one country:
    * traders' odds         (prediction_markets.py  -> pm:latest)
    * commentary            (think_tank_feeds.py    -> commentary:latest)
    * public attention      (wikipedia_attention.py -> wiki:latest)   v1.1.0
    * (later) Reddit
  next to Asifah's own level (GPI country rollup -> gpi:global:latest).

  Nothing here is scored. Nothing here raises or lowers a level. Its value
  is the moments when the layers DISAGREE with the sensors:

    ahead_of_score   commentary is spiking and/or traders moved toward
                     pressure, while Asifah's level is quiet (L0-L2).
                     "The conversation is running ahead of the score."
    score_ahead      Asifah reads serious pressure (L4+) while commentators
                     are quieter than usual and traders have not moved.
                     "The score is running ahead of the conversation."
    lopsided         one side of the political spectrum is doing most of
                     the talking about this country this week.

v1.1.0 (Nov 6 2026) -- WIKIPEDIA. The public layer: how many people READ about
  a country, against their usual. A Wikipedia spike counts toward
  ahead_of_score like a commentary spike. score_ahead can now also fire when
  the public is reading LESS than usual (Wikipedia 'quiet') while Asifah reads
  L4+ -- commentary's own baseline is still being learned until ~Nov 19.

ROUTES
  /api/attention/<country>    the "Beside the score" panel's one call
                              (accepts page slugs: us, uk, north_korea ...)
  /api/attention/summary      every country with a flag, grouped by region

COST
  $0. Reads three Redis keys. No outside calls, no Claude calls.
"""

import json
import os
from datetime import datetime, timezone

import requests

__version__ = '1.1.0'

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
_MEM = {}

QUIET_MAX_LEVEL = 2
HOT_MIN_LEVEL = 4

try:
    from country_ids import canonical as _canonical, display as _display
except Exception:
    _canonical, _display = None, None


def canon(c):
    if not c:
        return c
    c = str(c).lower().strip().replace('-', '_').replace(' ', '_')
    if _canonical:
        try:
            return _canonical(c) or c
        except Exception:
            return c
    return {'us': 'usa', 'uk': 'united_kingdom', 'north_korea': 'dprk'}.get(c, c)


def label(c):
    if _display:
        try:
            d = _display(c)
            if d:
                return d
        except Exception:
            pass
    return str(c).replace('_', ' ').title()


# Regional pages' country cards (Nov 5 2026), canonical ids
_REGION_PAGES = {
    'me': 'algeria bahrain egypt iran iraq israel jordan kuwait lebanon libya morocco oman qatar '
          'saudi_arabia syria tunisia uae yemen gaza',
    'europe': 'albania armenia azerbaijan belarus belgium cyprus greece greenland hungary kazakhstan '
              'moldova poland russia turkey turkmenistan ukraine uk',
    'asia': 'afghanistan china india japan north_korea pakistan philippines south_korea taiwan vietnam',
    'africa': 'burkina_faso car chad drc equatorial_guinea ethiopia guinea kenya madagascar mali '
              'mozambique niger nigeria rwanda somalia south_africa south_sudan sudan tanzania uganda',
    'wha': 'argentina brazil canada chile colombia cuba haiti mexico panama paraguay peru us venezuela',
}
REGION_OF = {}
for _r, _cs in _REGION_PAGES.items():
    for _c in _cs.split():
        REGION_OF[canon(_c)] = _r
# armed-group gauges point at their country
REGION_OF.setdefault(canon('hezbollah'), 'me')
REGION_OF.setdefault(canon('houthis'), 'me')


def _rget(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return _MEM.get(key)
    try:
        r = requests.get('%s/get/%s' % (UPSTASH_REDIS_URL, key),
                         headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN}, timeout=6)
        res = r.json().get('result') if r.status_code == 200 else None
        return json.loads(res) if res else None
    except Exception:
        return None


def _sources():
    return {'markets': _rget('pm:latest'), 'commentary': _rget('commentary:latest'),
            'gpi': _rget('gpi:global:latest'), 'wiki': _rget('wiki:latest')}


def _our_level(c, gpi):
    for r in (gpi or {}).get('country_rollup') or []:
        if isinstance(r, dict) and canon(r.get('country')) == c and r.get('max_level') is not None:
            return int(r['max_level'])
    return None


def _market_items(c, markets):
    out = []
    for it in (markets or {}).get('items') or []:
        cs = {canon(x) for x in (it.get('countries') or [])}
        pages = {canon(p) for p in (it.get('pages') or []) if ':' not in p}
        if c in cs or c in pages:
            out.append(it)
    out.sort(key=lambda it: -len(it.get('flags') or []))
    return out


def _market_pressure_moves(items):
    """Market items that moved or settled TOWARD pressure, non-thin."""
    moves = []
    for it in items:
        for f in it.get('flags') or []:
            if f.get('kind') == 'jump' and f.get('direction') == 'toward pressure':
                moves.append({'label': it.get('label'), 'what': f.get('text'), 'kind': 'jump'})
            elif f.get('kind') == 'settled':
                s = (it.get('settled_recent') or [{}])[0]
                ym = it.get('yes_means')
                if (ym == 'less_pressure' and s.get('resolved_yes') is False) or \
                   (ym == 'more_pressure' and s.get('resolved_yes') is True):
                    moves.append({'label': it.get('label'), 'what': f.get('text'), 'kind': 'settled'})
            elif f.get('kind') == 'consensus':
                moves.append({'label': it.get('label'), 'what': f.get('text'), 'kind': 'consensus'})
    return moves


def _market_calm(items):
    return not any(f.get('kind') in ('jump', 'settled') for it in items for f in it.get('flags') or [])


def country(c, src=None):
    """Everything 'beside the score' for one country."""
    c = canon(c)
    src = src or _sources()
    m, cm, gpi = src.get('markets'), src.get('commentary'), src.get('gpi')
    wk = src.get('wiki')
    wa = ((wk or {}).get('countries') or {}).get(c)
    wa_pub = {k: v for k, v in (wa or {}).items() if k != 'articles'} if wa else None
    lvl = _our_level(c, gpi)
    mk = _market_items(c, m)
    moves = _market_pressure_moves(mk)
    att = ((cm or {}).get('attention') or {}).get(c)
    bal = next((t for t in ((cm or {}).get('balance') or {}).get('by_country', []) if t.get('country') == c), None)
    pieces = ((cm or {}).get('by_country') or {}).get(c, [])[:5]
    name = label(c)
    flags = []

    spike = bool(att and att.get('spike'))
    wiki_spike = bool(wa and wa.get('state') == 'spike')
    layers_up = (['commentary'] if spike else []) + (['traders'] if moves else []) + \
                (['public'] if wiki_spike else [])
    if layers_up and lvl is not None and lvl <= QUIET_MAX_LEVEL:
        what = []
        if spike:
            what.append('commentary on %s is running at %.1f times its usual weekly volume'
                        % (name, att.get('ratio') or 0))
        if moves:
            what.append('traders moved toward pressure (%s)' % moves[0]['label'].rstrip('?'))
        if wiki_spike:
            what.append('Wikipedia readers are looking up "%s" at %.1f times the usual rate'
                        % (wa.get('lead_article'), wa.get('ratio') or 0))
        flags.append({'kind': 'ahead_of_score', 'layers': layers_up,
                      'text': '%s, while Asifah reads %s at L%d. The conversation is running ahead of '
                              'the score: worth watching, not yet evidence.'
                              % ('; '.join(what).capitalize(), name, lvl)})
    quiet_talk = bool(att and att.get('state') == 'quiet')
    talk_unknown = not att or att.get('state') == 'baseline_building'
    wiki_quiet = bool(wa and wa.get('state') == 'quiet')
    if lvl is not None and lvl >= HOT_MIN_LEVEL and _market_calm(mk) and not spike and not wiki_spike \
            and (quiet_talk or (talk_unknown and wiki_quiet)):
        who = ('commentators are quieter than usual' if quiet_talk else
               'fewer people than usual are reading about it on Wikipedia')
        flags.append({'kind': 'score_ahead',
                      'text': 'Asifah reads serious pressure on %s (L%d) while %s and traders have not moved. '
                              'The score is running ahead of the conversation: a crisis the world is not '
                              'watching.' % (name, lvl, who)})
    if bal and bal.get('lopsided'):
        flags.append({'kind': 'lopsided', 'text': bal.get('sentence')})

    return {
        'version': __version__,
        'country': c, 'country_name': name, 'region': REGION_OF.get(c),
        'asifah_level': lvl,
        'available': {'markets': bool(m), 'commentary': bool(cm), 'asifah_level': lvl is not None,
                      'wiki': bool(wk)},
        'flags': flags,
        'markets': {'items': mk[:4], 'count': len(mk), 'pressure_moves': moves,
                    'generated_at': (m or {}).get('generated_at')},
        'commentary': {'pieces': pieces, 'balance': bal, 'attention': att,
                       'generated_at': (cm or {}).get('last_updated')},
        'public': wa_pub,
        'label': 'What people are saying, betting and reading about %s -- context beside the score, never '
                 'part of it.' % name,
    }


def summary(src=None):
    src = src or _sources()
    cs = set()
    for it in (src.get('markets') or {}).get('items') or []:
        cs |= {canon(x) for x in (it.get('countries') or [])}
    cm = src.get('commentary') or {}
    cs |= set((cm.get('attention') or {}).keys())
    cs |= {t.get('country') for t in (cm.get('balance') or {}).get('by_country', [])}
    cs |= set(((src.get('wiki') or {}).get('countries') or {}).keys())
    out = {}
    for c in sorted(x for x in cs if x):
        rec = country(c, src)
        if rec['flags']:
            out.setdefault(rec['region'] or 'other', []).append(
                {'country': c, 'name': rec['country_name'], 'asifah_level': rec['asifah_level'],
                 'flags': rec['flags']})
    return {'version': __version__, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'by_region': out}


def voice_context(region=None, max_items=6):
    """Labelled attention context for the GPI voice (region=None) or one
    region's voice. fingerprint_flags hold only the slow facts."""
    s = summary()
    rows, fp = [], []
    regions = [region] if region else list(s['by_region'].keys())
    for r in regions:
        for rec in s['by_region'].get(r, []):
            rows.append({'country': rec['name'], 'asifah_level': rec['asifah_level'],
                         'what_the_attention_layer_shows': [f['text'] for f in rec['flags']]})
            fp += ['%s:%s' % (rec['country'], f['kind']) for f in rec['flags']]
    if not rows:
        return None
    rows.sort(key=lambda x: -len(x['what_the_attention_layer_shows']))
    return {'items': rows[:max_items], 'fingerprint_flags': sorted(set(fp))}


def register_attention_routes(app):
    from flask import jsonify

    try:                                   # v1.1.0: the public layer rides along
        from wikipedia_attention import register_wiki_routes
        register_wiki_routes(app, start=True)
    except Exception as e:
        print('[Attention] Wikipedia layer not started (non-fatal): %s' % str(e)[:100])

    @app.route('/api/attention/summary')
    def _att_summary():
        return jsonify(summary())

    @app.route('/api/attention/<cid>')
    def _att_country(cid):
        return jsonify(country(cid))

    print('[Attention] routes registered: /api/attention/<country>, /api/attention/summary (v%s)'
          % __version__)
