"""
convergence_layer2.py -- Asifah Analytics
================================================================================
LAYER 2 FOR EVERY BACKEND, AND FOR BOTH KINDS OF CONVERGENCE.

THE PROBLEM THIS SOLVES
-----------------------
Layer 2 is the step that stamps `{entry_id}_active` and `convergence_states` onto
a published signal so the GPI's Layer 1 can detect a convergence. Without it a
registry entry is inert: the GPI looks for a flag nobody sets.

Only the ME backend has ever had a Layer 2, and its implementation does this:

    commodity_id    = entry['commodity']
    commodity_state = _fetch_commodity_pressure(commodity_id)
    if not commodity_state:
        continue

Eight of the twenty registry entries carry `commodity: None`. They are the
regime and diplomatic-axis convergences -- dedollarisation, arms-trade
realignment, sanctions evasion, Belt and Road resource leverage, the Asia
security-architecture pair. For every one of them `_fetch_commodity_pressure(None)`
returns nothing and the loop skips, silently, every cycle since May.

That is why those entries' trigger categories have no emitter anywhere. It was
never an oversight in the trackers. Layer 2 structurally could not reach them.

ALL FOUR of Asia's registry entries are in that set, so porting ME's function to
the Asia backend verbatim would have produced a function that finds four
convergences and enriches none of them, forever, without a word in the log.

TWO GATES, ONE MODULE
---------------------
  commodity-driven   entry['commodity'] is set. Gate: is the commodity at or
                     above entry['commodity_threshold']? Byte-for-byte the
                     behaviour ME has today -- this module must not re-level
                     anything that already works.

  regime-driven      entry['commodity'] is None. There is no commodity to ask
                     about, so the gate is the TRIGGER SIGNAL ITSELF: does a
                     published signal carry the trigger category, and is it at
                     or above the entry's minimum level?

WHY SIGNAL-CENTRIC RATHER THAN COUNTRY-CENTRIC
----------------------------------------------
ME's Layer 2 is called per-country while a signal is being assembled. Asia's
BLUF receives signals already built by its trackers. A country-keyed function
does not fit that shape, and the thing the GPI actually consumes is a SIGNAL
carrying a flag -- not a country. So this takes the signal list.

ABSENCE IS REPORTED, NOT INFERRED
---------------------------------
`enrich_signals` returns a report naming every entry it did NOT activate and
why: no trigger signal published at all, trigger published but below level,
commodity below threshold, commodity unreadable. Four different silences that
look identical from outside, which is the failure this platform keeps finding.

PURE MODULE. No Redis, no HTTP, no Flask, no third-party imports. The caller
passes its own accessors, so this deploys byte-identical to all five backends
the way spoke_wheel_reader.py does.

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

from datetime import datetime, timezone

__version__ = '1.0.0'

# A regime entry whose own registry record does not name a floor. Level 2 is
# "pressure building" on the platform ladder -- below that a signal is noise and
# a convergence built on it would fire every cycle, which is the monotonous-GPI
# failure the Sep 20 registry audit named.
DEFAULT_REGIME_MIN_LEVEL = 2

# Freshness baselines live under this prefix when the caller supplies Redis.
FRESHNESS_KEY_PREFIX = 'convergence_freshness:'
FRESHNESS_TTL = 14 * 24 * 3600


def _level(value):
    """Coerce a signal level to an int. None when it cannot be read -- NEVER 0.

    A signal whose level is unreadable is not a quiet signal. Returning 0 here
    would let an unreadable trigger fail its gate for the wrong reason, and the
    report would say 'below level' when the truth is 'could not be read'.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        t = value.strip()
        if not t:
            return None
        try:
            return int(float(t))
        except ValueError:
            pass
        try:
            import severity_canon
            lvl, _ladder, _amb = severity_canon.resolve(t)
            return lvl
        except Exception:
            return None
    return None


def _categories_of(entry):
    """Every category this entry answers to. Mirrors the GPI's own fallback:
    an entry may declare `trigger_signal_categories` (a list) when its analytic
    scope is reached under more than one id."""
    cats = entry.get('trigger_signal_categories')
    if isinstance(cats, (list, tuple)) and cats:
        return [str(c) for c in cats if c]
    one = entry.get('trigger_signal_category')
    return [str(one)] if one else []


def _find_trigger(signals, entry):
    """The published signal carrying this entry's trigger category, loudest first.
    Returns (signal, level) or (None, None)."""
    cats = set(_categories_of(entry))
    if not cats:
        return (None, None)
    best, best_lvl = None, None
    for s in signals or []:
        if not isinstance(s, dict) or s.get('category') not in cats:
            continue
        lvl = _level(s.get('level'))
        if best is None or (lvl is not None and (best_lvl is None or lvl > best_lvl)):
            best, best_lvl = s, lvl
    return (best, best_lvl)


def _is_fresh(entry_id, reading, redis_get, redis_set):
    """Is this convergence RISING, or a steady baseline?

    Same contract as me_regional_bluf._convergence_is_fresh: fresh -> GPI
    topline, stale -> GPI watch tier. Without Redis the caller gets True, which
    is the legacy behaviour and keeps a backend with no cache from silently
    demoting every convergence it finds.
    """
    if not (callable(redis_get) and callable(redis_set)):
        return True, 'no baseline store -- defaulting to fresh'
    key = FRESHNESS_KEY_PREFIX + entry_id
    try:
        prior = redis_get(key) or {}
    except Exception:
        prior = {}
    prior_val = prior.get('reading') if isinstance(prior, dict) else None
    try:
        redis_set(key, {'reading': reading,
                        'ts': datetime.now(timezone.utc).isoformat()},
                  FRESHNESS_TTL)
    except Exception:
        pass
    if prior_val is None:
        # Cold start. Only an intrinsically loud reading is news on its own;
        # anything else waits for a baseline rather than claiming a rise it
        # cannot have measured.
        return (reading >= 4), 'cold start -- no prior reading'
    if reading > prior_val:
        return True, 'rose from %s to %s' % (prior_val, reading)
    return False, 'flat or falling (%s -> %s)' % (prior_val, reading)


def enrich_signals(signals, region, commodity_fetch=None,
                   redis_get=None, redis_set=None, registry=None):
    """Stamp convergence flags onto published signals. Returns a report.

    signals          list of canonical top_signals dicts. MUTATED IN PLACE --
                     this is the point: the GPI reads the flags off the signals
                     the BLUF publishes.
    region           'me' | 'asia' | 'europe' | 'africa' | 'wha'
    commodity_fetch  callable(commodity_id) -> {'alert_level','signal_count',...}
                     or None. Absent means commodity entries report
                     'commodity_unreadable' rather than being skipped in silence.
    redis_get/set    optional, for freshness baselines.
    registry         optional, for tests. Defaults to the deployed registry.

    Never raises. A convergence layer that throws takes the whole BLUF with it,
    and a missing BLUF is worse than a missing convergence.
    """
    report = {
        'version': __version__, 'region': region,
        'activated': [], 'skipped': [], 'entries_considered': 0,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    try:
        if registry is None:
            from convergence_registry import CONVERGENCE_REGISTRY as registry
            try:
                from convergence_registry import registry_identity
                report['registry'] = registry_identity()
            except ImportError:
                report['registry'] = {'version': 'pre-1.2.0', 'as_of': 'unknown',
                                      'entries': len(registry),
                                      'fingerprint': 'no identity marker'}
        from convergence_registry import alert_meets_threshold, format_enrichment_text
    except Exception as e:
        report['error'] = ('convergence_registry not importable on this backend '
                           '(%s). THIS IS THE DEPENDENCY: convergence_layer2 is '
                           'the engine, the registry is the fuel, and the engine '
                           'alone does nothing.' % str(e)[:100])
        return report

    for entry in registry:
        if entry.get('trigger_region') != region:
            continue
        report['entries_considered'] += 1
        eid = entry.get('id') or '?'

        sig, lvl = _find_trigger(signals, entry)
        if sig is None:
            # The loudest silence: nothing in this region publishes the category
            # this entry waits on. Not "quiet" -- UNWIRED.
            report['skipped'].append({
                'id': eid, 'reason': 'no_trigger_signal',
                'waiting_on': _categories_of(entry),
                'note': ('No published signal carries this category. The entry '
                         'cannot fire until some tracker emits it.')})
            continue

        commodity_id = entry.get('commodity')

        if commodity_id:
            # ── COMMODITY GATE (ME's existing behaviour, unchanged) ──
            state = None
            if callable(commodity_fetch):
                try:
                    state = commodity_fetch(commodity_id)
                except Exception:
                    state = None
            if not state:
                report['skipped'].append({
                    'id': eid, 'reason': 'commodity_unreadable',
                    'commodity': commodity_id,
                    'note': ('Commodity pressure could not be read. UNREAD, not '
                             'normal -- the entry is not reported as quiet.')})
                continue
            actual = state.get('alert_level', 'normal')
            threshold = entry.get('commodity_threshold') or 'elevated'
            if not alert_meets_threshold(actual, threshold):
                report['skipped'].append({
                    'id': eid, 'reason': 'commodity_below_threshold',
                    'commodity': commodity_id, 'actual': actual,
                    'required': threshold})
                continue
            count = state.get('signal_count', 0)
            reading = _level(actual) or 0
            gate = {'kind': 'commodity', 'commodity': commodity_id,
                    'alert_level': actual, 'signal_count': count}
            enrich_alert, enrich_count = actual, count
        else:
            # ── REGIME GATE (new -- the eight entries Layer 2 never reached) ──
            min_level = entry.get('trigger_signal_min_level')
            if min_level is None:
                min_level = DEFAULT_REGIME_MIN_LEVEL
            if lvl is None:
                report['skipped'].append({
                    'id': eid, 'reason': 'trigger_level_unreadable',
                    'waiting_on': _categories_of(entry),
                    'note': ('The trigger signal is published but its level '
                             'could not be read. Unread, not below threshold.')})
                continue
            if lvl < int(min_level):
                report['skipped'].append({
                    'id': eid, 'reason': 'trigger_below_level',
                    'actual': lvl, 'required': int(min_level),
                    'category': sig.get('category')})
                continue
            reading = lvl
            gate = {'kind': 'regime', 'category': sig.get('category'),
                    'trigger_level': lvl, 'required_level': int(min_level)}
            # The enrichment template speaks in {alert} and {signals}. A regime
            # entry has no commodity, so the trigger's own level IS the alert and
            # the count of signals on that category is the volume.
            enrich_alert = 'L%d' % lvl
            enrich_count = sum(1 for s in (signals or [])
                               if isinstance(s, dict)
                               and s.get('category') == sig.get('category'))

        fresh, why_fresh = _is_fresh(eid, reading, redis_get, redis_set)

        # THE STAMP. This exact shape is what global_pressure_index's
        # _detect_convergences_from_registry reads; changing it breaks Layer 1.
        sig['%s_active' % eid] = True
        sig.setdefault('convergence_states', {})[eid] = {
            'alert_level':  enrich_alert,
            'signal_count': enrich_count,
            'is_fresh':     fresh,
            'commodity':    commodity_id,
            'gate':         gate,
            'layer2_version': __version__,
        }

        enrichment = ''
        try:
            if entry.get('enrichment_text_template'):
                enrichment = format_enrichment_text(entry, str(enrich_alert), enrich_count)
        except Exception:
            enrichment = ''

        report['activated'].append({
            'id': eid, 'gate': gate['kind'], 'fresh': fresh,
            'freshness_basis': why_fresh,
            'on_signal': sig.get('category'),
            'enrichment': enrichment,
        })

    return report


def log_report(report, tag='Layer2'):
    """One block per cycle, printed even when nothing fired.

    A convergence layer that prints only on success is indistinguishable from
    one that never ran -- which is how ME's silent skip survived five months.
    """
    region = report.get('region', '?')
    if report.get('error'):
        print('[%s %s] ERROR: %s' % (tag, region, report['error']))
        print('[%s %s] No convergence flags set. Every registry entry for this '
              'region is inert until the registry is deployed here.'
              % (tag, region))
        return
    ident = report.get('registry')
    if ident:
        # Printed every cycle on every backend. Two copies that disagree now
        # disagree VISIBLY, in the log, on the first scan after the fork.
        print('[%s %s] registry v%s (%s) -- %d entries, fingerprint %s'
              % (tag, region, ident.get('version'), ident.get('as_of'),
                 ident.get('entries'), ident.get('fingerprint')))
    act, skip = report.get('activated', []), report.get('skipped', [])
    print('[%s %s] %d/%d convergence(s) activated'
          % (tag, region, len(act), report.get('entries_considered', 0)))
    for a in act:
        print('[%s %s]   ACTIVE %-34s via %-22s gate=%-9s %s'
              % (tag, region, a['id'], a['on_signal'], a['gate'],
                 'TOPLINE' if a['fresh'] else 'WATCH'))
    for s in skip:
        extra = ''
        if s['reason'] == 'trigger_below_level':
            extra = ' (L%s < L%s)' % (s.get('actual'), s.get('required'))
        elif s['reason'] == 'commodity_below_threshold':
            extra = ' (%s < %s)' % (s.get('actual'), s.get('required'))
        elif s['reason'] == 'no_trigger_signal':
            extra = ' (waiting on %s)' % ', '.join(s.get('waiting_on') or ['?'])
        print('[%s %s]   dark   %-34s %s%s'
              % (tag, region, s['id'], s['reason'], extra))


if __name__ == '__main__':
    print('convergence_layer2 v%s -- self-test\n' % __version__)

    REG = [
        {'id': 'regime_fires', 'trigger_region': 'asia', 'commodity': None,
         'trigger_signal_category': 'japan_outbound_posture',
         'trigger_signal_min_level': 3, 'priority': 14,
         'enrichment_text_template': 'ASIA at {alert} on {signals} signal(s).'},
        {'id': 'regime_too_quiet', 'trigger_region': 'asia', 'commodity': None,
         'trigger_signal_category': 'taiwan_us_alliance',
         'trigger_signal_min_level': 4, 'priority': 13},
        {'id': 'regime_unwired', 'trigger_region': 'asia', 'commodity': None,
         'trigger_signal_category': 'nobody_emits_this', 'priority': 9},
        {'id': 'comm_fires', 'trigger_region': 'me', 'commodity': 'wheat',
         'commodity_threshold': 'elevated',
         'trigger_signal_category': 'humanitarian_lebanon', 'priority': 15},
    ]
    sigs = [
        {'category': 'japan_outbound_posture', 'level': 4, 'short_text': 'x'},
        {'category': 'taiwan_us_alliance', 'level': 2, 'short_text': 'y'},
        {'category': 'humanitarian_lebanon', 'level': 4, 'short_text': 'z'},
    ]

    class _Store(dict):
        def get_(self, k):
            return self.get(k)

        def set_(self, k, v, ttl=None):
            self[k] = v

    st = _Store()
    rep = enrich_signals(sigs, 'asia', registry=REG,
                         redis_get=st.get_, redis_set=st.set_)
    log_report(rep, 'SelfTest')

    assert sigs[0].get('regime_fires_active') is True, 'regime gate must fire'
    assert 'regime_too_quiet_active' not in sigs[1], 'below-level must not fire'
    reasons = {s['id']: s['reason'] for s in rep['skipped']}
    assert reasons['regime_too_quiet'] == 'trigger_below_level'
    assert reasons['regime_unwired'] == 'no_trigger_signal'
    assert rep['entries_considered'] == 3, rep['entries_considered']

    print('\n-- ME region, commodity gate, no fetcher supplied --')
    sigs2 = [{'category': 'humanitarian_lebanon', 'level': 4}]
    rep2 = enrich_signals(sigs2, 'me', registry=REG)
    log_report(rep2, 'SelfTest')
    assert rep2['skipped'][0]['reason'] == 'commodity_unreadable', \
        'an unreadable commodity must be reported, not silently skipped'

    print('\n-- ME region, commodity gate, fetcher says HIGH --')
    sigs3 = [{'category': 'humanitarian_lebanon', 'level': 4}]
    rep3 = enrich_signals(sigs3, 'me', registry=REG,
                          commodity_fetch=lambda c: {'alert_level': 'high',
                                                     'signal_count': 30})
    log_report(rep3, 'SelfTest')
    assert sigs3[0].get('comm_fires_active') is True
    assert sigs3[0]['convergence_states']['comm_fires']['gate']['kind'] == 'commodity'

    print('\nSELF-TEST COMPLETE')
