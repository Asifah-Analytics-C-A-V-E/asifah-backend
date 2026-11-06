"""
Asifah Analytics -- WIKIPEDIA ATTENTION  (ME backend)
v1.0.0  (Nov 6 2026)

WHAT IT MEASURES
  How many people READ about a country on Wikipedia each day, compared with
  their usual. News measures journalists, commentary measures pundits, markets
  measure traders. This measures the public.

  Two questions it answers beside the score:
    * Is the world suddenly looking something up before Asifah's level moves?
      ("the conversation is running ahead of the score")
    * Is Asifah reading serious pressure on a country nobody is reading about?
      (a crisis the world is ignoring -- itself a finding)

  Where a local-language Wikipedia is listed (Hebrew for Israel, Persian for
  Iran ...), its readers are counted separately: domestic attention is a
  different signal from foreign attention.

NEVER SCORED
  Like markets and commentary, this sits BESIDE the score. It feeds
  attention_layer.py (flags + the "Beside the score" panel) and, through it,
  the voices as labelled context. It never raises or lowers a level.

SOURCE
  Wikimedia REST API, per-article daily pageviews, agent=user (bots and known
  automated traffic excluded by Wikimedia). Free, no key. Wikimedia asks for a
  descriptive User-Agent; ours names the site.
  https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/...

  Pageviews lag about a day: "recent" means the last 3 complete days.
  Wikipedia keeps years of history, so the baseline works from day one.

METHOD (per article)
  recent   = mean of the last 3 complete days
  usual    = median of days 8-31 back (the 24 days before the last week)
  ratio    = recent / usual
  state    = spike (>= 2.5x and >= MIN_VIEWS a day) | elevated (>= 1.6x)
             | normal | quiet (<= 0.6x) | thin (too few readers to say)
  One day alone never makes a spike: the 3-day mean has to carry it, so a
  single viral day (a Google Doodle, a bot burst that slipped through) is
  damped by the two days around it.
  Per country: the article with the highest ratio (that is not thin) leads.

COST
  $0. About 150 small HTTP reads every 6 hours from the leader instance.
  No Claude calls.

ROUTES (registered from attention_layer.register_attention_routes)
  /api/wiki-attention            every country's state
  /api/wiki-attention/<country>  one country, with each article's 30-day series
  /api/wiki-attention/debug      per-article health (404s mean a title to fix)
"""

import json
import os
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

__version__ = '1.0.0'

UA = {'User-Agent': 'AsifahAnalytics-WikiAttention/1.0 (+https://www.asifahanalytics.com; OSINT research)'}
API = 'https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/%s/all-access/user/%s/daily/%s/%s'
LATEST_KEY = 'wiki:latest'
TTL = 14 * 3600
REFRESH_HOURS = 6
SPACING = 0.15                     # Wikimedia allows far more; be a good citizen anyway

SPIKE_RATIO = 2.5
ELEVATED_RATIO = 1.6
QUIET_RATIO = 0.6
MIN_VIEWS = {'en': 1000}           # daily readers below which a ratio means little
MIN_VIEWS_LOCAL = 300

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
_MEM = {}

# ── WATCHLIST ───────────────────────────────────────────────────────────────
# canonical country id -> list of (wiki project, exact article title).
# Titles must be the article's CURRENT title (a redirect's views are counted
# on the redirect, not the target). /api/wiki-attention/debug lists any title
# that returns 404 so it can be corrected.
# Topic articles (armed groups, straits) are chosen because they are STABLE
# titles that spike when the topic is news -- not leaders, who change.
_EN = 'en.wikipedia'
WATCHLIST = {
    # Middle East
    'iran':         [(_EN, 'Iran'), (_EN, 'Islamic Revolutionary Guard Corps'), (_EN, 'Strait of Hormuz'),
                     ('fa.wikipedia', 'ایران')],
    'israel':       [(_EN, 'Israel'), (_EN, 'Israel Defense Forces'), ('he.wikipedia', 'ישראל')],
    'gaza':         [(_EN, 'Gaza Strip'), (_EN, 'Hamas')],
    'lebanon':      [(_EN, 'Lebanon'), (_EN, 'Hezbollah'), ('ar.wikipedia', 'لبنان')],
    'syria':        [(_EN, 'Syria')],
    'iraq':         [(_EN, 'Iraq')],
    'yemen':        [(_EN, 'Yemen'), (_EN, 'Houthis'), (_EN, 'Bab-el-Mandeb')],
    'saudi_arabia': [(_EN, 'Saudi Arabia')],
    'jordan':       [(_EN, 'Jordan')],
    'egypt':        [(_EN, 'Egypt'), (_EN, 'Suez Canal')],
    'qatar':        [(_EN, 'Qatar')],
    'uae':          [(_EN, 'United Arab Emirates')],
    'oman':         [(_EN, 'Oman')],
    'kuwait':       [(_EN, 'Kuwait')],
    'bahrain':      [(_EN, 'Bahrain')],
    'libya':        [(_EN, 'Libya')],
    'algeria':      [(_EN, 'Algeria')],
    'morocco':      [(_EN, 'Morocco')],
    'tunisia':      [(_EN, 'Tunisia')],
    # Europe
    'russia':       [(_EN, 'Russia'), (_EN, 'Kaliningrad'), ('ru.wikipedia', 'Россия')],
    'ukraine':      [(_EN, 'Ukraine'), ('uk.wikipedia', 'Україна')],
    'belarus':      [(_EN, 'Belarus')],
    'poland':       [(_EN, 'Poland')],
    'turkey':       [(_EN, 'Turkey')],
    'greece':       [(_EN, 'Greece')],
    'cyprus':       [(_EN, 'Cyprus')],
    'hungary':      [(_EN, 'Hungary')],
    'moldova':      [(_EN, 'Moldova'), (_EN, 'Transnistria')],
    'armenia':      [(_EN, 'Armenia')],
    'azerbaijan':   [(_EN, 'Azerbaijan')],
    'kazakhstan':   [(_EN, 'Kazakhstan')],
    'turkmenistan': [(_EN, 'Turkmenistan')],
    'greenland':    [(_EN, 'Greenland')],
    'albania':      [(_EN, 'Albania')],
    'belgium':      [(_EN, 'Belgium')],
    'united_kingdom': [(_EN, 'United Kingdom')],
    # Asia
    'china':        [(_EN, 'China'), (_EN, 'South China Sea')],
    'taiwan':       [(_EN, 'Taiwan'), (_EN, 'Taiwan Strait')],
    'dprk':         [(_EN, 'North Korea')],
    'south_korea':  [(_EN, 'South Korea')],
    'japan':        [(_EN, 'Japan')],
    'philippines':  [(_EN, 'Philippines')],
    'vietnam':      [(_EN, 'Vietnam')],
    'india':        [(_EN, 'India')],
    'pakistan':     [(_EN, 'Pakistan'), (_EN, 'Tehrik-i-Taliban Pakistan')],
    'afghanistan':  [(_EN, 'Afghanistan'), (_EN, 'Taliban')],
    # Africa
    'sudan':        [(_EN, 'Sudan'), (_EN, 'Rapid Support Forces')],
    'south_sudan':  [(_EN, 'South Sudan')],
    'somalia':      [(_EN, 'Somalia'), (_EN, 'Al-Shabaab (militant group)')],
    'ethiopia':     [(_EN, 'Ethiopia')],
    'mali':         [(_EN, 'Mali'), (_EN, "Jama'at Nasr al-Islam wal Muslimin")],
    'burkina_faso': [(_EN, 'Burkina Faso')],
    'niger':        [(_EN, 'Niger')],
    'nigeria':      [(_EN, 'Nigeria')],
    'chad':         [(_EN, 'Chad')],
    'drc':          [(_EN, 'Democratic Republic of the Congo'), (_EN, 'M23 campaign (2022–present)')],
    'kenya':        [(_EN, 'Kenya')],
    'uganda':       [(_EN, 'Uganda')],
    'mozambique':   [(_EN, 'Mozambique')],
    'south_africa': [(_EN, 'South Africa')],
    # Western Hemisphere
    'usa':          [(_EN, 'United States')],
    'venezuela':    [(_EN, 'Venezuela'), ('es.wikipedia', 'Venezuela')],
    'cuba':         [(_EN, 'Cuba')],
    'mexico':       [(_EN, 'Mexico')],
    'colombia':     [(_EN, 'Colombia')],
    'haiti':        [(_EN, 'Haiti')],
    'panama':       [(_EN, 'Panama'), (_EN, 'Panama Canal')],
    'brazil':       [(_EN, 'Brazil')],
    'argentina':    [(_EN, 'Argentina')],
    'chile':        [(_EN, 'Chile')],
    'peru':         [(_EN, 'Peru')],
    'paraguay':     [(_EN, 'Paraguay'), ('es.wikipedia', 'Paraguay')],
    'canada':       [(_EN, 'Canada')],
}

_state = {'running': False, 'last_run': None}
_lock = threading.Lock()


# ── Redis ───────────────────────────────────────────────────────────────────
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


def _rset(key, value, ttl):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        _MEM[key] = json.loads(json.dumps(value, default=str))
        return
    try:
        requests.post('%s/set/%s' % (UPSTASH_REDIS_URL, key),
                      headers={'Authorization': 'Bearer %s' % UPSTASH_REDIS_TOKEN,
                               'Content-Type': 'application/json'},
                      data=json.dumps(value, default=str), params={'EX': int(ttl)}, timeout=8)
    except Exception:
        pass


# ── Maths (pure; tested offline) ────────────────────────────────────────────
def assess(series, project=_EN):
    """series: list of daily view counts, oldest first, ending yesterday."""
    floor = MIN_VIEWS.get(project.split('.')[0], MIN_VIEWS_LOCAL)
    if len(series) < 14:
        return {'state': 'unread', 'why': 'fewer than 14 days of history'}
    recent = sum(series[-3:]) / 3.0
    base_days = series[-31:-7] if len(series) >= 31 else series[:-7]
    usual = statistics.median(base_days) if base_days else 0
    ratio = round(recent / usual, 2) if usual > 0 else None
    out = {'recent_daily': int(round(recent)), 'usual_daily': int(round(usual)), 'ratio': ratio,
           'peak_day': max(series[-7:]) if series else 0}
    if max(recent, usual) < floor:
        out['state'] = 'thin'
        out['why'] = 'under %d readers a day -- too few to read a change' % floor
    elif ratio is None:
        out['state'] = 'unread'
    elif ratio >= SPIKE_RATIO and recent >= floor:
        out['state'] = 'spike'
    elif ratio >= ELEVATED_RATIO:
        out['state'] = 'elevated'
    elif ratio <= QUIET_RATIO:
        out['state'] = 'quiet'
    else:
        out['state'] = 'normal'
    return out


_RANK = {'spike': 4, 'elevated': 3, 'normal': 2, 'quiet': 1, 'thin': 0, 'unread': -1, 'error': -2}


def country_summary(articles):
    """Pick the lead article: highest ratio among readable ones."""
    readable = [a for a in articles if a.get('state') in ('spike', 'elevated', 'normal', 'quiet')]
    if not readable:
        return {'state': 'unread' if not articles or all(a.get('state') in ('error', 'unread') for a in articles)
                else 'thin', 'articles': articles}
    lead = max(readable, key=lambda a: (a.get('ratio') or 0))
    local = [a for a in readable if not a['project'].startswith('en.')]
    rec = {'state': lead['state'], 'ratio': lead.get('ratio'), 'lead_article': lead['title'],
           'lead_project': lead['project'], 'recent_daily': lead.get('recent_daily'),
           'usual_daily': lead.get('usual_daily'), 'articles': articles}
    # "quiet" for a country means EVERY readable article is quiet, not just the lead
    if lead['state'] != 'quiet' and all(a['state'] == 'quiet' for a in readable):
        rec['state'] = 'quiet'
    if local:
        lo = max(local, key=lambda a: (a.get('ratio') or 0))
        rec['local'] = {'project': lo['project'], 'title': lo['title'], 'state': lo['state'],
                        'ratio': lo.get('ratio')}
    rec['sentence'] = sentence(rec)
    return rec


def _lang(project):
    return {'he': 'Hebrew', 'fa': 'Persian', 'ar': 'Arabic', 'ru': 'Russian', 'uk': 'Ukrainian',
            'es': 'Spanish', 'en': 'English'}.get(project.split('.')[0], project.split('.')[0])


def sentence(rec):
    st, r, t = rec.get('state'), rec.get('ratio'), rec.get('lead_article')
    if st == 'spike':
        s = 'Wikipedia readers are looking up "%s" at about %.1f times the usual rate.' % (t, r)
    elif st == 'elevated':
        s = 'Wikipedia readership of "%s" is above usual (about %.1f times).' % (t, r)
    elif st == 'quiet':
        s = 'Fewer people than usual are reading about it on Wikipedia.'
    elif st == 'normal':
        s = 'Wikipedia readership is about usual.'
    else:
        return 'Too few Wikipedia readers to read a change.'
    lo = rec.get('local')
    if lo and lo['state'] in ('spike', 'elevated') and lo['project'] != rec.get('lead_project'):
        s += ' In %s, readers are up too (about %.1f times).' % (_lang(lo['project']), lo.get('ratio') or 0)
    elif lo and lo['state'] in ('spike', 'elevated'):
        s += ' The rise is in the %s-language Wikipedia: domestic readers, not only foreign ones.' % _lang(lo['project'])
    return s


# ── Fetch ───────────────────────────────────────────────────────────────────
def _fetch(project, title, start, end):
    url = API % (project, quote(title.replace(' ', '_'), safe=''), start, end)
    try:
        r = requests.get(url, headers=UA, timeout=15)
        if r.status_code == 404:
            return None, 'HTTP 404 (title not found -- fix it in the watchlist)'
        if r.status_code != 200:
            return None, 'HTTP %s' % r.status_code
        items = r.json().get('items') or []
        by_day = {it['timestamp'][:8]: int(it.get('views') or 0) for it in items}
        return by_day, None
    except Exception as e:
        return None, str(e)[:100]


def scan():
    with _lock:
        if _state['running']:
            return _rget(LATEST_KEY)
        _state['running'] = True
    t0 = time.time()
    try:
        end_d = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        start_d = end_d - timedelta(days=40)
        days = [(start_d + timedelta(days=i)).strftime('%Y%m%d') for i in range((end_d - start_d).days + 1)]
        start, end = days[0] + '00', days[-1] + '00'
        countries, health = {}, []
        for cid, arts in WATCHLIST.items():
            rows = []
            for project, title in arts:
                by_day, err = _fetch(project, title, start, end)
                time.sleep(SPACING)
                if err:
                    rows.append({'project': project, 'title': title, 'state': 'error', 'why': err})
                    health.append({'country': cid, 'project': project, 'title': title, 'ok': False, 'why': err})
                    continue
                series = [by_day.get(d, 0) for d in days]
                a = assess(series, project)
                a.update(project=project, title=title, series=series[-30:])
                rows.append(a)
                health.append({'country': cid, 'project': project, 'title': title, 'ok': True,
                               'state': a['state']})
            countries[cid] = country_summary(rows)
        ok = sum(1 for h in health if h['ok'])
        payload = {
            'version': __version__, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'through_day': end_d.isoformat(), 'scan_seconds': round(time.time() - t0, 1),
            'countries': countries,
            'spikes': sorted([c for c, v in countries.items() if v.get('state') == 'spike']),
            'health': {'articles': len(health), 'ok': ok, 'failed': [h for h in health if not h['ok']]},
            'note': 'Public attention beside the score: never part of it. Pageviews lag a day.',
        }
        _rset(LATEST_KEY, payload, TTL)
        print('[WikiAttention] %d/%d articles read, %d spikes (%.0fs)'
              % (ok, len(health), len(payload['spikes']), time.time() - t0))
        return payload
    finally:
        _state['running'] = False
        _state['last_run'] = time.time()


def latest():
    return _rget(LATEST_KEY)


def _loop():
    try:
        from instance_lock import my_turn as _my_turn
    except ImportError:
        _my_turn = lambda job: True
    time.sleep(120)
    while True:
        try:
            if _my_turn('wiki_attention'):
                scan()
        except Exception as e:
            print('[WikiAttention] scan error: %s' % str(e)[:120])
        time.sleep(REFRESH_HOURS * 3600)


_started = {'v': False}


def register_wiki_routes(app, start=True):
    from flask import jsonify

    @app.route('/api/wiki-attention')
    def _wiki_all():
        p = latest() or {}
        slim = {c: {k: v for k, v in r.items() if k != 'articles'} for c, r in (p.get('countries') or {}).items()}
        return jsonify({'version': __version__, 'generated_at': p.get('generated_at'),
                        'through_day': p.get('through_day'), 'spikes': p.get('spikes', []),
                        'countries': slim, 'available': bool(p)})

    @app.route('/api/wiki-attention/debug')
    def _wiki_debug():
        p = latest() or {}
        return jsonify({'version': __version__, 'generated_at': p.get('generated_at'),
                        'scan_seconds': p.get('scan_seconds'), 'health': p.get('health'),
                        'watchlist_size': sum(len(v) for v in WATCHLIST.values())})

    @app.route('/api/wiki-attention/<cid>')
    def _wiki_one(cid):
        p = latest() or {}
        try:
            from attention_layer import canon
            cid = canon(cid)
        except Exception:
            pass
        return jsonify({'country': cid, 'generated_at': p.get('generated_at'),
                        'record': (p.get('countries') or {}).get(cid)})

    if start and not _started['v']:
        _started['v'] = True
        threading.Thread(target=_loop, daemon=True).start()
    print('[WikiAttention] routes registered: /api/wiki-attention[/<country>|/debug] (v%s, every %dh)'
          % (__version__, REFRESH_HOURS))
