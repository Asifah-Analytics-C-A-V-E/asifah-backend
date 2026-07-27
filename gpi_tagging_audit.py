"""
gpi_tagging_audit.py
Asifah Analytics — GPI tagging & bundling diagnostic
v1.0.0 — July 27, 2026  |  ME backend

Answers three questions the GPI cannot currently answer about itself.

────────────────────────────────────────────────────────────────────────────
1. WHICH SIGNALS ARRIVE UNTAGGED?
────────────────────────────────────────────────────────────────────────────
The GPI defaults untagged signals to KINETIC for backwards compatibility.
That is sensible for scoring and dangerous for NAMING: the landing page now
says "Iran: active war footing" vs "Japan: mass-casualty humanitarian
disaster" based on pressure_type, so an untagged humanitarian signal is
announced to a first-time visitor as a war.

Rather than migrate a dozen source modules blind, this reports WHICH modules
send untagged signals and HOW OFTEN those signals actually surface. Most
signals never reach top_signals, so tagging them would be invisible work.
This turns a guessing game into a ranked list.

────────────────────────────────────────────────────────────────────────────
2. WHICH SIGNALS NAME COUNTRIES THEY ARE NOT TAGGED WITH?
────────────────────────────────────────────────────────────────────────────
Dedupe keys on `theatre`. A signal whose prose says "Sudan" but whose theatre
is 'global' cannot bundle with Sudan's other signals -- so it occupies its own
slot and the reader sees the same country twice under different headings.

────────────────────────────────────────────────────────────────────────────
3. WHAT DOES BUNDLING ACTUALLY COST?
────────────────────────────────────────────────────────────────────────────
IMPORTANT FINDING, and it is not what "bundling" implies. The GPI does not
bundle -- it DEDUPES. For each theatre:category pair the highest-priority
signal survives and the rest are DISCARDED with no trace: no count, no
"+4 more". A reader cannot tell whether Iran fired once or forty times.

Slots are genuinely freed (dedupe runs BEFORE the cap, so other worldwide
signals do bubble up -- that part works as intended). What is lost is the
INTENSITY information: forty Iran signals and one Iran signal render
identically. This audit measures the collapse ratio so that loss is visible,
and the fix -- carrying a `bundled_count` onto the survivor -- becomes a
decision rather than an oversight.

ENDPOINT:  GET /api/gpi/audit/tagging
           GET /api/gpi/audit/tagging?verbose=true   (per-signal detail)

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone
from flask import jsonify, request

__version__ = '1.0.0'

# Countries the platform tracks, for prose scanning. Word-boundary matched so
# 'Chad' does not fire on 'Chadian-adjacent' prose and ' mali' does not fire
# inside 'Somalia' -- the same trap the Telegram relevance gate documents.
TRACKED_COUNTRIES = [
    'afghanistan', 'algeria', 'armenia', 'azerbaijan', 'bahrain', 'belarus',
    'brazil', 'burkina faso', 'car', 'central african republic', 'chad',
    'chile', 'china', 'colombia', 'cuba', 'cyprus', 'denmark', 'drc', 'egypt',
    'ethiopia', 'gaza', 'georgia', 'greece', 'greenland', 'haiti', 'hungary',
    'india', 'indonesia', 'iran', 'iraq', 'israel', 'japan', 'jordan',
    'kazakhstan', 'kenya', 'kuwait', 'lebanon', 'libya', 'madagascar', 'mali',
    'mexico', 'moldova', 'morocco', 'mozambique', 'myanmar', 'niger',
    'nigeria', 'north korea', 'dprk', 'oman', 'pakistan', 'panama', 'peru',
    'philippines', 'poland', 'qatar', 'russia', 'rwanda', 'saudi arabia',
    'somalia', 'south africa', 'south korea', 'south sudan', 'sudan', 'syria',
    'taiwan', 'tanzania', 'thailand', 'tunisia', 'turkey', 'uae', 'uganda',
    'ukraine', 'venezuela', 'vietnam', 'yemen',
]

_VALID_AXES = ('kinetic', 'economic', 'humanitarian', 'diplomatic')


def _countries_in_text(text):
    """Countries named in prose. Word-boundary matched."""
    if not text:
        return set()
    low = str(text).lower()
    found = set()
    for c in TRACKED_COUNTRIES:
        if re.search(r'\b' + re.escape(c) + r'\b', low):
            found.add(c)
    return found


def audit_signals(raw_signals, final_signals=None, infer_fn=None):
    """Audit a set of GPI signals. Pure function -- no Redis, no network.

    raw_signals   : the signal list BEFORE dedupe
    final_signals : the list AFTER dedupe + cap (optional; enables the
                    bundling-cost section)
    infer_fn      : the GPI's own _infer_pressure_type, injected so this audit
                    measures what the GPI ACTUALLY does rather than a
                    reimplementation that could drift from it.
    """
    raw = [s for s in (raw_signals or []) if isinstance(s, dict)]

    # ── 1. PRESSURE_TYPE COVERAGE ─────────────────────────────────────
    tagged, inferred, defaulted = [], [], []
    by_source_untagged = defaultdict(lambda: {'count': 0, 'categories': set(),
                                              'example': None})
    for s in raw:
        pt = s.get('pressure_type')
        if pt in _VALID_AXES:
            tagged.append(s)
            continue
        guess = None
        if infer_fn:
            try:
                guess = infer_fn(s)
            except Exception:
                guess = None
        cat = s.get('category') or 'uncategorised'
        theatre = s.get('theatre') or 'unknown'
        rec = by_source_untagged[theatre]
        rec['count'] += 1
        rec['categories'].add(cat)
        if rec['example'] is None:
            rec['example'] = (s.get('short_text') or '')[:90]
        # An inference that lands on kinetic is indistinguishable from the
        # DEFAULT. That is the dangerous case -- flag it separately.
        if guess and guess != 'kinetic':
            inferred.append(s)
        else:
            defaulted.append(s)

    untagged_ranked = sorted(
        ({'theatre': k, 'untagged_count': v['count'],
          'categories': sorted(v['categories']), 'example': v['example']}
         for k, v in by_source_untagged.items()),
        key=lambda r: -r['untagged_count'])

    # ── 2. COUNTRY TAGGING ────────────────────────────────────────────
    # A signal whose prose names a country it is not tagged with cannot bundle
    # with that country's other signals.
    mismatches = []
    for s in raw:
        theatre = (s.get('theatre') or '').lower().replace('_', ' ')
        text = ' '.join(str(s.get(k) or '') for k in
                        ('short_text', 'long_text', 'headline', 'detail'))
        named = _countries_in_text(text)
        if not named:
            continue
        # Tagged theatre counts as covered, however it is spelled.
        # GUARD: an empty theatre must not match everything -- `'' in 'japan'`
        # is True, which silently marked every country as covered and hid the
        # exact untagged-signal case this audit exists to find.
        covered = ({c for c in named if c in theatre or theatre in c}
                   if theatre.strip() else set())
        orphans = named - covered
        if orphans and theatre in ('', 'global', 'unknown', 'worldwide'):
            mismatches.append({
                'theatre': s.get('theatre'),
                'category': s.get('category'),
                'countries_named': sorted(orphans),
                'text': (s.get('short_text') or '')[:100],
                'issue': ('names specific countries but is tagged global -- '
                          'cannot bundle with those countries\' signals'),
            })
        elif len(orphans) >= 2:
            mismatches.append({
                'theatre': s.get('theatre'),
                'category': s.get('category'),
                'countries_named': sorted(orphans),
                'text': (s.get('short_text') or '')[:100],
                'issue': ('multi-country signal tagged to a single theatre -- '
                          'the other countries get no credit for it'),
            })

    # ── 3. BUNDLING COST ──────────────────────────────────────────────
    bundling = None
    if final_signals is not None:
        groups = defaultdict(list)
        for s in raw:
            groups[f"{s.get('theatre','')}:{s.get('category','')}"].append(s)
        collapsed = [{'key': k, 'raw_count': len(v),
                      'discarded': len(v) - 1,
                      'survivor': (v[0].get('short_text') or '')[:80]}
                     for k, v in groups.items() if len(v) > 1]
        collapsed.sort(key=lambda r: -r['raw_count'])
        total_discarded = sum(c['discarded'] for c in collapsed)

        # Slots freed by dedupe are slots OTHER signals can occupy. That part
        # works. What is lost is intensity.
        bundling = {
            'raw_signal_count': len(raw),
            'after_dedupe': len(raw) - total_discarded,
            'displayed': len(final_signals),
            'silently_discarded': total_discarded,
            'collapsed_groups': collapsed[:15],
            'slots_freed_for_other_signals': total_discarded,
            'note': ('Dedupe runs BEFORE the cap, so freed slots DO go to other '
                     'signals -- that works as intended. What is lost is '
                     'INTENSITY: the survivor carries no count, so forty Iran '
                     'signals and one Iran signal render identically. Adding a '
                     '`bundled_count` to the survivor would preserve it.'),
        }

    total = len(raw) or 1
    return {
        'success': True,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'audit_version': __version__,

        'pressure_type': {
            'total_signals':  len(raw),
            'tagged':         len(tagged),
            'inferred_nonkinetic': len(inferred),
            'defaulted_to_kinetic': len(defaulted),
            'coverage_pct':   round(len(tagged) / total * 100, 1),
            'untagged_by_theatre': untagged_ranked[:20],
            'risk_note': ('Signals in `defaulted_to_kinetic` are announced on '
                          'the landing page as kinetic states -- "active war '
                          'footing", "armed incident". Any humanitarian or '
                          'economic signal in that bucket is being MISLABELLED '
                          'to a first-time visitor, which is the highest-'
                          'visibility error surface on the platform.'),
        },

        'country_tagging': {
            'mismatch_count': len(mismatches),
            'mismatches': mismatches[:20],
            'note': ('Dedupe keys on `theatre`. A signal naming Sudan but '
                     'tagged global cannot bundle with Sudan\'s other signals, '
                     'so the reader sees the same country twice under '
                     'different headings and a slot is spent on the repeat.'),
        },

        'bundling': bundling,
    }


def register_gpi_audit_endpoints(app):
    @app.route('/api/gpi/audit/tagging', methods=['GET'])
    def gpi_audit_tagging():
        verbose = request.args.get('verbose', '').lower() in ('true', '1', 'yes')
        try:
            from global_pressure_index import (build_gpi, _infer_pressure_type)
            payload = build_gpi(force=False) or {}
            # `top_signals` is post-dedupe/post-cap. `_all_signals_raw` is the
            # pre-dedupe list if the GPI exposes it; absent that we audit what
            # we can and say so rather than inventing a denominator.
            final = payload.get('top_signals') or []
            raw = payload.get('_all_signals_raw') or final
            result = audit_signals(raw, final, infer_fn=_infer_pressure_type)
            result['raw_list_available'] = bool(payload.get('_all_signals_raw'))
            if not result['raw_list_available']:
                result['caveat'] = (
                    'The GPI does not expose its PRE-dedupe signal list, so this '
                    'audit ran against the post-cap top_signals only. Tagging '
                    'coverage is therefore measured on signals that SURFACED -- '
                    'which is the population that matters most for the landing '
                    'page, but understates the total. Set _all_signals_raw on '
                    'the GPI payload for the full picture.')
            if not verbose:
                result['country_tagging'].pop('mismatches', None)
                result['pressure_type'].pop('untagged_by_theatre', None)
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:250]}), 500

    print("[GPI Audit] \u2705 Registered: /api/gpi/audit/tagging (+?verbose=true)")
