"""
mecca_pact_watch.py -- Asifah Analytics (ME backend)
================================================================================
MECCA PACT WATCH  v1.0.0  (Nov 1 2026)

THE QUESTION (from the Oct 31 scoping)
  "Is the Mecca Pact a SHIELD (defending Saudi Arabia from Iran's network), a
  CHANNEL (to Tehran, and between Tehran and Washington), or both -- and which
  members are moving?"

WHY A SEPARATE MODULE
  The Saudi tracker already reads the pact -- but from Riyadh, through a Saudi
  country gate. It cannot hear a Turkish parliamentary debate, a Pakistani DG
  ISPR briefing in Urdu, or Syria's foreign minister "studying" accession unless
  a Saudi-gated outlet repeats it. The members' pages (Pakistan, Turkey, Syria)
  could not see their own treaty commitment at all. This module is the pact's
  ONE home: it reads each member from its OWN capital's press, in its own
  language, and joins that to what the Saudi and Egypt trackers already
  emit. Proxy, not clone: Saudi and Egypt are read from their trackers, never
  re-scanned.

MEMBERS (dated -- MEMBERSHIP_AS_OF)
  saudi_arabia  anchor / signatory      (signed Aug 2026; deterrence activated 5 Oct)
  turkey        signatory / guarantor   (NATO member: the Article 5 tail risk)
  pakistan      signatory / guarantor   (troops present in KSA per DG ISPR, Oct 2026)
  egypt         authorised supporter    (parliament 26 Oct 2026; NOT a signatory)
  syria         studying accession      (FM Shaibani, 21 Aug 2026; re-raised late Oct)

LANES (same three the Saudi tracker counts, plus local-language vocabulary)
  defence      deployment, troops, air defence, intercepts, basing   -> SHIELD
  diplomacy    Tehran, talks, mediation, guarantor, proposal         -> CHANNEL
  enlargement  joining, membership, accession                        -> GROWTH

DOCTRINE
  * Talk is not deployment: hedged phrasing ("could send", "ready to") counts
    as TALK, never as the defence lane.
  * The falsifier is the point (Saudi tracker, Oct 11): if the anchor is under
    fire and no signatory moves, that is the pact-is-paper READING -- a
    finding, not an absence.
  * Unread is not quiet: a member whose feeds fail reads "unread".
  * Egypt is reported, never counted as a signatory.

REDIS
  mecca_pact:latest     payload (13h TTL)
  mecca_pact:history    LPUSH snapshots (lane counts per member, for a tempo
                        baseline once two weeks exist)

ENDPOINTS (register_mecca_pact_endpoints(app))
  GET /api/mecca-pact                 cached; ?refresh=true starts a rescan
  GET /api/mecca-pact?member=turkey   same payload plus 'focus' for that member

No Claude calls anywhere in this module.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import requests

MODULE_VERSION = '1.0.0'

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    feedparser = None
    FEEDPARSER_AVAILABLE = False
    print('[Mecca Pact] feedparser unavailable -- member scans disabled (Saudi/Egypt lenses still read)')

UPSTASH_REDIS_URL = (os.environ.get('UPSTASH_REDIS_URL')
                     or os.environ.get('UPSTASH_REDIS_REST_URL'))
UPSTASH_REDIS_TOKEN = (os.environ.get('UPSTASH_REDIS_TOKEN')
                       or os.environ.get('UPSTASH_REDIS_REST_TOKEN'))

REDIS_KEY_LATEST = 'mecca_pact:latest'
REDIS_KEY_HISTORY = 'mecca_pact:history'
CACHE_TTL_HOURS = 13
REFRESH_HOURS = 6
INITIAL_SCAN_DELAY_SECONDS = 300
RSS_MAX_AGE_DAYS = 8
CACHE_FILE = '/tmp/mecca_pact_cache.json'
HTTP_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

MEMBERSHIP_AS_OF = '2026-11-01'
MEMBERS = {
    'saudi_arabia': {'name': 'Saudi Arabia', 'flag': '\U0001F1F8\U0001F1E6', 'status': 'anchor',
                     'status_text': 'Anchor and signatory (Aug 2026); collective deterrence activated 5 Oct 2026',
                     'signatory': True, 'page': 'rhetoric-saudi_arabia.html'},
    'turkey':       {'name': 'Turkiye', 'flag': '\U0001F1F9\U0001F1F7', 'status': 'signatory',
                     'status_text': 'Signatory and guarantor; also a NATO member',
                     'signatory': True, 'page': 'rhetoric-turkey.html'},
    'pakistan':     {'name': 'Pakistan', 'flag': '\U0001F1F5\U0001F1F0', 'status': 'signatory',
                     'status_text': 'Signatory and guarantor; troops present in Saudi Arabia per DG ISPR (Oct 2026)',
                     'signatory': True, 'page': 'rhetoric-pakistan.html'},
    'egypt':        {'name': 'Egypt', 'flag': '\U0001F1EA\U0001F1EC', 'status': 'supporter',
                     'status_text': 'Not a signatory; parliament authorised support for Saudi Arabia on 26 Oct 2026',
                     'signatory': False, 'page': 'rhetoric-egypt.html'},
    'syria':        {'name': 'Syria', 'flag': '\U0001F1F8\U0001F1FE', 'status': 'candidate',
                     'status_text': 'Studying accession (FM Shaibani, 21 Aug 2026); keeps Russia\'s bases (Aug 2026 deal)',
                     'signatory': False, 'page': 'rhetoric-syria.html'},
}


def _gn(q, hl='en-US', gl='US', ceid='US:en'):
    return f'https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl={hl}&gl={gl}&ceid={ceid}'


# Member-capital feeds. Local-language queries use co-occurrence terms, not an
# assumed official name: the Urdu name is verified from headlines (Oct 11
# handover); the Arabic and Turkish names are not, so those feeds search on
# "Mecca + defence + Saudi" vocabulary and the gate below does the rest.
MEMBER_FEEDS = {
    'turkey': [
        ('en', _gn('(Turkey OR Turkiye) ("Mecca pact" OR "Mecca defence" OR "Mecca defense" OR (Saudi deployment))')),
        ('tr', _gn('Mekke Suudi Arabistan savunma', 'tr', 'TR', 'TR:tr')),
    ],
    'pakistan': [
        ('en', _gn('Pakistan ("Mecca pact" OR "mutual defence" OR "mutual defense") Saudi')),
        ('ur', _gn('مکہ دفاعی معاہدہ', 'ur', 'PK', 'PK:ur')),
    ],
    'syria': [
        ('en', _gn('Syria ("Mecca pact" OR "defence pact" OR "defense pact") Saudi')),
        ('ar', _gn('سوريا مكة دفاع السعودية', 'ar', 'SY', 'SY:ar')),
    ],
}

MEMBER_GATE = {
    'turkey': re.compile(r"\b(turkey|turkiye|türkiye|turkish|ankara|erdogan|erdoğan|fidan|kalin|kalın)\b|"
                         r"(türk|ankara)", re.I),
    'pakistan': re.compile(r"\b(pakistan|pakistani|islamabad|munir|sharif|ispr)\b|"
                           r"(پاکستان|آئی ایس پی آر|عاصم منیر)", re.I),
    'syria': re.compile(r"\b(syria|syrian|damascus|shaibani|sharaa)\b|"
                        r"(سوريا|دمشق|الشيباني|الشرع)", re.I),
}

# A story is about the pact if it names it, or pairs Saudi Arabia with defence
# vocabulary (local scripts included).
_PACT_NAME = re.compile(
    r"\b(mecca (?:pact|defen[cs]e|alliance|joint defen[cs]e)|strategic mutual defen[cs]e|mekke (?:pakt\w*|savunma\w*|ittifak\w*))\b|"
    r"(مکہ دفاعی|معاہدہ مکہ|"
    r"اتفاقية مكة|حلف مكة|ميثاق مكة)", re.I)
_SAUDI = re.compile(r"\b(saudi|riyadh|kingdom|suudi|riyad)\b|(السعودية|الرياض|سعودی)", re.I)

LANE_RX = {
    'defence': re.compile(
        r"\b(deploy\w*|troops?|forces|contingents?|air[\s-]defen[cs]e|intercept\w*|bas(?:e|es|ing)|jets?|"
        r"batter(?:y|ies)|patriot|deterrence|military support|defend\w*|asker\w*|konuşlan\w*|"
        r"hava savunma\w*|caydırıcılık|birlik\w*)\b|"
        r"(نشر|قوات|دفاع جوي|جنود|ردع|"
        r"فوجی|دستے|تعینات)", re.I),
    'diplomacy': re.compile(
        r"\b(tehran|talks?|dialogue|delegation|mediat\w*|proposal|negotiat\w*|guarantor\w*|non-?aggression|"
        r"peace|visit\w*|tahran|görüşme\w*|arabulucu\w*|garantör\w*|müzakere\w*)\b|"
        r"(طهران|محادثات|وساطة|ضامن|مقترح|"
        r"تہران|مذاکرات|ثالثی)", re.I),
    'enlargement': re.compile(
        r"\b(join\w*|membership|accession|expand\w*|enlarg\w*|new members?|katılım\w*|üyelik\w*|genişle\w*)\b|"
        r"(انضمام|عضوية|توسيع|شمولیت|رکنیت)", re.I),
}
_HEDGE = re.compile(r"\b(could|may|might|would|ready to|prepared to|if asked|if requested|consider\w*|"
                    r"mulls?|weighs?|plans? to|studying|study)\b|(قد |مستعد|يدرس)", re.I)
_COMMENTARY = re.compile(r"^\s*(opinion|analysis|explainer|editorial|comment|study|research|interview)\b|"
                         r"\b(what to know|op-ed|why it matters)\b", re.I)


# ============================================================
# REDIS
# ============================================================
def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f'{UPSTASH_REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}, timeout=8)
        if r.status_code != 200:
            return None
        raw = (r.json() or {}).get('result')
        if raw is None:
            return None
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception as e:
        print(f'[Mecca Pact] Redis GET error ({key}): {str(e)[:100]}')
        return None


def _redis_set(key, value, ttl_seconds):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(f'{UPSTASH_REDIS_URL}/setex/{key}/{int(ttl_seconds)}',
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
                          data=json.dumps(value, default=str), timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f'[Mecca Pact] Redis SET error ({key}): {str(e)[:100]}')
        return False


def _redis_lpush_trim(key, value, max_len=120):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        hdr = {'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}
        r = requests.post(f'{UPSTASH_REDIS_URL}/lpush/{key}', headers=hdr,
                          data=json.dumps(value, default=str), timeout=8)
        if r.status_code == 200:
            requests.post(f'{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_len - 1}', headers=hdr, timeout=8)
            return True
    except Exception as e:
        print(f'[Mecca Pact] Redis LPUSH error: {str(e)[:100]}')
    return False


def _redis_lrange(key, n):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return []
    try:
        r = requests.get(f'{UPSTASH_REDIS_URL}/lrange/{key}/0/{n - 1}',
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}, timeout=8)
        out = []
        for e in (r.json() or {}).get('result') or []:
            try:
                out.append(json.loads(e) if isinstance(e, str) else e)
            except Exception:
                continue
        return out
    except Exception:
        return []


# ============================================================
# MEMBER SCANS
# ============================================================
def _too_old(e):
    st = e.get('published_parsed') or e.get('updated_parsed')
    if not st:
        return False
    try:
        return (datetime.now(timezone.utc) - datetime(*st[:6], tzinfo=timezone.utc)) > timedelta(days=RSS_MAX_AGE_DAYS)
    except Exception:
        return False


def fetch_feed(url, lang):
    """(articles, ok). ok=False means the feed could not be read -- not 'no news'."""
    if not FEEDPARSER_AVAILABLE:
        return [], False
    try:
        f = feedparser.parse(url, agent=HTTP_UA)
        if getattr(f, 'bozo', False) and not (f.entries or []):
            return [], False
        out = []
        for e in (f.entries or [])[:40]:
            if _too_old(e):
                continue
            out.append({'title': (e.get('title') or '').strip(), 'url': e.get('link', ''),
                        'published': e.get('published', '') or e.get('updated', ''),
                        'source': ((e.get('source') or {}).get('title') if isinstance(e.get('source'), dict) else None) or 'Google News',
                        'language': lang})
        return out, True
    except Exception as e:
        print(f'[Mecca Pact] feed error ({lang}): {str(e)[:100]}')
        return [], False


def classify_story(title):
    """-> (lanes set, hedged bool). Defence that is hedged becomes 'talk'."""
    lanes = {k for k, rx in LANE_RX.items() if rx.search(title)}
    hedged = bool(_HEDGE.search(title))
    if hedged and 'defence' in lanes:
        lanes.discard('defence')
        lanes.add('talk')
    return lanes, hedged


def scan_member(member, fetch=fetch_feed):
    feeds = MEMBER_FEEDS.get(member) or []
    gate = MEMBER_GATE[member]
    arts, ok_feeds = [], 0
    for lang, url in feeds:
        got, ok = fetch(url, lang)
        ok_feeds += 1 if ok else 0
        arts.extend(got)
    seen, stories = set(), []
    for a in arts:
        t = a.get('title') or ''
        k = re.sub(r'\W+', ' ', t.lower()).strip()[:120]
        if not t or k in seen or _COMMENTARY.search(t):
            continue
        if not gate.search(t):
            continue
        if not (_PACT_NAME.search(t) or (_SAUDI.search(t) and LANE_RX['defence'].search(t))):
            continue
        seen.add(k)
        lanes, hedged = classify_story(t)
        stories.append({**a, 'lanes': sorted(lanes), 'hedged': hedged})
    counts = {k: sum(1 for s in stories if k in s['lanes']) for k in ('defence', 'diplomacy', 'enlargement', 'talk')}
    return {'read': ok_feeds > 0, 'feeds_ok': ok_feeds, 'feeds': len(feeds),
            'stories': len(stories), 'lanes': counts,
            'top': sorted(stories, key=lambda s: s.get('published') or '', reverse=True)[:5]}


def posture(lanes, stories, read=True):
    if not read:
        return 'unread'
    d, c, e = lanes.get('defence', 0), lanes.get('diplomacy', 0), lanes.get('enlargement', 0)
    if stories == 0:
        return 'quiet'
    if d >= 2 and c >= 2 and abs(d - c) <= 1:
        return 'both'
    if d >= 2 and d > c:
        return 'shield'
    if c >= 2 and c >= d:
        return 'channel'
    if e >= 2:
        return 'enlargement'
    if lanes.get('talk', 0):
        return 'talk'
    return 'present'


POSTURE_WORDS = {
    'shield': 'Shield -- defence lane leads', 'channel': 'Channel -- diplomacy lane leads',
    'both': 'Both -- defending and talking', 'enlargement': 'Enlargement talk',
    'talk': 'Talk of deployment, no deployment', 'present': 'Present, below lane threshold',
    'quiet': 'Quiet this week', 'unread': 'Unread this cycle (not quiet)',
    'under_fire': 'Anchor under fire -- the pact is being tested',
    'steady': 'Anchor not under a strike cycle this scan',
}
POSTURE_COLORS = {'shield': '#ef4444', 'channel': '#38bdf8', 'both': '#a78bfa', 'enlargement': '#f59e0b',
                  'talk': '#9ca3af', 'present': '#6b7280', 'quiet': '#4b5563', 'unread': '#374151',
                  'under_fire': '#dc2626', 'steady': '#38bdf8'}


# ============================================================
# LENSES: Saudi and Egypt trackers (read, never re-scanned)
# ============================================================
_LVL_ORDER = ['low', 'normal', 'elevated', 'high', 'surge']


def read_saudi():
    s = _redis_get('rhetoric:saudi_arabia:latest')
    if not isinstance(s, dict):
        return None
    mp = s.get('mecca_pact') or {}
    lanes = (mp.get('lanes') or {}) if isinstance(mp.get('lanes'), dict) else {}
    inner = lanes.get('lanes') if isinstance(lanes.get('lanes'), dict) else {}
    vl = s.get('vector_levels') or {}
    return {
        'theatre_level': s.get('theatre_level'), 'scanned_at': s.get('scanned_at') or s.get('cached_at'),
        'reading': mp.get('reading'), 'note': mp.get('note'),
        'kinetic_level': mp.get('kinetic_level'),
        'turkiye_level': mp.get('turkiye_level'), 'pakistan_level': mp.get('pakistan_level'),
        'lanes': {'defence': inner.get('defence', 0), 'diplomacy': inner.get('diplomacy', 0),
                  'enlargement': inner.get('expansion', 0)},
        'lane_stories': lanes.get('stories'), 'us_drawdown': bool(lanes.get('us_drawdown')),
        'us_anchor_level': vl.get('us_security_anchor'),
    }


def read_egypt():
    e = _redis_get('rhetoric:egypt:latest')
    if not isinstance(e, dict):
        fp = _redis_get('rhetoric:egypt:fingerprint')
        if isinstance(fp, dict):
            gd = fp.get('gulf_defence') or {}
            return {'level': gd.get('level'), 'basis': gd.get('basis'), 'lanes': None, 'stories': 0, 'top': []}
        return None
    gd = (e.get('fronts') or {}).get('gulf_defence') or {}
    titles = [x.get('title') or '' for x in (gd.get('evidence') or [])] + \
             [x.get('title') or '' for x in (gd.get('mooted') or [])] + \
             [x.get('title') or '' for x in (gd.get('relief') or [])]
    lanes = {'defence': 0, 'diplomacy': 0, 'enlargement': 0, 'talk': 0}
    for t in titles:
        ls, _h = classify_story(t)
        for k in ls:
            lanes[k] = lanes.get(k, 0) + 1
    return {'level': gd.get('level'), 'basis': gd.get('basis'), 'claims': gd.get('claims'),
            'lanes': lanes, 'stories': len(titles), 'scanned_at': e.get('scanned_at'),
            'top': [{'title': x.get('title'), 'url': x.get('url'), 'source': x.get('source')}
                    for x in (gd.get('evidence') or [])[:3]]}


# ============================================================
# THE READING
# ============================================================
def build_reading(members, saudi, egypt):
    tested = bool(saudi and (saudi.get('kinetic_level') in ('high', 'surge') or (saudi.get('theatre_level') or 0) >= 3))
    sig_moving = [m for m in ('turkey', 'pakistan')
                  if members[m]['posture'] in ('shield', 'both', 'channel')]
    others = {m: v for m, v in members.items() if m != 'saudi_arabia'}
    shield_side = [m for m, v in others.items() if v['posture'] in ('shield', 'both')]
    channel_side = [m for m, v in others.items() if v['posture'] in ('channel', 'both')]
    unread = [m for m, v in members.items() if v['posture'] == 'unread']

    if tested and not sig_moving and not any(members[m]['posture'] == 'unread' for m in ('turkey', 'pakistan')):
        verdict, word = 'paper', 'Paper pattern -- anchor under fire, signatories flat'
    elif shield_side and channel_side and set(shield_side) != set(channel_side):
        verdict, word = 'both', 'Both -- some members shield, others talk'
    elif shield_side and not channel_side:
        verdict, word = 'shield', 'Shield -- members moving on the defence lane'
    elif channel_side and not shield_side:
        verdict, word = 'channel', 'Channel -- members moving on diplomacy, not defence'
    elif shield_side and channel_side:
        verdict, word = 'both', 'Both -- defending and talking'
    elif any(v['posture'] not in ('quiet', 'unread') for v in others.values()):
        verdict, word = 'present', 'Present -- coverage below the lane threshold'
    else:
        verdict, word = 'quiet', 'Quiet -- no member moving this week' + (' (anchor not under test)' if not tested else '')

    lines = []
    if verdict == 'paper':
        lines.append("Saudi Arabia is under a strike cycle and neither Turkiye nor Pakistan is moving in its own "
                     "press. That is the falsifier the Saudi tracker was built around: the pact-is-paper pattern.")
    if verdict == 'both':
        sh = ', '.join(MEMBERS[m]['name'] for m in shield_side)
        ch = ', '.join(MEMBERS[m]['name'] for m in channel_side)
        lines.append(f"Members are split: on the defence lane {sh}; on the diplomacy lane {ch}. The pact "
                     "is doing both jobs at once -- shielding Riyadh from the Houthis while talking to "
                     "Tehran -- and which side grows next is the read.")
    if verdict == 'channel':
        lines.append("Members are talking more than deploying. A pact that talks while its anchor is under "
                     "fire is behaving as a channel to Tehran -- which fits the 26 Oct joint delegation "
                     "(Saudi Defence Minister, Munir, Kalin) and the guarantor role floated for a US-Iran deal.")
    if members['turkey']['posture'] in ('shield', 'both'):
        lines.append("Turkiye on the defence lane is the NATO tail risk: Turkish troops in Saudi Arabia sit "
                     "outside Article 6, but retaliation on Turkish soil would not.")
    if members['syria']['posture'] in ('enlargement', 'channel', 'both', 'present'):
        lines.append("Syria in the pact conversation while keeping Russia's Tartus and Hmeimim bases is "
                     "multi-alignment, not a break -- and Moscow hedging on Iran.")
    eg = members['egypt']
    if eg['posture'] not in ('quiet', 'unread'):
        lines.append("Egypt is moving as an outsider: authorised, defensive, conditioned on a Saudi request, "
                     "and defending its own Suez revenue as much as Riyadh.")
    if saudi and saudi.get('us_drawdown'):
        lines.append("The incumbent guarantor is shrinking its footprint in the same window (US ordered-departure "
                     "reporting) while the new guarantors talk to Tehran.")
    if unread:
        lines.append('Unread this cycle, not quiet: ' + ', '.join(MEMBERS[m]['name'] for m in unread) + '.')

    totals = {k: sum((v.get('lanes') or {}).get(k, 0) for v in others.values())
              for k in ('defence', 'diplomacy', 'enlargement', 'talk')}
    return {'verdict': verdict, 'verdict_word': word, 'tested': tested,
            'signatories_moving': sig_moving, 'shield_side': shield_side, 'channel_side': channel_side,
            'unread': unread, 'lane_totals': totals, 'lines': lines,
            'hub_question': 'Shield or channel -- and which members are moving?'}


def scan_mecca_pact(fetch=fetch_feed):
    t0 = time.time()
    now = datetime.now(timezone.utc)
    saudi = read_saudi()
    egypt = read_egypt()
    members = {}
    for m, cfg in MEMBERS.items():
        rec = {k: cfg[k] for k in ('name', 'flag', 'status', 'status_text', 'signatory', 'page')}
        if m == 'saudi_arabia':
            if saudi:
                # The anchor's row is its CONDITION (under fire or not), not a lane
                # posture: the Saudi tracker's lane counts are Riyadh's view of the
                # GUARANTORS, so they are shown as that and kept out of the verdict.
                tested = (saudi.get('kinetic_level') in ('high', 'surge')
                          or (saudi.get('theatre_level') or 0) >= 3)
                rec.update(read=True, source="Saudi tracker (Riyadh's view of the guarantors)",
                           lanes=saudi['lanes'], stories=saudi.get('lane_stories') or 0,
                           posture='under_fire' if tested else 'steady',
                           note=saudi.get('note'), riyadh_reading=saudi.get('reading'), top=[])
            else:
                rec.update(read=False, source='Saudi tracker not read', lanes={}, stories=0, posture='unread', top=[])
        elif m == 'egypt':
            if egypt:
                ln = egypt['lanes'] or {}
                rec.update(read=True, source='Egypt tracker, Gulf defence front', lanes=ln,
                           stories=egypt['stories'], posture=posture(ln, egypt['stories']),
                           note=f"Egypt Gulf defence front L{egypt.get('level')} ({egypt.get('basis')})",
                           top=egypt.get('top') or [])
            else:
                rec.update(read=False, source='Egypt tracker not read', lanes={}, stories=0, posture='unread', top=[])
        else:
            sc = scan_member(m, fetch)
            rec.update(read=sc['read'], source=f"own-capital press ({sc['feeds_ok']}/{sc['feeds']} feeds read)",
                       lanes=sc['lanes'], stories=sc['stories'], posture=posture(sc['lanes'], sc['stories'], sc['read']),
                       top=sc['top'])
            if m in ('turkey', 'pakistan') and saudi:
                rec['saudi_view_level'] = saudi.get('turkiye_level' if m == 'turkey' else 'pakistan_level')
        rec['posture_word'] = POSTURE_WORDS[rec['posture']]
        rec['posture_color'] = POSTURE_COLORS[rec['posture']]
        members[m] = rec
    reading = build_reading(members, saudi, egypt)
    hist = _redis_lrange(REDIS_KEY_HISTORY, 60)
    payload = {
        'success': True, 'version': MODULE_VERSION, 'scanned_at': now.isoformat(),
        'scan_seconds': round(time.time() - t0, 1),
        'membership_as_of': MEMBERSHIP_AS_OF, 'members': members, 'reading': reading,
        'anchor': saudi, 'baseline': {'snapshots': len(hist),
                                      'note': ('Tempo baseline builds from two weeks of snapshots; until then '
                                               'lanes are counts, not anomalies.') if len(hist) < 28 else 'baseline available'},
        'disclaimer': 'Convergence indicator, not a probability of action.',
    }
    _redis_set(REDIS_KEY_LATEST, payload, CACHE_TTL_HOURS * 3600)
    _redis_lpush_trim(REDIS_KEY_HISTORY, {'scanned_at': payload['scanned_at'], 'verdict': reading['verdict'],
                                          'lanes': {m: v.get('lanes') for m, v in members.items()}})
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(payload, f, default=str)
    except Exception:
        pass
    print(f"[Mecca Pact] scan done: verdict={reading['verdict']} "
          f"postures={ {m: v['posture'] for m, v in members.items()} } {payload['scan_seconds']}s")
    return payload


# ============================================================
# CACHE / LOOP / FLASK
# ============================================================
_scan_lock = threading.Lock()
_scan_running = {'active': False}


def load_cache():
    c = _redis_get(REDIS_KEY_LATEST)
    if c:
        return c
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _age_hours(p):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(p['scanned_at'])).total_seconds() / 3600
    except Exception:
        return None


def _run_guarded():
    with _scan_lock:
        if _scan_running['active']:
            return
        _scan_running['active'] = True
    try:
        scan_mecca_pact()
    except Exception as e:
        print(f'[Mecca Pact] scan error: {e}')
        traceback.print_exc()
    finally:
        _scan_running['active'] = False


def _loop():
    time.sleep(INITIAL_SCAN_DELAY_SECONDS)
    try:
        from instance_lock import own_this_job as _own
    except ImportError:
        def _own(_n):
            return True
    while True:
        try:
            if _own('mecca_pact_scan'):
                c = load_cache()
                a = _age_hours(c) if c else None
                if a is None or a >= REFRESH_HOURS:
                    _run_guarded()
        except Exception as e:
            print(f'[Mecca Pact] loop error: {e}')
        time.sleep(30 * 60)


def register_mecca_pact_endpoints(app, start_background=True):
    from flask import jsonify, request

    @app.route('/api/mecca-pact', methods=['GET', 'OPTIONS'])
    def api_mecca_pact():
        if request.method == 'OPTIONS':
            return ('', 204)
        force = (request.args.get('refresh', '') or request.args.get('force', '')).lower() in ('true', '1', 'yes')
        cached = load_cache()
        if force or not cached:
            started = not _scan_running['active']
            if started:
                threading.Thread(target=_run_guarded, daemon=True).start()
            if not cached:
                return jsonify({'success': True, 'warming': True,
                                'note': 'First scan running (under a minute). Reload shortly.'}), 202
            cached = dict(cached)
            cached['rescan'] = 'started' if started else 'already_running'
        out = dict(cached)
        out['from_cache'] = True
        age = _age_hours(out)
        out['cache_age_hours'] = round(age, 2) if age is not None else None
        member = (request.args.get('member') or '').lower().strip()
        if member in (out.get('members') or {}):
            out['focus'] = member
        return jsonify(out)

    print('[Mecca Pact] Routes registered: /api/mecca-pact')
    if start_background:
        threading.Thread(target=_loop, daemon=True, name='MeccaPactBG').start()
        print(f'[Mecca Pact] background loop started (first check in {INITIAL_SCAN_DELAY_SECONDS}s)')
