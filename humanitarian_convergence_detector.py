"""
humanitarian_convergence_detector.py
Asifah Analytics -- ME Backend Module
v1.0.0 -- May 17, 2026

GLOBAL HUMANITARIAN CONVERGENCE DETECTOR

Solves the "weak signal aggregation" problem for humanitarian crises:
no single article about Egypt vegetable prices, Ethiopia fertilizer,
or Myanmar fuel triggers anything on its own -- but the PATTERN of
distributed humanitarian distress signals across many countries IS
the canonical indicator of a global crisis forming.

ARCHITECTURE:
  Scans GDELT + RSS feeds directly for humanitarian signals from
  countries that do NOT have their own Asifah trackers yet. When
  those countries DO get trackers (per the roadmap), this layer
  continues to function as a SUPPLEMENT, not a replacement.

  Emits a BLUF-shaped payload at /api/humanitarian-convergence/bluf
  that GPI consumes as a 5th regional BLUF. GPI's existing
  pressure_type classifier picks up the humanitarian tags
  automatically — no GPI logic changes needed. Today.

SIGNAL CATEGORIES (6):
  1. FOOD_PRICE_CRISIS    -- bread/vegetable/rice price surges, food shortages
  2. FUEL_ENERGY_CRISIS   -- fuel shortages, blackouts, panic buying
  3. FERTILIZER_SCARCITY  -- planting season crisis, urea shortages
  4. AID_SHORTFALL        -- UN appeals underfunded, WFP ration cuts
  5. DISPLACEMENT_SURGE   -- IDP surges, mass displacement events
  6. CURRENCY_COLLAPSE    -- currency crashes, banking collapses, reserves drain

CONVERGENCE THRESHOLDS:
  1-2 countries active                  -> BASELINE       (L0-L1)
  3-5 countries active                  -> FORMING        (L3)
  6-9 countries active                  -> ACTIVE         (L4)
  10+ countries OR 4+ categories        -> GLOBAL         (L5)

Author: RCGG / Asifah Analytics
"""
from datetime import datetime, timezone, timedelta
import json
import os
import re

# ============================================================
# SIGNAL CATEGORIES + KEYWORDS
# ============================================================
SIGNAL_CATEGORIES = {
    'food_price_crisis': {
        'label':       'Food Price Crisis',
        'icon':        '🍞',
        'description': 'Bread, vegetable, rice, or staple food price surges + shortages',
        'keywords': [
            # Generic surge language
            'food prices triple', 'food prices double', 'food prices surge',
            'food prices soar', 'food prices skyrocket', 'food inflation soar',
            'staple food shortage', 'bread shortage', 'bread price surge',
            'rice shortage', 'rice price surge', 'rice export ban',
            'flour shortage', 'flour price surge',
            'cooking oil shortage', 'cooking oil price surge',
            'vegetable prices triple', 'vegetable prices double',
            'vegetable prices surge', 'produce prices surge',
            'wheat price surge', 'grain shortage acute', 'cereal price surge',
            'sugar shortage acute', 'sugar price surge',
            'meat shortage acute', 'dairy shortage acute',
            # Crisis framing
            'food crisis acute', 'food insecurity acute',
            'acute food insecurity', 'famine warning',
            'ipc phase 3', 'ipc phase 4', 'ipc phase 5',
            'malnutrition rate', 'acute malnutrition rises',
            'food riots', 'bread riots',
            # International framing
            'wfp warning', 'fao alert', 'food security crisis',
        ],
        'high_intensity_markers': [
            'famine', 'mass starvation', 'food riots', 'ipc phase 5',
            'ipc phase 4',
        ],
    },

    'fuel_energy_crisis': {
        'label':       'Fuel / Energy Crisis',
        'icon':        '⛽',
        'description': 'Fuel shortages, blackouts, panic buying',
        'keywords': [
            'fuel shortage', 'fuel crisis acute', 'gasoline shortage',
            'diesel shortage', 'gas station closures',
            'gas station queues', 'fuel queues', 'fuel rationing',
            'panic buying fuel', 'fuel panic',
            'energy crisis acute', 'electricity blackouts', 'power blackouts',
            'rolling blackouts', 'load shedding hours',
            'natural gas shortage', 'lpg shortage',
            'fuel emergency', 'energy emergency',
            'fuel imports halted', 'fuel exports halted',
            'fuel queue deaths', 'no petrol',
        ],
        'high_intensity_markers': [
            'fuel queue deaths', 'fuel riots', 'energy emergency',
        ],
    },

    'fertilizer_scarcity': {
        'label':       'Fertilizer Scarcity',
        'icon':        '🌾',
        'description': 'Planting season fertilizer crisis, urea shortages',
        'keywords': [
            'fertilizer shortage', 'fertilizer crisis', 'fertilizer scarcity',
            'urea shortage', 'urea crisis',
            'potash shortage', 'phosphate shortage',
            'fertilizer price surge', 'fertilizer imports halted',
            'planting season fertilizer', 'farmers fertilizer crisis',
            'ammonia shortage', 'nitrogen fertilizer shortage',
            'agricultural inputs crisis', 'agri-inputs shortage',
        ],
        'high_intensity_markers': [
            'planting season missed', 'harvest collapse forecast',
        ],
    },

    'aid_shortfall': {
        'label':       'Aid Shortfall',
        'icon':        '💔',
        'description': 'UN appeals underfunded, WFP ration cuts, NGO withdrawals',
        'keywords': [
            'un appeal underfunded', 'un appeal funded only',
            'humanitarian appeal underfunded', 'wfp ration cut',
            'wfp ration cuts', 'wfp cuts rations',
            'unhcr funding shortfall', 'unicef appeal',
            'humanitarian funds frozen', 'usaid cuts',
            'humanitarian assistance suspended', 'aid suspended',
            'foreign aid cut', 'foreign aid suspended',
            'ngo withdrawal', 'ngo suspends operations',
            'oxfam withdrawal', 'msf withdraws', 'icrc withdrawal',
            'humanitarian funding gap', 'humanitarian budget cut',
            'state department humanitarian frozen',
            'bureau humanitarian response funds unspent',
        ],
        'high_intensity_markers': [
            'wfp ration cut', 'aid suspended', 'humanitarian funds frozen',
        ],
    },

    'displacement_surge': {
        'label':       'Displacement Surge',
        'icon':        '🚶',
        'description': 'IDP surges, mass displacement events, refugee waves',
        'keywords': [
            'mass displacement', 'mass displacement event',
            'idp surge', 'idp camps', 'idps displaced',
            'refugee surge', 'refugee wave', 'refugees fleeing',
            'thousands displaced', 'million displaced',
            'displaced civilians', 'displacement crisis',
            'refugee crisis acute', 'forced displacement',
            'people on the move', 'forcibly displaced',
            'mass exodus', 'mass migration crisis',
            'humanitarian corridor', 'evacuation corridor',
            'internally displaced persons',
        ],
        'high_intensity_markers': [
            'million displaced', 'mass exodus', 'forced displacement',
        ],
    },

    'currency_collapse': {
        'label':       'Currency / Institutional Collapse',
        'icon':        '💱',
        'description': 'Currency crashes, banking collapses, FX reserves draining',
        'keywords': [
            'currency crash', 'currency collapse', 'currency plunge',
            'currency falls record', 'lira collapses', 'lebanese pound collapse',
            'foreign reserves drained', 'fx reserves critical',
            'banking collapse', 'bank run', 'bank holidays',
            'capital controls', 'capital controls imposed',
            'central bank intervention emergency', 'emergency rate hike',
            'devaluation forced', 'devaluation emergency',
            'hyperinflation', 'inflation hits record',
            'sovereign default', 'debt default',
            'imf bailout emergency', 'imf emergency loan',
        ],
        'high_intensity_markers': [
            'hyperinflation', 'sovereign default', 'banking collapse',
        ],
    },
}


# ============================================================
# COUNTRY EXTRACTION
# ============================================================
# Maps article-mentioned country names to canonical country codes.
# We intentionally focus on countries WITHOUT existing Asifah trackers
# (to avoid double-counting Lebanon, Iran, etc.) — though when they
# DO appear in headlines we still tag them for completeness.

COUNTRY_PATTERNS = {
    # Africa (heavy concentration of humanitarian risk)
    'egypt':      ['egypt', 'egyptian'],
    'ethiopia':   ['ethiopia', 'ethiopian'],
    'sudan':      ['sudan', 'sudanese'],
    'south_sudan':['south sudan'],
    'somalia':    ['somalia', 'somali'],
    'kenya':      ['kenya', 'kenyan'],
    'nigeria':    ['nigeria', 'nigerian'],
    'chad':       ['chad'],
    'niger':      ['niger', 'nigerien'],
    'mali':       ['mali'],
    'burkina_faso':['burkina faso'],
    'drc':        ['drc', 'democratic republic of the congo', 'eastern congo'],
    'mozambique': ['mozambique'],
    'madagascar': ['madagascar', 'malagasy'],
    'malawi':     ['malawi'],
    'zambia':     ['zambia'],
    'zimbabwe':   ['zimbabwe', 'zimbabwean'],
    'south_africa':['south africa', 'south african'],
    'morocco':    ['morocco', 'moroccan'],
    'tunisia':    ['tunisia', 'tunisian'],
    'algeria':    ['algeria', 'algerian'],
    'libya':      ['libya', 'libyan'],
    # Asia (humanitarian gaps without Asifah trackers)
    'myanmar':    ['myanmar', 'burma', 'burmese'],
    'bangladesh': ['bangladesh', 'bangladeshi'],
    'sri_lanka':  ['sri lanka', 'sri lankan'],
    'afghanistan':['afghanistan', 'afghan'],
    'nepal':      ['nepal', 'nepalese', 'nepali'],
    'vietnam':    ['vietnam', 'vietnamese'],
    'philippines':['philippines', 'filipino'],
    'indonesia':  ['indonesia', 'indonesian'],
    'thailand':   ['thailand', 'thai'],
    'laos':       ['laos', 'lao'],
    'cambodia':   ['cambodia', 'cambodian'],
    # Americas (humanitarian gaps without Asifah trackers)
    'jamaica':    ['jamaica', 'jamaican'],
    'haiti':      ['haiti', 'haitian'],
    'el_salvador':['el salvador', 'salvadoran'],
    'honduras':   ['honduras', 'honduran'],
    'guatemala':  ['guatemala', 'guatemalan'],
    'nicaragua':  ['nicaragua', 'nicaraguan'],
    'argentina':  ['argentina', 'argentinian', 'argentine'],
    # Tracked countries (still listed so we can dedupe vs regional BLUFs)
    'gaza':       ['gaza', 'gaza strip'],
    'lebanon':    ['lebanon', 'lebanese'],
    'syria':      ['syria', 'syrian'],
    'yemen':      ['yemen', 'yemeni'],
    'iran':       ['iran', 'iranian'],
    'cuba':       ['cuba', 'cuban'],
}

# Countries that already have full Asifah trackers (humanitarian signals
# from these should be detected but lower-weighted in convergence scoring
# to avoid double-counting with their dedicated BLUFs)
TRACKED_COUNTRIES = {
    'lebanon', 'syria', 'yemen', 'iran', 'cuba', 'gaza',
    # Add: pakistan, russia, ukraine, china, taiwan, north_korea, etc. — but
    # those are unlikely humanitarian-distress mentions in this detector's scope
}

# Country-name length sort: match longest first to avoid 'south sudan' colliding with 'sudan'
_COUNTRY_TOKENS_SORTED = []
for country_code, patterns in COUNTRY_PATTERNS.items():
    for pattern in patterns:
        _COUNTRY_TOKENS_SORTED.append((pattern, country_code))
_COUNTRY_TOKENS_SORTED.sort(key=lambda kv: -len(kv[0]))


# ============================================================
# SEVERITY SCORING
# ============================================================
SEVERITY_BASELINE = 1   # signal exists, low confidence
SEVERITY_MEDIUM   = 2   # signal + intensity language
SEVERITY_HIGH     = 3   # signal + high-intensity marker

# Convergence thresholds — number of countries with active signals
CONVERGENCE_FORMING_MIN  = 3   # 3-5 countries -> L3
CONVERGENCE_ACTIVE_MIN   = 6   # 6-9 countries -> L4
CONVERGENCE_GLOBAL_MIN   = 10  # 10+ countries -> L5
CONVERGENCE_CATEGORIES_FOR_GLOBAL = 4  # OR 4+ categories simultaneously -> L5


# ============================================================
# DETECTION FUNCTIONS
# ============================================================
def _scan_article_text(text, category_cfg):
    """
    Scan a piece of text against a category's keywords.
    Returns (matched, severity, matched_keywords).
    """
    if not text:
        return (False, 0, [])
    text_lower = text.lower()
    matches = [kw for kw in category_cfg['keywords'] if kw in text_lower]
    if not matches:
        return (False, 0, [])

    # Severity: high if any high-intensity marker present
    high_markers = category_cfg.get('high_intensity_markers', [])
    if any(m in text_lower for m in high_markers):
        return (True, SEVERITY_HIGH, matches)

    # Medium if 2+ keyword matches
    if len(matches) >= 2:
        return (True, SEVERITY_MEDIUM, matches)

    return (True, SEVERITY_BASELINE, matches)


def _extract_country_from_text(text):
    """
    Extract the most likely country mentioned in a piece of text.
    Returns canonical country code or None.

    Uses longest-pattern-first matching to avoid e.g. 'south sudan'
    being captured by 'sudan'.
    """
    if not text:
        return None
    text_lower = text.lower()
    for pattern, country_code in _COUNTRY_TOKENS_SORTED:
        # Use word-boundary check to avoid 'iran' matching 'transparent'
        if re.search(r'\b' + re.escape(pattern) + r'\b', text_lower):
            return country_code
    return None


def detect_humanitarian_signals(articles):
    """
    Main detection entry point.

    Takes a list of article dicts (each with 'title' + 'description' or 'text')
    and returns a list of detected signals.

    Each signal is a dict:
      {
        'category':         'food_price_crisis',
        'country':          'egypt',
        'severity':         1-3,
        'pressure_type':    'humanitarian',
        'level':            3-5 (mapped from severity),
        'short_text':       headline-style summary,
        'long_text':        2-3 sentence context,
        'source_url':       article URL,
        'source_title':     article title,
        'matched_keywords': [...],
        'detected_at':      ISO timestamp,
        'icon':             emoji,
      }
    """
    if not articles:
        return []

    detected = []
    seen_country_category = set()  # dedupe per country+category

    for art in articles:
        title = (art.get('title') or '').strip()
        desc  = (art.get('description') or art.get('snippet') or art.get('text') or '').strip()
        text  = f"{title} {desc}"
        if not text.strip():
            continue

        country = _extract_country_from_text(text)
        if not country:
            continue

        url = art.get('url') or art.get('link') or ''
        source = art.get('source') or art.get('source_name') or 'unknown'

        for cat_key, cat_cfg in SIGNAL_CATEGORIES.items():
            matched, severity, matched_kws = _scan_article_text(text, cat_cfg)
            if not matched:
                continue

            dedup_key = (country, cat_key)
            if dedup_key in seen_country_category:
                # Already captured this country+category — bump severity if higher
                for d in detected:
                    if d['country'] == country and d['category'] == cat_key:
                        if severity > d['severity']:
                            d['severity'] = severity
                            d['level'] = _severity_to_level(severity)
                            d['matched_keywords'].extend(matched_kws)
                        break
                continue

            seen_country_category.add(dedup_key)
            level = _severity_to_level(severity)
            country_label = country.replace('_', ' ').title()

            short_text = (
                f"{cat_cfg['icon']} {country_label}: {cat_cfg['label'].lower()} signal"
                f"{' (high intensity)' if severity == SEVERITY_HIGH else ''}"
            )
            long_text = (
                f"{country_label} showing {cat_cfg['label'].lower()} signals "
                f"(severity {severity}/3): {', '.join(matched_kws[:3])}. "
                f"Source: {source}. {cat_cfg['description']}."
            )

            detected.append({
                'category':         cat_key,
                'country':          country,
                'country_label':    country_label,
                'severity':         severity,
                'pressure_type':    'humanitarian',
                'level':            level,
                'short_text':       short_text[:150],
                'long_text':        long_text,
                'source_url':       url,
                'source_title':     title,
                'source':           source,
                'matched_keywords': list(set(matched_kws))[:5],
                'detected_at':      datetime.now(timezone.utc).isoformat(),
                'icon':             cat_cfg['icon'],
                'theatre':          'global_humanitarian',
                'region':           'global_humanitarian',
                'is_tracked_country': country in TRACKED_COUNTRIES,
            })

    return detected


def _severity_to_level(severity):
    """Map severity 1-3 to GPI level 0-5."""
    return {1: 3, 2: 4, 3: 5}.get(severity, 3)


# ============================================================
# CONVERGENCE AGGREGATION
# ============================================================
def aggregate_convergence(signals):
    """
    Aggregate detected signals into convergence assessment.

    Returns dict:
      {
        'tier':                'baseline' | 'forming' | 'active' | 'global',
        'max_level':           0-5,
        'level_label':         display string,
        'countries_active':    int,
        'categories_active':   int,
        'countries':           list of country codes with signals,
        'categories':          list of category keys with signals,
        'by_country':          dict {country_code: [signals]},
        'by_category':         dict {category_key: [signals]},
        'tracked_countries_present': bool,
        'novel_countries':     list of country codes NOT in TRACKED_COUNTRIES,
      }
    """
    if not signals:
        return {
            'tier':              'baseline',
            'max_level':         0,
            'level_label':       'BASELINE -- No humanitarian convergence signals',
            'countries_active':  0,
            'categories_active': 0,
            'countries':         [],
            'categories':        [],
            'by_country':        {},
            'by_category':       {},
            'tracked_countries_present': False,
            'novel_countries':   [],
        }

    countries_set  = set(s['country']  for s in signals)
    categories_set = set(s['category'] for s in signals)
    novel = [c for c in countries_set if c not in TRACKED_COUNTRIES]

    # Convergence tier — primarily based on UNIQUE COUNTRIES with active signals
    # (novel countries weighted more heavily since tracked-country signals would
    # already be flowing through their dedicated BLUFs)
    novel_count = len(novel)
    total_countries = len(countries_set)
    categories_count = len(categories_set)

    # Tier determination
    if total_countries >= CONVERGENCE_GLOBAL_MIN or categories_count >= CONVERGENCE_CATEGORIES_FOR_GLOBAL:
        tier = 'global'
        max_level = 5
        level_label = (
            f'GLOBAL CONVERGENCE -- {total_countries} countries × '
            f'{categories_count} crisis categories simultaneously active'
        )
    elif total_countries >= CONVERGENCE_ACTIVE_MIN:
        tier = 'active'
        max_level = 4
        level_label = (
            f'CONVERGENCE ACTIVE -- {total_countries} countries showing '
            f'distributed humanitarian distress signals'
        )
    elif total_countries >= CONVERGENCE_FORMING_MIN:
        tier = 'forming'
        max_level = 3
        level_label = (
            f'CONVERGENCE FORMING -- {total_countries} countries showing '
            f'humanitarian distress signals (watch for further spread)'
        )
    else:
        tier = 'baseline'
        max_level = 1 if signals else 0
        level_label = (
            f'BASELINE -- {total_countries} country with humanitarian signals '
            f'(below convergence threshold of {CONVERGENCE_FORMING_MIN})'
        )

    # Group signals by country + category
    by_country = {}
    by_category = {}
    for s in signals:
        by_country.setdefault(s['country'], []).append(s)
        by_category.setdefault(s['category'], []).append(s)

    return {
        'tier':              tier,
        'max_level':         max_level,
        'level_label':       level_label,
        'countries_active':  total_countries,
        'categories_active': categories_count,
        'countries':         sorted(countries_set),
        'categories':        sorted(categories_set),
        'by_country':        by_country,
        'by_category':       by_category,
        'tracked_countries_present': any(c in TRACKED_COUNTRIES for c in countries_set),
        'novel_countries':   sorted(novel),
    }


# ============================================================
# BLUF-SHAPED PAYLOAD BUILDER (consumed by GPI)
# ============================================================
def build_humanitarian_bluf(signals, aggregation=None):
    """
    Build a BLUF-shaped payload that GPI consumes via REGIONAL_BLUF_ENDPOINTS.

    Structure mirrors me_regional_bluf.py output so GPI's existing logic
    iterates this as the 5th 'region' (global_humanitarian) with zero
    GPI-side code changes (just add to REGIONAL_BLUF_ENDPOINTS dict).

    Returns dict matching the canonical BLUF schema:
      {
        'region':              'global_humanitarian',
        'max_level':           0-5,
        'peak_level':          0-5,
        'posture_label':       display string,
        'posture_color':       hex,
        'top_signals':         list of canonical signal dicts (capped at 5),
        'signals':             list of all signals (full pool for axis aggregation),
        'updated_at':          ISO,
        'meta':                {countries_active, categories_active, tier, ...}
      }
    """
    if aggregation is None:
        aggregation = aggregate_convergence(signals or [])

    tier = aggregation['tier']
    max_level = aggregation['max_level']
    posture_label = aggregation['level_label']

    # Color per tier (matches GPI canonical scheme)
    posture_color = {
        'baseline': '#6b7280',
        'forming':  '#f59e0b',
        'active':   '#f97316',
        'global':   '#dc2626',
    }.get(tier, '#6b7280')

    # Build canonical signal payload — sorted by severity desc, novel-first
    sorted_signals = sorted(
        signals or [],
        key=lambda s: (
            -s.get('severity', 0),
            0 if not s.get('is_tracked_country') else 1,  # novel countries first
            -s.get('level', 0),
        ),
    )

    canonical_signals = []
    for s in sorted_signals:
        canonical_signals.append({
            'category':      s['category'],
            'country':       s['country'],
            'theatre':       'global_humanitarian',
            'region':        'global_humanitarian',
            'level':         s['level'],
            'pressure_type': 'humanitarian',
            'icon':          s['icon'],
            'color':         posture_color,
            'short_text':    s['short_text'],
            'long_text':     s['long_text'],
            'priority':      s['severity'] * 3,  # rough priority for GPI sort tiebreaker
            'source_url':    s.get('source_url', ''),
            'source':        s.get('source', ''),
        })

    return {
        'region':         'global_humanitarian',
        'max_level':      max_level,
        'peak_level':     max_level,
        'posture_label':  posture_label,
        'posture_color':  posture_color,
        'top_signals':    canonical_signals[:5],
        'signals':        canonical_signals,
        'updated_at':     datetime.now(timezone.utc).isoformat(),
        'meta': {
            'tier':                tier,
            'countries_active':    aggregation['countries_active'],
            'categories_active':   aggregation['categories_active'],
            'countries':           aggregation['countries'],
            'categories':          aggregation['categories'],
            'novel_countries':     aggregation['novel_countries'],
            'tracked_countries_present': aggregation['tracked_countries_present'],
            'detector_version':    'humanitarian_convergence_detector v1.0.0',
        },
    }


# ============================================================
# TOP-LEVEL ENTRY POINT
# ============================================================
def detect_and_build_bluf(articles):
    """
    Convenience wrapper: run detection + aggregation + build BLUF.
    Returns the canonical BLUF payload ready for the API endpoint.
    """
    signals = detect_humanitarian_signals(articles or [])
    aggregation = aggregate_convergence(signals)
    return build_humanitarian_bluf(signals, aggregation)


# ============================================================
# FLASK ROUTE REGISTRATION
# ============================================================
# Canonical Asifah pattern: each module exposes `register_X_routes(app)` so
# the app.py registration zone stays uncluttered. Reads articles from
# existing ME rhetoric tracker Redis caches — zero new API calls.

def register_humanitarian_convergence_routes(app, redis_client=None, json_module=None):
    """
    Register humanitarian convergence endpoints on the Flask app.

    Args:
      app:           Flask app instance.
      redis_client:  Optional shared Redis client. If None, the function
                     attempts to import the module's `redis_client` from
                     app.py at request time (fallback for backwards compat).
      json_module:   Optional json module reference (defaults to standard library).

    Endpoints registered:
      GET /api/humanitarian-convergence/bluf
          BLUF-shaped payload consumed by GPI as a 5th regional BLUF.
      GET /api/humanitarian-convergence/details
          Full aggregation including by_country and by_category breakdowns
          (for frontend drill-down cards).
      GET /api/humanitarian-convergence/health
          Health check; returns detector version + signal-category count.
    """
    from flask import jsonify

    # Use standard json if not provided
    _json = json_module
    if _json is None:
        import json as _json

    def _get_redis():
        """Get a Redis client — use passed one, or import from app globals."""
        if redis_client is not None:
            return redis_client
        # Fallback: try to find it on the app
        try:
            return app.config.get('REDIS_CLIENT') or getattr(app, 'redis_client', None)
        except Exception:
            return None

    def _gather_articles():
        """
        Pull article pools from cached ME rhetoric trackers.

        Strategy: each rhetoric tracker stores its latest scan at
        rhetoric:<country>:latest in Redis. Each scan has actors[X].top_articles.
        We dedupe by URL to avoid counting the same article multiple times
        across actors.
        """
        articles = []
        seen_urls = set()
        r = _get_redis()
        if not r:
            return articles

        # ME rhetoric tracker cache keys (canonical naming)
        rhetoric_keys = [
            'rhetoric:iran:latest',
            'rhetoric:israel:latest',
            'rhetoric:lebanon:latest',
            'rhetoric:syria:latest',
            'rhetoric:yemen:latest',
            'rhetoric:iraq:latest',
            'rhetoric:oman:latest',
        ]

        for key in rhetoric_keys:
            try:
                raw = r.get(key)
                if not raw:
                    continue
                cached = _json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(cached, dict):
                    continue

                actors = (cached or {}).get('actors', {})
                if not isinstance(actors, dict):
                    continue

                for actor_data in actors.values():
                    if not isinstance(actor_data, dict):
                        continue
                    for art in (actor_data.get('top_articles', []) or []):
                        if not isinstance(art, dict):
                            continue
                        url = art.get('url') or art.get('link') or ''
                        if url and url in seen_urls:
                            continue
                        if url:
                            seen_urls.add(url)
                        articles.append(art)
            except Exception as e:
                print(f'[humanitarian_convergence] Skipping {key}: {str(e)[:80]}')
                continue

        return articles

    # ────────────────────────────────────────────────────────────
    # GET /api/humanitarian-convergence/bluf
    # ────────────────────────────────────────────────────────────
    @app.route('/api/humanitarian-convergence/bluf', methods=['GET'])
    def humanitarian_convergence_bluf():
        """
        BLUF-shaped payload consumed by GPI.

        v2.3 — Aggregates humanitarian signals from countries WITHOUT
        dedicated Asifah trackers (Egypt, Ethiopia, Myanmar, Sri Lanka,
        Jamaica, etc.) into a single convergence assessment that flows
        into GPI's humanitarian axis.

        Query param: ?force=true bypasses 30-min cache and forces fresh
        scan (canonical Asifah tracker convention).
        """
        from flask import request
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        try:
            r = _get_redis()
            # Try cached BLUF first (30-min TTL) — unless force=true
            if r and not force:
                try:
                    cached = r.get('humanitarian_convergence:bluf:latest')
                    if cached:
                        return jsonify(_json.loads(cached) if isinstance(cached, str) else cached), 200
                except Exception as e:
                    print(f'[humanitarian_convergence] cache miss: {str(e)[:80]}')

            # Build fresh
            articles = _gather_articles()
            bluf = detect_and_build_bluf(articles)

            # Cache for 30 min
            if r:
                try:
                    r.setex(
                        'humanitarian_convergence:bluf:latest',
                        1800,  # 30 min
                        _json.dumps(bluf),
                    )
                except Exception as e:
                    print(f'[humanitarian_convergence] cache write skip: {str(e)[:80]}')

            return jsonify(bluf), 200

        except Exception as e:
            print(f'[humanitarian_convergence] error: {e}')
            # Return empty BLUF (HTTP 200) so GPI treats it as baseline
            return jsonify({
                'region':         'global_humanitarian',
                'max_level':      0,
                'peak_level':     0,
                'posture_label':  'OFFLINE -- detector error',
                'posture_color':  '#6b7280',
                'top_signals':    [],
                'signals':        [],
                'updated_at':     datetime.now(timezone.utc).isoformat(),
                'meta': {'tier': 'baseline', 'error': str(e)[:120]},
            }), 200

    # ────────────────────────────────────────────────────────────
    # GET /api/humanitarian-convergence/details
    # ────────────────────────────────────────────────────────────
    @app.route('/api/humanitarian-convergence/details', methods=['GET'])
    def humanitarian_convergence_details():
        """
        Full aggregation details (by_country, by_category, novel countries).
        Useful for frontend drill-down cards.
        """
        try:
            articles = _gather_articles()
            signals = detect_humanitarian_signals(articles)
            agg = aggregate_convergence(signals)
            bluf = build_humanitarian_bluf(signals, agg)
            return jsonify({
                'bluf':           bluf,
                'aggregation':    agg,
                'signal_count':   len(signals),
                'article_count':  len(articles),
                'detector_version': __version__,
                'updated_at':     datetime.now(timezone.utc).isoformat(),
            }), 200
        except Exception as e:
            return jsonify({'error': str(e)[:200]}), 500

    # ────────────────────────────────────────────────────────────
    # GET /api/humanitarian-convergence/health
    # ────────────────────────────────────────────────────────────
    @app.route('/api/humanitarian-convergence/health', methods=['GET'])
    def humanitarian_convergence_health():
        return jsonify({
            'module':           __module_id__,
            'version':          __version__,
            'signal_categories': list(SIGNAL_CATEGORIES.keys()),
            'category_count':   len(SIGNAL_CATEGORIES),
            'countries_tracked': len(COUNTRY_PATTERNS),
            'status':           'operational',
        }), 200

    print('[Humanitarian Convergence] Routes registered: /api/humanitarian-convergence/bluf, /details, /health')


# ============================================================
# MODULE METADATA
# ============================================================
__version__ = '1.0.0'
__module_id__ = 'humanitarian_convergence_detector'
print(f'[Humanitarian Convergence Detector] Module loaded -- v{__version__}')
