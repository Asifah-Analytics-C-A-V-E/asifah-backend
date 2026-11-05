"""
gpi_voice.py -- Asifah Analytics -- ME backend
================================================================================
THE PLAIN-LANGUAGE VOICE FOR THE GPI.

WHAT IT DOES
  Takes the finished GPI payload, packs it into a compact FACT SHEET (levels,
  what is new vs long-running, the evidence), and asks Claude (Messages API) to
  write it up for a reader at any level: a headline, a two-sentence So What, a
  longer read and what to watch -- for All Vectors and each of the five axes.
  The write-up is stored in Redis and served at /api/gpi/voice; gpi.html shows
  it on top of each tab, with the analyst prose one click below.

WHY THE MESSAGES API, NOT AN AGENT
  The analysis is already done by Asifah's sensors. This is a writer handed a
  fact sheet, not a researcher with a browser -- and it must NOT browse: it may
  only say what the sensors saw. One request in, one write-up out.

COST GUARDRAILS (Rachel: credits cannot auto-reload; nothing may cost money by
accident; ?force must never trigger a Claude call)
  1. REWRITE ONLY WHEN THE FACTS CHANGE. The fact sheet is fingerprinted
     (ages and timestamps excluded); the same facts reuse the stored write-up.
  2. ?force=true NEVER calls Claude. A forced GPI rebuild reuses the last
     write-up. Calls happen on organic rebuilds (12h cache expiry), or on a
     manual refresh protected by VOICE_REFRESH_TOKEN.
  3. DAILY CAP (VOICE_DAILY_CAP, default 6) and a 15-minute minimum gap.
  4. Thinking OFF, compact fact sheet: ~ $0.04-0.05 per write-up on Sonnet 5.5.
  5. Outer fence: the $20/month spend cap in the Claude Console.
  6. Any failure (no key, timeout, bad output) -> the last good write-up, or
     nothing; gpi.html then shows the existing analyst prose. Never blank.

The key is read from the ANTHROPIC_API_KEY environment variable on Render.
It is never in this file and never in the repo.

v1.1.0 (Oct 30 2026)
  * Hizballah spelling fixed in EVERY field (was headline only).
  * Style check: phrases that leak plumbing ("fact sheet", "first seen",
    "72 hours", "tracking began") are FLAGGED in the stored write-up
    (style_flags) and logged. Flag, never block: a rejected write-up would
    have been paid for and thrown away.
  * Background list also catches the humanitarian detector's v1.14.0
    "(retrospective, background)" and annual-comparison rows.
  * New rule in the writer's instructions (Rachel, Oct 30): a keyword alert
    or a rhetoric surge is not active conflict; only a report that fighting
    has actually started or resumed is.
  * _call_claude() takes the system prompt, schema and validator as
    arguments, so regional_voice.py reuses the same call, budget and logging.

v1.3.0 (Nov 5 2026) -- "same headline three days running" (Rachel)
  The write-up only changes when the facts change, and every way it can fail
  to change was SILENT: a reuse, a failed call, the daily cap, the 15-minute
  gap and a forced rebuild all left the old text up with nothing on the page
  to say which. Now:
  * Every check is recorded (gpi:voice:status) -- not just errors.
  * /api/gpi/voice carries a `freshness` block the page shows under the read:
      current          facts unchanged since it was written -- and for how long,
                       so "no new news for 30 hours" is SAID, and flagged for a
                       feed check when it runs past a day
      stale            the facts changed but the writer did not run, with the
                       reason in plain words (failed call, cap, forced rebuild)
    plus the GPI's own input health (regions live, trackers stale/missing).
  * One automatic retry after a min-gap or a failed call (organic paths only;
    a forced rebuild still never leads to a Claude call). The daily cap holds.

v1.3.1 (Nov 5 2026) -- the writer now sees its PREVIOUS read: the old headline,
  when it was written, and which evidence items are new since then. The same
  lead story three days running should say what moved in it (or that nothing
  did) instead of repeating itself. The fingerprint is still computed from the
  facts alone, so this adds no extra calls.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import re
import json
import time
import hashlib
import threading
from datetime import datetime, timezone

import requests

__version__ = '1.3.1'   # Nov 5 2026: the writer sees its previous read (no same-headline days); (1.3.0) freshness block + status of every check + one retry; (1.2.0) what_it_means

VOICE_MODEL       = os.environ.get('VOICE_MODEL', 'claude-sonnet-5-5')
VOICE_DAILY_CAP   = int(os.environ.get('VOICE_DAILY_CAP', '6'))
VOICE_MIN_GAP_SEC = int(os.environ.get('VOICE_MIN_GAP_SEC', '900'))     # 15 min
VOICE_MAX_TOKENS  = 4000
VOICE_THINKING_OFF = os.environ.get('VOICE_THINKING_OFF', 'between_tools')
VOICE_TIMEOUT_SEC = 120
VOICE_KEY         = 'gpi:voice:latest'
VOICE_TTL         = 14 * 24 * 3600
VOICE_CALLS_KEY   = 'gpi:voice:calls:'          # + YYYY-MM-DD
VOICE_STATUS_KEY  = 'gpi:voice:status'          # v1.3.0: outcome of EVERY check
GPI_CACHE_KEY     = 'gpi:global:latest'         # read-only here (freshness / retry)
RETRY_FAILED_SEC  = 30 * 60
UNCHANGED_WARN_H  = 24                          # facts unchanged this long -> suggest a feed check
VIEWS             = ('all_vectors', 'kinetic', 'economic', 'diplomatic',
                     'humanitarian', 'governance')

# USD per million tokens (Claude Platform pricing page, Oct 29 2026). Used only
# to LOG an estimate next to each write-up; the Console is the real ledger.
_PRICES = {'claude-sonnet-5-5': (2.0, 10.0), 'claude-haiku-5-5': (0.10, 0.50),
           'claude-opus-5-5': (4.0, 20.0)}

UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

_lock = threading.Lock()
_running = {'busy': False}


# ════════════════════════════════════════════════════════════════════════
# THE WRITER'S INSTRUCTIONS  (voice v4, Oct 30 2026 -- Rachel's rulings)
# Kept in sync with project doc claude/voice_system_prompt.txt.
# ════════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are the plain-language writer for Asifah Analytics, an open-source geopolitical pressure index. Asifah's sensors have already done the analysis. Your job is to make it readable: tell a reader at any level what the picture is, what is new, and why it matters (the "So What"), using only the fact sheet you are given.

VOICE
- Intelligence-product structure in plain words: bottom line first, then support.
- Institutional voice: "we assess", "Asifah reads". Never "I". Never describe yourself or how this text was produced.
- Calm and specific. Name the countries, the evidence and the numbers that are in the fact sheet. No throat-clearing, no filler.
- Judgment words are yours to choose ("likely", "appears to", "suggests", "probably"), but never claim more certainty than the evidence carries. Never write "will" about the future.
- Answer the unasked question: after reading, the reader should know what changed, what did not, and why they should care.

LEVELS
- Asifah grades pressure L0-L6. In prose, say it in words first, with the level in parentheses the first time it appears in each view, e.g. "heavy but steady (L4)". After that, words only.
- Ladder, for your own use: L1-L2 quiet or routine; L3 watch, something worth tracking; L4 serious, sustained pressure; L5 active conflict or a new escalation (on non-kinetic axes: severe); L6 world-altering shock.
- The INDEX and an AXIS measure different things. An axis level is SEVERITY: how bad the worst reading is. The index level is MOTION: whether the world got worse in the last 14 days. When an axis reads higher than the index, say plainly why (for example: wars are severe but none is new). Never present this as a contradiction.

FRESHNESS -- THE MOST IMPORTANT RULE
- What is new is decided by AGE, not by prominence. An item is new only if "is_new" is true, or its "first_seen" is a plain date within the last 3 days. "first_seen": "before <date>" means OLD -- it was already happening when tracking began, however it is worded. A state that persists ("framework signed, rejected by Hizballah", "talks active") is old unless its first_seen says otherwise. Describe old items as long-running, briefly.
- An axis "motion": "new" only means some reading on it changed; check the items' ages and the calibration_notes before calling anything on that axis news.
- A high level or a prominent story is NOT the same as new. Never write that something is "tightening", "rising", "escalating" or "worsening" unless the fact sheet shows the change.
- Anything "sustained", "standing", in "continuing_l5_fronts", or in "standing_watches" is a continuing condition. Say it is continuing, briefly. Do not present it as news.
- Items in "background_not_news" (annual comparisons, modelled estimates) are context only. Never lead with them. If you mention one, say what it is ("an annual comparison", "a modelled estimate, not confirmed damage").
- If nothing is new on an axis, say so in one sentence. That is a finding, not a failure.

SELECTION
- all_vectors leads with the single highest-consequence NEW development, judged by who and how many it affects and whether it crosses borders or systems. It does not lead with whichever axis happens to be marked new.
- Each "read" covers at most 3 developments. Group or drop the rest. A reader remembers three things.
- If a "continuing_l5_fronts" entry's driver describes something other than fighting (an alignment shift, a market reading), do not call that country a war or an active conflict. Say what the driver actually is, or leave the country out.

SINCE THE LAST READ
- "previous_read" (when present) is the headline you wrote last time, when, and "new_since_previous": the evidence items that were not in that read.
- If your lead story is the same as the previous headline's, the headline must say what is DIFFERENT now (a new country, a new number, a new stage) -- or, if nothing in it moved, lead with the most consequential item in "new_since_previous" instead. Never repeat the previous headline's wording.
- If "new_since_previous" is empty, say plainly in all_vectors that little has changed since the last read, and keep it short.

HONESTY
- Use only facts in the fact sheet. Do not add events, numbers, names, history or context from outside it, even if you believe them true.
- "Unread", "not confirming" or missing data means Asifah could not see it. Never turn it into "calm" or "no risk".
- Asifah reports convergence, not prediction. Do not forecast outcomes or recommend any action (buying, selling, travel, policy).
- PATTERN RECOGNITION IS WELCOME. When the fact sheet supplies a historical pattern or analog, say what today's picture matches, how closely (if given), what happened in that earlier episode and on what timeline. Say plainly that past timelines describe what happened then, not what will happen now. Never introduce an analog the fact sheet does not supply.
- If the fact sheet seems internally inconsistent, write around it conservatively. Do not resolve it by inventing.
- Never mention the fact sheet, its fields, Asifah's tracking mechanics or measurement windows ("the sheet flags", "first-seen date", "held more than 72 hours", "age tracking began"). Say what they MEAN instead: "long-running", "not new", "recently reported", "of unknown age".
- Name things as a reader knows them. Tickers become plain words ("shares in TSMC, the main Taiwan chipmaker"). Asifah category names become descriptions ("several pressures on Israel at once", not "multi-axis convergence reading"; "a warning trigger based on keywords", not "a tripwire").
- No disclaimer lines in the prose ("Asifah reports convergence, not prediction", "this is not a forecast"). The page carries that label; say it through careful wording instead.
- MEANING. When an item carries "what_it_means", use it to tell the reader what the event does in the real world: who is affected, what could get more expensive or scarcer, and over what time frame -- in your own words, never beyond what it says. When an item carries "not_implied", respect it: never claim what it rules out. An item marked "standing" is a long-running condition, not news. A count of articles or a "busier than usual" reading is never an event: say "more reporting than usual on X", never "X hits a severe level".
- Read figures for WHEN and HOW they were counted. A report or study estimating past deaths (for example, deaths from smoke last month) is a retrospective estimate: say so ("a report estimates...in September"). Never present it as an event happening now, and never lead with it.
- A continuing front marked "NOT CONFIRMED AS FIGHTING" is not a war. Leave it out of any list of conflicts. If it matters, describe it as what it is (a rhetoric surge, a flagged trigger) in a clause.
- A keyword alert or a surge in rhetoric is never "active conflict" on its own. Call something active conflict only when the evidence reports actual fighting starting, resuming or continuing (strikes, clashes, ground operations).

TERMS
- Spell it "Hizballah", including when correcting a misspelling in the source.
- Avoid Asifah's internal shorthand (detector names, "composite 4.68", "TCI", "feature overlap", "red line BREACHED", "wheel", "spoke"). If a term of art genuinely helps, use it once and explain it in the same sentence. Example: "markets are a dry forest -- stretched and concentrated, so a spark travels further than usual."
- Hype words ("unprecedented", "black swan", "crisis", "collapse") only when the facts support them at L5 or above, and never as the first word of a headline.

OUTPUT
Return ONLY a JSON object, no other text, with exactly these keys: "all_vectors", "kinetic", "economic", "diplomatic", "humanitarian", "governance". Each value is an object with:
  "headline": at most 15 words; leads with what changed, or says plainly that nothing did.
  "so_what": exactly 2 sentences for a smart reader who does not follow the news.
  "read": 90-150 words for a practitioner: what is new, what is standing, why it matters, and what would change the picture.
  "watch": a list of 2-3 short, concrete things to look for next, drawn from the fact sheet.
"all_vectors" synthesises across the axes and leads with the single most important new development. Each axis view stays on its own axis and may mention another axis in at most one clause."""

_VIEW_SCHEMA = {
    'type': 'object',
    'properties': {
        'headline': {'type': 'string'},
        'so_what':  {'type': 'string'},
        'read':     {'type': 'string'},
        'watch':    {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['headline', 'so_what', 'read', 'watch'],
    'additionalProperties': False,
}
OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {v: _VIEW_SCHEMA for v in VIEWS},
    'required': list(VIEWS),
    'additionalProperties': False,
}


# ════════════════════════════════════════════════════════════════════════
# FACT PACKER  (pack v2.2 -- see the sandbox runs of Oct 29-30)
# ════════════════════════════════════════════════════════════════════════
# Categories that describe actual fighting. A "continuing L5 front" whose driver
# is anything else (a rhetoric-volume surge, a keyword tripwire, an alignment
# reading) is passed to the writer as NOT CONFIRMED AS FIGHTING.
FIGHTING_CATS = ('kinetic_pressure', 'red_line', 'red_line_breached', 'kinetic_threshold',
                 'multi_axis_convergence', 'strategic_strike', 'vector_escalation',
                 'kinetic_tempo', 'ground_operations', 'strike', 'ballistic')
_ROLLUP_PREFIX_RX = re.compile(r'^[\w .\'-]+ humanitarian L\d\s*[—-]\s*', re.I)

PRIORITY_CATS = ('outbreak_spread', 'red_line_breached', 'red_line',
                 'fragility_exogenous_watch', 'commodity_web')
BACKGROUND_RX = re.compile(r'\bYoY\b|year[- ]on[- ]year|\(modelled\)|Population affected by'
                           r'|retrospective|\bbackground\b|annual comparison', re.I)


# FIGHTING is decided by what the signal REPORTS, not by its category name
# (Rachel, Oct 30: a keyword alert is active conflict only when it reports that
# kinetic activity has started or resumed). Tested on the Oct 30 payloads:
#   counts:  "5 ballistic missile alert(s) in 24h", "Active ground operations",
#            "Russian Major Territorial Advance", "War tempo L4 (active)"
#   doesn't: "Tripwire: Hajj Mass Casualty", "TTP -- SURGE-level rhetoric",
#            "Operation True Promise -- Wave Acceleration" (its own text calls it
#            "retaliation signaling"), "PLA coercion at incident-level tempo",
#            "Houthi maritime threat at L4"
# Bare "missile" / "drone" / "strike" are NOT enough: "missile/drone retaliation
# signaling" is talk about strikes, not a strike.
NON_COMBAT_RX = re.compile(r'tripwire|rhetoric|surge-level|silence|quiet|alignment drift'
                            r'|commodity|approaching:', re.I)
KINETIC_EVENT_RX = re.compile(
    r'\b(airstrikes?|air strikes?|strikes? (?:on|against|hit)|struck|attack(?:s|ed)? on'
    r'|clash(?:es|ed)?|shelling|ballistic(?: missile)? alerts?|rocket (?:fire|alerts?)'
    r'|killed|offensive|incursion|ground (?:operations?|L[45])|siege|fighting'
    r'|war tempo|territorial (?:advance|gain)|cross-border (?:fire|L[45]))', re.I)
def is_fighting_signal(s):
    """Does this signal REPORT actual fighting? (Rachel, Oct 30 2026.) Shared by
    the GPI L5 gate, the GPI packer and regional_voice.py."""
    kind = str(s.get('type') or '').lower()
    short = str(s.get('short_text') or '')
    lvl = s.get('level')
    if not isinstance(lvl, int) or lvl < 4:
        return False                     # word levels ("surge") are volume readings
    if kind in ('tripwire', 'actor_signal', 'commodity_coupling') or NON_COMBAT_RX.search(short):
        return False
    return bool(KINETIC_EVENT_RX.search(short + ' ' + str(s.get('long_text') or '')))


def clean(t):
    t = re.sub(r'[\U0001F1E6-\U0001F1FF]{2}', '', t or '')
    t = re.sub(r'[\U0001F300-\U0001FAFF☀-➿️]', '', t)
    return ' '.join(t.split())


def _rank(s):
    cat = str(s.get('category') or '')
    pri = 0 if any(cat.startswith(c) for c in PRIORITY_CATS) else 1
    try:
        lvl = int(s.get('level') or 0)
    except (TypeError, ValueError):
        lvl = 0
    return (pri, -lvl, -(s.get('priority') or 0))


def _front(e):
    drv = clean(e.get('driver') or '')
    cat = drv.split(':', 1)[0].strip().lower() if ':' in drv else ''
    rec = {'where': e.get('display'),
           'held_since': ('before ' if e.get('days_is_floor') else '') + str(e.get('since')),
           'driver': drv[:140] or None}
    if not any(cat.startswith(c) for c in FIGHTING_CATS):
        rec['driver_type'] = ('NOT CONFIRMED AS FIGHTING -- the signal holding this at L5 is '
                              'a rhetoric surge, keyword tripwire or other non-combat reading')
    return rec


def pack(d):
    ax = d['pressure_axes']['axes']
    gate = d.get('level_gate') or {}
    out = {
        'as_of_utc': d.get('generated_at'),
        'index': {
            'level': d.get('global_level'), 'label': d.get('global_label'),
            'why': gate.get('summary') or gate.get('reason'),
            'new_l5_fronts_last_14_days': [f.get('display') for f in gate.get('fresh') or []],
            'continuing_l5_fronts': [_front(e) for e in gate.get('sustained') or []],
            'world_altering_shock_L6': bool((d.get('l6') or {}).get('active')),
        },
        'axes': {},
        'stories': [],
        'standing_watches': [],
        'calibration_notes': [],
        'tracking_note': ('"first_seen" is when Asifah first saw an item. "before <date>" '
                          'means it was already present when age tracking began: OLD, exact '
                          'age unknown. "is_new": true means first seen within 72 hours.'),
    }
    # Global feed signals, used to fill axes with high-importance items the axis
    # top-5 may have crowded out (e.g. outbreak_spread).
    feed = d.get('top_signals') or []
    for name, a in ax.items():
        pool = list(a.get('top_signals') or [])
        pool += [s for s in feed if s.get('pressure_type') == name]
        seen, main, background = set(), [], []
        for s in sorted(pool, key=_rank):
            txt = _ROLLUP_PREFIX_RX.sub('', clean(s.get('short_text')))
            key = txt[:60].lower()
            if not txt or key in seen:
                continue
            seen.add(key)
            row = {'level': s.get('level'), 'where': s.get('theatre') or s.get('region'),
                   'text': txt[:170]}
            # v2.3 (Nov 4 2026): what the event MEANS, written by the tracker that
            # knows the subject. Without it the writer could only restate the
            # headline ("Las Bambas hits a severe rhetoric level").
            if s.get('meaning'):
                row['what_it_means'] = clean(s['meaning'])[:400]
            _ni = s.get('not_implied') or (s.get('what_it_means') or {}).get('not_implied')
            if _ni:
                row['not_implied'] = clean(_ni)[:200]
            if s.get('standing'):
                row['standing'] = True
            if s.get('first_seen'):     # GPI v3.18.0 signal age memory
                row['first_seen'] = (('before ' if s.get('first_seen_is_floor') else '')
                                     + s['first_seen'])
                row['is_new'] = bool(s.get('is_new'))
            if BACKGROUND_RX.search(txt) or s.get('background'):
                row['why_background'] = (
                    'retrospective estimate of a past period, not an event now'
                    if re.search(r'retrospective', txt, re.I) or s.get('retrospective')
                    else 'annual comparison' if re.search(r'YoY|year|annual', txt, re.I)
                    else 'modelled exposure estimate, no confirmed outcome')
                background.append(row)
            else:
                main.append(row)
        out['axes'][name] = {
            'level': a.get('level'), 'motion': a.get('motion'),
            'what_is_new': clean(a.get('motion_note') or ''),
            'by_region': a.get('region_levels'),
            'evidence': main[:5],
            'background_not_news': background[:3],
        }
    for n in d.get('narratives', []):
        if n.get('category') in ('global_baseline', 'global_warning'):
            continue
        rec = {'headline': clean(n.get('headline')),
               'level': n.get('level_hint'),
               'axes': n.get('axes'),
               'unchanged_days': n.get('unchanged_days'),
               'changed_this_cycle': bool(n.get('moved_this_cycle'))}
        if n.get('first_seen'):
            rec['first_seen'] = (('before ' if n.get('first_seen_is_floor') else '')
                                 + n['first_seen'])
            rec['age_days'] = n.get('age_days')
        if n.get('evidence_gate'):
            rec['evidence'] = n['evidence_gate']
        (out['standing_watches'] if n.get('tier') == 'standing' else out['stories']).append(rec)
    cap = d.get('commodity_cap') or {}
    if cap.get('capped'):
        out['calibration_notes'].append(
            '%d country-level commodity "SURGE" readings were held at the level the commodity '
            'itself has earned; commodity news volume is not treated as an economic rupture.'
            % cap['capped'])
    return out


def _evidence_keys(facts):
    """Short text keys for every evidence row and story (v1.3.1)."""
    keys = []
    for ax in (facts.get('axes') or {}).values():
        for r in (ax.get('evidence') or []):
            t = (r.get('text') or '')[:90]
            if t and t not in keys:
                keys.append(t)
    for st in (facts.get('stories') or []):
        t = (st.get('headline') or '')[:90]
        if t and t not in keys:
            keys.append(t)
    return keys


def facts_fingerprint(facts):
    """Hash of the facts that MATTER. Ages and timestamps drift every build
    and must not force a rewrite; a change in what is new, levels or evidence
    must."""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items()
                    if k not in ('as_of_utc', 'age_days', 'unchanged_days')}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    blob = json.dumps(strip(facts), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


# ════════════════════════════════════════════════════════════════════════
# REDIS (Upstash REST)
# ════════════════════════════════════════════════════════════════════════
def _rget(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f'{UPSTASH_REDIS_URL}/get/{key}',
                         headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'}, timeout=5)
        res = r.json().get('result') if r.status_code == 200 else None
        return json.loads(res) if res else None
    except Exception:
        return None


def _rset(key, value, ttl):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(f'{UPSTASH_REDIS_URL}/set/{key}',
                          headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                                   'Content-Type': 'application/json'},
                          data=json.dumps(value, default=str), params={'EX': int(ttl)}, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════════════
# THE CALL
# ════════════════════════════════════════════════════════════════════════
def _validate(obj):
    """Return a cleaned write-up or raise ValueError. A malformed answer is
    discarded, never half-published."""
    if not isinstance(obj, dict):
        raise ValueError('not an object')
    out = {}
    for v in VIEWS:
        x = obj.get(v)
        if not isinstance(x, dict):
            raise ValueError('missing view %s' % v)
        rec = {}
        for f in ('headline', 'so_what', 'read'):
            t = ' '.join(str(x.get(f) or '').split())
            if not t:
                raise ValueError('%s.%s empty' % (v, f))
            rec[f] = t
        if len(rec['headline'].split()) > 30:
            raise ValueError('%s headline too long' % v)
        rec['watch'] = [' '.join(str(w).split()) for w in (x.get('watch') or []) if str(w).strip()][:3]
        out[v] = fix_terms(rec)
    return out


_HEZ_RX = re.compile(r'\bHezboll?ah?\b|\bHizbollah\b|\bHezbolla\b', re.I)


def fix_terms(rec):
    """House spellings in every field of one view (v1.1.0)."""
    def f(t):
        return _HEZ_RX.sub('Hizballah', t) if isinstance(t, str) else t
    return {k: ([f(w) for w in v] if isinstance(v, list) else f(v)) for k, v in rec.items()}


# Phrases that mean the writer is describing Asifah's plumbing instead of the
# world. Flagged, not blocked (see v1.1.0).
_PLUMBING_RX = re.compile(
    r'fact[- ]sheet|first[- ]seen|tracking (?:began|start)|age tracking|\b72[- ]hours?\b'
    r'|\bis_new\b|calibration[_ ]note|\bthe sheet\b|\bfield\b|\bpayload\b|\bdetector\b'
    r'|\btripwire\b|\bTCI\b|\bcomposite score\b|fighting-class', re.I)


def style_flags(views):
    """[(view, phrase), ...] for plumbing phrases found anywhere in the write-up."""
    out = []
    for name, rec in (views or {}).items():
        blob = ' '.join([rec.get('headline', ''), rec.get('so_what', ''), rec.get('read', '')]
                        + list(rec.get('watch') or []))
        for m in _PLUMBING_RX.finditer(blob):
            out.append([name, m.group(0)])
    return out[:20]


def _call_claude(facts, system=None, schema=None, validate=None, max_tokens=None):
    """One Messages API call. Returns (writeup, usage) or raises.

    v1.1.0 -- the prompt, schema and validator are arguments (defaults: the
    GPI's), so regional_voice.py shares this call, its pricing log and its
    thinking-off setting rather than keeping a second copy."""
    system = system or SYSTEM_PROMPT
    schema = schema or OUTPUT_SCHEMA
    validate = validate or _validate
    import anthropic                       # lazy: a missing package must not break the GPI
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key:
        raise RuntimeError('ANTHROPIC_API_KEY not set')
    client = anthropic.Anthropic(api_key=key, timeout=VOICE_TIMEOUT_SEC, max_retries=1)
    msg = client.messages.create(
        model=VOICE_MODEL,
        max_tokens=max_tokens or VOICE_MAX_TOKENS,
        # Oct 30 2026 -- first live call: Sonnet 5.5 rejects {'type': 'disabled'}
        # ("To turn thinking off on this model, send {'type': 'between_tools'}").
        # With no tools in this request, between_tools means no thinking at all.
        thinking={'type': VOICE_THINKING_OFF},
        system=[{'type': 'text', 'text': system,
                 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': json.dumps(facts, separators=(',', ':'),
                                                         ensure_ascii=False, default=str)}],
        output_config={'format': {'type': 'json_schema', 'schema': schema}},
    )
    text = ''.join(getattr(b, 'text', '') for b in msg.content if getattr(b, 'type', '') == 'text')
    writeup = validate(json.loads(text))
    u = msg.usage
    usage = {'input_tokens': getattr(u, 'input_tokens', 0) or 0,
             'output_tokens': getattr(u, 'output_tokens', 0) or 0,
             'cache_read_tokens': getattr(u, 'cache_read_input_tokens', 0) or 0,
             'cache_write_tokens': getattr(u, 'cache_creation_input_tokens', 0) or 0,
             'stop_reason': getattr(msg, 'stop_reason', None)}
    pin, pout = _PRICES.get(VOICE_MODEL, (2.0, 10.0))
    usage['est_cost_usd'] = round((usage['input_tokens'] * pin + usage['output_tokens'] * pout
                                   + usage['cache_read_tokens'] * pin * 0.1
                                   + usage['cache_write_tokens'] * pin * 1.25) / 1e6, 4)
    return writeup, usage


def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


_retry = {'pending': False}


def _record(status, fp=None, gpi_payload=None):
    """v1.3.0: remember the outcome of every check, so a silent reuse and a
    silent failure can be told apart from the page."""
    try:
        dc = (gpi_payload or {}).get('data_completeness') or {}
        _rset(VOICE_STATUS_KEY, {
            'status': status.get('status'), 'error': status.get('error'),
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'fingerprint_now': fp,
            'gpi_generated_at': (gpi_payload or {}).get('generated_at'),
            'inputs': {'regions_live': dc.get('regions_live'), 'regions_expected': dc.get('regions_expected'),
                       'trackers_stale': (dc.get('trackers_stale') or [])[:12],
                       'trackers_missing': (dc.get('trackers_missing') or [])[:12]},
        }, VOICE_TTL)
    except Exception as e:
        print('[GPI voice] status record failed (non-fatal): %s' % str(e)[:100])
    return status


def _schedule_retry(delay):
    """One delayed retry against the CACHED GPI (organic paths only)."""
    if _retry['pending']:
        return
    _retry['pending'] = True

    def _go():
        _retry['pending'] = False
        cached = _rget(GPI_CACHE_KEY)
        if isinstance(cached, dict):
            print('[GPI voice] retrying once after %ss' % int(delay))
            refresh(cached, allow_call=True, reason='retry', _may_retry=False)
    t = threading.Timer(max(60, delay), _go)
    t.daemon = True
    t.start()


def refresh(gpi_payload, allow_call=True, reason='organic', _may_retry=True):
    """Make sure the stored write-up matches this GPI payload's facts.
    v1.3.0: every outcome is recorded; min-gap / failed calls retry once.
    Returns a status dict. Never raises.
    """
    st = _refresh(gpi_payload, allow_call, reason)
    _record(st, st.get('fingerprint'), gpi_payload)
    if _may_retry and allow_call and reason != 'manual':
        if st.get('status') == 'min_gap':
            _schedule_retry(st.get('retry_after_sec', VOICE_MIN_GAP_SEC) + 30)
        elif st.get('status') == 'call_failed' and 'not set' not in (st.get('error') or ''):
            _schedule_retry(RETRY_FAILED_SEC)
    return st


def _refresh(gpi_payload, allow_call=True, reason='organic'):
    try:
        facts = pack(gpi_payload)
    except Exception as e:
        return {'status': 'pack_failed', 'error': str(e)[:160]}
    fp = facts_fingerprint(facts)
    _fp = {'fingerprint': fp}
    latest = _rget(VOICE_KEY) or {}

    if latest.get('fingerprint') == fp and latest.get('views'):
        return {'status': 'reused', 'fingerprint': fp}
    if not allow_call:
        return {'status': 'facts_changed_call_not_allowed', 'fingerprint': fp,
                'note': '?force rebuilds never call Claude; the last write-up stays up'}
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return dict(_fp, status='disabled_no_key')

    with _lock:
        if _running['busy']:
            return dict(_fp, status='already_running')
        _running['busy'] = True
    try:
        now = time.time()
        last = latest.get('last_attempt_epoch') or 0
        # The gap guards against automatic retries hammering the API. A manual
        # refresh (Rachel's secret link) skips it; the daily cap still applies.
        if reason != 'manual' and now - last < VOICE_MIN_GAP_SEC:
            return dict(_fp, status='min_gap', retry_after_sec=int(VOICE_MIN_GAP_SEC - (now - last)))
        calls_key = VOICE_CALLS_KEY + _today()
        calls = int((_rget(calls_key) or {}).get('n', 0))
        if calls >= VOICE_DAILY_CAP:
            return dict(_fp, status='daily_cap_reached', cap=VOICE_DAILY_CAP)
        _rset(calls_key, {'n': calls + 1}, 2 * 24 * 3600)
        latest['last_attempt_epoch'] = now
        _rset(VOICE_KEY, latest, VOICE_TTL)

        t0 = time.time()
        # v1.3.1 -- what changed since the last write-up (call-only; not in the fingerprint)
        now_keys = _evidence_keys(facts)
        call_facts = dict(facts)
        prev_views = latest.get('views') or {}
        if prev_views:
            prev_keys = set(latest.get('evidence_keys') or [])
            call_facts['previous_read'] = {
                'written_at': latest.get('generated_at'),
                'headline': ((prev_views.get('all_vectors') or {}).get('headline') or ''),
                'new_since_previous': [k for k in now_keys if k not in prev_keys][:10] if prev_keys else 'unknown',
            }
        writeup, usage = _call_claude(call_facts)
        rec = {
            'views': writeup,
            'fingerprint': fp,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'gpi_generated_at': gpi_payload.get('generated_at'),
            'gpi_version': gpi_payload.get('version'),
            'model': VOICE_MODEL,
            'voice_version': __version__,
            'usage': usage,
            'seconds': round(time.time() - t0, 1),
            'reason': reason,
            'last_attempt_epoch': now,
            'calls_today': calls + 1,
            'label': 'Plain-language read, AI-drafted from Asifah signals',
            'style_flags': style_flags(writeup),
            'evidence_keys': now_keys[:80],
        }
        if rec['style_flags']:
            print('[GPI voice] style flags (published anyway): %s' % rec['style_flags'][:6])
        _rset(VOICE_KEY, rec, VOICE_TTL)
        print('[GPI voice] wrote %s via %s in %.0fs -- %s in / %s out, ~$%.3f (%d/%d today)'
              % (fp, VOICE_MODEL, rec['seconds'], usage['input_tokens'], usage['output_tokens'],
                 usage['est_cost_usd'], calls + 1, VOICE_DAILY_CAP))
        return {'status': 'written', 'fingerprint': fp, 'usage': usage}
    except Exception as e:
        print('[GPI voice] call failed (non-fatal, last write-up stays): %s' % str(e)[:200])
        latest['last_error'] = str(e)[:200]
        latest['last_error_at'] = datetime.now(timezone.utc).isoformat()
        _rset(VOICE_KEY, latest, VOICE_TTL)
        return dict(_fp, status='call_failed', error=str(e)[:200])
    finally:
        with _lock:
            _running['busy'] = False


def refresh_async(gpi_payload, allow_call=True, reason='organic'):
    """Fire-and-forget: the GPI response never waits for the writer."""
    try:
        threading.Thread(target=refresh, args=(gpi_payload, allow_call, reason),
                         daemon=True, name='gpi-voice').start()
    except Exception as e:
        print('[GPI voice] could not start thread: %s' % str(e)[:120])


def latest():
    """The stored write-up for /api/gpi/voice (no call, ever)."""
    rec = _rget(VOICE_KEY) or {}
    if not rec.get('views'):
        return {'available': False, 'last_error': rec.get('last_error'),
                'note': 'No plain-language write-up yet; the page shows the analyst prose.'}
    out = {k: v for k, v in rec.items() if k not in ('last_attempt_epoch', 'evidence_keys')}
    out['available'] = True
    out['freshness'] = _freshness(rec)
    return out


_REASON = {
    'call_failed': 'the writing call failed',
    'daily_cap_reached': "today's cost cap for the writer was reached",
    'min_gap': 'the writer ran very recently; a retry is scheduled',
    'facts_changed_call_not_allowed': 'the last rebuild was a forced one, which never calls the writer (cost rule)',
    'already_running': 'a rewrite was already in progress',
    'disabled_no_key': 'the writer is switched off (no API key)',
    'pack_failed': 'the signal sheet could not be built',
}


def _hours_since(iso):
    try:
        return round((datetime.now(timezone.utc) - datetime.fromisoformat(str(iso).replace('Z', '+00:00')))
                     .total_seconds() / 3600, 1)
    except Exception:
        return None


def _freshness(rec):
    """Is the write-up on the page the write-up for the CURRENT facts?"""
    st = _rget(VOICE_STATUS_KEY) or {}
    written_h = _hours_since(rec.get('generated_at'))
    out = {'written_at': rec.get('generated_at'), 'hours_since_written': written_h,
           'last_check_at': st.get('checked_at'), 'last_check_status': st.get('status'),
           'gpi_generated_at': st.get('gpi_generated_at'), 'inputs': st.get('inputs')}
    if not st:
        out.update(state='unknown', plain='Freshness not recorded yet (first check after this update).')
        return out
    same = st.get('fingerprint_now') and st.get('fingerprint_now') == rec.get('fingerprint')
    inp = st.get('inputs') or {}
    gaps = []
    if inp.get('regions_live') is not None and inp.get('regions_expected') and inp['regions_live'] < inp['regions_expected']:
        gaps.append('%s of %s regions reporting' % (inp['regions_live'], inp['regions_expected']))
    if inp.get('trackers_stale'):
        gaps.append('%d stale tracker(s)' % len(inp['trackers_stale']))
    if same:
        out['state'] = 'current'
        msg = 'Up to date: the signals have not changed since this was written'
        if written_h is not None and written_h >= UNCHANGED_WARN_H:
            out['state'] = 'unchanged_long'
            msg = ('No change in the signals for %d hours -- either a quiet stretch or a feed problem; '
                   'worth a check' % int(written_h))
        out['plain'] = msg + ('.' if not gaps else ' (inputs: ' + '; '.join(gaps) + ').')
    else:
        out['state'] = 'stale'
        out['plain'] = ('The signals have changed since this was written, but the rewrite did not run: %s. '
                        'The analyst detail below is current.'
                        % _REASON.get(st.get('status'), st.get('status') or 'unknown reason'))
        if st.get('error'):
            out['error'] = st['error']
    return out
