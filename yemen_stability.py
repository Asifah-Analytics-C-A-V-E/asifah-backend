"""
Yemen Stability Module — Asifah Analytics
v1.0.0 — March 2026

Covers:
- Houthi control index
- Red Sea / Bab el-Mandeb shipping status
- Coalition activity (KSA/UAE/US)
- Somaliland/Horn of Africa watch (sub-card)
- Humanitarian indicators
- Refugee/displacement flows
- Government legitimacy (PLC vs Houthi parallel govt)

Registers on ME backend (asifah-backend.onrender.com)
Endpoints:
  GET /api/yemen/stability
  GET /api/yemen/redSea
  GET /api/yemen/humanitarian
"""

import os
import json
import threading
import time
import requests
from datetime import datetime, timezone, timedelta
from flask import jsonify, request

# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWS_API_KEY') or os.environ.get('NEWSAPI_KEY')

YEMEN_CACHE_KEY     = 'yemen_stability_cache'
YEMEN_CACHE_TTL     = 4 * 3600   # 4 hours

_yemen_scan_running = False
_yemen_scan_lock    = threading.Lock()


# ============================================
# REDIS HELPERS
# ============================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5
        )
        data = resp.json()
        if data.get('result'):
            return json.loads(data['result'])
    except Exception as e:
        print(f"[Yemen Redis] GET error: {e}")
    return None


def _redis_set(key, value, ttl=YEMEN_CACHE_TTL):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        payload = json.dumps(value, default=str)
        resp = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{key}",
            headers={
                "Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                "Content-Type": "application/json"
            },
            data=payload,
            params={"EX": ttl},
            timeout=5
        )
        result = resp.json()
        if result.get('result') == 'OK':
            print(f"[Yemen Redis] ✅ Saved key: {key}")
            return True
    except Exception as e:
        print(f"[Yemen Redis] SET error: {e}")
    return False


# ============================================
# STATIC GOVERNMENT STATUS
# ============================================
def get_yemen_government_status():
    """Yemen's fragmented government landscape — updated Mar 2026"""
    return {
        "houthi_ansar_allah": {
            "name": "Abdul-Malik al-Houthi",
            "title": "Supreme Leader, Ansar Allah (Houthis)",
            "since": "2004",
            "note": "Controls Sana'a, Sa'dah, Hodeidah, and ~70% of Yemen's population",
            "status": "ACTIVE",
            "status_color": "red",
            "status_detail": "Declared 'escalation phase' following US-Iran war. Firing ballistic missiles at Israel and threatening Bab el-Mandeb closure.",
            "territory": "North Yemen incl. Sana'a, Hodeidah, Sa'dah, Hajjah, Dhamar"
        },
        "plc_chair": {
            "name": "Rashad al-Alimi",
            "title": "Chair, Presidential Leadership Council (PLC)",
            "since": "2022-04-07",
            "note": "Internationally recognized government; based in Aden",
            "status": "ACTIVE",
            "status_color": "yellow",
            "status_detail": "PLC authority limited to south/east Yemen. Dependent on KSA financial support. Internal divisions with STC remain.",
            "territory": "South Yemen incl. Aden, Hadramawt, Marib (contested)"
        },
        "stc_leader": {
            "name": "Aidarous al-Zubaidi",
            "title": "President, Southern Transitional Council (STC)",
            "since": "2017",
            "note": "UAE-backed separatist movement seeking independent South Yemen",
            "status": "ACTIVE",
            "status_color": "orange",
            "status_detail": "STC controls much of Aden and southern coast. Nominal PLC partner but seeks full southern independence.",
            "territory": "Aden, Lahj, Abyan, Socotra"
        },
        "ksa_envoy": {
            "name": "Saudi Arabia",
            "title": "Coalition Leader / Key Patron",
            "since": "2015",
            "note": "Led military intervention; primary financial backer of PLC",
            "status": "REDUCED ENGAGEMENT",
            "status_color": "orange",
            "status_detail": "KSA-Houthi back-channel talks ongoing since 2023 Saudi-Iran normalization. Airstrike tempo significantly reduced. Focus shifted to Iran war.",
        },
        "regime_summary": {
            "overall": "FRAGMENTED — HOUTHI ESCALATION",
            "color": "red",
            "summary": "No unified government. Houthis control population centers and are actively escalating. PLC/KSA coalition in reduced operational tempo. US-Iran war has dramatically elevated Houthi threat posture.",
            "last_updated": "2026-03-14"
        }
    }


# ============================================
# STATIC HUMANITARIAN DATA
# ============================================
def get_yemen_humanitarian():
    """Static humanitarian data — updated from UN/OCHA reports"""
    return {
        "population_in_need": {
            "value": 21600000,
            "display": "21.6M",
            "pct_of_population": 67,
            "source": "OCHA Yemen Humanitarian Update 2026",
            "source_url": "https://www.unocha.org/yemen"
        },
        "idps": {
            "value": 4500000,
            "display": "4.5M",
            "note": "Internally displaced persons since 2015",
            "source": "IOM DTM Yemen",
            "source_url": "https://dtm.iom.int/yemen"
        },
        "food_insecurity": {
            "value": 17400000,
            "display": "17.4M",
            "phase": "IPC Phase 3+",
            "note": "Crisis or worse food insecurity",
            "source": "IPC Yemen 2026",
            "source_url": "https://www.ipcinfo.org"
        },
        "cholera_cases": {
            "value": 800000,
            "display": "800K+",
            "note": "Cumulative suspected cases since 2016 outbreak",
            "source": "WHO Yemen",
            "source_url": "https://www.who.int/emergencies/crises/yem/en/"
        },
        "hodeidah_port": {
            "status": "OPERATIONAL (REDUCED)",
            "note": "~70% of Yemen's food imports transit Hodeidah. Port capacity constrained by conflict damage and inspection regime.",
            "status_color": "orange"
        },
        "refugee_flows": {
            "in_ksa": {"estimate": 500000, "note": "Yemenis in Saudi Arabia (many undocumented)"},
            "in_oman": {"estimate": 90000, "note": "Yemenis in Oman; significant in Dhofar region"},
            "in_djibouti": {"estimate": 30000, "note": "Yemenis in Djibouti; used as transit point"},
            "in_somalia": {"estimate": 25000, "note": "Yemenis in Somalia — ironic reversal of pre-war flows"},
            "source": "UNHCR Yemen Regional Overview 2026",
            "source_url": "https://www.unhcr.org/yemen.html"
        },
        "funding_gap": {
            "required_usd_billions": 4.3,
            "received_pct": 43,
            "note": "UN Humanitarian Response Plan consistently underfunded",
            "source": "OCHA FTS 2026"
        },
        "last_updated": "2026-03-14"
    }


# ============================================
# ARTICLE FETCHING
# ============================================
def fetch_yemen_articles(days=7):
    """Fetch Yemen/Houthi articles from Google News RSS"""
    queries = [
        ("Yemen Houthi", "en"),
        ("Red Sea attack Houthi", "en"),
        ("Bab el-Mandeb", "en"),
        ("Yemen war 2026", "en"),
        ("Ansar Allah missile", "en"),
        ("Yemen KSA coalition", "en"),
        ("Somaliland Israel", "en"),
        ("اليمن الحوثيون", "ar"),
        ("البحر الأحمر هجوم", "ar"),
    ]

    articles = []
    since = datetime.now(timezone.utc) - timedelta(days=days)

    for query, lang in queries:
        try:
            url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl={lang}&gl=US&ceid=US:{lang}"
            resp = requests.get(url, timeout=10,
                                headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)
            for item in root.findall('.//item'):
                title = item.findtext('title', '')
                link  = item.findtext('link', '')
                pub   = item.findtext('pubDate', '')
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt = parsedate_to_datetime(pub)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    if pub_dt < since:
                        continue
                    pub_str = pub_dt.isoformat()
                except Exception:
                    pub_str = pub

                articles.append({
                    'title': title,
                    'url': link,
                    'published': pub_str,
                    'query': query,
                    'language': lang,
                    'source': 'Google News RSS'
                })
        except Exception as e:
            print(f"[Yemen Articles] Error for '{query}': {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for a in articles:
        if a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)

    print(f"[Yemen] Fetched {len(unique)} unique articles")
    return unique


# ============================================
# RED SEA / BAB EL-MANDEB STATUS
# ============================================
RED_SEA_ATTACK_KEYWORDS = [
    'houthi attack', 'houthi strike', 'houthi missile', 'houthi drone',
    'red sea attack', 'red sea strike', 'vessel attacked', 'ship attacked',
    'tanker struck', 'cargo ship hit', 'bab el-mandeb', 'bab-el-mandeb',
    'gulf of aden attack', 'strait closure', 'houthi naval',
    'anti-ship missile', 'houthi fires', 'houthi targets ship',
]

RED_SEA_CLOSURE_KEYWORDS = [
    'bab el-mandeb closed', 'red sea closed', 'strait closed',
    'shipping suspended', 'rerouting suez', 'cape of good hope reroute',
    'red sea blocked', 'commercial shipping halted',
]

SOMALILAND_WATCH_KEYWORDS = [
    'somaliland israel', 'israel somaliland', 'somaliland base',
    'berbera port israel', 'israel horn of africa', 'us somaliland',
    'american troops somaliland', 'idf somaliland', 'socotra israel',
    'perim island', 'bab el-mandeb island', 'israeli forces somalia',
    'somaliland military', 'us base djibouti expansion',
    'camp lemonnier', 'horn of africa deployment',
]

KSA_UAE_KEYWORDS = [
    'saudi houthi', 'ksa airstrike yemen', 'saudi coalition yemen',
    'uae houthi', 'uae yemen', 'arab coalition yemen',
    'saudi houthi talks', 'ceasefire yemen', 'ksa houthi deal',
    'yemen peace talks', 'houthi saudi negotiations',
]


def scan_red_sea_status(articles):
    """Analyze articles for Red Sea/Bab el-Mandeb threat level"""
    attack_count = 0
    closure_signals = 0
    somaliland_signals = 0
    ksa_signals = 0
    attack_articles = []
    somaliland_articles = []
    ksa_articles = []

    for a in articles:
        text = f"{a.get('title','')} {a.get('query','')}".lower()

        for kw in RED_SEA_ATTACK_KEYWORDS:
            if kw in text:
                attack_count += 1
                attack_articles.append(a)
                break

        for kw in RED_SEA_CLOSURE_KEYWORDS:
            if kw in text:
                closure_signals += 1
                break

        for kw in SOMALILAND_WATCH_KEYWORDS:
            if kw in text:
                somaliland_signals += 1
                somaliland_articles.append(a)
                break

        for kw in KSA_UAE_KEYWORDS:
            if kw in text:
                ksa_signals += 1
                ksa_articles.append(a)
                break

    # Determine status
    if closure_signals >= 2:
        status = 'severely_restricted'
        status_text = 'SEVERELY RESTRICTED'
        emoji = '🔴'
        color = 'red'
    elif attack_count >= 5:
        status = 'active_attacks'
        status_text = 'ACTIVE ATTACKS'
        emoji = '🟠'
        color = 'orange'
    elif attack_count >= 2:
        status = 'elevated'
        status_text = 'ELEVATED THREAT'
        emoji = '🟡'
        color = 'yellow'
    else:
        status = 'monitoring'
        status_text = 'MONITORING'
        emoji = '🟢'
        color = 'green'

    # Somaliland alert level
    if somaliland_signals >= 3:
        somaliland_alert = 'HIGH'
        somaliland_color = 'red'
    elif somaliland_signals >= 1:
        somaliland_alert = 'ELEVATED'
        somaliland_color = 'orange'
    else:
        somaliland_alert = 'BASELINE'
        somaliland_color = 'green'

    # KSA/UAE engagement level
    if ksa_signals >= 5:
        coalition_status = 'ACTIVE'
        coalition_color = 'orange'
    elif ksa_signals >= 2:
        coalition_status = 'MONITORING'
        coalition_color = 'yellow'
    else:
        coalition_status = 'REDUCED'
        coalition_color = 'green'

    return {
        'status': status,
        'status_text': status_text,
        'emoji': emoji,
        'color': color,
        'attack_signals': attack_count,
        'closure_signals': closure_signals,
        'recent_articles': attack_articles[:5],
        'key_facts': {
            'global_trade_share': '~10% of global trade transits Bab el-Mandeb',
            'normal_daily_vessels': '~50-60 vessels/day',
            'suez_link': 'Closure forces Cape of Good Hope reroute (+14 days, +$1M/voyage)',
        },
        'live_tracker_url': 'https://www.marinetraffic.com/en/ais/home/centerx:43.4/centery:12.6/zoom:8',
        # Sub-card: Somaliland/Horn of Africa Watch
        'somaliland_watch': {
            'alert_level': somaliland_alert,
            'color': somaliland_color,
            'signals': somaliland_signals,
            'note': 'Monitoring Israeli/US presence signals in Somaliland, Socotra, Perim Island — potential ground operation precursors',
            'key_indicators': [
                'Israeli recognition of Somaliland (Jan 2026) — basing rights implied',
                'Berbera port (Somaliland) — strategic for Red Sea access',
                'Socotra Island — Yemeni territory, UAE-administered',
                'Perim Island — controls Bab el-Mandeb narrows',
            ],
            'recent_articles': somaliland_articles[:3],
            'last_updated': datetime.now(timezone.utc).isoformat()
        },
        # Sub-card: Coalition Activity
        'coalition_activity': {
            'status': coalition_status,
            'color': coalition_color,
            'signals': ksa_signals,
            'ksa_posture': 'Reduced — back-channel talks with Houthis ongoing',
            'uae_posture': 'Minimal direct engagement; STC support continues',
            'us_posture': 'Active — CENTCOM strikes on Houthi targets; USS Dwight Eisenhower CSG in region',
            'recent_articles': ksa_articles[:3],
        }
    }


# ============================================
# HOUTHI CONTROL INDEX
# ============================================
HOUTHI_ESCALATION_KEYWORDS = [
    'houthi missile launch', 'houthi fires missile', 'houthi drone attack',
    'ansar allah attack', 'houthi targets', 'houthi strikes',
    'houthi escalat', 'houthi threatens', 'houthi warns',
    'houthi ballistic', 'houthi cruise missile',
]

HOUTHI_DEESCALATION_KEYWORDS = [
    'houthi ceasefire', 'houthi pause', 'houthi halt',
    'houthi stops', 'houthi agrees', 'houthi deal',
    'yemen peace', 'houthi negotiations', 'houthi talks',
]


def scan_houthi_activity(articles):
    """Score Houthi escalation level from articles"""
    escalation_count = 0
    deescalation_count = 0
    escalation_articles = []

    for a in articles:
        text = f"{a.get('title','')}".lower()
        for kw in HOUTHI_ESCALATION_KEYWORDS:
            if kw in text:
                escalation_count += 1
                escalation_articles.append(a)
                break
        for kw in HOUTHI_DEESCALATION_KEYWORDS:
            if kw in text:
                deescalation_count += 1
                break

    # Score 0-100 (100 = maximum escalation)
    score = min(100, escalation_count * 8)
    score = max(0, score - deescalation_count * 5)

    if score >= 70:
        level = 'MAXIMUM ESCALATION'
        color = 'red'
    elif score >= 45:
        level = 'HIGH ESCALATION'
        color = 'orange'
    elif score >= 20:
        level = 'ELEVATED'
        color = 'yellow'
    else:
        level = 'BASELINE'
        color = 'green'

    return {
        'escalation_score': score,
        'level': level,
        'color': color,
        'escalation_signals': escalation_count,
        'deescalation_signals': deescalation_count,
        'recent_articles': escalation_articles[:5],
        'territory_held': [
            'Sana\'a (capital)',
            'Hodeidah (port)',
            'Sa\'dah (stronghold)',
            'Hajjah', 'Amran', 'Dhamar', 'Ibb',
            'Parts of Marib (contested)'
        ],
        'population_controlled_pct': 70,
        'parallel_govt': {
            'ministries': True,
            'courts': True,
            'taxation': True,
            'central_bank': 'Disputed — Houthi CBY in Sana\'a vs PLC CBY in Aden',
        }
    }


# ============================================
# STABILITY SCORE
# ============================================
def calculate_yemen_stability(articles, red_sea, houthi, humanitarian):
    """Calculate Yemen stability score 0-100 (100 = most stable)"""
    score = 50  # baseline

    # Houthi escalation penalty
    houthi_penalty = (houthi['escalation_score'] / 100) * 25
    score -= houthi_penalty

    # Red Sea status penalty
    red_sea_penalties = {
        'severely_restricted': 20,
        'active_attacks': 15,
        'elevated': 8,
        'monitoring': 0
    }
    score -= red_sea_penalties.get(red_sea['status'], 0)

    # Humanitarian drag
    score -= 15  # Yemen is chronically at worst-in-world level

    # Somaliland watch bonus/penalty
    if red_sea['somaliland_watch']['alert_level'] == 'HIGH':
        score -= 10
    elif red_sea['somaliland_watch']['alert_level'] == 'ELEVATED':
        score -= 5

    score = max(0, min(100, score))

    if score >= 70:
        risk = 'Moderate Risk'
        risk_color = 'yellow'
    elif score >= 40:
        risk = 'High Risk'
        risk_color = 'orange'
    else:
        risk = 'Critical Risk'
        risk_color = 'red'

    return {
        'score': round(score),
        'risk_level': risk,
        'risk_color': risk_color,
        'components': {
            'houthi_escalation': round(houthi_penalty),
            'red_sea_status': red_sea_penalties.get(red_sea['status'], 0),
            'humanitarian_drag': 15,
            'somaliland_watch': 10 if red_sea['somaliland_watch']['alert_level'] == 'HIGH' else 5 if red_sea['somaliland_watch']['alert_level'] == 'ELEVATED' else 0,
        }
    }


# ============================================
# MAIN SCAN
# ============================================
def run_yemen_scan(days=7):
    """Full Yemen stability scan"""
    print(f"[Yemen] Starting scan ({days}-day window)...")

    articles = fetch_yemen_articles(days)
    red_sea  = scan_red_sea_status(articles)
    houthi   = scan_houthi_activity(articles)
    govt     = get_yemen_government_status()
    humanitarian = get_yemen_humanitarian()
    stability = calculate_yemen_stability(articles, red_sea, houthi, humanitarian)

    result = {
        'success': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_articles': len(articles),
        'stability': stability,
        'government': govt,
        'houthi_activity': houthi,
        'red_sea': red_sea,
        'humanitarian': humanitarian,
        'articles_en': [a for a in articles if a.get('language') == 'en'][:20],
        'articles_ar': [a for a in articles if a.get('language') == 'ar'][:10],
        'version': '1.0.0-yemen'
    }

    _redis_set(YEMEN_CACHE_KEY, result)
    print(f"[Yemen] ✅ Scan complete. Stability: {stability['score']}/100 ({stability['risk_level']})")
    return result


def _background_yemen_scan():
    """Background scan wrapper"""
    global _yemen_scan_running
    try:
        run_yemen_scan()
    except Exception as e:
        print(f"[Yemen] Background scan error: {e}")
    finally:
        with _yemen_scan_lock:
            _yemen_scan_running = False


# ============================================
# ROUTE REGISTRATION
# ============================================
def register_yemen_routes(app):
    """Register Yemen endpoints on the ME Flask app"""

    @app.route('/api/yemen/stability', methods=['GET'])
    def yemen_stability():
        force = request.args.get('force', 'false').lower() == 'true'
        global _yemen_scan_running

        if not force:
            cached = _redis_get(YEMEN_CACHE_KEY)
            if cached and cached.get('timestamp'):
                try:
                    age = (datetime.now(timezone.utc) -
                           datetime.fromisoformat(cached['timestamp'])).total_seconds()
                    if age < YEMEN_CACHE_TTL:
                        cached['cached'] = True
                        cached['cache_age_minutes'] = round(age / 60, 1)
                        print(f"[Yemen] ✅ Serving cache ({round(age/60)}m old)")
                        return jsonify(cached)
                except Exception:
                    pass

            # Cache miss — trigger background scan, return skeleton
            with _yemen_scan_lock:
                if not _yemen_scan_running:
                    _yemen_scan_running = True
                    t = threading.Thread(target=_background_yemen_scan, daemon=True)
                    t.start()
                    print("[Yemen] 🔄 Background scan triggered")

            # Return skeleton while scan runs
            return jsonify({
                'success': True,
                'cached': False,
                'scan_in_progress': True,
                'message': 'Yemen stability scan in progress. Refresh in 60-90 seconds.',
                'government': get_yemen_government_status(),
                'humanitarian': get_yemen_humanitarian(),
                'stability': {'score': 0, 'risk_level': 'Scanning...', 'risk_color': 'gray'},
                'houthi_activity': {'escalation_score': 0, 'level': 'Scanning...'},
                'red_sea': {'status': 'unknown', 'status_text': 'SCANNING...', 'emoji': '⚪'},
                'version': '1.0.0-yemen'
            })

        # Force refresh
        result = run_yemen_scan()
        return jsonify(result)

    @app.route('/api/yemen/redSea', methods=['GET'])
    def yemen_red_sea():
        cached = _redis_get(YEMEN_CACHE_KEY)
        if cached and cached.get('red_sea'):
            return jsonify(cached['red_sea'])
        articles = fetch_yemen_articles(days=7)
        return jsonify(scan_red_sea_status(articles))

    @app.route('/api/yemen/humanitarian', methods=['GET'])
    def yemen_humanitarian():
        return jsonify(get_yemen_humanitarian())

    print("[Yemen] ✅ Routes registered: /api/yemen/stability, /api/yemen/redSea, /api/yemen/humanitarian")
