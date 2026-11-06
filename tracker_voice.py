"""
tracker_voice.py -- Asifah Analytics -- ME backend
================================================================================
THE PLAIN-LANGUAGE READ FOR THE MILITARY, COMMODITIES AND MARKET WATCH PAGES.

THE ASK (Rachel, Nov 3 2026)
  "Use our API to add the PLAIN LANGUAGE read to the three trackers -- this is
  really important. What does it MEAN when we discuss conflict repricing, what
  does it MEAN that the Strait of Hormuz is contested, what does it MEAN that
  there is a URANIUM-ROUTE-DEPENDENCY convergence? How does this play into
  local, regional, and global geopolitics, global economies?"

WHAT IT DOES
  Three "desks" -- military, commodities, market. For each desk it:
    1. reads the tracker's CACHED scan from Redis (never runs a scan),
    2. packs a compact fact sheet: what is lit, at what level, the evidence,
       what is new vs long-running, and -- for every lit item -- a
       meaning_basis from tracker_meanings.py (what the thing IS, and what it
       means locally, regionally, globally and for the economy),
    3. asks Claude (Messages API, the GPI's shared call) for a headline, a
       two-sentence So What, a fuller read, what to watch, and a "what this
       means today" note for each lit item at the four altitudes,
    4. stores it, and serves it at /api/tracker-voice?desk=...

  The deterministic meanings ride along in every response as 'explainers',
  so a page ALWAYS has "what this means" for each lit item, even when the
  writer has never run, the key is missing or the month's credits are gone.

COST GUARDRAILS (identical rules to gpi_voice / regional_voice)
  * Rewrite only when the facts change. The fingerprint is the set of lit
    items, their states and their new/long-running status -- not scores,
    counts, headlines or timestamps, so a busy news day does not cost money.
  * ?force on any tracker NEVER reaches this module. The writer runs from its
    own background loop (every 3h, leader instance only) or from Rachel's
    manual link (&refresh=<VOICE_REFRESH_TOKEN>).
  * Caps: TRACKER_VOICE_DESK_CAP (default 2) per desk per day, and
    TRACKER_VOICE_TOTAL_CAP (default 4) across the three desks per day, plus
    the shared 15-minute gap. At ~$0.02-0.04 per write-up on Sonnet 5.5 that
    is at most ~$0.16/day, ~$5/month. Outer fence: the Console spend cap.
  * Any failure -> the last good write-up stays up; the page falls back to
    the deterministic explainers and its own analyst prose. Never blank.

PATTERN RECOGNITION (market desk)
  When market_blackswan_detector supplies an analog (and, from step 19, the
  analog lens -- matched conditions, the chain of events with dates, the
  interval between warning stage and event, and the effects), the writer is
  told to say what matches, what does not, what happened then and on what
  timeline, and that it describes THEN, not now.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import hashlib
import threading
from datetime import datetime, timezone, timedelta

import requests

import tracker_meanings as M

__version__ = '1.2.0'   # Nov 6 2026: lane status is a hard fact (no 'none disrupted' next to a Disrupted tile); chokepoint evidence picks headlines about the passage. 1.1.0 Nov 3 2026: prose first -- grouped items, sentences not labels, deterministic fallback read
PROMPT_VERSION = 'tracker-v3'          # part of the fingerprint: a prompt upgrade rewrites once

DESKS = ('military', 'commodities', 'market')
DESK_NAMES = {'military': 'Military Posture', 'commodities': 'Commodity Pressure',
              'market': 'Market Watch'}

DESK_CAP = int(os.environ.get('TRACKER_VOICE_DESK_CAP', '2'))
TOTAL_CAP = int(os.environ.get('TRACKER_VOICE_TOTAL_CAP', '4'))
MIN_GAP_SEC = int(os.environ.get('TRACKER_VOICE_MIN_GAP_SEC', '900'))
LOOP_INTERVAL_SEC = int(os.environ.get('TRACKER_VOICE_INTERVAL_SEC', str(3 * 3600)))
LOOP_FIRST_DELAY_SEC = int(os.environ.get('TRACKER_VOICE_FIRST_DELAY_SEC', '420'))
MAX_TOKENS = 3500
MAX_ITEMS = 9
NEW_WINDOW_HOURS = 72

LATEST_KEY = 'tracker_voice:%s:latest'        # % desk
FACTS_KEY = 'tracker_voice:%s:facts'
MEMORY_KEY = 'tracker_voice:%s:memory'
CALLS_KEY = 'tracker_voice:calls:%s:%s'       # % (desk|'all', day)
VOICE_TTL = 14 * 24 * 3600
MEMORY_TTL = 60 * 24 * 3600

SOURCE_KEYS = {
    'military': ['military_tracker_cache'],
    'commodities': ['commodity_tracker_cache'],
    'market': ['blackswan:market:latest', 'repricing:israel:latest',
               'repricing:europe_ukraine:latest', 'repricing:korea:latest'],
}

try:
    import gpi_voice as _gv            # shared call, pricing log, Redis helpers, house terms
except Exception as _e:                 # pragma: no cover -- only if gpi_voice is absent
    _gv = None
    print('[Tracker voice] gpi_voice unavailable (%s) -- writer disabled, explainers still served' % _e)

_lock = threading.Lock()
_running = {'busy': False}


# ════════════════════════════════════════════════════════════════════════
# REDIS
# ════════════════════════════════════════════════════════════════════════
def _url_tok():
    url = (os.environ.get('UPSTASH_REDIS_REST_URL') or os.environ.get('UPSTASH_REDIS_URL') or '').rstrip('/')
    tok = os.environ.get('UPSTASH_REDIS_REST_TOKEN') or os.environ.get('UPSTASH_REDIS_TOKEN') or ''
    return url, tok


def _rget_checked(key):
    """(value, read_ok). read_ok False = we could not look (never 'empty')."""
    url, tok = _url_tok()
    if not (url and tok):
        return None, False
    try:
        r = requests.get(f'{url}/get/{key}', headers={'Authorization': f'Bearer {tok}'}, timeout=6)
        if r.status_code != 200:
            return None, False
        res = r.json().get('result')
        if not res:
            return None, True
        val = json.loads(res)
        if isinstance(val, dict) and set(val.keys()) == {'value'}:     # legacy wrapper
            val = val['value']
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
        return val, True
    except Exception:
        return None, False


def _rget(key):
    return _rget_checked(key)[0]


def _rset(key, value, ttl):
    url, tok = _url_tok()
    if not (url and tok):
        return False
    try:
        r = requests.post(url, headers={'Authorization': f'Bearer {tok}'},
                          json=['SET', key, json.dumps(value, default=str), 'EX', str(int(ttl))],
                          timeout=6)
        return r.status_code == 200
    except Exception:
        return False


def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _count(key):
    return int((_rget(key) or {}).get('n', 0))


# ════════════════════════════════════════════════════════════════════════
# SMALL HELPERS
# ════════════════════════════════════════════════════════════════════════
def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _txt(t, n=None):
    t = ' '.join(str(t or '').split())
    return (t[:n].rstrip() + '...') if (n and len(t) > n) else t


def _title(sig):
    sig = _d(sig)
    return _txt(sig.get('article_title') or sig.get('title') or sig.get('short_text') or '', 160)


# v1.2.0: for a contested / disrupted passage, quote reporting ABOUT the passage
# being contested -- not "CENTCOM Commander Visits..." that merely mentions it.
_LANE_WORDS = re.compile(r'attack|strike|struck|seiz|board|hijack|mine|drone|missile|tanker|vessel|ship|'
                         r'divert|reroute|halt|suspend|clos|block|disrupt|threat|warn|escort|transit|insur',
                         re.I)
_SOFT_WORDS = re.compile(r'\bvisit|ceremony|conference|award|change of command|meets with|tour\b', re.I)


def _lane_titles(sigs, n=3):
    ranked = sorted(_l(sigs), key=lambda s: (bool(_SOFT_WORDS.search(_title(s))),
                                             not bool(_LANE_WORDS.search(_title(s)))))
    return _titles(ranked, n)


def _titles(sigs, n=3):
    out, seen = [], set()
    for s in _l(sigs):
        t = _title(s)
        k = t.lower()[:80]
        if t and k not in seen:
            seen.add(k)
            out.append(t)
        if len(out) >= n:
            break
    return out


def _altitudes(rec):
    rec = _d(rec)
    return {k: rec.get(k) or '' for k in ('local', 'regional', 'global', 'economy')}


def _item(kind, iid, name, state, level_words, plain, alt=None, evidence=None, facts=None,
          basis='', verified=True, extra=None):
    it = {'id': '%s:%s' % (kind, iid), 'kind': kind, 'name': name, 'state': state,
          'level_words': level_words, 'meaning_basis': {'plain': plain}, 'evidence': evidence or [],
          'basis': basis, 'verified': bool(verified)}
    it['meaning_basis'].update(alt or {})
    if facts:
        it['facts'] = facts
    if extra:
        it.update(extra)
    return it


# ════════════════════════════════════════════════════════════════════════
# PACKERS -- one per desk. Each returns (facts, source_as_of) or (None, reason)
# ════════════════════════════════════════════════════════════════════════
_CP_RANK = {'open': 0, 'monitored': 1, 'contested': 2, 'disrupted': 3}
_TH_RANK = {'normal': 0, 'elevated': 1, 'high': 2, 'surge': 3}
_CM_RANK = {'normal': 0, 'monitor': 1, 'elevated': 2, 'high': 3, 'surge': 4}


def pack_military(cache):
    cache = _d(cache)
    if not cache.get('theatre_groupings') and not cache.get('chokepoint_postures'):
        return None, 'military cache empty or unread'
    items, quiet = [], []

    # Chokepoints (monitored+), most severe first
    cps = _d(cache.get('chokepoint_postures'))
    try:
        from military_signal_interpreter import _extract_critical_phrases_for_signals as _crit
    except Exception:
        def _crit(_s):
            return []
    ranked = sorted(cps.items(), key=lambda kv: (-_CP_RANK.get(_d(kv[1]).get('alert_level', 'open'), 0),
                                                 -(_d(kv[1]).get('signal_count') or 0)))
    for cp_id, cp in ranked:
        cp = _d(cp)
        lvl = cp.get('alert_level', 'open')
        if _CP_RANK.get(lvl, 0) < 1:
            quiet.append(M.chokepoint_meaning(cp_id)['name'])
            continue
        mean = M.chokepoint_meaning(cp_id)
        items.append(_item(
            'chokepoint', cp_id, mean['name'], lvl,
            '%s -- %s' % (lvl, M.CHOKEPOINT_LEVEL_MEANING.get(lvl, '')),
            mean['plain'], _altitudes(mean),
            _lane_titles(cp.get('top_signals')) if _CP_RANK.get(lvl, 0) >= 2 else _titles(cp.get('top_signals')),
            basis=mean.get('basis', ''), verified=mean.get('verified', False),
            extra={'reported_phenomena': _crit(_l(cp.get('top_signals')))[:3],
                   'signal_count': cp.get('signal_count', 0)}))

    # Coupled chokepoints
    for label, cv in _d(cache.get('chokepoint_convergences')).items():
        cv = _d(cv)
        if not cv.get('active'):
            continue
        names = [M.chokepoint_meaning(c)['name'] for c in _d(cv.get('chokepoint_levels'))]
        t = M.TERMS['coupled_chokepoints']
        items.append(_item(
            'pair', label, ' + '.join(names), cv.get('level', 'contested'),
            'both passages at %s or worse' % cv.get('level', 'contested'),
            t['plain'], _altitudes(t), [], facts={'why_this_pair': _txt(cv.get('rationale'), 240)},
            basis='Asifah method definition'))

    # Regions, grouped (v1.1.0). Four "theatre" rows at surge read as four
    # alarms; one paragraph naming the hottest actors per region reads as a
    # picture. The level is taken from the ACTORS (hottest actor), not the
    # theatre field, which summed every actor's score before tracker v3.17.1.
    theatres, region_lines, ev = [], [], []
    top_rank = 0
    for tid, th in _d(cache.get('theatre_groupings')).items():
        th = _d(th)
        acts = _d(th.get('actors'))
        hot = sorted(((a, _d(ad).get('alert_level', 'normal')) for a, ad in acts.items()
                      if _TH_RANK.get(_d(ad).get('alert_level'), 0) >= 1),
                     key=lambda x: (-_TH_RANK.get(x[1], 0), -(_d(acts.get(x[0])).get('total_score') or 0)))
        lvl = hot[0][1] if hot else 'normal'
        names = ['%s (%s)' % (_d(acts.get(a)).get('name') or a, M.ACTOR_LEVEL_WORDS.get(l, l)) for a, l in hot[:4]]
        theatres.append({'region': th.get('label') or tid, 'hottest_actor_level': lvl,
                         'actors_above_baseline': names})
        if hot:
            top_rank = max(top_rank, _TH_RANK.get(lvl, 0))
            region_lines.append({'region': M.REGION_PLAIN.get(tid, th.get('label') or tid),
                                 'actors': names, 'level': lvl})
            for a, _lv in hot[:1]:
                ev += _titles(_d(acts.get(a)).get('top_signals'), 1)
    if region_lines:
        region_lines.sort(key=lambda r: -_TH_RANK.get(r['level'], 0))
        top = ['normal', 'elevated', 'high', 'surge'][top_rank]
        items.append(_item('regions', 'all', 'Military activity by region', top,
                           M.ACTOR_LEVEL_WORDS.get(top, top),
                           M.TERMS['military_reporting']['plain'], {}, ev[:4],
                           facts={'regions': region_lines}, basis='Asifah method definition'))

    # Evacuations
    evac = _l(cache.get('evacuation_alerts'))
    if evac:
        t = M.TERMS['neo']
        actors = sorted({_d(e).get('actor') for e in evac if _d(e).get('actor')})
        items.append(_item('neo', 'active', t['name'], 'active', '%d signal(s)' % len(evac),
                           t['plain'], _altitudes(t), [_txt(_d(e).get('title'), 160) for e in evac[:3]],
                           facts={'actors': actors[:6]}, basis='Asifah method definition'))

    interp = _d(cache.get('interpretation'))
    ik = _d(interp.get('iran_kinetic_prose'))
    special = {}
    if ik.get('active'):
        special['iran_kinetic_pattern'] = {'severity': ik.get('severity'),
                                           'pattern': ik.get('pattern_detected'),
                                           'matched_phrases': _l(ik.get('matched_phrases'))[:6]}
    mv = _d(interp.get('asset_movement_prose'))
    if mv.get('active'):
        special['named_ship_movements'] = [m.get('prose') for m in _l(mv.get('movements'))[:4]] or \
                                          [s.get('prose') for s in _l(mv.get('sightings'))[:4]]
        special['ship_order_known'] = mv.get('ordering') == 'chronological'

    facts = {
        'desk': 'military',
        'desk_note': ('Levels read defence and open-source REPORTING about deployments, exercises, '
                      'strikes and shipping -- not ship counts or satellite tracks.'),
        'theatres': theatres,
        'items_to_explain': items[:MAX_ITEMS],
        'chokepoints_open': quiet[:20],
        # v1.2.0: the lane status, stated flat, so the write-up cannot contradict the tiles
        'shipping_lanes_status': {
            'disrupted': [M.chokepoint_meaning(c)['name'] for c, v in cps.items()
                          if _d(v).get('alert_level') == 'disrupted'],
            'contested': [M.chokepoint_meaning(c)['name'] for c, v in cps.items()
                          if _d(v).get('alert_level') == 'contested'],
        },
        'special_reads': special,
        'analyst_summary': _txt(interp.get('executive_summary'), 600),
    }
    return facts, cache.get('cached_at') or cache.get('last_updated')


def pack_commodities(cache):
    cache = _d(cache)
    cs = _d(cache.get('commodity_summaries'))
    if not cs:
        return None, 'commodity cache empty or unread'
    items = []
    try:
        import convergence_registry as _cr
        reg = {e.get('id'): e for e in getattr(_cr, 'CONVERGENCE_REGISTRY', []) if isinstance(e, dict)}
    except Exception:
        reg = {}

    convs = sorted(_l(cache.get('active_convergences')),
                   key=lambda c: (0 if _d(c).get('fresh', True) else 1, -(_d(c).get('priority') or 0)))
    for c in convs[:4]:
        c = _d(c)
        cid = c.get('id')
        entry = reg.get(cid) or {'id': cid, 'detail': c.get('detail'), 'regions': c.get('regions')}
        mean = M.registry_meaning(entry)
        fresh = c.get('fresh', True)
        state = 'firing' if fresh else 'standing_watch'
        cm, ct = entry.get('commodity') or c.get('commodity'), entry.get('country') or c.get('country')
        nice = mean['name']
        if cm and ct and cid == '%s_%s' % (cm, ct):
            nice = '%s supply to %s' % (M.humanise_id(cm), M.humanise_id(ct))
        else:
            nice = nice[:1] + nice[1:].lower()
        items.append(_item(
            'convergence', cid, nice, state,
            ('coupled trigger confirmed this cycle' if fresh else
             'structural exposure present, coupled trigger not confirmed (%s)' % (c.get('trigger_state') or 'unconfirmed')),
            mean['plain'], {}, [_txt(c.get('headline'), 200)] if c.get('headline') else [],
            facts=dict(mean['facts'], **({'watch': mean['watch']} if mean['watch'] else {})),
            basis=mean['basis'],
            extra={'commodity_level': c.get('alert_level'), 'regions': mean['regions'],
                   'commodity_name': M.humanise_id(cm) if cm else None,
                   'country_name': M.humanise_id(ct) if ct and ct != 'global' else None,
                   'not_implied': mean['not_implied'],
                   'standing_note': (M.TERMS['standing_watch']['plain'] if not fresh else '')}))

    # Commodities under pressure, grouped (v1.1.0): seven rows of "SURGE /
    # HIGH" chips is a list, not a read. One item names them in order, with
    # the loudest headline for the top three.
    hot = sorted(((k, _d(v)) for k, v in cs.items() if _CM_RANK.get(_d(v).get('alert_level'), 0) >= 3),
                 key=lambda kv: (-_CM_RANK.get(kv[1].get('alert_level'), 0), -(kv[1].get('total_score') or 0)))
    elevated = [(_d(v).get('name') or k) for k, v in cs.items() if _CM_RANK.get(_d(v).get('alert_level'), 0) == 2]
    t = M.TERMS['commodity_pressure']
    if hot:
        rows = []
        for k, v in hot[:10]:
            rows.append({'commodity': v.get('name') or k, 'level': M.COMMODITY_LEVEL_WORDS.get(v.get('alert_level'), v.get('alert_level')),
                         'loudest_headline': (_titles(v.get('top_signals'), 1) or [''])[0] if len(rows) < 3 else ''})
        items.append(_item(
            'commodities', 'pressure', 'Commodities under heavy news pressure', hot[0][1].get('alert_level'),
            M.COMMODITY_LEVEL_MEANING.get(hot[0][1].get('alert_level'), ''), t['plain'],
            {'economy': t['economy']}, [r['loudest_headline'] for r in rows if r['loudest_headline']],
            facts={'commodities': rows, 'also_above_normal': elevated[:8]},
            basis='commodity tracker'))

    countries = sorted(((k, _d(v)) for k, v in _d(cache.get('country_summaries')).items()
                        if _CM_RANK.get(_d(v).get('alert_level'), 0) >= 2),
                       key=lambda kv: -(kv[1].get('total_score') or 0))
    facts = {
        'desk': 'commodities',
        'desk_note': M.TERMS['commodity_pressure']['plain'],
        'items_to_explain': items[:MAX_ITEMS],
        'commodities_at_baseline_count': sum(1 for v in cs.values() if _CM_RANK.get(_d(v).get('alert_level'), 0) < 2),
        'countries_under_commodity_pressure': [M.humanise_id(k) + ' (%s)' % v.get('alert_level') for k, v in countries[:8]],
        'analyst_summary': _txt(_d(cache.get('interpretation')).get('executive_summary'), 600),
    }
    return facts, cache.get('cached_at') or cache.get('last_updated')


def pack_market(sources):
    bs = _d(sources.get('blackswan:market:latest'))
    items = []
    if bs.get('band'):
        t = M.TERMS['fragility']
        band = bs.get('band')
        feats = [{'condition': f.get('plain') or f.get('name'), 'why_it_matters': _txt(f.get('why'), 240),
                  'last_seen_before': f.get('precedent')} for f in _l(bs.get('active_features'))]
        items.append(_item(
            'fragility', 'composite', 'Market fragility', band,
            M.FRAGILITY_BAND_MEANING.get(band, ''), t['plain'], _altitudes(t), [],
            facts={'conditions_present_now': feats[:10],
                   'conditions_absent_now': [M.humanise_id(x) for x in _l(bs.get('quiet_features'))],
                   'conditions_unmeasured': [M.humanise_id(x) for x in _l(bs.get('features_unavailable'))],
                   'as_of_month': bs.get('as_of_month'),
                   'data_scope': ('The ten conditions are measured on US markets (S&P 500, VIX, US '
                                  'credit spreads and rates). Other markets are read separately on '
                                  'their own index and currency (see any market_read items).')},
            basis='market_blackswan_detector'))
        lens = {x.get('id'): x for x in _l(bs.get('analog_lens'))}
        tn = M.TERMS['analog']
        for m in _l(bs.get('similarity_matches'))[:2]:
            m = _d(m)
            if (m.get('similarity_pct') or 0) < 30:
                continue
            ov = _d(m.get('overlap'))
            lz = _d(lens.get(m.get('id')))
            f = {'similarity_pct': m.get('similarity_pct'),
                 'episode_type': (m.get('type') or '').replace('_', ' '),
                 'event_month': m.get('event_month'), 'outcome': m.get('drawdown'),
                 'shared_conditions': [M.humanise_id(x) for x in _l(ov.get('shared'))],
                 'present_now_not_then': [M.humanise_id(x) for x in _l(ov.get('now_only'))],
                 'present_then_not_now': [M.humanise_id(x) for x in _l(ov.get('then_only'))],
                 'mechanism_then': m.get('mechanism'),
                 'data_spine': ('partial -- non-US episode scored on US-built conditions, weaker evidence'
                                if m.get('data_spine') == 'partial' else m.get('data_spine'))}
            if lz:
                for k in ('chain', 'interval_then', 'effects', 'live_checks', 'what_the_match_is_not'):
                    if lz.get(k):
                        f[k] = lz[k]
            items.append(_item('analog', m.get('id'), m.get('label') or m.get('id'),
                               _d(bs.get('match_strength')).get('level') or 'match',
                               _txt(_d(bs.get('match_strength')).get('text'), 220),
                               tn['plain'], {'economy': tn['economy']}, [], facts=f,
                               basis='market_blackswan_detector episode library'))
        # Market-by-market pattern matches (detector v1.5.0): markets OUTSIDE the
        # US whose own index + currency match an episode's pattern.
        try:
            import market_analog_lens as _L
        except Exception:
            _L = None
        for fl in _l(bs.get('regional_flags'))[:2]:
            fl = _d(fl)
            dz = _d(getattr(_L, 'DOSSIERS', {}).get(fl.get('episode'))) if _L else {}
            mrec = _d(_d(_d(bs.get('regional_reads')).get('markets')).get(fl.get('market')))
            top = _d((_l(mrec.get('closest')) or [{}])[0])
            items.append(_item(
                'market_read', fl.get('market'), fl.get('name'), 'pattern_match',
                fl.get('text'),
                ('This market, read on its own index and currency, shares %s%% of the measurable '
                 'conditions of the %s pattern%s.' % (fl.get('similarity_pct'), fl.get('label'),
                                                      '' if fl.get('home_region') else
                                                      ' (an episode from another region)')),
                {}, [],
                facts={'conditions_now': [c.get('words') for c in _l(mrec.get('conditions_now'))],
                       'conditions_of_that_episode_not_present': [_L.CONDITION_WORDS.get(c, c) if _L else c
                                                                  for c in _l(top.get('then_only'))],
                       'not_visible_in_prices': [_L.CONDITION_WORDS.get(c, c) if _L else c
                                                 for c in _l(top.get('unmeasured_in_episode'))],
                       'figures': mrec.get('detail'),
                       'chain': ['%s -- %s' % (d, t) for d, t in dz.get('chain', [])],
                       'interval_then': dz.get('interval_then'),
                       'effects': dz.get('effects'),
                       'what_the_match_is_not': dz.get('not')},
                basis='market_analog_lens (monthly closes; episode dates are Claude research)',
                verified=False))
    rep = []
    for th in ('israel', 'europe_ukraine', 'korea'):
        p = _d(sources.get('repricing:%s:latest' % th))
        if not p.get('state'):
            continue
        state = p.get('state')
        mean = M.repricing_meaning(th, state)
        gauges = ['%s %s %.1f%%' % (i.get('name'), 'up' if i['change_pct'] >= 0 else 'down', abs(i['change_pct']))
                  for i in _l(p.get('instruments')) if isinstance(i.get('change_pct'), (int, float))]
        off = _d(p.get('offramp'))
        rep.append(th)
        items.append(_item(
            'repricing', th, mean['name'], state, state.replace('_', ' '), mean['plain'],
            _altitudes(mean), [],
            facts={'what_conflict_repricing_is': mean['term'],
                   'gauges_over_about_a_week': gauges,
                   'peace_track_in_rhetoric': off.get('maturity_phrase') if off.get('active') else 'none active',
                   'closest_market_episode': _txt(p.get('episode_read'), 200),
                   'detector_sentence': _txt(p.get('market_read'), 300).split(' This is a CONVERGENCE read')[0]},
            basis='conflict_repricing_detector'))
    if not items:
        return None, 'no market detector payloads readable'
    facts = {
        'desk': 'market',
        'desk_note': ('Two different reads: FRAGILITY (how exposed markets are to any shock, measured '
                      'monthly) and CONFLICT REPRICING (whether money agrees with diplomacy in specific '
                      'war zones, measured over about a week).'),
        'items_to_explain': items[:MAX_ITEMS],
        'match_strength': _txt(_d(bs.get('match_strength')).get('text'), 260),
        'global_majors_near_highs': _l(_d(_d(bs.get('global_majors')).get('_sync')).get('near_high')),
        'historical_lag_read': _txt(bs.get('historical_lag_read'), 400),
    }
    as_of = bs.get('last_updated') or max([_d(sources.get('repricing:%s:latest' % t)).get('last_updated') or ''
                                           for t in rep] or [''])
    return facts, as_of


def _read_sources(desk):
    out, ok_all = {}, True
    for k in SOURCE_KEYS[desk]:
        v, ok = _rget_checked(k)
        ok_all = ok_all and ok
        out[k] = v
    return out, ok_all


def pack(desk, sources=None):
    """(facts or None, as_of or reason). Reads caches only."""
    if sources is None:
        sources, _ok = _read_sources(desk)
    if desk == 'military':
        return pack_military(sources.get('military_tracker_cache'))
    if desk == 'commodities':
        return pack_commodities(sources.get('commodity_tracker_cache'))
    return pack_market(sources)


# ════════════════════════════════════════════════════════════════════════
# MEMORY -- what is new vs long-running (same rule as regional_voice)
# ════════════════════════════════════════════════════════════════════════
def apply_memory(facts, mem, now=None, mem_ok=True):
    """Mark each item is_new / since / previous_state. Returns the new memory.

    First sighting of a desk (empty memory) seeds every item as 'before',
    so a deploy is never news. Memory unread -> ages 'unread', not new."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    mem = mem if isinstance(mem, dict) else {}
    first_run = not mem.get('items')
    prev = _d(mem.get('items'))
    out = {'began': mem.get('began') or now_iso, 'items': {}}
    cutoff = now - timedelta(hours=NEW_WINDOW_HOURS)
    for it in _l(facts.get('items_to_explain')):
        key = it['id']
        p = _d(prev.get(key))
        if not mem_ok:
            it['since'], it['is_new'] = 'unread', False
            continue
        if not p or first_run:
            since = 'before %s' % (out['began'][:10]) if first_run else now_iso
            rec = {'state': it['state'], 'since': since}
        elif p.get('state') != it['state']:
            rec = {'state': it['state'], 'since': now_iso, 'previous_state': p.get('state')}
        else:
            rec = dict(p)
        out['items'][key] = rec
        it['since'] = rec['since'] if rec['since'].startswith('before') else rec['since'][:10]
        if rec.get('previous_state'):
            it['previous_state'] = rec['previous_state']
        try:
            it['is_new'] = (not rec['since'].startswith('before')
                            and datetime.fromisoformat(rec['since']) >= cutoff)
        except Exception:
            it['is_new'] = False
    # remember items that went quiet for a while, so a return reads as new
    for key, rec in prev.items():
        if key not in out['items'] and mem_ok:
            r = dict(_d(rec))
            r['gone_since'] = r.get('gone_since') or now_iso
            out['items'][key] = r if len(out['items']) < 200 else None
    out['items'] = {k: v for k, v in out['items'].items() if v}
    return out


def fingerprint(facts):
    core = [(it.get('id'), it.get('state'), bool(it.get('is_new')))
            for it in _l(facts.get('items_to_explain'))]
    blob = json.dumps({'p': PROMPT_VERSION, 'd': facts.get('desk'), 'i': sorted(core)},
                      sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


# ════════════════════════════════════════════════════════════════════════
# THE WRITER'S INSTRUCTIONS
# ════════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are the plain-language writer for Asifah Analytics, an open-source geopolitical monitor. Asifah's sensors have already done the analysis for one tracker page: military posture, commodity pressure, or markets. Your job is to make it readable for a reader at any level: what the picture is, what is new, and why it matters (the "So What"), and for each lit item, what it MEANS -- locally, regionally, globally and for the economy -- using only the fact sheet you are given.

VOICE
- Intelligence-product structure in plain words: bottom line first, then support.
- Institutional voice: "we assess", "Asifah reads". Never "I". Never describe yourself or how this text was produced.
- Calm and specific. Name the places, the evidence and the numbers in the fact sheet. No throat-clearing.
- Judgment words are yours ("likely", "appears to", "suggests"), but never claim more certainty than the evidence carries. Never write "will" about the future.
- Answer the unasked question. The reader should finish knowing what changed, what did not, and why someone far away should care.

WHAT THE LEVELS MEASURE
- Every level on these pages reads the weight and seriousness of REPORTING (and, for markets, prices), as described in "desk_note" and each item's "level_words". It is not a count of ships, battles or shortages, and not a probability. Say "reporting describes..." rather than presenting a level as a measured fact on the ground.
- Use each item's "level_words" to say a level in plain words. Do not invent a level the item does not carry.
- A keyword alert or heavy reporting is never "fighting" or "an attack" on its own. Say an attack or seizure happened only when the evidence headlines report one.
- A "standing_watch" item is a permanent structural exposure. It explains why something matters; it is never the news or the lead.

FRESHNESS -- THE MOST IMPORTANT RULE
- What is new is decided by AGE, not prominence. An item is new only if "is_new" is true. "since": "before <date>" means it was already present when Asifah began this record -- long-running, age unknown. "previous_state" shows what it changed from.
- Never write "rising", "escalating", "tightening" or "worsening" unless an item is new with a "previous_state" lower than its state.
- If nothing is new, say so plainly in the headline. That is a finding.

HOW IT MUST READ (Rachel, Nov 3: "full sentences, in a natural voice, telling the reader what they are seeing")
- Write like a sharp colleague briefing a smart friend over coffee: whole sentences, plain words, a natural rhythm. Never a list of labels.
- Never show an internal state word as a label or in capitals: "surge", "contested", "standing_watch", "firing", "offramp_market_mixed", "rhetoric_pending", "pattern_match", "theatre". Say what each means ("reporting describes confrontation around ships, but they are still getting through"; "the markets have not made up their minds").
- Every "what_it_means" opens with the thing itself and what is happening to it today, then why that matters. No sentence fragments, no colons used as bullets.
- Grouped items ("Military activity by region", "Commodities under heavy news pressure") are one paragraph each: name the leaders, say what the grouping shows, do not list every member.
- Lead the read with what matters most to someone outside the field: a shipping lane, fuel, food, money, a war.

THE MEANING LAYER (this page's purpose)
- For EACH item in "items_to_explain", write an entry in "items" with its exact "id". "what_it_means" is 1-2 sentences: what this reading means TODAY, given its state and evidence -- not a dictionary definition. Then one sentence each for "local" (the country, waterway or market itself), "regional" (neighbours and the region), "global" (the wider world and great-power politics) and "economy" (prices, trade, money, borrowing).
- Build these from the item's "meaning_basis", "facts" and "evidence". The meaning_basis describes the STRUCTURE (what flows through a strait, who depends on it); combine it with the CURRENT state. Example of the move: a contested strait = structure ("a fifth of the world's oil passes here") + state ("reporting describes boardings, but ships are still passing") -> meaning ("the risk is being priced into insurance and freight; supply has not stopped").
- Scale the altitudes to the evidence. If an item is merely monitored, say the wider effects are potential, not present. If an altitude has nothing in the fact sheet to support it, write a short honest line ("No regional effect is reported yet.") rather than inventing one.
- You may explain HOW a mechanism works in general terms (why rerouting raises freight costs, why a weaker currency raises import prices). You may NOT add current events, numbers, names or dates that are not in the fact sheet.
- "not_implied" on an item lists what the reading must not be taken to mean. Respect it.

PATTERN RECOGNITION (market desk)
- When an analog item is supplied, say how closely today matches (the share of conditions in common), WHICH conditions match ("shared_conditions") and which do not ("present_now_not_then", "present_then_not_now"), what the chain of events was then ("mechanism_then", "chain"), how long it took then ("interval_then"), and what the effects were ("effects"). Say plainly this describes what happened THEN, not what will happen now.
- If the analog's "data_spine" is partial, or "what_the_match_is_not" says the match cannot see the episode's real mechanism (for example a currency peg), say that clearly and early: the match is about the conditions Asifah measures, not proof the same crisis is forming.
- If "live_checks" says which steps of the old chain Asifah can see today and whether they are lit, report that: it is the most useful line in the read.
- If the match strength is weak or thin, say so first.
- A "market_read" item is a market OUTSIDE the US matching a past episode on its own index and currency. Name the market, the pattern, the conditions it shares and the ones it lacks, what happened then and how long it took, and the steps prices cannot show ("not_visible_in_prices"). A strained market abroad matters even when US markets look calm; say so when that is the case.
- Conflict repricing: say in plain words whether the money agrees with the diplomacy, using the gauges listed, and what that means for the country, its neighbours and oil.

HONESTY
- Use only the fact sheet. "Unread", "unmeasured" or missing means Asifah could not see it; never turn it into "calm".
- Convergence, not prediction. Do not forecast, and do not recommend any action (buying, selling, travel, policy).
- Facts marked "verified": false are reference figures awaiting review; use them as approximate ("roughly", "about").
- Never mention the fact sheet, its fields, or Asifah's mechanics ("is_new", "since", "items_to_explain", "meaning_basis", "fingerprint", "detector", "composite", "Jaccard", "feature overlap", "tripwire"). Say what they mean.
- No disclaimer lines in the prose; the page carries the label.

TERMS
- Spell it "Hizballah". Tickers become plain words. Hype words ("unprecedented", "black swan", "crisis", "collapse") only when the evidence supports them, never as a headline's first word.

OUTPUT
Return ONLY a JSON object with exactly these keys:
  "headline": at most 18 words; the page's picture in plain words, leading with what changed or saying plainly that nothing did.
  "so_what": exactly 2 sentences for a smart reader who does not follow this subject.
  "read": 110-180 words for a practitioner: what is new, what is long-running, why it matters beyond the immediate place, and what would change the picture.
  "watch": 2-3 short, concrete things to look for next, drawn from the fact sheet.
  "items": one object per item in items_to_explain, each {"id", "what_it_means", "local", "regional", "global", "economy"}."""

_ITEM_SCHEMA = {
    'type': 'object',
    'properties': {k: {'type': 'string'} for k in ('id', 'what_it_means', 'local', 'regional',
                                                    'global', 'economy')},
    'required': ['id', 'what_it_means', 'local', 'regional', 'global', 'economy'],
    'additionalProperties': False,
}
OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'headline': {'type': 'string'},
        'so_what': {'type': 'string'},
        'read': {'type': 'string'},
        'watch': {'type': 'array', 'items': {'type': 'string'}},
        'items': {'type': 'array', 'items': _ITEM_SCHEMA},
    },
    'required': ['headline', 'so_what', 'read', 'watch', 'items'],
    'additionalProperties': False,
}


def _clean(t):
    return ' '.join(str(t or '').split())


_NONE_RX = {
    'disrupted': re.compile(r'\b(no|none|not any|zero)\b[^.;]{0,50}\bdisrupt', re.I),
    'contested': re.compile(r'\b(no|none|not any|zero)\b[^.;]{0,50}\bcontest', re.I),
}


def make_validator(allowed_ids, facts=None):
    allowed = set(allowed_ids)
    lanes = _d(_d(facts).get('shipping_lanes_status'))

    def _validate(obj):
        if not isinstance(obj, dict):
            raise ValueError('not an object')
        rec = {}
        for f in ('headline', 'so_what', 'read'):
            t = _clean(obj.get(f))
            if not t:
                raise ValueError('%s empty' % f)
            rec[f] = t
        if len(rec['headline'].split()) > 32:
            raise ValueError('headline too long')
        # v1.2.0: a write-up that says "none disrupted" while a lane IS disrupted is rejected
        # (the call is retried, then the deterministic read is used).
        blob = ' '.join(rec[f] for f in ('headline', 'so_what', 'read'))
        for state, rx in _NONE_RX.items():
            if _l(lanes.get(state)) and rx.search(blob):
                raise ValueError('says no lane is %s while %s is' % (state, _l(lanes.get(state))[0]))
        rec['watch'] = [_clean(w) for w in (obj.get('watch') or []) if _clean(w)][:3]
        items = {}
        for it in obj.get('items') or []:
            if not isinstance(it, dict) or it.get('id') not in allowed:
                continue                       # an id we did not send is dropped, never shown
            items[it['id']] = {k: _clean(it.get(k)) for k in ('what_it_means', 'local', 'regional',
                                                              'global', 'economy')}
        if _gv is not None:
            rec = _gv.fix_terms(rec)
            items = {k: _gv.fix_terms(v) for k, v in items.items()}
        rec['items'] = items
        return rec
    return _validate


# ════════════════════════════════════════════════════════════════════════
# EXPLAINERS -- the deterministic, always-on layer
# ════════════════════════════════════════════════════════════════════════
def _join(xs):
    xs = [x for x in xs if x]
    if len(xs) <= 1:
        return ''.join(xs)
    return ', '.join(xs[:-1]) + ' and ' + xs[-1]


def _first_sentence(t):
    t = ' '.join(str(t or '').split())
    m = re.search(r'(?<=[.!?])\s', t)
    return t[:m.start()] if m else t


def _lc(t):
    return (t[:1].lower() + t[1:]) if t else t


def _bare(name):
    return str(name or '').split(' (')[0]


def item_sentence(it):
    """2-4 plain sentences for one lit item, from Asifah's own notes. This is
    the always-on read; the AI's what_it_means replaces it when written."""
    kind, name, state = it.get('kind'), it.get('name') or '', it.get('state') or ''
    mb, f, ev = _d(it.get('meaning_basis')), _d(it.get('facts')), _l(it.get('evidence'))
    try:
        if kind == 'chokepoint':
            short = name.split(' /')[0]
            short = short if short.lower().startswith('the ') else 'The ' + short
            parts = ['%s %s.' % (short, M.CHOKEPOINT_STATE_SENTENCE.get(state, 'is being watched'))]
            if ev:
                parts.append('Recent reporting: \u201c%s.\u201d' % _bare(ev[0]).split(' - ')[0].rstrip('.'))
            pl = mb.get('plain', '')
            if pl:
                parts.append('This is ' + _lc(pl) if pl.split(' ')[0] in ('The', 'A', 'An') or pl.startswith("Egypt") else pl)
            if state != 'monitored' and mb.get('economy'):
                parts.append(mb['economy'])
            return ' '.join(p for p in parts if p)
        if kind == 'pair':
            return ('Two linked sea passages are under pressure at the same time: %s. %s %s'
                    % (name, mb.get('plain', ''), f.get('why_this_pair', ''))).strip()
        if kind == 'regions':
            bits = []
            for r in _l(f.get('regions'))[:5]:
                acts = [_bare(a) for a in _l(r.get('actors'))[:3]]
                bits.append('%s in %s (%s)' % (M.ACTOR_LEVEL_WORDS.get(r.get('level'), r.get('level')),
                                               r.get('region'), _join(acts)))
            return ('Military reporting is %s. %s' % ('; '.join(bits), mb.get('plain', ''))).strip()
        if kind == 'neo':
            return ('Governments are moving people out: %s, involving %s. %s'
                    % (it.get('level_words'), _join(_l(f.get('actors'))[:4]) or 'several governments',
                       mb.get('plain', ''))).strip()
        if kind == 'commodities':
            rows = _l(f.get('commodities'))
            named = ['%s (%s)' % (r.get('commodity'), r.get('level')) for r in rows[:7]]
            out = '%d commodit%s drawing heavy, serious news coverage: %s.' % (
                len(rows), 'y is' if len(rows) == 1 else 'ies are', _join(named))
            loud = [r for r in rows if r.get('loudest_headline')]
            if loud:
                out += ' The loudest story, on %s: \u201c%s.\u201d' % (
                    _lc(loud[0]['commodity']), _bare(loud[0]['loudest_headline']).split(' - ')[0].rstrip('.'))
            out += ' This measures how much reporting there is, not prices; check the price lines before reading it as a shortage.'
            return out
        if kind == 'convergence':
            cm, ct = it.get('commodity_name'), it.get('country_name')
            if state == 'firing':
                lead = ('%s is active: %s is under heavy pressure and the trigger in %s it depends on has been '
                        'confirmed.' % (name, _lc(cm) if cm else 'the commodity', ct) if ct else
                        '%s is active: the commodity is under heavy pressure and its trigger has been confirmed.' % name)
            else:
                lead = ('%s is a standing exposure: it is always there, and it is shown so you know it exists, '
                        'not because anything new happened.' % name)
            tail = mb.get('plain', '')
            facts_txt = [str(v) for k, v in f.items()
                         if k not in ('watch', 'measurement') and isinstance(v, str) and len(v) < 160][:2]
            out = ' '.join(x for x in (lead, (tail[:1].upper() + tail[1:]) if tail else '') if x)
            if facts_txt and len(out) < 300:
                out += ' Key facts: ' + '; '.join(facts_txt) + '.'
            return out
        if kind == 'fragility':
            cond = [c.get('condition') for c in _l(f.get('conditions_present_now')) if c.get('condition')]
            n = len(cond)
            out = ('Market fragility is %s: %d of the ten warning signs seen before past market crashes %s '
                   'present in US markets now.' % (state, n, 'is' if n == 1 else 'are'))
            if cond:
                out += ' Among them: ' + _lc(cond[0].rstrip('.')) + '.'
            out += ' ' + M.FRAGILITY_BAND_MEANING.get(state, '')
            return out
        if kind == 'analog':
            out = ('Today\'s US market conditions share %s%% of their warning signs with the months before the %s (%s).'
                   % (f.get('similarity_pct'), name, _month_words(f.get('event_month'))))
            if f.get('what_the_match_is_not'):
                out += ' ' + _first_sentence(f['what_the_match_is_not'])
            if f.get('interval_then'):
                out += ' Back then: ' + _lc(_first_sentence(f['interval_then']))
            return out
        if kind == 'market_read':
            out = it.get('level_words') or mb.get('plain', '')
            if f.get('interval_then'):
                out += ' In that episode: ' + _lc(_first_sentence(f['interval_then']))
            return out
        if kind == 'repricing':
            out = '%s, %s.' % (M.REPRICING_LEAD.get(it['id'].split(':', 1)[1], name),
                               M.REPRICING_STATE_SHORT.get(state, words_or(state)))
            g = _l(f.get('gauges_over_about_a_week'))
            if g:
                out += ' Over about a week: %s.' % _join(g)
            return out
    except Exception:
        pass
    return mb.get('plain', '') or name


_MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
           'September', 'October', 'November', 'December']


def _month_words(ym):
    try:
        y, m = str(ym).split('-')[:2]
        return '%s %s' % (_MONTHS[int(m) - 1], y)
    except Exception:
        return str(ym or '')


def words_or(state):
    return str(state or '').replace('_', ' ')


def fallback_view(facts):
    """A GPI-shaped read built only from Asifah's notes -- shown until the AI
    write-up exists (and whenever it cannot be written)."""
    items = _l((facts or {}).get('items_to_explain'))
    if not items:
        return None
    desk = facts.get('desk')
    by = {}
    for it in items:
        by.setdefault(it['kind'], []).append(it)
    if desk == 'military':
        hot = [i for i in by.get('chokepoint', []) if i['state'] in ('contested', 'disrupted')]
        regs = _l(_d((by.get('regions') or [{}])[0].get('facts')).get('regions'))
        head = ('%s %s' % (hot[0]['name'], hot[0]['state']) if hot else 'No major shipping lane contested')
        if regs:
            head += '; military reporting heaviest in %s' % _join([r['region'] for r in regs[:2]])
    elif desk == 'commodities':
        grp = _l(_d((by.get('commodities') or [{}])[0].get('facts')).get('commodities'))
        firing = [i['name'] for i in by.get('convergence', []) if i['state'] == 'firing']
        head = ('%d commodities under heavy news pressure, led by %s' % (len(grp), _join([_lc(g['commodity']) for g in grp[:2]]))
                if grp else 'No commodity under heavy news pressure')
        if firing:
            head += '; %s active' % firing[0]
    else:
        fr = (by.get('fragility') or [{}])[0]
        an = (by.get('analog') or [{}])[0]
        head = 'Market fragility %s' % (fr.get('state') or 'unread')
        if an:
            head += '; closest past pattern %s (%s%%)' % (an.get('name'), _d(an.get('facts')).get('similarity_pct'))
    s1 = _first_sentence(item_sentence(items[0]))
    s2 = _first_sentence(item_sentence(items[1])) if len(items) > 1 else ''
    return {'headline': head[:1].upper() + head[1:], 'so_what': ' '.join(x for x in (s1, s2) if x),
            'read': '', 'watch': [], 'items': {}}


def explainers(facts):
    out = []
    for it in _l((facts or {}).get('items_to_explain')):
        mb = _d(it.get('meaning_basis'))
        out.append({
            'id': it['id'], 'kind': it['kind'], 'name': it['name'], 'state': it['state'],
            'level_words': it.get('level_words'), 'is_new': bool(it.get('is_new')),
            'since': it.get('since'), 'previous_state': it.get('previous_state'),
            'plain': mb.get('plain', ''), 'local': mb.get('local', ''), 'regional': mb.get('regional', ''),
            'global': mb.get('global', ''), 'economy': mb.get('economy', ''),
            'facts': it.get('facts') or {}, 'not_implied': it.get('not_implied') or '',
            'evidence': it.get('evidence') or [], 'basis': it.get('basis'),
            'sentence': item_sentence(it),
            'verified': it.get('verified', True),
        })
    return out


# ════════════════════════════════════════════════════════════════════════
# REFRESH
# ════════════════════════════════════════════════════════════════════════
def _style_flags(view):
    if _gv is None:
        return []
    blob = {'v': {'headline': view.get('headline', ''), 'so_what': view.get('so_what', ''),
                  'read': view.get('read', ''), 'watch': view.get('watch', [])}}
    for k, v in (view.get('items') or {}).items():
        blob[k] = {'headline': '', 'so_what': v.get('what_it_means', ''),
                   'read': ' '.join([v.get('local', ''), v.get('regional', ''), v.get('global', ''),
                                     v.get('economy', '')]), 'watch': []}
    return _gv.style_flags(blob)


def _write(desk, facts, as_of, reason):
    fp = fingerprint(facts)
    latest = _rget(LATEST_KEY % desk) or {}
    if latest.get('fingerprint') == fp and latest.get('view'):
        return {'status': 'reused', 'fingerprint': fp}
    if _gv is None:
        return {'status': 'disabled_no_gpi_voice'}
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return {'status': 'disabled_no_key'}
    now = time.time()
    if reason != 'manual' and now - (latest.get('last_attempt_epoch') or 0) < MIN_GAP_SEC:
        return {'status': 'min_gap'}
    day = _today()
    n_desk, n_all = _count(CALLS_KEY % (desk, day)), _count(CALLS_KEY % ('all', day))
    if n_desk >= DESK_CAP:
        return {'status': 'daily_cap_reached', 'cap': DESK_CAP}
    if n_all >= TOTAL_CAP:
        return {'status': 'total_cap_reached', 'cap': TOTAL_CAP}
    _rset(CALLS_KEY % (desk, day), {'n': n_desk + 1}, 2 * 24 * 3600)
    _rset(CALLS_KEY % ('all', day), {'n': n_all + 1}, 2 * 24 * 3600)
    latest['last_attempt_epoch'] = now
    _rset(LATEST_KEY % desk, latest, VOICE_TTL)
    ids = [it['id'] for it in _l(facts.get('items_to_explain'))]
    try:
        t0 = time.time()
        view, usage = _gv._call_claude(facts, system=SYSTEM_PROMPT, schema=OUTPUT_SCHEMA,
                                       validate=make_validator(ids, facts), max_tokens=MAX_TOKENS)
        rec = {
            'desk': desk, 'desk_name': DESK_NAMES[desk], 'view': view, 'fingerprint': fp,
            'generated_at': datetime.now(timezone.utc).isoformat(), 'source_as_of': as_of,
            'model': getattr(_gv, 'VOICE_MODEL', None), 'voice_version': __version__,
            'usage': usage, 'seconds': round(time.time() - t0, 1), 'reason': reason,
            'last_attempt_epoch': now, 'calls_today': n_desk + 1,
            'label': 'Plain-language read, AI-drafted from Asifah signals',
            'style_flags': _style_flags(view),
        }
        _rset(LATEST_KEY % desk, rec, VOICE_TTL)
        print('[Tracker voice] %s written in %.0fs -- %s in / %s out, ~$%.3f (%d/%d today)'
              % (desk, rec['seconds'], usage.get('input_tokens'), usage.get('output_tokens'),
                 usage.get('est_cost_usd', 0), n_desk + 1, DESK_CAP))
        return {'status': 'written', 'fingerprint': fp, 'usage': usage}
    except Exception as e:
        print('[Tracker voice] %s call failed (non-fatal, last write-up stays): %s' % (desk, str(e)[:200]))
        latest['last_error'] = str(e)[:200]
        latest['last_error_at'] = datetime.now(timezone.utc).isoformat()
        _rset(LATEST_KEY % desk, latest, VOICE_TTL)
        return {'status': 'call_failed', 'error': str(e)[:200]}


def refresh(desk, allow_call=True, reason='organic'):
    """Pack the desk from its caches, update memory, store facts, and write if
    the facts changed (and allow_call). Never raises."""
    if desk not in DESKS:
        return {'status': 'unknown_desk'}
    with _lock:
        if _running.get(desk):
            return {'status': 'already_running'}
        _running[desk] = True
    try:
        facts, as_of = pack(desk)
        if facts is None:
            return {'status': 'no_source', 'reason': as_of}
        mem, mem_ok = _rget_checked(MEMORY_KEY % desk)
        new_mem = apply_memory(facts, mem, mem_ok=mem_ok)
        if mem_ok:
            _rset(MEMORY_KEY % desk, new_mem, MEMORY_TTL)
        facts['source_as_of'] = as_of
        _rset(FACTS_KEY % desk, facts, VOICE_TTL)
        if not allow_call:
            return {'status': 'packed_only', 'fingerprint': fingerprint(facts)}
        return _write(desk, facts, as_of, reason)
    except Exception as e:
        return {'status': 'refresh_failed', 'error': str(e)[:200]}
    finally:
        with _lock:
            _running[desk] = False


def refresh_from_stored(desk):
    """Rachel's manual link: rewrite one desk from its last stored facts."""
    facts = _rget(FACTS_KEY % desk)
    if not isinstance(facts, dict):
        r = refresh(desk, allow_call=True, reason='manual')
        return r
    return _write(desk, facts, facts.get('source_as_of'), 'manual')


def latest(desk):
    """Stored write-up + always-on explainers. Never calls Claude."""
    rec = _rget(LATEST_KEY % desk) or {}
    facts = _rget(FACTS_KEY % desk)
    if not isinstance(facts, dict):
        facts, _ = pack(desk)                  # cold store: pack from caches (Redis reads only)
        facts = facts if isinstance(facts, dict) else {}
    out = {'desk': desk, 'desk_name': DESK_NAMES.get(desk, desk),
           'explainers': explainers(facts), 'source_as_of': facts.get('source_as_of'),
           'meanings_version': M.__version__}
    if rec.get('view'):
        out.update({k: v for k, v in rec.items() if k not in ('last_attempt_epoch',)})
        out['available'] = True
    else:
        out['available'] = False
        out['last_error'] = rec.get('last_error')
        out['fallback_view'] = fallback_view(facts)
        out['note'] = 'No AI write-up yet; fallback_view and the explainers are built from Asifah\'s own notes.'
    return out


# ════════════════════════════════════════════════════════════════════════
# BACKGROUND LOOP + FLASK
# ════════════════════════════════════════════════════════════════════════
def _loop():
    time.sleep(LOOP_FIRST_DELAY_SEC)
    try:
        from instance_lock import my_turn
    except Exception:
        def my_turn(_job):
            return True
    while True:
        try:
            if not my_turn('tracker_voice'):
                continue
            for desk in DESKS:
                st = refresh(desk, allow_call=True, reason='organic')
                print('[Tracker voice] %s: %s' % (desk, st.get('status')))
        except Exception as e:
            print('[Tracker voice] loop error: %s' % str(e)[:160])
        time.sleep(LOOP_INTERVAL_SEC)


def register_tracker_voice_endpoints(app, start_background=True):
    from flask import request, jsonify

    @app.route('/api/tracker-voice', methods=['GET', 'OPTIONS'])
    def api_tracker_voice():
        """?desk=military|commodities|market. Reading never calls Claude.
        &refresh=<VOICE_REFRESH_TOKEN> rewrites that desk once (caps apply)."""
        if request.method == 'OPTIONS':
            return '', 200
        desk = (request.args.get('desk') or '').strip().lower()
        if desk not in DESKS:
            return jsonify({'available': False, 'error': 'unknown desk', 'desks': list(DESKS)}), 400
        status = None
        token = os.environ.get('VOICE_REFRESH_TOKEN') or ''
        given = request.args.get('refresh') or ''
        if token and given:
            import hmac
            status = (refresh_from_stored(desk) if hmac.compare_digest(token, given)
                      else {'status': 'refresh_token_rejected'})
        out = latest(desk)
        if status:
            out['refresh'] = status
        return jsonify(out)

    @app.route('/api/tracker-voice/meanings', methods=['GET'])
    def api_tracker_meanings():
        """The reference library itself (for the pages' glossary and for review)."""
        return jsonify({'version': M.__version__, 'as_of': M.AS_OF,
                        'chokepoints': M.CHOKEPOINTS, 'terms': M.TERMS,
                        'chokepoint_levels': M.CHOKEPOINT_LEVEL_MEANING,
                        'theatre_levels': M.THEATRE_LEVEL_MEANING,
                        'commodity_levels': M.COMMODITY_LEVEL_MEANING,
                        'fragility_bands': M.FRAGILITY_BAND_MEANING,
                        'repricing_states': M.REPRICING_STATE_MEANING,
                        'repricing_theatres': M.REPRICING_THEATRES})

    if start_background:
        threading.Thread(target=_loop, daemon=True, name='tracker-voice').start()
    print('[Tracker voice] v%s routes: /api/tracker-voice, /api/tracker-voice/meanings '
          '(caps %d/desk, %d total per day)' % (__version__, DESK_CAP, TOTAL_CAP))
