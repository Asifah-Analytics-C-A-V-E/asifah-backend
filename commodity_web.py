"""
commodity_web.py -- Asifah Analytics  (ME backend, commodities)
================================================================================
WHAT MOVES A COMMODITY, AND WHAT THE COMMODITY MOVES.

THE QUESTION (Rachel, Oct 29 2026)
  "Tracking the global convergences of a certain commodity and how other world
  events either affect it or it has effects on world events." Rice first, then
  beyond. Kept on constant watch, but a CLOSED box unless something is new, so
  a standing condition never reads as breaking news.

WHY THIS IS NOT A COPY OF WHEAT
  The Levant wheat cluster is OUTBOUND only: four importers, one corridor, fired
  by humanitarian triggers. Wheat's chokepoint is a PLACE (the Black Sea).
  Rice's chokepoint is a POLICY: India is ~40% of world rice trade and a single
  export notification (Sep 2022 broken-rice ban, Jul 2023 non-basmati ban)
  reprices the whole market. A web therefore reads BOTH directions:

    INBOUND   world events -> the commodity
              exporter policy, harvest weather, war/disaster in an exporter,
              the market's own price confirmation, shipping corridors.
    OUTBOUND  the commodity -> world events
              importer governments RESPONDING (price ceilings, tariff cuts,
              emergency tenders) and importers already under food/FX stress.

LEVELS  (a web reports a convergence, never a forecast)
    quiet         nothing lit. Not emitted to the GPI.
    L3 watch      one direction lit (inbound news, or an importer responding).
    L4 convergence  an inbound STRESS (not relief) AND >=1 outbound node lit.
    L5 compound   convergence + the commodity itself at L5 (price AND physical
                  disruption) + >=2 outbound nodes lit.
  Relief is information too: India EASING a ban is news and opens the box, but
  easing never counts toward a convergence -- it does not compound stress.

THE NUANCE RULES  (each one a mistake this module refuses to make)
  * War is not a supply cut. A war or disaster in an exporter is listed as
    EXPOSURE and only counts when the price is rising. India fighting Pakistan
    does not mean Indian rice stopped moving.
  * Talk is not policy. "India may curb exports" is MOOTED, not lit.
  * A forecast is not a harvest. "El Nino could hit yields" is noted, not lit.
  * Importer stress is co-occurrence, not causation. Nigeria's food crisis has
    many parents; the web says it is present while rice is under stress.
  * Absence is named: no corridor sensor, store unread, country unread.

FRESHNESS -- THE CLOSED BOX
  Every lit element (channel:state, country:state) is remembered with the time
  it first appeared. A web is FRESH only if an element appeared in the last
  72 hours or the level ROSE. Otherwise it is STANDING and the GPI collapses it.
  First sighting of a web (deploy day) seeds as standing. No store -> standing.
  A newly-added profile seeds on its own first cycle, so adding zinc next month
  will not make zinc shout NEW.

PURE MODULE. No Redis, no HTTP, no Flask. The caller passes readers, a price
function and an optional redis_get/redis_set pair.

ADDING A COMMODITY: add a profile to COMMODITY_WEBS and a matching
`commodity_web_<id>` entry to convergence_registry.py. Nothing else.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import re
from datetime import datetime, timezone, timedelta

__version__ = '1.0.0'

WEB_STATE_KEY = 'commodity_web:state'
WEB_STATE_TTL = 120 * 24 * 3600
FRESH_WINDOW_HOURS = 72
CARRIER_LEVEL = 3          # a web carrier never raises the economic axis above watch;
                           # the convergence is told by the GPI narrative, not the axis

STATE_WORD = {0: 'quiet', 3: 'watch', 4: 'convergence', 5: 'compound'}
STATE_COLOR = {0: '#6b7280', 3: '#f59e0b', 4: '#f97316', 5: '#dc2626'}

_HEDGE_RX = re.compile(
    r"\b(could|may|might|consider(?:s|ing)?|mulls?|weighs?|plans? to|proposed?|"
    r"seeks?|calls? for|urged?|threatens?|warns? of|fears?|risk of|forecasts?|"
    r"expected to|likely to|outlook|projected)\b", re.I)


# ════════════════════════════════════════════════════════════════════════
# PROFILES
# ════════════════════════════════════════════════════════════════════════
# 'verified' follows corridor_dependence.py: True = lifted from Rachel's own
# COUNTRY_COMMODITY_EXPOSURE notes; False = Claude research, carried and
# flagged, awaiting her correction pass.

COMMODITY_WEBS = {
    'rice': {
        'registry_id': 'commodity_web_rice',
        'label': 'Rice',
        'icon': '\U0001F35A',
        'as_of': '2026-10-29',
        'subject_rx': r'\b(rice|paddy|basmati)\b',
        'chokepoint_kind': 'policy',
        'chokepoint_note': (
            "Rice's chokepoint is a policy, not a strait. India supplies roughly 40% "
            "of world rice trade and its export notifications set the world price: the "
            "Sep 2022 broken-rice ban and the Jul 2023 non-basmati ban (eased in stages "
            "through 2024) sent prices to multi-year highs. Thailand, Vietnam and "
            "Pakistan are the substitutes and gain share whenever India restricts."),
        'export_producers': ['india', 'thailand', 'vietnam', 'pakistan', 'myanmar'],
        'beneficiaries': ['Vietnam', 'Thailand', 'Pakistan'],
        'corridors': [],   # no shipping-lane sensor for rice; declared, not hidden
        'inbound': [
            {'id': 'india_export_policy', 'label': 'India export policy',
             'kind': 'policy',
             'actor_rx': r'\b(india|indian|dgft|new delhi|fci)\b',
             'action_rx': (r'\b(export ban|bans? (?:[\w-]+ ){0,3}exports?|export curbs?|'
                           r'curbs? (?:[\w-]+ ){0,3}exports?|restrict(?:s|ed|ion|ions)? (?:[\w-]+ ){0,3}exports?|'
                           r'export restrictions?|export dut(?:y|ies)|minimum export price|'
                           r'\bmep\b|prohibit(?:s|ed)? (?:[\w-]+ ){0,3}exports?|halts? (?:[\w-]+ ){0,3}exports?)'),
             'easing_rx': (r'\b(lift(?:s|ed|ing)?|eas(?:e|es|ed|ing)|scrap(?:s|ped)?|remov(?:e|es|ed)|'
                           r'relax(?:es|ed)?|allows? (?:[\w-]+ ){0,3}exports?|resum(?:e|es|ed)|'
                           r'cut(?:s)? (?:the )?(?:export )?duty|reopen(?:s|ed)?)\b'),
             'stress_label': 'restricting exports', 'relief_label': 'easing restrictions'},
            {'id': 'other_exporter_policy', 'label': 'Other exporters (Vietnam, Thailand, Pakistan, Myanmar)',
             'kind': 'policy',
             'actor_rx': r'\b(vietnam(?:ese)?|thai(?:land)?|pakistan(?:i)?|myanmar|cambodia)\b',
             'action_rx': (r'\b(export ban|bans? (?:[\w-]+ ){0,3}exports?|export curbs?|'
                           r'restrict(?:s|ed|ion|ions)? (?:[\w-]+ ){0,3}exports?|export restrictions?|'
                           r'halts? (?:[\w-]+ ){0,3}exports?|export quotas?)'),
             'easing_rx': r'\b(lift(?:s|ed)?|eas(?:e|es|ed)|scrap(?:s|ped)?|resum(?:e|es|ed))\b',
             'stress_label': 'restricting exports', 'relief_label': 'easing restrictions'},
            {'id': 'harvest_weather', 'label': 'Asian harvest weather',
             'kind': 'weather',
             'harm_rx': (r'\b(monsoon (?:deficit|shortfall|delay(?:ed)?|failure|fail(?:s|ed)?|weak(?:ens|ened)?)|'
                         r'drought|salinity(?: intrusion)?|crop (?:damage|losses?|failure)|'
                         r'harvest (?:losses?|shortfall|damage|failure)|paddy (?:damage|losses?)|'
                         r'(?:floods?|flooding|typhoon|cyclone) (?:[\w-]+ ){0,3}(?:damag|destroy|wipe|submerg|ruin)\w*|'
                         r'output (?:falls?|drops?|slumps?|plunges?))\b'),
             'stress_label': 'harvest damage reported'},
            {'id': 'producer_shock', 'label': 'War or disaster in an exporter', 'kind': 'producer_shock'},
            {'id': 'market', 'label': 'World price', 'kind': 'market'},
            {'id': 'corridor', 'label': 'Shipping corridor', 'kind': 'corridor'},
        ],
        'outbound': [
            {'country': 'philippines', 'label': 'Philippines', 'verified': True,
             'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note",
             'actor_rx': r'\b(philippines?|philippine|manila|nfa|marcos|filipino)\b',
             'response_rx': (r'\b(price (?:ceiling|cap)s?|tariffs?|import (?:ban|surge|tenders?|curbs?)|'
                             r'food security emergency|state of calamity|imports?)\b'),
             'failure_mode': ('RETAIL POLITICS -- among the largest importers, Vietnam the '
                              'dominant supplier; price spikes become price ceilings and tariff '
                              'cuts within weeks (ceilings imposed 2023).')},
            {'country': 'indonesia', 'label': 'Indonesia', 'verified': True,
             'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note",
             'actor_rx': r'\b(indonesia(?:n)?|bulog|bapanas|jakarta)\b',
             'response_rx': r'\b(imports?|tenders?|stocks?|reserves?|stockpile)\b',
             'failure_mode': ('STATE BUFFER -- Bulog reserves and import tenders absorb the '
                              'first shock; a large emergency tender is itself a world-price '
                              'event.')},
            {'country': 'nigeria', 'label': 'Nigeria', 'verified': True,
             'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note",
             'actor_rx': r'\b(nigeria(?:n)?|cbn|abuja|tinubu|lagos)\b',
             'response_rx': (r'\b(imports?|border|duty|waiver|ban|protests?|hunger|'
                             r'price controls?)\b'),
             'failure_mode': ('FX AND BORDERS -- imports gated by central-bank FX access and a '
                              'porous land border; food inflation is a live stability variable.')},
            {'country': 'iran', 'label': 'Iran', 'verified': True,
             'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note",
             'actor_rx': r'\b(iran(?:ian)?|tehran)\b',
             'response_rx': r'\b(imports?|basmati|rupee|ration(?:ing)?|subsid(?:y|ies|ised|ized))\b',
             'failure_mode': ('SANCTIONS-CONSTRAINED PROCUREMENT -- Indian basmati paid partly '
                              'via rupee/barter; rice sits beside wheat in the subsidised, '
                              'stability-sensitive staple basket.')},
            {'country': 'saudi_arabia', 'label': 'Saudi Arabia', 'verified': True,
             'source': "Rachel's COUNTRY_COMMODITY_EXPOSURE note",
             'actor_rx': r'\b(saudi|sago|gfsa|riyadh)\b',
             'response_rx': r'\b(imports?|tenders?|reserves?|basmati)\b',
             'failure_mode': ('FISCAL ABSORPTION -- near-100% imported (Indian/Pakistani '
                              'basmati) but with strategic reserves and the money to pay: the '
                              'exposure is cost and Red Sea routing, not hunger.')},
            {'country': 'bangladesh', 'label': 'Bangladesh', 'verified': False,
             'source': 'Claude research Oct 29 2026 -- verify',
             'actor_rx': r'\b(bangladesh(?:i)?|dhaka)\b',
             'response_rx': r'\b(imports?|tenders?|g2g|duty|price)\b',
             'failure_mode': ('PRODUCER-IMPORTER SWING -- a large producer that imports in bad '
                              'harvest years; flood damage converts into import tenders.'),
             'needs_rachel': 'Confirm import share in a normal year and the main suppliers.'},
            {'country': 'senegal', 'label': 'Senegal (West Africa broken-rice belt)', 'verified': False,
             'source': 'Claude research Oct 29 2026 -- verify',
             'actor_rx': r'\b(senegal(?:ese)?|dakar|west africa(?:n)?)\b',
             'response_rx': r'\b(imports?|price|broken rice|shortages?)\b',
             'failure_mode': ('BROKEN-RICE DEPENDENCE -- West African diets run on imported '
                              'broken rice, historically Indian; India\'s Sep 2022 broken-rice '
                              'ban landed here first.'),
             'needs_rachel': 'Is Senegal the right anchor for the belt, or Cote d\'Ivoire / Ghana?'},
        ],
        'so_what': {
            'region': ('When India restricts, Southeast Asian and West African buyers bid for '
                       'the same Thai, Vietnamese and Pakistani cargoes: one policy shock, '
                       'competing importers, and the substitutes\' prices rise with it.'),
            'global': ('Rice is the calorie staple for roughly half the world. A restriction by '
                       'the price-setter reprices the whole trade and pushes some buyers toward '
                       'wheat, tightening that market too; the exporter windfall goes to Vietnam '
                       'and Thailand.'),
        },
        'watch': ['India DGFT export notifications', 'FAO All Rice Price Index',
                  'Thai and Vietnamese 5% broken export quotes',
                  'Philippines / Indonesia import tenders', 'Indian monsoon progress (IMD)'],
        'not_implied': [
            'Not a forecast of shortage, price or unrest.',
            'An export restriction is a policy setting, not a harvest failure -- it can '
            'reverse in a single notification.',
            'Importer stress listed here is co-occurrence, not causation: it may have '
            'causes that have nothing to do with rice.',
        ],
    },
}


# ════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════

def _titles(summ):
    out = []
    for s in (summ or {}).get('top_signals') or []:
        if isinstance(s, dict):
            t = (s.get('article_title') or s.get('title') or '').strip()
            if t:
                out.append(t)
    return out


def _hedged_before(text, start, width=45):
    return bool(_HEDGE_RX.search(text[max(0, start - width):start]))


def _read_policy(ch, titles, subject_rx):
    """'stress' | 'relief' | 'mooted' | 'quiet', with the headline that set it."""
    actor, action = re.compile(ch['actor_rx'], re.I), re.compile(ch['action_rx'], re.I)
    easing = re.compile(ch['easing_rx'], re.I) if ch.get('easing_rx') else None
    subj = re.compile(subject_rx, re.I)
    found = {'stress': None, 'relief': None, 'mooted': None}
    for t in titles:
        if not (subj.search(t) and actor.search(t)):
            continue
        m = action.search(t)
        if not m:
            continue
        if easing and easing.search(t):
            found['relief'] = found['relief'] or t
        elif _hedged_before(t, m.start()):
            found['mooted'] = found['mooted'] or t
        else:
            found['stress'] = found['stress'] or t
    for st in ('stress', 'relief', 'mooted'):
        if found[st]:
            return st, found[st]
    return 'quiet', None


def _read_weather(ch, titles, subject_rx):
    harm, subj = re.compile(ch['harm_rx'], re.I), re.compile(subject_rx + r'|\b(crops?|harvest|grain)\b', re.I)
    mooted = None
    for t in titles:
        if not subj.search(t):
            continue
        m = harm.search(t)
        if not m:
            continue
        if _hedged_before(t, m.start()):
            mooted = mooted or t
            continue
        return 'stress', t
    return ('mooted', mooted) if mooted else ('quiet', None)


def _producer_in_theatre(producer, theatre_key):
    th = str(theatre_key).lower()
    if th.startswith('region:'):
        return False
    return producer == th or producer in th.split('_') or ('_' in producer and producer in th)


def _label(cid):
    return str(cid).replace('_', ' ').title()


def _join(items):
    items = [i for i in items if i]
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' and ' + items[-1]


# ════════════════════════════════════════════════════════════════════════
# ONE WEB
# ════════════════════════════════════════════════════════════════════════

def read_web(cid, profile, summ, econ_sig, ctx, price_fn=None):
    """Read one commodity web. Pure -- no store, no stamping."""
    titles = _titles(summ)
    subject_rx = profile.get('subject_rx') or r'\b%s\b' % re.escape(cid)
    ctx = ctx or {}

    # Price: prefer what the economic emitter already measured.
    price = (econ_sig or {}).get('price_evidence')
    if price is None and callable(price_fn) and summ:
        try:
            price = price_fn(cid, summ)
        except Exception:
            price = None
    price = price or {'state': 'unread', 'reason': 'commodity not in this scan'}
    rising = price.get('state') == 'move' and (price.get('pct') or 0) > 0

    inbound = []
    for ch in profile.get('inbound', []):
        kind = ch['kind']
        rec = {'id': ch['id'], 'label': ch['label'], 'kind': kind,
               'state': 'quiet', 'direction': None, 'evidence': None, 'counts': False}
        if kind == 'policy':
            st, t = _read_policy(ch, titles, subject_rx)
            if st == 'stress':
                rec.update(state='lit', direction='stress', counts=True,
                           evidence='%s: %s' % (ch.get('stress_label', 'restriction'), t))
            elif st == 'relief':
                rec.update(state='lit', direction='relief', counts=True,
                           evidence='%s: %s' % (ch.get('relief_label', 'easing'), t))
            elif st == 'mooted':
                rec.update(state='mooted', evidence='talked about, not done: %s' % t)
        elif kind == 'weather':
            st, t = _read_weather(ch, titles, subject_rx)
            if st == 'stress':
                rec.update(state='lit', direction='stress', counts=True,
                           evidence='%s: %s' % (ch.get('stress_label', 'harvest damage'), t))
            elif st == 'mooted':
                rec.update(state='mooted', evidence='forecast, not yet a harvest: %s' % t)
        elif kind == 'producer_shock':
            hits = []
            for p in profile.get('export_producers', []):
                for th, age in (ctx.get('new_fronts') or {}).items():
                    if _producer_in_theatre(p, th):
                        hits.append('%s at a new active-conflict front (%s, day %s)'
                                    % (_label(p), th.replace('_', ' '), age))
                        break
                d = (ctx.get('disasters') or {}).get(p)
                if d:
                    hits.append('%s under a confirmed-impact natural disaster (L%s)'
                                % (_label(p), d.get('level')))
            unread = [u for u in (ctx.get('unread') or [])
                      if 'kinetic' in u or 'disaster' in u]
            if hits and rising:
                rec.update(state='lit', direction='stress', counts=True,
                           evidence='; '.join(hits[:2]) + ' -- and the price is rising')
            elif hits:
                rec.update(state='exposure',
                           evidence='; '.join(hits[:2]) + ' -- exposure only: the price is '
                                    'not rising, so supply is not shown to be hit')
            elif unread:
                rec.update(state='unread', evidence='could not read: ' + ', '.join(unread))
        elif kind == 'market':
            if price.get('state') == 'move':
                span = '30 days' if price.get('window') == '30d' else 'five sessions'
                rec.update(state='lit', counts=True,
                           direction='stress' if rising else 'relief',
                           evidence='price %s %s%% over %s' % ('up' if rising else 'down',
                                                              abs(round(price.get('pct') or 0)), span))
            elif price.get('state') == 'unread':
                rec.update(state='unread', evidence=price.get('reason') or 'price unread')
            else:
                c30 = price.get('change_pct_30d')
                rec.update(evidence='price not confirming'
                                    + (' (%+.0f%% over 30 days)' % c30 if c30 is not None else ''))
        elif kind == 'corridor':
            cors = profile.get('corridors') or []
            if not cors:
                rec.update(state='no_sensor',
                           evidence='no shipping-corridor sensor for this commodity '
                                    '(declared, not assumed open)')
            else:
                bad = [(c, (ctx.get('corridors') or {}).get(c, 'unknown')) for c in cors]
                hit = [(c, s) for c, s in bad if s in ('impaired', 'blocked')]
                if hit:
                    rec.update(state='lit', direction='stress', counts=True,
                               evidence='; '.join('%s reads %s' % (c.replace('_', ' '), s.upper())
                                                  for c, s in hit))
                elif all(s == 'unknown' for _, s in bad):
                    rec.update(state='unread', evidence='corridor state not in Redis')
        inbound.append(rec)

    outbound = []
    hum = ctx.get('hum_by_country')
    subj = re.compile(subject_rx, re.I)
    for node in profile.get('outbound', []):
        rec = {'country': node['country'], 'label': node['label'], 'state': 'quiet',
               'evidence': None, 'failure_mode': node.get('failure_mode'),
               'verified': node.get('verified', False), 'source': node.get('source'),
               'needs_rachel': node.get('needs_rachel')}
        actor = re.compile(node['actor_rx'], re.I)
        resp = re.compile(node['response_rx'], re.I)
        mooted = None
        for t in titles:
            if not (subj.search(t) and actor.search(t)):
                continue
            m = resp.search(t)
            if not m:
                continue
            if _hedged_before(t, m.start()):
                mooted = mooted or t
                continue
            rec.update(state='responding', evidence='government/market response: %s' % t)
            break
        if rec['state'] == 'quiet':
            if hum is None:
                rec.update(state='unread', evidence='humanitarian read unavailable')
            else:
                worst = None
                for (cat, lvl, txt) in hum.get(node['country'], []):
                    food = cat in ('food_price_crisis', 'currency_collapse', 'aid_shortfall')
                    if (food and lvl >= 3) or lvl >= 4:
                        if worst is None or lvl > worst[1]:
                            worst = (cat, lvl, txt)
                if worst:
                    rec.update(state='stressed',
                               evidence='already under stress (L%d %s): %s'
                                        % (worst[1], worst[0].replace('_', ' '), worst[2][:110]))
                elif mooted:
                    rec.update(evidence='response talked about, not taken: %s' % mooted)
        outbound.append(rec)

    lit_in = [r for r in inbound if r['counts']]
    stress_in = [r for r in lit_in if r['direction'] == 'stress']
    relief_only = bool(lit_in) and not stress_in
    responding = [r for r in outbound if r['state'] == 'responding']
    lit_out = [r for r in outbound if r['state'] in ('responding', 'stressed')]
    econ_level = int((econ_sig or {}).get('level') or 0)

    if stress_in and lit_out:
        level = 5 if (econ_level >= 5 and len(lit_out) >= 2) else 4
    elif lit_in or responding:
        level = 3
    else:
        level = 0

    reading = {
        'commodity': cid, 'registry_id': profile.get('registry_id'),
        'label': profile.get('label', _label(cid)), 'icon': profile.get('icon', ''),
        'level': level, 'state': STATE_WORD[level], 'color': STATE_COLOR[level],
        'relief_only': relief_only, 'econ_level': econ_level,
        'inbound': inbound, 'outbound': outbound,
        'chokepoint_kind': profile.get('chokepoint_kind'),
        'chokepoint_note': profile.get('chokepoint_note'),
        'watch': profile.get('watch', []), 'not_implied': profile.get('not_implied', []),
        'as_of': profile.get('as_of'),
        'unverified_nodes': [n['country'] for n in profile.get('outbound', [])
                             if not n.get('verified')],
    }
    reading.update(_compose(profile, reading, stress_in, lit_in, lit_out, responding))
    return reading


_PHRASE = {
    ('india_export_policy', 'stress'): 'India restricting exports',
    ('india_export_policy', 'relief'): 'India easing export curbs',
    ('other_exporter_policy', 'stress'): 'a substitute exporter restricting exports',
    ('other_exporter_policy', 'relief'): 'a substitute exporter easing curbs',
    ('market', 'stress'): 'the world price rising',
    ('market', 'relief'): 'the world price falling',
}
_KIND_PHRASE = {'weather': 'harvest damage in producing countries',
                'producer_shock': 'war or disaster hitting an exporter',
                'corridor': 'a shipping corridor impaired'}


def _phrase(x):
    return (_PHRASE.get((x['id'], x.get('direction')))
            or _KIND_PHRASE.get(x['kind'])
            or ('%s (%s)' % (x['label'], 'easing' if x.get('direction') == 'relief' else 'stress')))


def _out_phrase(lit_out):
    resp = [x['label'].split(' (')[0] for x in lit_out if x['state'] == 'responding']
    strs = [x['label'].split(' (')[0] for x in lit_out if x['state'] == 'stressed']
    bits = []
    if resp:
        bits.append('%s %s' % (_join(resp[:3]), 'is responding' if len(resp) == 1 else 'are responding'))
    if strs:
        bits.append('%s %s already under stress' % (_join(strs[:3]), 'is' if len(strs) == 1 else 'are'))
    return ' and '.join(bits)


_PHRASE_ORDER = {'policy': 0, 'market': 1, 'weather': 2, 'corridor': 3, 'producer_shock': 4}


def _compose(profile, r, stress_in, lit_in, lit_out, responding):
    """Headline, detail and the So What at three altitudes."""
    # Lead with the most direct evidence: a policy act, then the market, and
    # an exposure-type channel (war/disaster in an exporter) last.
    stress_in = sorted(stress_in, key=lambda x: _PHRASE_ORDER.get(x['kind'], 9))
    lit_in = sorted(lit_in, key=lambda x: _PHRASE_ORDER.get(x['kind'], 9))
    name = r['label']
    lvl = r['level']
    in_words = _join([_phrase(x) for x in lit_in][:3])
    if lvl == 0:
        headline = '%s web quiet -- nothing moving it, nothing it is moving' % name
    elif lvl == 3 and r['relief_only']:
        headline = '%s web on watch -- relief: %s' % (name, in_words)
    elif lvl == 3 and lit_in:
        headline = '%s web on watch -- %s; no importer stress read alongside it' % (name, in_words)
    elif lvl == 3:
        headline = '%s web on watch -- %s responding to %s' % (
            name, _join([x['label'].split(' (')[0] for x in responding][:3]), name.lower())
    elif lvl == 4:
        headline = '%s convergence -- %s while %s' % (
            name, _join([_phrase(x) for x in stress_in][:2]), _out_phrase(lit_out))
    else:
        headline = '%s COMPOUND convergence -- supply rupture (%s) while %s' % (
            name, _join([_phrase(x) for x in stress_in][:2]), _out_phrase(lit_out))

    parts = []
    if r.get('chokepoint_note'):
        parts.append(r['chokepoint_note'])
    if lit_in:
        parts.append('INBOUND (what is moving %s): ' % name.lower()
                     + ' | '.join(x['evidence'] for x in lit_in if x.get('evidence')) + '.')
    noted = [x for x in r['inbound'] if x['state'] in ('mooted', 'exposure')]
    if noted:
        parts.append('Noted, not counted: ' + ' | '.join(x['evidence'] for x in noted[:2]) + '.')
    if lit_out:
        parts.append('OUTBOUND (what %s is moving): ' % name.lower()
                     + ' | '.join('%s -- %s' % (x['label'], x['evidence']) for x in lit_out[:4]) + '.')
    if any(x['direction'] == 'stress' and x['kind'] == 'policy' for x in lit_in) \
            and profile.get('beneficiaries'):
        parts.append('Who gains: %s exporters, in share and price.' % _join(profile['beneficiaries']))

    so_what = {}
    if lit_out:
        so_what['country'] = ' '.join('%s: %s' % (x['label'].split(' (')[0], x['failure_mode'])
                                      for x in lit_out[:3] if x.get('failure_mode'))
    if lvl >= 4 or (lvl == 3 and stress_in):
        so_what['region'] = (profile.get('so_what') or {}).get('region')
        so_what['global'] = (profile.get('so_what') or {}).get('global')
    elif lvl == 3 and r['relief_only']:
        so_what['global'] = ('Relief, not stress: easing pressure on %s lowers import costs for '
                             'the exposed buyers -- the box opened because the setting changed, '
                             'not because risk rose.' % name.lower())
    so_what = {k: v for k, v in so_what.items() if v}
    if so_what:
        parts.append('SO WHAT -- ' + ' '.join('%s: %s' % (k.upper(), v) for k, v in so_what.items()))
    if r.get('not_implied'):
        parts.append('NOT IMPLIED: ' + ' '.join(r['not_implied']))
    return {'headline': headline, 'detail': ' '.join(parts), 'so_what': so_what}


# ════════════════════════════════════════════════════════════════════════
# FRESHNESS -- the closed box
# ════════════════════════════════════════════════════════════════════════

def _elements(reading):
    els = set()
    for x in reading['inbound']:
        if x['counts']:
            els.add('in:%s:%s' % (x['id'], x['direction'] or 'lit'))
    for x in reading['outbound']:
        if x['state'] in ('responding', 'stressed'):
            els.add('out:%s:%s' % (x['country'], x['state']))
    return els


def apply_freshness(readings, store, now=None):
    """Mutates readings (fresh, fresh_basis, new_elements) and returns the new store.

    store is the prior value of WEB_STATE_KEY, or None if it could not be read.
    The caller decides whether a read failure is 'no store' (pass store_ok=False).
    """
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    store = store if isinstance(store, dict) else {}
    webs = store.get('webs') if isinstance(store.get('webs'), dict) else {}
    out = {'tracking_began': store.get('tracking_began') or now_iso, 'webs': {}}
    cutoff = now - timedelta(hours=FRESH_WINDOW_HOURS)

    for r in readings:
        cid = r['commodity']
        prev = webs.get(cid) if isinstance(webs.get(cid), dict) else None
        cur = _elements(r)
        rec = {'elements': {}, 'level': r['level'],
               'max_level_72h': r['level'], 'level_rose_at': None}
        if prev is None:
            # First sighting of this web: seed as standing. A deploy is not news.
            for e in cur:
                rec['elements'][e] = 'seeded'
            r['fresh'] = False
            r['fresh_basis'] = 'first observation -- seeded as standing'
            r['new_elements'] = []
        else:
            pel = prev.get('elements') if isinstance(prev.get('elements'), dict) else {}
            new = []
            for e in cur:
                first = pel.get(e) or now_iso
                rec['elements'][e] = first
                if first != 'seeded':
                    try:
                        if datetime.fromisoformat(first) >= cutoff:
                            new.append(e)
                    except Exception:
                        pass
            prev_level = int(prev.get('level') or 0)
            rose_at = prev.get('level_rose_at')
            if r['level'] > prev_level:
                rose_at = now_iso
            rec['level_rose_at'] = rose_at
            rose_recent = False
            if rose_at:
                try:
                    rose_recent = datetime.fromisoformat(rose_at) >= cutoff
                except Exception:
                    rose_recent = False
            r['new_elements'] = sorted(new)
            if r['level'] == 0:
                r['fresh'], r['fresh_basis'] = False, 'quiet'
            elif new or rose_recent:
                r['fresh'] = True
                r['fresh_basis'] = ('new in the last %dh: %s' % (FRESH_WINDOW_HOURS, ', '.join(sorted(new)))
                                    if new else 'level rose to L%d' % r['level'])
            else:
                r['fresh'] = False
                r['fresh_basis'] = 'nothing new in %dh -- standing' % FRESH_WINDOW_HOURS
        out['webs'][cid] = rec
    return out


# ════════════════════════════════════════════════════════════════════════
# ALL WEBS + STAMPING
# ════════════════════════════════════════════════════════════════════════

def build_webs(summaries, econ_signals, ctx, price_fn=None,
               redis_get=None, redis_set=None, profiles=None, now=None):
    """Read every web, apply freshness, stamp registry flags.

    Returns (carriers, report):
      carriers  new signals to append to the global_commodity BLUF -- one per
                web that is lit but whose commodity was not admitted on its own.
      report    every web, quiet ones included, for /api/commodity-web.

    The registry flag goes on the commodity's own economic signal when it
    exists (that IS the commodity's published signal); otherwise on a carrier
    held at L3 so a web never inflates the economic axis by itself.
    Never raises.
    """
    profiles = profiles if profiles is not None else COMMODITY_WEBS
    by_cid = {s.get('commodity'): s for s in (econ_signals or []) if isinstance(s, dict)}
    readings, carriers = [], []
    report = {'version': __version__, 'webs': [], 'store': 'unread',
              'generated_at': datetime.now(timezone.utc).isoformat()}
    try:
        for cid, prof in profiles.items():
            try:
                readings.append(read_web(cid, prof, (summaries or {}).get(cid),
                                         by_cid.get(cid), ctx, price_fn))
            except Exception as e:
                readings.append({'commodity': cid, 'label': prof.get('label', cid), 'level': 0,
                                 'state': 'error', 'error': str(e)[:120], 'inbound': [],
                                 'outbound': [], 'headline': '', 'detail': ''})

        store, store_ok = None, False
        if callable(redis_get) and callable(redis_set):
            try:
                store, store_ok = redis_get(WEB_STATE_KEY), True
            except Exception:
                store, store_ok = None, False
        if store_ok:
            new_store = apply_freshness([r for r in readings if r.get('state') != 'error'],
                                        store, now)
            try:
                redis_set(WEB_STATE_KEY, new_store, WEB_STATE_TTL)
                report['store'] = 'ok'
            except Exception:
                report['store'] = 'write failed'
        else:
            for r in readings:
                r['fresh'] = False
                r['fresh_basis'] = 'no baseline store -- held as standing (closed) until history exists'
                r['new_elements'] = []
            report['store'] = 'unavailable -- every web held as standing'

        for r in readings:
            report['webs'].append(r)
            if r.get('level', 0) < 3 or not r.get('registry_id'):
                continue
            rid = r['registry_id']
            carrier = by_cid.get(r['commodity'])
            if carrier is None:
                carrier = {
                    'category': 'commodity_web_%s' % r['commodity'],
                    'commodity': r['commodity'],
                    'theatre': 'global_commodity', 'region': 'global_commodity',
                    'level': CARRIER_LEVEL, 'pressure_type': 'economic',
                    'icon': r.get('icon') or '\U0001F578', 'color': r.get('color'),
                    'short_text': ('%s %s' % (r.get('icon', ''), r['headline'])).strip()[:160],
                    'long_text': r['detail'], 'priority': CARRIER_LEVEL * 3,
                    'fresh': r.get('fresh', False), 'web_carrier': True,
                }
                carriers.append(carrier)
            carrier['%s_active' % rid] = True
            carrier.setdefault('convergence_states', {})[rid] = {
                'alert_level':   r['state'],
                'signal_count':  len([x for x in r['inbound'] if x['counts']])
                                 + len([x for x in r['outbound'] if x['state'] in ('responding', 'stressed')]),
                'is_fresh':      bool(r.get('fresh')),
                'commodity':     None,
                'gate':          {'kind': 'commodity_web', 'level': r['level'],
                                  'fresh_basis': r.get('fresh_basis')},
                'live_headline': r['headline'],
                'live_detail':   r['detail'],
                'web_level':     r['level'],
                'priority':      {3: 10, 4: 13, 5: 15}.get(r['level'], 10),
                'layer2_version': 'commodity_web %s' % __version__,
            }
    except Exception as e:
        report['error'] = str(e)[:200]
    return carriers, report


def log_report(report):
    """One line per web, printed every cycle, quiet ones included."""
    print('[CommodityWeb] v%s store=%s' % (report.get('version'), report.get('store')))
    for r in report.get('webs', []):
        lit_in = [x['id'] for x in r.get('inbound', []) if x.get('counts')]
        lit_out = [x['country'] for x in r.get('outbound', [])
                   if x.get('state') in ('responding', 'stressed')]
        print('[CommodityWeb]   %-10s L%s %-11s %-8s in=%s out=%s'
              % (r.get('commodity'), r.get('level'), r.get('state'),
                 'FRESH' if r.get('fresh') else 'standing',
                 ','.join(lit_in) or '-', ','.join(lit_out) or '-'))
