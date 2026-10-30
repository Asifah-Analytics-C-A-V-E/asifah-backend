"""
regional_voice.py -- Asifah Analytics -- ME backend
================================================================================
THE PLAIN-LANGUAGE VOICE FOR THE FIVE REGIONAL BLUFs
(Middle East & North Africa, Asia-Pacific, Europe, Western Hemisphere, Africa)

WHAT IT DOES
  The GPI already fetches every regional BLUF on each build. After that build,
  this module packs each region into a compact FACT SHEET (posture, theatres,
  what is new vs long-running, the evidence) and asks Claude to write it up the
  same way the GPI is written up: a headline (the posture in plain words), a
  two-sentence So What, a fuller read and what to watch.

  Stored per region in Redis and served by the ME backend at
      /api/regional/voice              -> all five regions (gpi.html cards)
      /api/regional/voice?region=africa -> one region (the regional page)
  Each regional page shows it at the top of its BLUF card, with the existing
  analyst prose one click below ("Analyst detail").

WHY IT LIVES ON THE ME BACKEND (not on each regional backend)
  One API key, one $20 Console cap, one daily counter. Copying the key to four
  more Render services would multiply the places it can leak and the places
  spending can happen. The facts are already here: the GPI pulled them.

COST GUARDRAILS (same rules as gpi_voice.py)
  1. Rewrite a region ONLY when its facts change. The fingerprint covers
     levels, what is new, which theatres are confirmed fighting and which
     signals are present -- NOT scores, counts or timestamps, which drift on
     every build and would buy a rewrite that says the same thing.
  2. ?force=true never calls Claude.
  3. Per region: REGION_VOICE_DAILY_CAP (default 2) calls a day and a 15-minute
     minimum gap. All regions together: REGION_VOICE_TOTAL_CAP (default 10).
     Worst case ~$0.21/day for all five on Sonnet 5.5.
  4. Thinking off; the writer's instructions are cached.
  5. Any failure -> the last good write-up stays, or the page shows the
     existing analyst prose. Never blank.

FRESHNESS
  Regional signals do not carry ages, so this module keeps its own memory
  (regional_voice:memory): when each signal was first seen, and when each
  theatre reached its current level. Day zero seeds as "before <date>" (old,
  age unknown). If the memory cannot be read, ages are marked unread and the
  memory is NOT overwritten -- a failed read is not a fresh start.

RACHEL'S RULING (Oct 30 2026)
  "A key word alert does NOT automatically equate active conflict -- active
  conflict is a key word alert that actual kinetic activity has resumed,
  started, etc." Each theatre at L4+ is marked fighting_confirmed only when a
  fighting-class signal (strikes, ground operations, ballistic alerts, war
  tempo, red-line breach) is present for it. Otherwise its level words say
  "high pressure, no confirmed fighting" and the writer is told what drives it.

v1.1.0 (Oct 30 2026, after the first five live write-ups)
  * Each country carries the regional builder's own sentence about it
    (tracker_read) and its hottest vectors -- Cuba's jump to L4 was written up
    as "no lead signal explains the jump" while the BLUF said "regime fracture
    -- armed incident (L4)".
  * Headlines in a signal's sources that REPORT fighting (e.g. "Afghanistan-
    Pakistan border clashes continue" under the TTP rhetoric signal) are passed
    as reported_fighting_headlines. They do NOT flip fighting_confirmed (that
    takes a fighting signal from the tracker) but the writer may say reporting
    includes clashes. Rachel's ruling read both ways: a keyword alert that
    reports kinetic activity is evidence.
  * Dated data: a signal with data_staleness (Lebanon humanitarian: figures as
    of Aug 30, 61 days old) carries data_as_of + the warning, and the writer
    must give the date ("as of late August"). The write-up had said "about
    1.0 million people are displaced" in the present tense.
  * Standing structural exposures (Hormuz oil-import dependence of China,
    Taiwan, Japan, Vietnam) go in their own list; they may explain WHY
    something matters, never lead as news. Asia's So What had led with them.
  * A tracker's own-scale label in a text ("Turkey axis at Rupture (L5)" --
    the Greece ladder, whose top rung maps to platform L4) is marked as the
    tracker's own scale.
  * Vocabulary: "red line breached" is a serious threshold crossed, not a
    "warning trigger"; no "fighting-class"; no speculating where something
    could spread next. PROMPT_VERSION in the fingerprint so this upgrade
    rewrites each region once.

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

import gpi_voice as _gv

__version__ = '1.1.0'
PROMPT_VERSION = 'regional-v2'   # part of the fingerprint: a prompt upgrade rewrites once

REGIONS = ('me', 'asia', 'europe', 'wha', 'africa')
REGION_NAMES = {
    'me':     'Middle East & North Africa',
    'asia':   'Asia-Pacific',
    'europe': 'Europe',
    'wha':    'Western Hemisphere',
    'africa': 'Africa',
}
# Countries that belong to a region's read even when that region has no
# dedicated tracker for them. Everything else is dropped from the region's fact
# sheet. Found Oct 30: the ME BLUF carries ~70 humanitarian rows for the WHOLE
# WORLD (Benin, Haiti, Kiribati...) because it feeds the convergence registry;
# a Middle East read must not lead with Ebola in Kenya.
REGION_EXTRA = {
    'me': {'gaza', 'palestine', 'west_bank', 'jordan', 'egypt', 'libya', 'tunisia',
           'algeria', 'morocco', 'kuwait', 'bahrain'},
    'asia': set(), 'europe': set(), 'wha': set(), 'africa': set(),
}

REGION_VOICE_DAILY_CAP = int(os.environ.get('REGION_VOICE_DAILY_CAP', '2'))
REGION_VOICE_TOTAL_CAP = int(os.environ.get('REGION_VOICE_TOTAL_CAP', '10'))
REGION_VOICE_MIN_GAP   = int(os.environ.get('REGION_VOICE_MIN_GAP_SEC', '900'))
REGION_MAX_TOKENS      = 1600
NEW_HOURS              = 72
FORGET_DAYS            = 30

LATEST_KEY = 'regional_voice:%s:latest'        # % region
FACTS_KEY  = 'regional_voice:%s:facts'         # % region -- for the manual refresh
CALLS_KEY  = 'regional_voice:calls:%s:%s'      # % (region|all, YYYY-MM-DD)
MEMORY_KEY = 'regional_voice:memory'
VOICE_TTL  = 14 * 24 * 3600
MEMORY_TTL = 60 * 24 * 3600

_lock = threading.Lock()
_running = {'busy': False}


# ════════════════════════════════════════════════════════════════════════
# THE WRITER'S INSTRUCTIONS (regional voice v1 -- the GPI voice v4 rules,
# adapted to one region and its rhetoric trackers)
# ════════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are the plain-language writer for Asifah Analytics, an open-source geopolitical monitor. Asifah's sensors have already done the analysis for one region. Your job is to make it readable: tell a reader at any level what the regional picture is, what is new, and why it matters (the "So What"), using only the fact sheet you are given.

VOICE
- Intelligence-product structure in plain words: bottom line first, then support.
- Institutional voice: "we assess", "Asifah reads". Never "I". Never describe yourself or how this text was produced.
- Calm and specific. Name the countries, the evidence and the numbers that are in the fact sheet. No throat-clearing, no filler.
- Judgment words are yours to choose ("likely", "appears to", "suggests", "probably"), but never claim more certainty than the evidence carries. Never write "will" about the future.
- Answer the unasked question: after reading, the reader should know what changed in this region, what did not, and why someone outside the region should care.

WHAT THE LEVELS MEASURE
- Country levels here come from rhetoric trackers: weighted volume and severity of statements by officials, state media, armed groups and open sources -- not counts of events, and not probabilities. Say "rhetoric and reporting point to..." rather than presenting a level as a measured fact on the ground.
- In prose, say a level in words first, with the number in parentheses the first time it appears in the write-up, e.g. "standoff hardening (L3)". After that, words only. Use the "level_words" given for each theatre.
- Ladder, for your own use: L0 quiet; L1 rhetorical signalling; L2 pressure building; L3 standoff hardening; L4 armed incident; L5 active war footing.
- ACTIVE CONFLICT RULE: a keyword alert or a surge in rhetoric is never "active conflict" or "fighting" on its own. Use those words only for a country whose "fighting_confirmed" is true. A country at L4 or L5 with "fighting_confirmed": false is high pressure without confirmed fighting: say what drives it (its "tracker_read", "hot_vectors" and lead signals) in a clause, or leave it out. If it has "reported_fighting_headlines", you may say that reporting includes those clashes, but not that Asifah's trackers confirm fighting.
- A level change is only worth reporting with its driver. Use the country's "tracker_read" and "hot_vectors" to say WHAT moved; never write that nothing explains a change when those fields do.
- "tracker_read" is the regional tracker's own sentence and uses its band names ("armed incident", "active war footing"). When "fighting_confirmed" is false, do not repeat those band names for that country; use "level_words".
- "hot_vectors" are readings on a country tracker's own dashboard, not Asifah levels: use them to say what is moving, not to restate a level.
- A label with its own scale inside a signal text (marked "own_scale" or "own_scale_note") belongs to that country's tracker, not to Asifah's L0-L5 ladder. Do not repeat its L-number or its strongest word ("rupture", "crisis") as if it were the regional level.

FRESHNESS -- THE MOST IMPORTANT RULE
- What is new is decided by AGE, not by prominence. A signal is new only if "is_new" is true. A theatre's level is new only if its "level_change" is present. "since": "before <date>" means OLD -- already present when Asifah began keeping this record, exact age unknown. A state that persists (a framework signed and rejected, talks under way, a siege line) is old unless marked new. Describe old items as long-running, briefly.
- A high level or a prominent story is NOT the same as new. Never write "tightening", "rising", "escalating" or "worsening" unless a level_change or a new signal shows it.
- Items in "background_not_news" (annual comparisons, modelled or retrospective estimates) are context only. Never lead with them; if you mention one, say what it is.
- Items in "standing_exposures" (for example, a country's dependence on oil shipped through the Strait of Hormuz) are permanent structural facts. Use one only to explain why a development matters; never make one the So What or the lead, and never call it news.
- DATED FIGURES: when a signal carries "data_as_of", give that date with the figure ("as of late August, about 1.0 million were displaced") and never state it in the present tense. If "data_warning" says the figures are stale, say they may be out of date.
- If nothing in the region is new, say so plainly in the headline. That is a finding, not a failure.

SELECTION
- The headline states the regional posture in plain words and leads with the single highest-consequence NEW development; if none is new, it says the picture is holding and names the heaviest long-running pressure.
- The read covers at most 3 developments. Group or drop the rest. A reader remembers three things.
- "network_reads" describe a hub country pressing many partner countries at once across regions. If you use one, say it in plain words ("China-linked pressure is showing in eight countries across four regions at once"), and say that partial reporting means the reach may be understated when the fact sheet says so.
- "outside_rhetoric_trackers" (for example, a disease outbreak) is real but comes from a different sensor; it may be one of the three developments if it is new and high-consequence.

HONESTY
- Use only facts in the fact sheet. Do not add events, numbers, names, history or context from outside it, even if you believe them true.
- "Unread", "not reporting", "missing" or "stale" means Asifah could not see it. Never turn it into "calm" or "no risk". Name a missing tracker when it matters to the read.
- Asifah reports convergence, not prediction. Do not forecast outcomes or recommend any action (buying, selling, travel, policy). Do not speculate about where something could spread or escalate next ("could move beyond the continent") unless the fact sheet itself says so.
- PATTERN RECOGNITION IS WELCOME. When the fact sheet supplies a historical pattern or precedent, say what today matches, what happened then and on what timeline, and say plainly that it describes what happened then, not what will happen now. Never introduce a precedent the fact sheet does not supply.
- If the fact sheet seems internally inconsistent, write around it conservatively. Do not resolve it by inventing.
- Never mention the fact sheet, its fields, or Asifah's tracking mechanics ("first seen", "is_new", "72 hours", "the record began", "composite score", "spoke", "wheel", "tripwire", "theatre"). Say what they MEAN instead: "long-running", "not new", "recently reported", "a warning trigger based on keywords", "country".
- Name things as a reader knows them. Category names become descriptions ("Iran-aligned groups active on several fronts at once", not "proxy activation L5").
- No disclaimer lines in the prose ("this is not a forecast"). The page carries that label.

TERMS
- Spell it "Hizballah", including when correcting a misspelling in the source.
- Avoid Asifah's internal shorthand ("TCI", "red line BREACHED", "OTP wave", "deterrence gap L3", "absorber-class", "fighting-class", "news-volume reading"). If a term of art genuinely helps, use it once and explain it in the same sentence.
- "Red line breached" means a threshold the tracker treats as serious has been crossed (say what it is, e.g. "Hizballah's armed presence south of the Litani, a line the ceasefire terms rule out" only if the fact sheet says so). A "warning trigger" is ONLY a keyword alert; never call a red line a warning trigger.
- Write "confirmed fighting", never "fighting-class signal".
- Hype words ("unprecedented", "crisis", "collapse") only when the facts support them at L5, and never as the first word of a headline.

OUTPUT
Return ONLY a JSON object, no other text, with exactly these keys:
  "headline": at most 18 words; the regional posture in plain words, leading with what changed or saying plainly that nothing did.
  "so_what": exactly 2 sentences for a smart reader who does not follow this region.
  "read": 110-170 words for a practitioner: what is new, what is long-running, why it matters beyond the region, and what would change the picture.
  "watch": a list of 2-3 short, concrete things to look for next, drawn from the fact sheet."""

OUTPUT_SCHEMA = {
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


def _validate(obj):
    """A cleaned regional write-up or ValueError. Never half-published."""
    if not isinstance(obj, dict):
        raise ValueError('not an object')
    rec = {}
    for f in ('headline', 'so_what', 'read'):
        t = ' '.join(str(obj.get(f) or '').split())
        if not t:
            raise ValueError('%s empty' % f)
        rec[f] = t
    if len(rec['headline'].split()) > 32:
        raise ValueError('headline too long')
    rec['watch'] = [' '.join(str(w).split()) for w in (obj.get('watch') or []) if str(w).strip()][:3]
    return _gv.fix_terms(rec)


# ════════════════════════════════════════════════════════════════════════
# FACT PACKER
# ════════════════════════════════════════════════════════════════════════
LEVEL_WORDS = {0: 'quiet', 1: 'rhetorical signalling', 2: 'pressure building',
               3: 'standoff hardening', 4: 'armed incident', 5: 'active war footing',
               6: 'world-altering shock'}

_BACKGROUND_RX = re.compile(r'\bYoY\b|year[- ]on[- ]year|\(modelled\)|retrospective'
                            r'|Population affected by|annual comparison', re.I)
_CHANGE_RX = re.compile(r'\b(up|down) from L(\d) last cycle', re.I)
# Word levels are news-volume readings: at most a watch (L3), per Rachel's
# commodity ruling (news alone is not a rupture).
_LEVEL_WORD_MAP = {'surge': 3, 'high': 3, 'elevated': 3, 'normal': 1, 'low': 1, 'baseline': 0}
# Annual structural statistics (food insecurity % of population, inflation,
# water stress...) are context, not this week's news.
_STRUCTURAL_RX = re.compile(r'compound structural stress|subsistence-failure|labou?r-market'
                            r'|hyperinflation-famine|balance-of-payments|price instability'
                            r'|\(moderate\+severe\)', re.I)
_COMMODITY_CATS = ('commodity', 'commodity_pressure', 'commodity_coupling')


def _num_level(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v or '').strip().lower()
    if s.isdigit():
        return int(s)
    return _LEVEL_WORD_MAP.get(s)


def _txt(t, n=None):
    t = _gv.clean(str(t or '')).replace('**', '')
    t = _gv._HEZ_RX.sub('Hizballah', t)
    return t[:n] if n else t


def _is_fighting(s):
    return _gv.is_fighting_signal(s)


_OWN_SCALE_RX = re.compile(r'\((?:L\d)\)|\bRupture\b', re.I)
_STANDING_RX = re.compile(r'^hormuz_.*_dependency$|_oil_dependency$|_energy_dependency$', re.I)
_VECTOR_HOT = {'surge': 'surge', 'high': 'high'}


def _tracker_read(bluf, name):
    """The regional builder's own sentence about this country (bluf_v2 first)."""
    texts = [str(x.get('text') or '') for x in (bluf.get('bluf_v2') or []) if isinstance(x, dict)]
    texts.append(str(bluf.get('bluf') or ''))
    nm = name.lower()
    for t in texts:
        sents = re.split(r'(?<=[.!?])\s+', _txt(t))
        for i, sent in enumerate(sents):
            pos = sent.lower().find(nm)
            # The sentence must be ABOUT the country (named near its start),
            # not merely mention it ("...absorbed pressure from Pakistan").
            if 0 <= pos <= 35 and len(sent) > len(name) + 12:
                out = sent
                nxt = sents[i + 1] if i + 1 < len(sents) else ''
                if re.match(r'(Active vectors|Vectors|Driven by|Lead signal)', nxt, re.I):
                    out += ' ' + nxt
                return out[:280]
    return None


def _hot_vectors(t):
    """Vectors at L4+ (or surge/high) on a country's own dashboard, in words."""
    out = []
    for k, v in (t.get('vector_levels') or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 4:
            out.append('%s at L%d' % (k.replace('_', ' '), int(v)))
        elif str(v).lower() in _VECTOR_HOT:
            out.append('%s: %s (volume reading)' % (k.replace('_', ' '), str(v).lower()))
    return out[:3]


def _fighting_headlines(s):
    """Source headlines under a signal that themselves REPORT fighting."""
    out = []
    for src in (s.get('sources') or [])[:6]:
        title = _txt((src or {}).get('title') if isinstance(src, dict) else '', 140)
        if title and _gv.KINETIC_EVENT_RX.search(title) and not re.search(
                r'\b(could|may|might|warns?|threatens?|risk of)\b', title, re.I):
            out.append(title)
    return out


def _allowed_theatres(region, bluf):
    ts = set((bluf.get('theatre_summary') or {}).keys())
    return ts | REGION_EXTRA.get(region, set()) | {'regional', region}


def _sig_fp(s):
    txt = re.sub(r'[^a-z ]+', ' ', str(s.get('short_text') or '').lower())
    txt = ' '.join(txt.split())[:90]
    return '%s|%s|%s|%s' % (s.get('category') or '', str(s.get('theatre') or '').lower(),
                            s.get('level'), txt)


def _level_changes(bluf):
    """{display_lower: ('up'|'down', from_level)} parsed from the regional
    builder's own 'up from L2 last cycle' wording (its memory, not ours)."""
    out = {}
    texts = [str(x.get('text') or '') for x in (bluf.get('bluf_v2') or []) if isinstance(x, dict)]
    texts.append(str(bluf.get('bluf') or ''))
    for t in texts:
        for m in _CHANGE_RX.finditer(t):
            head = t[:m.start()]
            # The country name is the last bold or capitalised name before the
            # level words: "**Cuba** -- armed incident (L4), up from L2".
            names = re.findall(r'\*\*([^*]+)\*\*|([A-Z][A-Za-z\' ]+?)\s+--\s', head)
            if names:
                nm = (names[-1][0] or names[-1][1]).strip().lower()
                out[nm] = (m.group(1).lower(), int(m.group(2)))
    return out


def _signals(region, bluf):
    allowed = _allowed_theatres(region, bluf)
    pool = bluf.get('signals') or bluf.get('top_signals') or []
    out = []
    for s in pool:
        if not isinstance(s, dict):
            continue
        th = str(s.get('theatre') or '').strip().lower() or 'regional'
        if th not in allowed:
            continue
        lvl = _num_level(s.get('level'))
        if lvl is not None and lvl <= 0:
            continue
        out.append(s)
    return out


def _update_memory(region, bluf, mem, now):
    """Stamp first-seen on signals and since-dates on theatre levels. Mutates mem."""
    now_iso = now.isoformat()
    reg = mem.setdefault('regions', {}).setdefault(region, {})
    first = not reg.get('began')
    reg.setdefault('began', now_iso)
    sigs = reg.setdefault('signals', {})
    ths = reg.setdefault('theatres', {})
    ages = {}
    for s in _signals(region, bluf):
        fp = _sig_fp(s)
        rec = sigs.get(fp)
        if rec is None:
            rec = {'first_seen': reg['began'] if first else now_iso, 'floor': first}
            sigs[fp] = rec
        rec['last_seen'] = now_iso
        ages[fp] = rec
    for fp in list(sigs):
        try:
            if (now - datetime.fromisoformat(sigs[fp].get('last_seen') or now_iso)).days > FORGET_DAYS:
                sigs.pop(fp, None)
        except Exception:
            sigs.pop(fp, None)
    levels = {}
    for th, t in (bluf.get('theatre_summary') or {}).items():
        lvl = _num_level(t.get('level'))
        lvl = 0 if lvl is None else lvl
        rec = ths.get(th)
        if rec is None:
            rec = {'level': lvl, 'since': reg['began'] if first else now_iso, 'floor': first, 'prev': None}
        elif rec.get('level') != lvl:
            rec = {'level': lvl, 'since': now_iso, 'floor': False, 'prev': rec.get('level')}
        ths[th] = rec
        levels[th] = rec
    return ages, levels


def _age(rec, now):
    if not rec:
        return {'since': 'unread'}
    since = (('before ' if rec.get('floor') else '') + str(rec.get('first_seen') or rec.get('since'))[:10])
    try:
        hrs = (now - datetime.fromisoformat(rec.get('first_seen') or rec.get('since'))).total_seconds() / 3600
    except Exception:
        hrs = 1e9
    return {'since': since, 'is_new': (not rec.get('floor')) and hrs <= NEW_HOURS}


def pack(region, bluf, ages=None, levels=None, now=None):
    """The compact fact sheet for one region."""
    now = now or datetime.now(timezone.utc)
    ages = ages if ages is not None else {}
    levels = levels if levels is not None else {}
    ages_read = bool(ages or levels)
    sigs = _signals(region, bluf)
    changes = _level_changes(bluf)

    by_th = {}
    for s in sigs:
        by_th.setdefault(str(s.get('theatre') or '').lower(), []).append(s)

    theatres, quiet = [], []
    for th, t in (bluf.get('theatre_summary') or {}).items():
        lvl = _num_level(t.get('level'))
        lvl = 0 if lvl is None else lvl
        name = _txt(t.get('display') or th.replace('_', ' ').title())
        if name.isupper():
            name = name.title()
        if lvl <= 1:
            quiet.append(name)
            continue
        own = sorted(by_th.get(th, []), key=lambda s: (-(_num_level(s.get('level')) or 0),
                                                       -(s.get('priority') or 0)))
        fighting = any(_is_fighting(s) for s in own)
        words = LEVEL_WORDS.get(lvl, '')
        if lvl >= 4 and not fighting:
            words = 'high pressure, no confirmed fighting'
        if lvl >= 4 and not fighting and any(_fighting_headlines(x) for x in own):
            words = 'high pressure; reporting includes clashes, not confirmed by the tracker'
        rec = {'country': name, 'level': lvl, 'level_words': words,
               'fighting_confirmed': fighting}
        lv = levels.get(th)
        if lv:
            rec['since'] = ('before ' if lv.get('floor') else '') + str(lv.get('since'))[:10]
            try:
                hrs = (now - datetime.fromisoformat(lv['since'])).total_seconds() / 3600
            except Exception:
                hrs = 1e9
            if not lv.get('floor') and hrs <= NEW_HOURS and lv.get('prev') is not None:
                rec['level_change'] = '%s from L%s' % ('up' if lvl > lv['prev'] else 'down', lv['prev'])
        ch = changes.get(name.lower()) or changes.get(th.replace('_', ' '))
        if ch and 'level_change' not in rec:
            rec['level_change'] = '%s from L%d (since the previous reading)' % ch
        if lvl >= 4 and not fighting:
            rec['driver_note'] = ('level carried by rhetoric volume, keyword alerts or '
                                  'non-combat signals; no confirmed-fighting signal this cycle')
        rec['lead_signals'] = [_txt(s.get('short_text'), 130) for s in own[:2]]
        tr = _tracker_read(bluf, name)
        if tr:
            rec['tracker_read'] = tr
            if re.search(r'\bRupture\b', tr):
                rec['own_scale_note'] = ('"Rupture (L5)" is this country tracker\'s own top rung; '
                                         'on Asifah\'s scale the country reads L%d' % lvl)
        hv = _hot_vectors(t)
        if hv:
            rec['hot_vectors'] = hv
        rf = [h for s in own for h in _fighting_headlines(s)][:2]
        if rf and not fighting:
            rec['reported_fighting_headlines'] = rf
        theatres.append(rec)
    theatres.sort(key=lambda r: -r['level'])

    main, background, standing, seen = [], [], [], set()
    ranked = sorted(sigs, key=lambda s: (-(_num_level(s.get('level')) or 2), -(s.get('priority') or 0)))
    for s in ranked:
        text = _gv._ROLLUP_PREFIX_RX.sub('', _txt(s.get('short_text')))[:170]
        key = text[:60].lower()
        if not text or key in seen:
            continue
        seen.add(key)
        lvl = s.get('level')
        row = {'level': lvl if isinstance(lvl, int) else _num_level(lvl),
               'where': str(s.get('theatre') or '').replace('_', ' '),
               'text': text}
        if not isinstance(lvl, int):
            row['reading'] = 'news-volume or keyword reading ("%s"), not a confirmed event' % lvl
        elif str(s.get('category') or '') in _COMMODITY_CATS and lvl > 3:
            row['level'] = 3                 # GPI v3.16 rule: volume is not a rupture
            row['reading'] = 'commodity news volume, not a confirmed price or supply disruption'
        if s.get('category') in ('tripwire',) or str(s.get('type') or '') == 'tripwire':
            row['reading'] = 'a warning trigger based on keywords, not a confirmed event'
        if row['level'] is None and _OWN_SCALE_RX.search(text):
            row['own_scale'] = ("this country tracker's own scale, not Asifah's L-ladder "
                                "(the country's Asifah level is in 'countries')")
        lt = _txt(s.get('long_text'), 260)
        if lt and lt[:60].lower() != key:
            row['context'] = lt
        st = s.get('data_staleness') or {}
        if isinstance(st, dict) and (st.get('last_manual_update') or st.get('age_days')):
            row['data_as_of'] = st.get('last_manual_update') or ('%s days old' % st.get('age_days'))
            if st.get('tier') in ('stale', 'expired') or (st.get('age_days') or 0) > 30:
                row['data_warning'] = ('figures %s days old: direction only, not current magnitude'
                                       % st.get('age_days'))
        if _STANDING_RX.search(str(s.get('category') or '')):
            standing.append({'where': row['where'], 'text': text,
                             'note': 'standing structural dependence; sharpens only if the '
                                     'route or supplier is actually disrupted'})
            continue
        if ages_read:
            row.update(_age(ages.get(_sig_fp(s)), now))
        if _BACKGROUND_RX.search(text) or _STRUCTURAL_RX.search(text) or s.get('background'):
            row['why_background'] = ('retrospective estimate' if re.search('retrospective', text, re.I)
                                     else 'annual comparison' if re.search('YoY|year|annual', text, re.I)
                                     else 'annual structural indicators, not a new event'
                                     if _STRUCTURAL_RX.search(text)
                                     else 'modelled estimate, no confirmed outcome')
            background.append(row)
        else:
            main.append(row)

    cp = bluf.get('convergence_panel') or {}
    network = []
    for w in (cp.get('resident_wheels') or []):
        if w.get('converged'):
            b = w.get('breadth') or {}
            network.append({'hub': _txt(w.get('title') or w.get('hub')).replace(' WHEEL', '').title(),
                            'partners_lit': w.get('lit_count'),
                            'regions_lit': sorted((b.get('regions_lit') or {}).keys()),
                            'partial_reporting': bool(b.get('unreported_total')),
                            'read': _txt(w.get('headline'), 240)})
    l2 = bluf.get('layer2') or {}
    linked = [{'id': x.get('id'), 'is_new': bool(x.get('is_fresh'))}
              for x in (l2.get('cross_regional') or []) if x.get('status') == 'stamped']

    facts = {
        'region': REGION_NAMES.get(region, region),
        'as_of_utc': bluf.get('generated_at'),
        'posture': {
            'label': _txt(bluf.get('posture_label')).lower(),
            'peak_level': _num_level(bluf.get('max_level')),
            'countries_at_L3_plus': bluf.get('theatres_at_l3plus'),
            'trackers_live': bluf.get('trackers_live'),
            'trackers_total': bluf.get('trackers_total'),
            'trackers_missing': bluf.get('trackers_missing') or [],
            'trackers_stale': bluf.get('trackers_stale') or [],
            'picture_complete': bluf.get('picture_complete', True),
        },
        'countries': theatres[:10],
        'quiet_or_baseline': quiet,
        'signals': main[:10],
        'background_not_news': background[:3],
        'standing_exposures': standing[:4],
        'network_reads': network[:2],
        'linked_cross_region_watches': linked[:4],
    }
    if not ages_read:
        facts['ages_unread'] = 'Ages could not be read this cycle: treat nothing as new unless a level_change says so.'
    hc = bluf.get('humanitarian_context') or {}
    if hc.get('rows'):
        facts['outside_rhetoric_trackers'] = [
            {'level': r.get('level'), 'country': str(r.get('country') or '').replace('_', ' '),
             'text': _txt(r.get('short_text'), 170)} for r in hc['rows'][:4]]
    return facts


def fingerprint(facts):
    """What MATTERS: levels, fighting, changes, which signals and what is new.
    Not scores, counts, contexts or dates (they drift every build)."""
    core = {
        'v': PROMPT_VERSION,
        'p': [facts['posture'].get(k) for k in ('label', 'peak_level', 'trackers_missing',
                                                 'trackers_stale')],
        'c': [(c['country'], c['level'], c['fighting_confirmed'], c.get('level_change'))
              for c in facts.get('countries') or []],
        's': sorted('%s|%s|%s|%s' % (s.get('where'), s.get('level'),
                                     re.sub(r'[\d.,%]+', '#', s.get('text', ''))[:70],
                                     s.get('is_new')) for s in facts.get('signals') or []),
        'n': [(n['hub'], n['partners_lit']) for n in facts.get('network_reads') or []],
        'h': [(h['country'], h['level']) for h in facts.get('outside_rhetoric_trackers') or []],
    }
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()[:16]


# ════════════════════════════════════════════════════════════════════════
# MEMORY (strict read: a failed read must not look like day zero)
# ════════════════════════════════════════════════════════════════════════
def _rget_checked(key):
    url, tok = _gv.UPSTASH_REDIS_URL, _gv.UPSTASH_REDIS_TOKEN
    if not (url and tok):
        return None, False
    try:
        r = requests.get(f'{url}/get/{key}', headers={'Authorization': f'Bearer {tok}'}, timeout=5)
        if r.status_code != 200:
            return None, False
        res = r.json().get('result')
        return (json.loads(res) if res else None), True
    except Exception:
        return None, False


def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _count(key):
    return int((_gv._rget(key) or {}).get('n', 0))


# ════════════════════════════════════════════════════════════════════════
# REFRESH
# ════════════════════════════════════════════════════════════════════════
def _write_region(region, facts, allow_call, reason):
    fp = fingerprint(facts)
    latest = _gv._rget(LATEST_KEY % region) or {}
    if latest.get('fingerprint') == fp and latest.get('view'):
        return {'status': 'reused', 'fingerprint': fp}
    if not allow_call:
        return {'status': 'facts_changed_call_not_allowed', 'fingerprint': fp}
    if not os.environ.get('ANTHROPIC_API_KEY'):
        return {'status': 'disabled_no_key'}
    now = time.time()
    if reason != 'manual' and now - (latest.get('last_attempt_epoch') or 0) < REGION_VOICE_MIN_GAP:
        return {'status': 'min_gap'}
    day = _today()
    n_reg, n_all = _count(CALLS_KEY % (region, day)), _count(CALLS_KEY % ('all', day))
    if n_reg >= REGION_VOICE_DAILY_CAP:
        return {'status': 'daily_cap_reached', 'cap': REGION_VOICE_DAILY_CAP}
    if n_all >= REGION_VOICE_TOTAL_CAP:
        return {'status': 'total_cap_reached', 'cap': REGION_VOICE_TOTAL_CAP}
    _gv._rset(CALLS_KEY % (region, day), {'n': n_reg + 1}, 2 * 24 * 3600)
    _gv._rset(CALLS_KEY % ('all', day), {'n': n_all + 1}, 2 * 24 * 3600)
    latest['last_attempt_epoch'] = now
    _gv._rset(LATEST_KEY % region, latest, VOICE_TTL)
    try:
        t0 = time.time()
        view, usage = _gv._call_claude(facts, system=SYSTEM_PROMPT, schema=OUTPUT_SCHEMA,
                                       validate=_validate, max_tokens=REGION_MAX_TOKENS)
        rec = {
            'region': region, 'region_name': REGION_NAMES.get(region, region),
            'view': view, 'fingerprint': fp,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'bluf_generated_at': facts.get('as_of_utc'),
            'model': _gv.VOICE_MODEL, 'voice_version': __version__,
            'usage': usage, 'seconds': round(time.time() - t0, 1), 'reason': reason,
            'last_attempt_epoch': now, 'calls_today': n_reg + 1,
            'label': 'Plain-language read, AI-drafted from Asifah signals',
            'style_flags': _gv.style_flags({'region': view}),
        }
        _gv._rset(LATEST_KEY % region, rec, VOICE_TTL)
        print('[Regional voice] %s written via %s in %.0fs -- %s in / %s out, ~$%.3f (%d/%d today)'
              % (region, _gv.VOICE_MODEL, rec['seconds'], usage['input_tokens'],
                 usage['output_tokens'], usage['est_cost_usd'], n_reg + 1, REGION_VOICE_DAILY_CAP))
        if rec['style_flags']:
            print('[Regional voice] %s style flags (published anyway): %s' % (region, rec['style_flags'][:6]))
        return {'status': 'written', 'fingerprint': fp, 'usage': usage}
    except Exception as e:
        print('[Regional voice] %s call failed (non-fatal, last write-up stays): %s' % (region, str(e)[:200]))
        latest['last_error'] = str(e)[:200]
        latest['last_error_at'] = datetime.now(timezone.utc).isoformat()
        _gv._rset(LATEST_KEY % region, latest, VOICE_TTL)
        return {'status': 'call_failed', 'error': str(e)[:200]}


def refresh_all(blufs, allow_call=True, reason='organic', only=None):
    """Pack every region (always: memory stays current even on ?force), then
    write the regions whose facts changed (only when allow_call). Never raises."""
    report = {}
    with _lock:
        if _running['busy']:
            return {'status': 'already_running'}
        _running['busy'] = True
    try:
        now = datetime.now(timezone.utc)
        mem, ok = _rget_checked(MEMORY_KEY)
        mem = mem if isinstance(mem, dict) else {}
        for region in REGIONS:
            if only and region != only:
                continue
            bluf = (blufs or {}).get(region)
            if not isinstance(bluf, dict):
                report[region] = {'status': 'no_bluf'}
                continue
            try:
                if ok:
                    ages, levels = _update_memory(region, bluf, mem, now)
                else:
                    ages, levels = {}, {}
                facts = pack(region, bluf, ages, levels, now)
                _gv._rset(FACTS_KEY % region, facts, VOICE_TTL)
                report[region] = _write_region(region, facts, allow_call, reason)
            except Exception as e:
                report[region] = {'status': 'pack_failed', 'error': str(e)[:160]}
        if ok:
            _gv._rset(MEMORY_KEY, mem, MEMORY_TTL)
        else:
            report['_memory'] = 'unread -- ages marked unread, memory not overwritten'
        return report
    finally:
        with _lock:
            _running['busy'] = False


def refresh_async(blufs, allow_call=True, reason='organic'):
    """Fire-and-forget after the GPI build; the GPI response never waits."""
    try:
        threading.Thread(target=refresh_all, args=(blufs, allow_call, reason),
                         daemon=True, name='regional-voice').start()
    except Exception as e:
        print('[Regional voice] could not start thread: %s' % str(e)[:120])


def refresh_from_stored(region):
    """Rachel's manual button: rewrite one region from its last stored facts
    (no GPI rebuild, no regional fetch). Daily caps still apply."""
    facts = _gv._rget(FACTS_KEY % region)
    if not isinstance(facts, dict):
        return {'status': 'no_stored_facts', 'note': 'Load /api/gpi once so the facts are packed.'}
    return _write_region(region, facts, True, 'manual')


def latest(region=None):
    """Stored write-up(s). Reading never calls Claude."""
    def one(r):
        rec = _gv._rget(LATEST_KEY % r) or {}
        if not rec.get('view'):
            return {'region': r, 'available': False, 'last_error': rec.get('last_error')}
        out = {k: v for k, v in rec.items() if k != 'last_attempt_epoch'}
        out['available'] = True
        return out
    if region:
        return one(region)
    return {'regions': {r: one(r) for r in REGIONS}}
