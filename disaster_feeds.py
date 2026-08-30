"""
disaster_feeds.py -- Asifah Analytics -- v1.0.0 Aug 2026
============================================================================
Worldwide structured disaster feed. Feeds the SAME signal list the
humanitarian convergence detector aggregates -- not a parallel axis.

WHY STRUCTURED FEEDS AND NOT MORE RSS: the humanitarian gatherer already
scrapes disaster keywords out of news. That works where news coverage exists,
which biases hard toward countries with press presence and toward events that
are already being talked about. A magnitude-7 offshore of a country nobody is
writing about produces no keywords and therefore no signal.

These feeds are POPULATION-BLIND AND PRESS-BLIND by construction. They fire on
the event, not on the coverage, which is exactly the worldwide-catch function:
picking up Nepal, Vanuatu or Mozambique when no country tracker exists and no
newsroom has filed yet.

SOURCES
  GDACS  Global Disaster Alert and Coordination System (EC JRC + UN). Global,
         multi-hazard: earthquakes, tropical cyclones, floods, volcanoes,
         droughts, wildfires. Ships a green/orange/red alert level that is an
         IMPACT estimate -- population exposure, vulnerability -- not a raw
         physical magnitude. That is why it is the spine here.
  USGS   Earthquake feed. Free, keyless GeoJSON. RAW MAGNITUDE ONLY, and that
         distinction is load-bearing: an M7.0 in open ocean and an M6.2 under a
         city are opposite humanitarian events and identical magnitudes. USGS
         is therefore a SUPPLEMENT that fills seismic gaps GDACS may lag on,
         never an impact judgement, and its signals say so in their own text.

DELIBERATELY NOT USED: NOAA's National Hurricane Center. Its area of
responsibility runs Prime Meridian to 140W -- Atlantic and Eastern Pacific
only. A global platform built on NHC would systematically miss Western Pacific
typhoons and Indian Ocean cyclones, which are the highest-humanitarian-impact
storms on earth. GDACS covers every basin.

CONTRACT: emit() returns signals in the exact shape
humanitarian_convergence_detector.detect_humanitarian_signals() produces, so
they merge via the existing `extra_signals` seam and land on
theatre='global_humanitarian' alongside everything else. No GPI change.
"""

import re
import json
import requests
from datetime import datetime, timezone, timedelta

__version__ = '1.0.0'

GDACS_RSS = 'https://www.gdacs.org/xml/rss.xml'
USGS_FEED = 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson'

HTTP_TIMEOUT = (5, 15)
UA = {'User-Agent': 'Mozilla/5.0 (compatible; AsifahAnalytics/1.0)'}

# GDACS alert level -> severity 1-3, matching the detector's scale.
# Green is NOT emitted: GDACS issues green for routine events with negligible
# expected impact, and emitting them would bury real signals under noise.
GDACS_ALERT_SEVERITY = {'red': 3, 'orange': 2, 'green': 0}

# Raw magnitude bands. Conservative on purpose -- see the USGS note above.
# M6.5 is the floor because below it, impact is almost entirely a function of
# depth and population, which this feed cannot see.
USGS_MIN_MAGNITUDE = 6.5

HAZARD_ICON = {
    'earthquake': '\U0001f30b', 'tropical cyclone': '\U0001f300',
    'flood': '\U0001f30a', 'volcano': '\U0001f30b',
    'drought': '\U0001f3dc\ufe0f', 'wildfire': '\U0001f525',
}

_HAZARD_NORMALISE = {
    'eq': 'earthquake', 'tc': 'tropical cyclone', 'fl': 'flood',
    'vo': 'volcano', 'dr': 'drought', 'wf': 'wildfire',
}


def _slug(name):
    return re.sub(r'[^a-z0-9]+', '_', str(name or '').lower()).strip('_')


def _fetch(url):
    try:
        r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            return r.text
        print(f'[Disaster Feeds] {url} -> HTTP {r.status_code}')
    except Exception as e:
        print(f'[Disaster Feeds] {url} failed: {str(e)[:110]}')
    return None


def fetch_gdacs(min_severity=2):
    """GDACS alerts as detector-shaped signals. Orange and red only by default."""
    raw = _fetch(GDACS_RSS)
    if not raw:
        return []

    out = []
    # GDACS RSS carries gdacs:-namespaced fields alongside standard RSS. Parsed
    # with regex rather than an XML lib so a single malformed item cannot take
    # the whole feed down -- absence of one alert beats absence of all of them.
    for item in re.findall(r'<item>(.*?)</item>', raw, re.S):
        def _tag(name):
            m = re.search(r'<%s[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>' % (name, name),
                          item, re.S)
            return (m.group(1).strip() if m else '')

        alert = _tag('gdacs:alertlevel').lower()
        sev = GDACS_ALERT_SEVERITY.get(alert, 0)
        if sev < min_severity:
            continue

        etype = _HAZARD_NORMALISE.get(_tag('gdacs:eventtype').lower(),
                                      _tag('gdacs:eventtype').lower()) or 'disaster'
        country = _tag('gdacs:country') or _tag('title')
        country = country.split(',')[0].strip()
        title = _tag('title')
        link = _tag('link')
        desc = re.sub(r'<[^>]+>', ' ', _tag('description'))[:400]
        pop = _tag('gdacs:population')

        label = country or 'Unspecified location'
        # Population exposure, where GDACS supplies it, is the most useful single
        # number in the alert -- it is the difference between a hazard and a
        # humanitarian event -- so it goes in the headline, not the footnotes.
        #
        # GDACS phrases this field DIFFERENTLY BY HAZARD: quakes give exposure
        # ("300 thousand in MMI VI"), floods give outcomes ("527 deaths and 0
        # displaced"). Appending "exposed" unconditionally produced "527 deaths
        # exposed", which is simply wrong. Only add the word where the string is
        # not already self-describing.
        _self_describing = any(w in (pop or '').lower()
                               for w in ('death', 'displaced', 'affected', 'killed'))
        pop_txt = ('' if not pop else
                   (' — %s' % pop.strip()) if _self_describing else
                   (' — %s exposed' % pop.strip()))
        out.append({
            'category': 'natural_disaster',
            'country': _slug(country) or 'unspecified',
            'country_label': label,
            'severity': sev,
            'pressure_type': 'humanitarian',
            'level': {1: 3, 2: 4, 3: 5}.get(sev, 3),
            'short_text': ('%s %s: %s alert — %s%s'
                           % (HAZARD_ICON.get(etype, '\U0001f30b'), label,
                              alert.upper(), etype, pop_txt))[:150],
            'long_text': ('%s: GDACS %s alert for %s. %s '
                          'GDACS alert levels are IMPACT estimates incorporating population '
                          'exposure and vulnerability, not raw physical magnitude. '
                          'Structured feed — fires on the event rather than on press coverage, '
                          'so it reaches countries with no tracker and no newsroom presence.'
                          % (label, alert.upper(), etype, desc[:220])),
            'source_url': link,
            'source_title': title[:200],
            'source': 'GDACS',
            'matched_keywords': [b for b in [etype, alert] if b],
            'detected_at': datetime.now(timezone.utc).isoformat(),
            'icon': HAZARD_ICON.get(etype, '\U0001f30b'),
            'theatre': 'global_humanitarian',
            'region': 'global_humanitarian',
            'is_tracked_country': False,      # caller re-stamps against its own set
            'feed': 'gdacs',
            'hazard_type': etype,
            'alert_level': alert,
        })
    print(f'[Disaster Feeds] GDACS: {len(out)} alert(s) at severity >= {min_severity}')
    return out


def fetch_usgs(min_magnitude=USGS_MIN_MAGNITUDE, hours=48):
    """Large earthquakes from USGS. MAGNITUDE, NOT IMPACT -- see module docstring."""
    raw = _fetch(USGS_FEED)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f'[Disaster Feeds] USGS parse failed: {str(e)[:100]}')
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for f in (data.get('features') or []):
        p = f.get('properties') or {}
        mag = p.get('mag')
        if mag is None or float(mag) < min_magnitude:
            continue
        try:
            when = datetime.fromtimestamp((p.get('time') or 0) / 1000, tz=timezone.utc)
            if when < cutoff:
                continue
        except Exception:
            continue

        place = p.get('place') or 'unknown location'
        country = place.split(',')[-1].strip() if ',' in place else place
        # Magnitude bands only. NOT an impact claim.
        sev = 3 if float(mag) >= 7.5 else (2 if float(mag) >= 7.0 else 1)
        depth = None
        try:
            depth = (f.get('geometry') or {}).get('coordinates', [None, None, None])[2]
        except Exception:
            pass

        out.append({
            'category': 'natural_disaster',
            'country': _slug(country),
            'country_label': country,
            'severity': sev,
            'pressure_type': 'humanitarian',
            'level': {1: 3, 2: 4, 3: 5}.get(sev, 3),
            'short_text': ('\U0001f30b %s: M%.1f earthquake — %s'
                           % (country, float(mag), place))[:150],
            'long_text': ('M%.1f earthquake, %s%s. USGS structured feed. '
                          'THIS IS A MAGNITUDE READING, NOT AN IMPACT ASSESSMENT: an M7.0 '
                          'offshore and an M6.2 beneath a city are identical on this scale and '
                          'opposite humanitarian events. Depth and population exposure govern '
                          'consequence and are not scored here — see any GDACS alert for the '
                          'same event, which does estimate impact.'
                          % (float(mag), place,
                             (', depth %.0f km' % depth) if depth is not None else '')),
            'source_url': p.get('url', ''),
            'source_title': p.get('title', '')[:200],
            'source': 'USGS',
            'matched_keywords': ['earthquake', 'magnitude %.1f' % float(mag)],
            'detected_at': datetime.now(timezone.utc).isoformat(),
            'icon': '\U0001f30b',
            'theatre': 'global_humanitarian',
            'region': 'global_humanitarian',
            'is_tracked_country': False,
            'feed': 'usgs',
            'hazard_type': 'earthquake',
            'magnitude': float(mag),
            'depth_km': depth,
        })
    print(f'[Disaster Feeds] USGS: {len(out)} quake(s) >= M{min_magnitude} in {hours}h')
    return out


def _dedupe(signals):
    """Collapse GDACS and USGS reporting the same event.

    GDACS WINS on a collision, because it estimates impact and USGS reports
    magnitude -- and impact is the thing this axis measures. Dropping the GDACS
    record in favour of the raw magnitude would discard the more analytically
    useful of two readings of the same earthquake.
    """
    seen, out = {}, []
    for s in sorted(signals, key=lambda x: 0 if x.get('feed') == 'gdacs' else 1):
        key = (s.get('country'), s.get('hazard_type'))
        if key in seen:
            continue
        seen[key] = True
        out.append(s)
    return out


def fetch_disaster_signals(min_gdacs_severity=2, min_magnitude=USGS_MIN_MAGNITUDE,
                           tracked_countries=None):
    """Worldwide catch. Returns detector-shaped signals ready for extra_signals.

    Absence-honest: a feed outage returns an empty list and says so in the log.
    It never fabricates a quiet world, and it never blocks the caller -- the
    news-derived signals stand on their own if these feeds are down.
    """
    signals = []
    try:
        signals += fetch_gdacs(min_severity=min_gdacs_severity)
    except Exception as e:
        print(f'[Disaster Feeds] GDACS stage failed (non-fatal): {str(e)[:110]}')
    try:
        signals += fetch_usgs(min_magnitude=min_magnitude)
    except Exception as e:
        print(f'[Disaster Feeds] USGS stage failed (non-fatal): {str(e)[:110]}')

    signals = _dedupe(signals)

    if tracked_countries:
        for s in signals:
            s['is_tracked_country'] = s.get('country') in tracked_countries

    untracked = [s['country_label'] for s in signals if not s.get('is_tracked_country')]
    print(f'[Disaster Feeds] {len(signals)} signal(s); '
          f'{len(untracked)} in countries with no dedicated tracker'
          + (f' — {", ".join(untracked[:5])}' if untracked else ''))
    return signals


def feed_status():
    return {
        'version': __version__,
        'sources': {'gdacs': GDACS_RSS, 'usgs': USGS_FEED},
        'gdacs_min_severity': 2,
        'usgs_min_magnitude': USGS_MIN_MAGNITUDE,
        'note': ('Worldwide catch. Structured feeds fire on the EVENT rather than on press '
                 'coverage, which is how countries with no tracker and no newsroom presence '
                 'reach the humanitarian axis at all.'),
    }


# ============================================================================
# CROSS-POOL DEDUPE
# ============================================================================
# humanitarian_article_gatherer.py ALREADY ingests the GDACS RSS feed (line 246,
# weight 1.2) and keyword-matches it like any other news source. That produces a
# second, much weaker reading of the same event: "Nepal: natural disaster --
# flooding, severity 1" alongside this module's "Nepal: ORANGE alert -- flood,
# 527 deaths". Same source, same event, and the vague one was surviving next to
# the specific one.
#
# Structured always wins. The news path reads a GDACS headline as prose and
# throws away the alert level, the hazard type and the exposure figure -- the
# three fields that make the alert worth having.

_HAZARD_FAMILY_TOKENS = {
    'earthquake': ('earthquake', 'quake', 'seismic', 'aftershock', 'tremor'),
    'flood':      ('flood', 'flooding', 'floodwater', 'inundation', 'deluge'),
    'tropical cyclone': ('cyclone', 'typhoon', 'hurricane', 'tropical storm', 'storm surge'),
    'wildfire':   ('wildfire', 'forest fire', 'bushfire', 'blaze'),
    'volcano':    ('volcan', 'eruption', 'lava', 'ashfall'),
    'drought':    ('drought', 'dry spell', 'water scarcity'),
    'landslide':  ('landslide', 'mudslide', 'rockslide'),
}


def hazard_family(*texts):
    """Normalise any hazard wording to a family. Returns '' when unrecognised --
    an unknown hazard is left alone rather than force-matched into a bucket."""
    joined = ' '.join(str(t or '') for t in texts).lower()
    for fam, toks in _HAZARD_FAMILY_TOKENS.items():
        if any(tok in joined for tok in toks):
            return fam
    return ''


def merge_with_news_signals(news_signals, structured_signals):
    """Fold structured disaster signals into the news-derived pool.

    On a (country, hazard-family) collision the STRUCTURED record replaces the
    news-derived one rather than sitting beside it. Returns
    (merged_list, replaced_count) so the caller can log what was collapsed --
    a silent dedupe would hide whether this is working at all.
    """
    structured = list(structured_signals or [])
    keys = set()
    for s in structured:
        fam = s.get('hazard_type') or hazard_family(s.get('short_text'))
        if fam:
            keys.add((str(s.get('country', '')).lower(), fam))

    kept, replaced = [], 0
    for n in (news_signals or []):
        if n.get('category') != 'natural_disaster':
            kept.append(n)
            continue
        fam = hazard_family(' '.join(n.get('matched_keywords') or []),
                            n.get('short_text'), n.get('long_text'))
        if fam and (str(n.get('country', '')).lower(), fam) in keys:
            replaced += 1
            continue
        kept.append(n)

    return kept + structured, replaced
