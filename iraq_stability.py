"""
Iraq Stability Index v1.0.0
March 2026

Calculates a composite Iraq stability score (0-100) from:
  - Oil price (Brent crude — live via Yahoo Finance, same feed as Iran)
  - Iraq oil production & Basra terminal status (static, updated manually)
  - IQD/USD exchange rate & parallel market gap (static)
  - Governance status: PM, parliament, KRG dispute (static)
  - PMF/security situation (static + rhetoric cache)
  - Rhetoric penalty (live from Redis rhetoric_tracker_iraq cache)
  - Humanitarian drag (chronic baseline)

Scoring philosophy (base 50):
  Oil is the jugular — 90% of govt revenue. Basra = single point of failure.
  Governance is fragmented but functional. PMF = permanent wild card.
  Rhetoric tracker is the leading indicator for escalation.

Provides:
  /api/iraq/stability        — full stability response
  /api/iraq/stability/score  — score + risk level only (for front page card)
  /debug/iraq-stability      — component breakdown

Env vars (already set on ME backend):
  UPSTASH_REDIS_URL, UPSTASH_REDIS_TOKEN
"""

import os
import json
import requests
import threading
import time
from flask import request, jsonify
from datetime import datetime, timezone, timedelta

# ============================================
# CONFIGURATION
# ============================================

UPSTASH_URL   = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')
CACHE_KEY     = 'iraq_stability'
CACHE_TTL_HOURS = 4
REFRESH_INTERVAL_SECONDS = 4 * 3600

# ============================================
# REDIS HELPERS
# ============================================

def _redis_available():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)

def _redis_get(key):
    try:
        r = requests.get(
            f"{UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
            timeout=5
        )
        data = r.json()
        if data.get('result'):
            return json.loads(data['result'])
        return None
    except Exception as e:
        print(f"[Iraq Stability Redis] GET error: {str(e)[:100]}")
        return None

def _redis_set(key, value):
    try:
        r = requests.post(
            f"{UPSTASH_URL}",
            headers={"Authorization": f"Bearer {UPSTASH_TOKEN}",
                     "Content-Type": "application/json"},
            json=["SET", key, json.dumps(value)],
            timeout=5
        )
        return r.json().get('result') == 'OK'
    except Exception as e:
        print(f"[Iraq Stability Redis] SET error: {str(e)[:100]}")
        return False


# ============================================
# BRENT CRUDE OIL PRICE
# Same Yahoo Finance feed as iran_protests.py
# ============================================

def get_brent_oil_price():
    """Fetch current Brent crude oil price from Yahoo Finance (BZ=F)."""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/BZ=F"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()

        result = data.get("chart", {}).get("result", [])
        if not result:
            raise ValueError("No chart data returned")

        meta = result[0].get("meta", {})
        current_price  = meta.get("regularMarketPrice") or meta.get("previousClose")
        previous_price = meta.get("chartPreviousClose") or meta.get("previousClose")

        if not current_price:
            raise ValueError("No price in meta")

        price_change   = round(current_price - previous_price, 2) if previous_price else 0.0
        percent_change = round((price_change / previous_price) * 100, 2) if previous_price else 0.0

        if price_change > 0.01:
            arrow, trend = "↑", "up"
        elif price_change < -0.01:
            arrow, trend = "↓", "down"
        else:
            arrow, trend = "→", "flat"

        # Sparkline (last 90 days)
        sparkline_data = []
        timestamps = result[0].get("timestamp", [])
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        for ts, price in zip(timestamps[-90:], closes[-90:]):
            if price:
                sparkline_data.append({
                    "date": datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"),
                    "price": round(price, 2)
                })

        print(f"[Iraq Oil] Brent ${current_price} ({arrow}{abs(percent_change)}%)")
        return {
            "success": True,
            "current_price": round(current_price, 2),
            "price_change": price_change,
            "percent_change": percent_change,
            "arrow": arrow, "trend": trend,
            "timestamp": datetime.now().strftime("%Y-%m-%d"),
            "currency": "USD", "unit": "bbl",
            "source": "yahoo_finance",
            "sparkline": sparkline_data
        }
    except Exception as e:
        print(f"[Iraq Oil] Yahoo Finance error: {e} — using fallback")
        return {
            "success": False,
            "current_price": 103.75,
            "price_change": 0.0, "percent_change": 0.0,
            "arrow": "→", "trend": "flat",
            "timestamp": datetime.now().strftime("%Y-%m-%d"),
            "currency": "USD", "unit": "bbl",
            "source": "fallback",
            "sparkline": []
        }


# ============================================
# IRAQ OIL PRODUCTION & BASRA STATUS
# Static — updated manually from OPEC/EIA reports
# ============================================

def get_iraq_oil_production():
    """
    Iraq oil production status.
    Iraq is OPEC's #2 producer. Basra terminals handle ~95% of exports.
    OPEC quota: ~4.0 mbpd. Actual: ~4.2 mbpd (slight overproduction).
    """
    return {
        "production_bpd": 4200000,
        "production_mbpd": 4.2,
        "opec_quota_mbpd": 4.0,
        "quota_compliance": "over",  # over | compliant | under
        "production_date": "2026-02-01",
        "source": "OPEC Monthly Oil Market Report",
        "source_url": "https://www.opec.org/opec_web/en/publications/338.htm",

        # Basra export terminals — the single point of failure
        "basra_terminals": {
            "status": "operational",        # operational | degraded | suspended | attacked
            "status_emoji": "🟢",
            "status_text": "OPERATIONAL",
            "detail": "Basra Oil Terminal and Al-Amaya terminal operating normally. "
                      "~3.5 mbpd export capacity. No active disruption signals.",
            "pct_of_exports": 95,
            "threat_level": "elevated",     # normal | elevated | high | critical
            "threat_note": "Iran-US war increases risk of PMF/IRGC-directed attack on terminals. "
                           "Monitoring for sabotage signals.",
            "coords": [29.6833, 48.7833],
            "live_tracker_url": "https://www.marinetraffic.com/en/ais/home/centerx:48.8/centery:29.7/zoom:11"
        },

        # KRG northern oil — separate pipeline, separate dispute
        "krg_northern": {
            "status": "suspended",
            "status_emoji": "🔴",
            "status_text": "KIRKUK–CEYHAN PIPELINE SUSPENDED",
            "detail": "Kirkuk–Ceyhan pipeline suspended since March 2023 ICC arbitration ruling. "
                      "~450K bpd of northern exports offline. Baghdad–KRG revenue dispute unresolved.",
            "bpd_offline": 450000,
            "dispute_active": True,
            "source": "Reuters / Iraq Oil Report"
        },

        "government_revenue_oil_pct": 90,
        "note": "Iraq's fiscal survival depends on Basra terminal operations. "
                "A 30-day Basra shutdown would exhaust FX reserves within 60 days."
    }


# ============================================
# IQD / USD EXCHANGE RATE
# Static — updated manually
# Official rate: ~1,300 IQD/USD (CBl pegged)
# Parallel market: ~1,480-1,520 IQD/USD
# ============================================

def get_iqd_exchange_rate():
    """
    Iraq Dinar exchange rate.
    CBI official rate is pegged. Parallel market gap is the real stress signal.
    Gap > 15% = capital flight / sanctions pressure signal.
    """
    official_rate  = 1300.0   # CBI official peg
    parallel_rate  = 1470.0   # Parallel market (bazaar rate)
    gap_pct        = round(((parallel_rate - official_rate) / official_rate) * 100, 1)

    if gap_pct > 25:
        gap_status = "critical"
        gap_emoji  = "🔴"
        gap_label  = "SEVERE PARALLEL GAP"
    elif gap_pct > 15:
        gap_status = "elevated"
        gap_emoji  = "🟠"
        gap_label  = "ELEVATED PARALLEL GAP"
    elif gap_pct > 8:
        gap_status = "moderate"
        gap_emoji  = "🟡"
        gap_label  = "MODERATE PARALLEL GAP"
    else:
        gap_status = "normal"
        gap_emoji  = "🟢"
        gap_label  = "NORMAL RANGE"

    return {
        "official_rate":   official_rate,
        "parallel_rate":   parallel_rate,
        "gap_pct":         gap_pct,
        "gap_status":      gap_status,
        "gap_emoji":       gap_emoji,
        "gap_label":       gap_label,
        "as_of":           "2026-03-16",
        "source":          "CBI / Iraq bazaar reports",
        "source_url":      "https://cbi.iq/",
        "note": "CBI hard peg at 1,300. US sanctions on Iraq's dollar access "
                "(for Iran payments) drove parallel rate up in 2023–24. "
                "Current gap reflects residual pressure + war uncertainty."
    }


# ============================================
# GOVERNANCE STATUS
# Static — updated manually
# ============================================

def get_iraq_governance():
    """
    Iraq governance status.
    PM al-Sudani is functional but dependent on PMF political bloc support.
    Parliament quorum issues are chronic but not destabilizing.
    KRG relationship is the permanent tension point.
    """
    return {
        "prime_minister": {
            "name":        "Mohammed Shia' al-Sudani",
            "party":       "State of Law / Coordination Framework",
            "since":       "2022-10-27",
            "status":      "active",
            "status_emoji": "🟢",
            "days_in_office": (datetime.now(timezone.utc) - datetime(2022, 10, 27, tzinfo=timezone.utc)).days,
            "next_election": "2025-10-01",  # Scheduled, may slip
            "note": "Dependent on Iran-aligned PMF political blocs for parliamentary majority. "
                    "Walking tightrope between US and Iran pressure during active war."
        },
        "president": {
            "name":   "Abdul Latif Rashid",
            "party":  "Kurdish (PUK)",
            "since":  "2022-10-13",
            "status": "active",
            "status_emoji": "🟢"
        },
        "parliament": {
            "status":       "functional",
            "status_emoji": "🟡",
            "note": "Quorum issues chronic. PMF-aligned blocs hold blocking minority. "
                    "War pressure has temporarily unified factions against US strikes."
        },
        "krg_dispute": {
            "active":       True,
            "status_emoji": "🟠",
            "issues": [
                "Kirkuk–Ceyhan pipeline suspended since 2023 ICC ruling",
                "KRG budget share withheld by Baghdad",
                "Peshmerga integration into Iraqi security forces stalled",
                "Disputed territories (Sinjar, Kirkuk) authority unresolved"
            ],
            "note": "KRG–Baghdad relationship is structurally dysfunctional but "
                    "neither side wants full rupture. Iran-US war may accelerate US-KRG realignment."
        },
        "pmf_political": {
            "status":       "dominant",
            "status_emoji": "🔴",
            "note": "PMF/Hashd al-Shaabi has parallel state authority. "
                    "Kata'ib Hezbollah and Asa'ib Ahl al-Haq operate outside "
                    "government control while nominally under MoD. "
                    "Active attacks on US forces undermining al-Sudani's authority."
        },
        "as_of": "2026-03-16",
        "source": "Open source / think tank analysis"
    }


# ============================================
# RHETORIC PENALTY
# Live — reads from Iraq rhetoric tracker Redis cache
# ============================================

RHETORIC_PENALTY = {0: 0, 1: -2, 2: -5, 3: -10, 4: -18, 5: -25}

def get_rhetoric_penalty():
    """Pull Iraq rhetoric theatre level from Redis cache and return penalty."""
    try:
        from rhetoric_tracker_iraq import RHETORIC_CACHE_KEY as IRAQ_RHETORIC_KEY, _redis_get as _iraq_redis_get
        rhetoric_cache = _iraq_redis_get(IRAQ_RHETORIC_KEY)
        if rhetoric_cache:
            level = max(
                rhetoric_cache.get('pmf_level', 0),
                rhetoric_cache.get('iran_strike_level', 0),
                rhetoric_cache.get('us_base_level', 0),
                rhetoric_cache.get('kurdish_level', 0),
                rhetoric_cache.get('isis_level', 0),
            )
            penalty = RHETORIC_PENALTY.get(level, 0)
            print(f"[Iraq Stability] Rhetoric penalty: {penalty} (level {level})")
            return penalty, level
    except Exception as e:
        print(f"[Iraq Stability] Rhetoric penalty skipped: {e}")
    return 0, 0


# ============================================
# STABILITY SCORE CALCULATION
# ============================================

def calculate_iraq_stability(oil_data, production_data, iqd_data, governance_data):
    """
    Calculate Iraq stability score (0-100).

    Base: 50
    Oil price:          +5 to -12  (fiscal health signal)
    Basra terminals:    0 to -20   (catastrophic if disrupted)
    KRG pipeline:        -4        (chronic — already suspended)
    IQD parallel gap:   0 to -8   (capital flight signal)
    Governance/PMF:     -5 to -12  (structural fragmentation)
    Rhetoric penalty:   0 to -25   (leading indicator — live)
    Humanitarian drag:  -5         (chronic baseline — IDPs, services)
    War context bonus:  0          (no bonus — active conflict theatre)
    """
    base_score = 50
    components = {}

    # ── Oil price ──
    # Iraq break-even: ~$70/bbl. Below = fiscal stress. Above $90 = cushion.
    oil_impact = 0
    if oil_data and oil_data.get('success'):
        price = oil_data.get('current_price', 75)
        if price >= 90:
            oil_impact = 5     # Strong fiscal cushion
        elif price >= 75:
            oil_impact = 2     # Comfortable
        elif price >= 65:
            oil_impact = -3    # Below break-even pressure
        elif price >= 55:
            oil_impact = -8    # Fiscal stress
        else:
            oil_impact = -12   # Crisis territory
        components['oil_price_impact'] = oil_impact
        print(f"[Iraq Stability] Oil price impact: {oil_impact:+d} (${price}/bbl)")

    # ── Basra terminals ──
    basra_impact = 0
    if production_data:
        basra = production_data.get('basra_terminals', {})
        basra_status = basra.get('status', 'operational')
        if basra_status == 'attacked':
            basra_impact = -20
        elif basra_status == 'suspended':
            basra_impact = -15
        elif basra_status == 'degraded':
            basra_impact = -8
        else:
            basra_impact = 0   # Operational — no penalty
        components['basra_impact'] = basra_impact
        print(f"[Iraq Stability] Basra impact: {basra_impact:+d} ({basra_status})")

    # ── KRG pipeline (chronic -4) ──
    krg_impact = 0
    if production_data:
        krg = production_data.get('krg_northern', {})
        if krg.get('dispute_active'):
            krg_impact = -4
        components['krg_impact'] = krg_impact
        print(f"[Iraq Stability] KRG impact: {krg_impact:+d}")

    # ── IQD parallel gap ──
    iqd_impact = 0
    if iqd_data:
        gap_status = iqd_data.get('gap_status', 'normal')
        if gap_status == 'critical':
            iqd_impact = -8
        elif gap_status == 'elevated':
            iqd_impact = -5
        elif gap_status == 'moderate':
            iqd_impact = -3
        else:
            iqd_impact = 0
        components['iqd_impact'] = iqd_impact
        print(f"[Iraq Stability] IQD impact: {iqd_impact:+d} ({gap_status})")

    # ── Governance / PMF fragmentation ──
    # Structural penalty — PMF parallel state, KRG dysfunction, PM dependency on Iran blocs
    governance_impact = -8  # Baseline structural fragmentation
    if governance_data:
        pmf = governance_data.get('pmf_political', {})
        if pmf.get('status') == 'dominant':
            governance_impact = -10  # Active parallel state authority
        krg = governance_data.get('krg_dispute', {})
        if krg.get('active'):
            governance_impact -= 2   # Active dispute adds fragmentation
    components['governance_impact'] = governance_impact
    print(f"[Iraq Stability] Governance impact: {governance_impact:+d}")

    # ── Humanitarian drag (chronic) ──
    humanitarian_drag = -5
    components['humanitarian_drag'] = humanitarian_drag

    # ── Rhetoric penalty (live from cache) ──
    rhetoric_penalty, rhetoric_level = get_rhetoric_penalty()
    components['rhetoric_penalty'] = rhetoric_penalty
    components['rhetoric_level'] = rhetoric_level

    # ── Final score ──
    stability_score = (
        base_score
        + oil_impact
        + basra_impact
        + krg_impact
        + iqd_impact
        + governance_impact
        + humanitarian_drag
        + rhetoric_penalty
    )
    stability_score = max(0, min(100, int(stability_score)))

    # ── Risk level ──
    if stability_score >= 70:
        risk_level = "Stable"
        risk_color = "green"
    elif stability_score >= 50:
        risk_level = "Moderate Risk"
        risk_color = "yellow"
    elif stability_score >= 30:
        risk_level = "High Risk"
        risk_color = "orange"
    elif stability_score >= 15:
        risk_level = "Critical"
        risk_color = "red"
    else:
        risk_level = "Collapse Risk"
        risk_color = "darkred"

    # ── Trend ──
    trend = "stable"
    if rhetoric_level >= 4:
        trend = "worsening"
    elif basra_impact < -8:
        trend = "worsening"
    elif oil_data and oil_data.get('trend') == 'down' and oil_data.get('current_price', 75) < 70:
        trend = "worsening"
    elif rhetoric_level <= 1 and basra_impact == 0 and oil_impact >= 0:
        trend = "improving"

    print(f"[Iraq Stability] ✅ Score: {stability_score}/100 ({risk_level}) | "
          f"oil:{oil_impact:+d} basra:{basra_impact:+d} krg:{krg_impact:+d} "
          f"iqd:{iqd_impact:+d} gov:{governance_impact:+d} "
          f"hum:{humanitarian_drag:+d} rhetoric:{rhetoric_penalty:+d}")

    return {
        'score':          stability_score,
        'risk_level':     risk_level,
        'risk_color':     risk_color,
        'trend':          trend,
        'components':     components,
        'component_labels': {
            'base':               50,
            'oil_price':          oil_impact,
            'basra_terminals':    basra_impact,
            'krg_pipeline':       krg_impact,
            'iqd_parallel_gap':   iqd_impact,
            'governance_pmf':     governance_impact,
            'humanitarian':       humanitarian_drag,
            'rhetoric':           rhetoric_penalty,
        }
    }


# ============================================
# MAIN DATA FETCH
# ============================================

def _fetch_all_stability():
    """Fetch all Iraq stability data and build full response."""
    print("[Iraq Stability] Fetching all data sources...")

    oil_data        = get_brent_oil_price()
    production_data = get_iraq_oil_production()
    iqd_data        = get_iqd_exchange_rate()
    governance_data = get_iraq_governance()
    stability       = calculate_iraq_stability(oil_data, production_data, iqd_data, governance_data)

    result = {
        'success':        True,
        'fetched_at':     datetime.now(timezone.utc).isoformat(),
        'from_cache':     False,
        'country':        'Iraq',

        # Core score
        'stability':      stability,

        # Economic data
        'oil_price':      oil_data,
        'oil_production': production_data,
        'iqd_rate':       iqd_data,

        # Governance
        'governance':     governance_data,

        # Convenience top-level fields for frontend
        'score':          stability['score'],
        'risk_level':     stability['risk_level'],
        'risk_color':     stability['risk_color'],
        'trend':          stability['trend'],
    }

    if _redis_available():
        _redis_set(CACHE_KEY, result)
        print(f"[Iraq Stability] ✅ Cached to Redis")

    return result


def get_stability_data(force_refresh=False):
    """Get Iraq stability data — Redis-first with 4-hour TTL."""
    if not force_refresh and _redis_available():
        cached = _redis_get(CACHE_KEY)
        if cached:
            try:
                age_hours = (
                    datetime.now(timezone.utc) -
                    datetime.fromisoformat(cached.get('fetched_at', '').replace('Z', '+00:00'))
                ).total_seconds() / 3600
                if age_hours < CACHE_TTL_HOURS:
                    print(f"[Iraq Stability] ✅ Serving cache ({age_hours:.1f}h old)")
                    cached['from_cache'] = True
                    cached['cache_age_hours'] = round(age_hours, 1)
                    return cached
            except Exception:
                pass

    return _fetch_all_stability()


# ============================================
# BACKGROUND REFRESH THREAD
# ============================================

def _background_refresh():
    print("[Iraq Stability] Background refresh thread started (4h cycle)")
    time.sleep(120)  # Boot delay
    while True:
        try:
            print("[Iraq Stability] Running background refresh...")
            _fetch_all_stability()
            print("[Iraq Stability] Background refresh complete")
        except Exception as e:
            print(f"[Iraq Stability] Background refresh error: {str(e)[:200]}")
        time.sleep(REFRESH_INTERVAL_SECONDS)


# ============================================
# REGISTER FLASK ENDPOINTS
# ============================================

def register_iraq_stability_endpoints(app):
    """Register Iraq stability endpoints on the Flask app."""

    @app.route('/api/iraq/stability', methods=['GET'])
    def api_iraq_stability():
        """
        Full Iraq stability index — score, oil, IQD, governance, rhetoric.
        ?force=true bypasses Redis cache.
        """
        force = request.args.get('force', 'false').lower() == 'true'
        try:
            data = get_stability_data(force_refresh=force)
            return jsonify(data)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 200

    @app.route('/api/iraq/stability/score', methods=['GET'])
    def api_iraq_stability_score():
        """
        Lightweight score endpoint — for front page card / rhetoric tracker badge.
        Returns score, risk_level, risk_color, trend only.
        """
        try:
            data = get_stability_data(force_refresh=False)
            return jsonify({
                'success':    True,
                'score':      data.get('score'),
                'risk_level': data.get('risk_level'),
                'risk_color': data.get('risk_color'),
                'trend':      data.get('trend'),
                'from_cache': data.get('from_cache', False),
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)[:200]}), 200

    @app.route('/debug/iraq-stability', methods=['GET'])
    def debug_iraq_stability():
        """Debug: run stability calculation and return component breakdown."""
        oil        = get_brent_oil_price()
        production = get_iraq_oil_production()
        iqd        = get_iqd_exchange_rate()
        governance = get_iraq_governance()
        stability  = calculate_iraq_stability(oil, production, iqd, governance)
        return jsonify({
            'score':           stability['score'],
            'risk_level':      stability['risk_level'],
            'component_labels': stability['component_labels'],
            'oil_price':       oil.get('current_price'),
            'basra_status':    production['basra_terminals']['status'],
            'iqd_gap_pct':     iqd['gap_pct'],
            'rhetoric_level':  stability['components'].get('rhetoric_level', 0),
        })

    # Start background refresh thread
    bg = threading.Thread(target=_background_refresh, daemon=True)
    bg.start()

    print("[Iraq Stability] ✅ Routes registered: "
          "/api/iraq/stability, /api/iraq/stability/score, /debug/iraq-stability")
