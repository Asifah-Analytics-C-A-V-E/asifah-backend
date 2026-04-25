"""
Asifah Analytics -- Oman Rhetoric & Influence Tracker
ME Backend Module
v1.0 - April 2026

Oman Rhetoric Tracker -- DUAL-AXIS Stability Anchor Model

Oman is structurally different from every other tracker we've built:
  - It is a stable police state, but a benign one
  - Primary analytical interest is INFLUENCE (mediation, convening) not just instability
  - Vulnerability surfaces: succession architecture, Iran/Houthi targeting of Salalah/Duqm,
    Yemen border (Dhofar), Baloch spillover from Pakistan, oil price exposure
  - Cross-theater diplomatic node: hosts US-Iran back-channel, Yemen mediation,
    Hamas indirect contacts. When Oman is mediating, Iran tracker should de-escalate.

ANALYTICAL FRAME (3 questions answered every scan):

  1. THREAT VECTOR: Is Oman facing genuine destabilization?
     - Sultan Haitham health / public absence patterns
     - Iran or Houthi targeting Salalah container port or Duqm logistics
     - Yemen border (Dhofar) refugee or kinetic spillover
     - Baloch unrest spillover from Pakistan
     - Internal security crackdowns (low baseline, watch for change)

  2. INFLUENCE VECTOR: Is Oman successfully exercising soft power?
     - Iran-US back-channel activation (Witkoff in Muscat, Tehran envoys)
     - Yemen mediation (Houthi hostage releases via Oman)
     - Hamas indirect contacts (Doha-Muscat axis)
     - GCC convening role
     - Hosting heads of state, summits, dialogues

  3. SUCCESSION WATCH: Is the dynastic transition architecture healthy?
     - Sultan public appearance frequency
     - Theyazin bin Haitham (heir apparent) profile elevation
     - Asad bin Tariq (cousin, alternative dynastic figure) mentions
     - Royal decree volume / silence patterns

ACTORS (6) -- composite scoring across two vectors:

  THREAT VECTOR (0-5, higher = more concern):
    omani_regime              -- Sultan Haitham, Diwan, MOFA -- regime stress signals
    omani_security            -- Royal Oman Police, ISS -- internal security posture
    external_threats_inbound  -- Iran/Houthi targeting, Yemen spillover, Baloch
    succession_watch          -- Sultan health, heir profile, dynastic stability

  INFLUENCE VECTOR (0-5, higher = more diplomatic activity):
    mediation_activity        -- Iran-US channel, Yemen mediation, Hamas indirect
    regional_diplomatic_hub   -- GCC convening, summits, Gulf-China-India triangulation

DISPLAY LOGIC:
  if threat_level >= 3:        BANNER = THREAT MODE     (red/orange)
  elif influence_level >= 3:   BANNER = INFLUENCE MODE  (purple — diplomatic activity)
  elif threat_level >= 1:      BANNER = MONITORING      (blue)
  else:                        BANNER = QUIET STABLE    (green)

REDIS KEYS:
  Cache:         rhetoric:oman:latest
  History:       rhetoric:oman:history
  Cross-theater: rhetoric:crosstheater:fingerprints (READS + WRITES)
  Summary:       rhetoric:oman:summary

CROSS-THEATER ARCHITECTURE:
  READS from:
    iran:salalah_targeted        -> external_threats_inbound boost
    iran:duqm_logistics_active   -> external_threats_inbound boost
    iran:oman_diplomatic_active  -> mediation_activity boost (Oman IS the channel)
    yemen:dhofar_refugee_pressure -> external_threats_inbound (graceful fallback if absent)
    pakistan:balochistan_unrest  -> external_threats_inbound (graceful fallback)
    zanzibar:unrest              -> succession_watch boost (placeholder, future Africa)

  WRITES:
    oman.threat_level
    oman.influence_level
    oman.mediation_active        (boolean — Iran tracker reads this as de-escalator)
    oman.salalah_under_threat    (boolean — emits to global)
    oman.succession_watch_active (boolean — flagged for ME regional risk)

ENDPOINTS:
  GET /api/rhetoric/oman           -- full scan
  GET /api/rhetoric/oman/summary   -- compact summary
  GET /api/rhetoric/oman/history   -- 12-week trail

SOURCE STRATEGY (per Rachel's directive — go broad):
  Primary RSS (English):    Reuters Middle East, Al Jazeera, Times of Oman EN, Muscat Daily
  Arabic RSS:               Al Mayadeen, Al-Manar (axis perspective on Oman),
                            Al Jazeera Arabic
  Iranian sources:          Iran International (English), Tasnim (English),
                            Press TV (Iranian state on Oman)
  GDELT:                    English, Arabic, Persian, Hebrew (4 languages)
  Brave Search fallback:    English + Arabic + Persian + Hebrew (multi-lang)

COPYRIGHT 2025-2026 Asifah Analytics. All rights reserved.
"""

import os
import json
import threading
import time
import requests
import xml.etree.ElementTree as ET
import urllib.parse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from flask import jsonify, request

# Signal interpreter (Red Lines + So What)
try:
    from oman_signal_interpreter import (
        check_red_lines,
        build_so_what,
        build_historical_matches,
    )
    _INTERPRETER_AVAILABLE = True
except ImportError as e:
    print(f"[Oman Rhetoric] WARNING: oman_signal_interpreter not available ({e})")
    _INTERPRETER_AVAILABLE = False

# ── v2.4: Brave Search (multi-language fallback) ──
# Imports the Brave fetcher from app.py (the ME backend's main module).
# Fires when GDELT+RSS underperform. Critical for Arabic/Persian coverage of
# Iran rhetoric about Salalah and Persian-language IRGC commentary on Oman.
try:
    from app import fetch_brave_news as _fetch_brave
    _BRAVE_AVAILABLE = True
    print("[Oman Rhetoric] ✅ Brave Search module loaded (multi-language)")
except ImportError as e:
    print(f"[Oman Rhetoric] WARNING: Brave fetch not available from app ({e})")
    _fetch_brave = None
    _BRAVE_AVAILABLE = False


# ============================================
# CONFIG
# ============================================
UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL') or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')
NEWSAPI_KEY         = os.environ.get('NEWSAPI_KEY')
GDELT_BASE_URL      = 'https://api.gdeltproject.org/api/v2/doc/doc'

RHETORIC_CACHE_KEY  = 'rhetoric:oman:latest'
HISTORY_KEY         = 'rhetoric:oman:history'
SUMMARY_KEY         = 'rhetoric:oman:summary'
CROSSTHEATER_KEY    = 'rhetoric:crosstheater:fingerprints'

SCAN_INTERVAL_HOURS = 12
HISTORY_CAP_WEEKS   = 12

# Lock to prevent overlapping scans
_rhetoric_running = False


# ============================================
# 6-ACTOR MODEL — Dual-Vector Composite
# ============================================
ACTORS = {
    # ── THREAT VECTOR (0-5) — instability signals ──
    'omani_regime': {
        'name':        'Sultan Haitham & Diwan',
        'role':        'Royal Court / MOFA / Ministry of Royal Office',
        'icon':        '🏛️',
        'flag':        '🇴🇲',
        'color':       '#dc2626',
        'feeds_into':  'threat',
        'description': (
            'Sultan Haitham bin Tariq, Diwan of the Royal Court, Ministry of Foreign '
            'Affairs, official statements from Royal Office. Watch for: tone shift in '
            'state media (Oman News Agency / Times of Oman), royal decree volume, '
            'Sultan public appearance patterns, foreign policy posture changes.'
        ),
        'keywords': [
            # English — names + institutions
            'sultan haitham', 'haitham bin tariq', 'sultan of oman',
            'diwan oman', 'ministry of foreign affairs oman', 'mofa oman',
            'royal office oman', 'oman news agency', 'ona oman',
            'badr al-busaidi', 'sayyid badr', 'fahd bin mahmoud',
            'majlis al-dawla', 'majlis al-shura', 'state council oman',
            'shura council oman',
            'omani statement', 'muscat statement', 'oman declared',
            'oman position', 'royal decree oman', 'oman cabinet',
            # Arabic
            'سلطان هيثم', 'هيثم بن طارق', 'الديوان السلطاني',
            'سلطان عمان', 'مرسوم سلطاني', 'وكالة الأنباء العمانية',
            'بدر البوسعيدي', 'سيد بدر', 'فهد بن محمود',
            'مجلس الدولة', 'مجلس الشورى',
            'بيان عماني', 'موقف عمان', 'الحكومة العمانية',
            # Farsi
            'سلطان هیثم', 'هیثم بن طارق', 'سلطان عمان',
            'وزارت خارجه عمان', 'بدر البوسعیدی',
            'مسقط بیانیه', 'دولت عمان',
        ],
        'tripwires': [
            'sultan dies', 'sultan dead', 'sultan haitham passes',
            'royal succession crisis', 'oman royal crisis',
            'diwan upheaval', 'sudden cabinet reshuffle oman',
            'وفاة السلطان', 'ازمة الخلافة',
        ],
    },
    'omani_security': {
        'name':        'Royal Oman Police & ISS',
        'role':        'Internal security, dissident management, port security',
        'icon':        '🛡️',
        'flag':        '🇴🇲',
        'color':       '#991b1b',
        'feeds_into':  'threat',
        'description': (
            'Royal Oman Police (ROP), Internal Security Service (ISS), Coast Guard. '
            'Oman is a benign police state — baseline noise is near zero. Watch for: '
            'protest suppression (rare), dissident detentions (rare), Dhofar tribal '
            'management, Salalah port security tightening, social media activist arrests. '
            'Crossing from baseline to active suppression is a major signal.'
        ),
        'keywords': [
            # English
            'royal oman police', 'rop oman', 'ross oman',
            'internal security service oman', 'iss oman',
            'oman security forces', 'oman coast guard',
            'oman arrest', 'oman detained', 'oman dissident',
            'omani activist', 'oman crackdown', 'oman protest',
            'salalah security', 'dhofar security',
            # Arabic
            'الشرطة العمانية', 'الأمن الداخلي',
            'الشرطة السلطانية', 'خفر السواحل العماني',
            'اعتقال في عمان', 'احتجاز عمان',
            'ناشط عماني', 'معارض عماني',
            'احتجاج عمان', 'تظاهرة عمان',
            'أمن صلالة', 'أمن ظفار',
            # Farsi
            'پلیس عمان', 'نیروهای امنیتی عمان',
            'دستگیری عمان', 'بازداشت عمان',
            'فعال عمانی', 'معترضان عمان',
            'امنیت صلاله', 'ظفار',
        ],
        ],
        'tripwires': [
            'mass arrests oman', 'protest dispersed muscat',
            'oman dissident jailed', 'oman activist detained',
            'salalah lockdown', 'dhofar curfew',
            'اعتقال جماعي عمان',
        ],
    },
    'external_threats_inbound': {
        'name':        'External Threats Inbound',
        'role':        'Iran/Houthi targeting, Yemen border, Baloch spillover',
        'icon':        '🚨',
        'flag':        '⚠️',
        'color':       '#ea580c',
        'feeds_into':  'threat',
        'description': (
            'Threats targeting Omani territory or assets. Salalah container port '
            '(US/UK logistics hub on Indian Ocean coast) and Duqm (UK base + dry dock, '
            'outside Strait of Hormuz) are the primary kinetic concern. Yemen border '
            '(Dhofar governorate) sees periodic refugee and Houthi spillover. Baloch '
            'unrest in Pakistan can spill into Omani Baloch communities.'
        ),
        'keywords': [
            # English — direct threats
            'iran threatens oman', 'iran target oman',
            'salalah strike', 'salalah missile', 'salalah attack',
            'duqm strike', 'duqm attack', 'duqm british base',
            'houthi missile oman', 'yemen border oman', 'dhofar spillover',
            'tanker attack salalah', 'tanker attack duqm', 'tanker attack gulf of oman',
            'limpet mine oman', 'mine gulf of oman',
            # English — Hormuz mining (specific kinetic indicator)
            'iran mining hormuz', 'iran lays mines hormuz', 'mine layer iran',
            'iran small boats hormuz', 'shoot and kill iran',
            # English — Baloch / Pakistan spillover (specific organizations)
            'baloch attack oman', 'baloch unrest dhofar',
            'baloch liberation army', 'bla pakistan',
            'baloch insurgency oman', 'baloch fighters oman',
            'gwadar baloch', 'cpec baloch attack',
            # English — Yemen border specifics
            'mahra yemen oman', 'yemen oman crossing',
            'yemeni refugees oman', 'al ghaydah yemen',
            # Arabic
            'استهداف صلالة', 'استهداف الدقم', 'هجوم على عمان',
            'صاروخ على صلالة', 'هجوم بالطائرات المسيرة عمان',
            'لغم خليج عمان', 'تلغيم مضيق هرمز',
            'البلوش عمان', 'جيش تحرير بلوشستان',
            'لاجئون يمنيون عمان', 'حدود اليمن عمان',
            'هجوم على ناقلة خليج عمان',
            # Farsi
            'تهدید عمان', 'حمله به عمان', 'هدف صلاله',
            'حمله به الدقم', 'تنگه هرمز مین گذاری',
            'قایق‌های کوچک هرمز', 'پایگاه بریتانیا الدقم',
            'بلوچستان عمان', 'پناهندگان یمنی عمان',
        ],
        'tripwires': [
            'salalah hit', 'duqm hit', 'oman struck',
            'iran fires at oman', 'houthi strike oman',
            'tanker explosion gulf of oman',
            'استهداف مباشر صلالة', 'صلالة مستهدفة',
        ],
    },
    'succession_watch': {
        'name':        'Succession & Dynastic Watch',
        'role':        'Sultan health, heir profile, dynastic stability indicators',
        'icon':        '👑',
        'flag':        '🇴🇲',
        'color':       '#7c2d12',
        'feeds_into':  'threat',
        'description': (
            'Sultan Haitham assumed power in January 2020 after Qaboos died. Unlike '
            'Qaboos who left a sealed succession letter (opened the day he died), '
            'Haitham is the first sultan to publicly designate an heir: Theyazin bin '
            'Haitham (eldest son, Crown Prince since Jan 2021). Asad bin Tariq is '
            'Sultan Haitham\'s elder cousin, formerly seen as a dynastic alternative. '
            'Watch for: Sultan public absences >7 days, Theyazin profile elevation '
            'or eclipse, Asad bin Tariq mentions, decree volume drops (silence pattern).'
        ),
        'keywords': [
            'theyazin bin haitham', 'crown prince oman', 'crown prince theyazin',
            'asad bin tariq', 'asaad bin tariq',
            'sultan haitham health', 'sultan oman hospital','keywords': [
            # English — primary heir + alternative dynastic figures
            'theyazin bin haitham', 'crown prince oman', 'crown prince theyazin',
            'asad bin tariq', 'asaad bin tariq',
            'sultan haitham health', 'sultan oman hospital',
            'sultan oman illness', 'sultan oman travel',
            'oman succession', 'oman dynasty', 'oman royal family',
            'oman royal decree', 'royal court oman', 'sayyid theyazin',
            'sayyida mona bint fahd', 'mona bint fahd',
            'al said dynasty', 'al busaid dynasty',
            # English — visibility / absence patterns
            'sultan haitham absent', 'sultan undisclosed',
            'royal birthday oman', 'national day oman',
            'sultan public appearance',
            # Arabic
            'ولي العهد عمان', 'صحة السلطان',
            'سيد ذي يزن', 'ذي يزن بن هيثم',
            'أسعد بن طارق', 'منى بنت فهد',
            'أسرة آل سعيد', 'العائلة المالكة العمانية',
            'وراثة عمان', 'صحة سلطان عمان',
            'السلطان غائب', 'يوم وطني عمان',
            # Farsi
            'ولیعهد عمان', 'سلامتی سلطان عمان',
            'ذی یزن بن هیثم', 'اسعد بن طارق',
            'خاندان سلطنتی عمان', 'جانشینی عمان',
            'سلطان عمان بیمار', 'غیبت سلطان',
        ],
            'sultan oman illness', 'sultan oman travel',
            'oman succession', 'oman dynasty', 'oman royal family',
            'ولي العهد عمان', 'صحة السلطان',
            'oman royal decree', 'royal court oman', 'sayyid theyazin',
        ],
        'tripwires': [
            'sultan haitham hospitalized', 'sultan unwell',
            'sultan absent', 'undisclosed travel',
            'crown prince elevated', 'crown prince emergency',
            'سلطان مريض', 'السلطان في المستشفى',
        ],
    },
    # ── INFLUENCE VECTOR (0-5) — diplomatic activity ──
    'mediation_activity': {
        'name':        'Diplomatic Mediation',
        'role':        'Iran-US channel, Yemen mediation, Hamas indirect, hostage releases',
        'icon':        '🕊️',
        'flag':        '🇴🇲',
        'color':       '#7c3aed',
        'feeds_into':  'influence',
        'description': (
            'Oman\'s historic and continuing role as the Gulf\'s diplomatic back-channel. '
            'Hosts US-Iran talks (Witkoff in Muscat 2024-2025 pattern), brokers Houthi '
            'hostage releases, maintains channels to Hamas. INVERSE polarity from threat '
            'vectors: high mediation activity is a STABILITY signal, not an alarm. The '
            'Iran tracker reads oman:mediation_active as a de-escalation modifier.'
        ),
        'keywords': [
            # English
            'oman mediation', 'omani mediation', 'oman brokered',
            'muscat talks', 'muscat channel', 'muscat back-channel',
            'oman us iran', 'witkoff muscat', 'witkoff oman',
            'oman hostage release', 'oman houthi release', 'omani envoy',
            'oman delegation tehran', 'iranian delegation muscat',
            'oman yemen mediation', 'oman hamas channel',
            'oman saudi yemen', 'omani diplomacy',
            # English — specific named individuals + scenarios
            'araghchi muscat', 'araghchi oman',
            'witkoff araghchi muscat', 'witkoff iran muscat',
            'oman released american', 'oman freed american',
            'oman freed prisoner iran', 'oman swap iran',
            'oman israel hamas indirect',
            # Arabic
            'وساطة عمانية', 'محادثات مسقط',
            'القناة العمانية', 'مسقط قناة خلفية',
            'مفاوضات مسقط', 'وفد إيراني مسقط',
            'وفد عماني طهران', 'مبعوث عماني',
            'الإفراج بوساطة عمانية', 'إطلاق سراح بوساطة مسقط',
            'وساطة عمانية يمن', 'دبلوماسية عمانية',
            'عراقجي مسقط', 'ويتكوف مسقط',
            # Farsi (CRITICAL — Iran International, Tasnim, Press TV cover this constantly)
            'میانجیگری عمان', 'مسقط مذاکرات',
            'کانال مسقط', 'گفتگوهای مسقط',
            'هیئت ایرانی مسقط', 'هیئت عمان تهران',
            'فرستاده عمانی', 'دیپلماسی عمانی',
            'عراقچی مسقط', 'عراقچی عمان',
            'ویتکاف مسقط', 'ویتکاف عراقچی',
            'آزادی زندانی توسط عمان', 'مبادله زندانی عمان',
            'وساطت عمان', 'مسقط ایران آمریکا',
        ],
        'tripwires': [
            'oman brokers ceasefire', 'oman secures release',
            'omani breakthrough', 'oman peace deal',
            'الوساطة العمانية تنجح', 'اتفاق وساطة عمان',
        ],
    },
    'regional_diplomatic_hub': {
        'name':        'Regional Convening',
        'role':        'GCC role, summits hosted, Gulf-China-India triangulation',
        'icon':        '🌐',
        'flag':        '🇴🇲',
        'color':       '#5b21b6',
        'feeds_into':  'influence',
        'description': (
            'Oman as convening venue and balanced regional actor. Hosts heads of state, '
            'GCC summits, Gulf-China-India triangulation, India-Oman strategic dialogue, '
            'UK-Oman defense cooperation. Independent foreign policy stance (didn\'t join '
            'Saudi-UAE blockade of Qatar 2017-2021) reinforces convening credibility.'
        ),
        'keywords': [
            # English
            'gcc summit muscat', 'oman hosts summit',
            'india oman strategic', 'oman china strategic',
            'oman uk defense', 'oman japan', 'oman korea',
            'visit muscat', 'visit oman', 'state visit oman',
            'oman foreign minister visit', 'sayyid badr',
            'oman convening', 'oman dialogue', 'oman conference',
            'oman india partnership', 'oman gulf cooperation',
            # English — specific bilateral patterns
            'oman russia talks', 'oman china talks',
            'oman india modi', 'oman pakistan',
            'oman uk talks', 'oman uae cooperation',
            # Arabic
            'بدر البوسعيدي',
            'قمة خليجية مسقط', 'عمان تستضيف قمة',
            'زيارة دولة عمان', 'وزير خارجية عمان',
            'حوار عماني', 'مؤتمر مسقط',
            'عمان الهند', 'عمان الصين',
            'عمان روسيا', 'عمان بريطانيا',
            'تعاون خليجي عماني',
            # Farsi
            'بدر البوسعیدی', 'وزیر خارجه عمان',
            'سفر به مسقط', 'دیدار مسقط',
            'عمان هند', 'عمان چین',
            'عمان روسیه', 'گفتگوهای عمان',
            'همکاری خلیج عمان',
        ],
        'tripwires': [
            'historic summit muscat', 'oman hosts unprecedented',
            'major breakthrough oman conference',
        ],
    },
}


# ============================================
# CROSS-THEATER FINGERPRINT READS
# ============================================
def _read_cross_theater_signals():
    """
    Reads other tracker fingerprints from shared Redis. Returns a dict of signals
    that boost or modify Oman vector levels. Graceful fallback on missing keys.
    """
    signals = {
        'iran_salalah_targeted':       False,
        'iran_duqm_logistics_active':  False,
        'iran_oman_diplomatic_active': False,
        'iran_command_node_level':     0,
        'yemen_dhofar_pressure':       0,
        'pakistan_balochistan_unrest': 0,
        'zanzibar_unrest':             0,  # placeholder for future Africa
    }
    try:
        fingerprints = _redis_get(CROSSTHEATER_KEY) or {}
    except Exception as e:
        print(f"[Oman Rhetoric] cross-theater read error: {e}")
        return signals

    iran_fp = fingerprints.get('iran', {}) or {}
    if iran_fp:
        signals['iran_salalah_targeted']       = bool(iran_fp.get('salalah_targeted', False))
        signals['iran_duqm_logistics_active']  = bool(iran_fp.get('duqm_logistics_active', False))
        signals['iran_oman_diplomatic_active'] = bool(iran_fp.get('oman_diplomatic_active', False))
        signals['iran_command_node_level']     = int(iran_fp.get('level', 0))

    yemen_fp = fingerprints.get('yemen', {}) or {}
    signals['yemen_dhofar_pressure'] = int(yemen_fp.get('dhofar_refugee_pressure', 0) or 0)

    pakistan_fp = fingerprints.get('pakistan', {}) or {}
    signals['pakistan_balochistan_unrest'] = int(pakistan_fp.get('balochistan_unrest', 0) or 0)

    zanzibar_fp = fingerprints.get('zanzibar', {}) or {}
    signals['zanzibar_unrest'] = int(zanzibar_fp.get('unrest_level', 0) or 0)

    return signals


def _apply_cross_theater_boosts(actor_levels, cross_signals):
    """
    Apply cross-theater fingerprint reads as boosts to actor levels.
    Returns updated actor_levels dict and a list of applied boost descriptions.
    """
    boosts = []

    # External threats inbound — boosted by Iran targeting + Yemen + Pakistan
    ext_boost = 0
    if cross_signals['iran_salalah_targeted']:
        ext_boost = max(ext_boost, 3)
        boosts.append("Iran rhetoric targeting Salalah → external_threats +3")
    if cross_signals['iran_duqm_logistics_active']:
        ext_boost = max(ext_boost, 2)
        boosts.append("Iran rhetoric on Duqm UK base → external_threats +2")
    if cross_signals['yemen_dhofar_pressure'] >= 3:
        ext_boost = max(ext_boost, 2)
        boosts.append(f"Yemen border pressure L{cross_signals['yemen_dhofar_pressure']} → external_threats +2")
    if cross_signals['pakistan_balochistan_unrest'] >= 3:
        ext_boost = max(ext_boost, 1)
        boosts.append(f"Pakistan Balochistan L{cross_signals['pakistan_balochistan_unrest']} → external_threats +1")

    if ext_boost > 0:
        actor_levels['external_threats_inbound'] = min(5, max(
            actor_levels.get('external_threats_inbound', 0),
            ext_boost
        ))

    # Mediation — boosted when Iran tracker confirms Oman channel is active
    if cross_signals['iran_oman_diplomatic_active']:
        actor_levels['mediation_activity'] = min(5, max(
            actor_levels.get('mediation_activity', 0),
            3
        ))
        boosts.append("Iran tracker confirms Muscat channel active → mediation +3")

    return actor_levels, boosts


# ============================================
# RSS FEEDS — Per Rachel's directive: GO BROAD
# ============================================
RHETORIC_RSS_FEEDS = [
    # ── Western/Regional English ──
    {
        'name': 'Reuters Middle East',
        'url':  'https://www.reuters.com/world/middle-east/rss',
        'lang': 'en',
        'weight': 1.0,
    },
    {
        'name': 'Al Jazeera English (Mideast)',
        'url':  'https://www.aljazeera.com/xml/rss/all.xml',
        'lang': 'en',
        'weight': 0.95,
    },
    {
        'name': 'Times of Oman (English)',
        'url':  'https://timesofoman.com/feed',
        'lang': 'en',
        'weight': 0.95,
    },
    {
        'name': 'Muscat Daily (English)',
        'url':  'https://www.muscatdaily.com/rss',
        'lang': 'en',
        'weight': 0.90,
    },
    # ── Arabic — axis-perspective on Oman ──
    {
        'name': 'Al Mayadeen (Arabic)',
        'url':  'https://www.almayadeen.net/rss',
        'lang': 'ar',
        'weight': 0.85,
    },
    {
        'name': 'Al-Manar (Arabic)',
        'url':  'https://almanar.com.lb/rss/feed/news/',
        'lang': 'ar',
        'weight': 0.80,
    },
    {
        'name': 'Al Jazeera Arabic',
        'url':  'https://www.aljazeera.net/aljazeerarss',
        'lang': 'ar',
        'weight': 0.95,
    },
    # ── Iranian sources — Iranian commentary on Oman channel ──
    {
        'name': 'Iran International (English)',
        'url':  'https://www.iranintl.com/en/rss.xml',
        'lang': 'en',
        'weight': 0.85,
    },
    {
        'name': 'Tasnim News (English)',
        'url':  'https://www.tasnimnews.com/en/rss/feed/0/8/0/breaking',
        'lang': 'en',
        'weight': 0.75,
    },
    {
        'name': 'Press TV (Iranian state, EN)',
        'url':  'https://www.presstv.ir/rss.xml',
        'lang': 'en',
        'weight': 0.70,
    },
    # ── Google News Oman-specific (English aggregator) ──
    {
        'name': 'Google News — Oman (EN)',
        'url':  'https://news.google.com/rss/search?q=oman+sultan+OR+muscat+OR+salalah&hl=en&gl=US&ceid=US:en',
        'lang': 'en',
        'weight': 0.85,
    },
    # ── Google News Oman-specific (Arabic aggregator) ──
    {
        'name': 'Google News — Oman (AR)',
        'url':  'https://news.google.com/rss/search?q=%D8%B9%D9%85%D8%A7%D9%86+%D8%B3%D9%84%D8%B7%D8%A7%D9%86+OR+%D9%85%D8%B3%D9%82%D8%B7&hl=ar&gl=OM&ceid=OM:ar',
        'lang': 'ar',
        'weight': 0.85,
    },
]


# ============================================
# GDELT QUERIES — multi-language
# ============================================
GDELT_QUERIES = {
    'eng': '(oman OR muscat OR salalah OR duqm OR "sultan haitham") AND (mediation OR threat OR succession OR strike OR diplomacy)',
    'ara': '(عمان OR مسقط OR صلالة OR الدقم OR "السلطان هيثم") AND (وساطة OR تهديد OR استهداف OR محادثات)',
    'fas': '(عمان OR مسقط OR صلاله OR الدقم OR "سلطان هیثم") AND (میانجیگری OR گفتگو OR تهدید)',
    'heb': '(עומאן OR מוסקט OR "סולטן הית\'אם") AND (תיווך OR איום OR שיחות)',
}


# ============================================
# REDIS HELPERS (Upstash REST)
# ============================================
def _redis_get(key):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return None
    try:
        r = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}'},
            timeout=5,
        )
        if r.ok:
            data = r.json().get('result')
            if data:
                return json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        print(f"[Oman Rhetoric Redis] GET error: {str(e)[:80]}")
    return None


def _redis_set(key, value, ttl=None):
    if not UPSTASH_REDIS_URL or not UPSTASH_REDIS_TOKEN:
        return False
    try:
        params = {}
        if ttl:
            params['EX'] = ttl
        r = requests.post(
            f"{UPSTASH_REDIS_URL}/set/{key}",
            headers={
                'Authorization': f'Bearer {UPSTASH_REDIS_TOKEN}',
                'Content-Type': 'application/json',
            },
            params=params,
            data=json.dumps(value),
            timeout=5,
        )
        return r.ok
    except Exception as e:
        print(f"[Oman Rhetoric Redis] SET error: {str(e)[:80]}")
        return False


# ============================================
# RSS FETCH
# ============================================
def _fetch_rss(url, source_name, weight=0.85, lang='en'):
    """Fetch and parse an RSS feed. Returns list of article dicts."""
    articles = []
    try:
        r = requests.get(url, timeout=(5, 10), headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*',
            'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
        })
        if not r.ok:
            print(f"[Oman RSS] ❌ {source_name}: HTTP {r.status_code}")
            return []
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as pe:
            print(f"[Oman RSS] ❌ {source_name}: XML parse error: {str(pe)[:80]}")
            return []
        items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
        if not items:
            print(f"[Oman RSS] ⚠️  {source_name}: HTTP 200 but 0 items in feed (size={len(r.content)})")
            return []
        for item in items[:30]:
            title_el = item.find('title') or item.find('{http://www.w3.org/2005/Atom}title')
            link_el  = item.find('link')  or item.find('{http://www.w3.org/2005/Atom}link')
            desc_el  = item.find('description') or item.find('{http://www.w3.org/2005/Atom}summary')
            pub_el   = item.find('pubDate') or item.find('{http://www.w3.org/2005/Atom}published')
            title = title_el.text if title_el is not None else ''
            link = link_el.text if link_el is not None and link_el.text else (
                link_el.get('href', '') if link_el is not None else ''
            )
            desc = desc_el.text if desc_el is not None else ''
            pub  = pub_el.text  if pub_el is not None  else ''
            if title and link:
                articles.append({
                    'title':       title.strip(),
                    'description': (desc or '').strip(),
                    'url':         link.strip(),
                    'publishedAt': pub.strip(),
                    'source':      {'name': source_name},
                    'feed_type':   'rss',
                    'language':    lang,
                    'source_weight_override': weight,
                })
    except Exception as e:
        print(f"[Oman RSS] ❌ {source_name} unexpected error: {type(e).__name__}: {str(e)[:100]}")
        return []
    if articles:
        print(f"[Oman RSS] ✅ {source_name}: {len(articles)} articles")
    return articles


# ============================================
# GDELT FETCH
# ============================================
def _fetch_gdelt(query, language='eng', max_records=20):
    articles = []
    try:
        params = {
            'query':       query + ' sourcelang:' + language,
            'mode':        'ArtList',
            'format':      'JSON',
            'maxrecords':  max_records,
            'timespan':    '2d',
            'sort':        'DateDesc',
        }
        r = requests.get(GDELT_BASE_URL, params=params, timeout=8)
        if not r.ok:
            print(f"[Oman GDELT] {language} HTTP {r.status_code}")
            return []
        data = r.json()
        for art in data.get('articles', []):
            articles.append({
                'title':       art.get('title', ''),
                'description': art.get('title', ''),
                'url':         art.get('url', ''),
                'publishedAt': art.get('seendate', ''),
                'source':      {'name': art.get('domain', 'GDELT')},
                'feed_type':   'gdelt',
                'language':    language[:2],
            })
    except Exception as e:
        print(f"[Oman GDELT] {language} error: {str(e)[:100]}")
    return articles


# ============================================
# NEWSAPI FETCH (fallback)
# ============================================
def _fetch_newsapi(query, language='en', max_records=20):
    if not NEWSAPI_KEY:
        return []
    try:
        r = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q':         query,
                'language':  language,
                'pageSize':  max_records,
                'sortBy':    'publishedAt',
                'apiKey':    NEWSAPI_KEY,
            },
            timeout=8,
        )
        if not r.ok:
            return []
        data = r.json()
        out = []
        for art in data.get('articles', []):
            out.append({
                'title':       art.get('title', '') or '',
                'description': art.get('description', '') or '',
                'url':         art.get('url', '') or '',
                'publishedAt': art.get('publishedAt', '') or '',
                'source':      art.get('source', {'name': 'NewsAPI'}),
                'feed_type':   'newsapi',
                'language':    language,
            })
        return out
    except Exception as e:
        print(f"[Oman NewsAPI] error: {str(e)[:100]}")
        return []


# ============================================
# AGGREGATE FETCH
# ============================================
def _fetch_all_articles():
    """Fetch from all sources. Returns deduplicated list."""
    articles = []

    # RSS feeds
    rss_count = 0
    for src in RHETORIC_RSS_FEEDS:
        try:
            fetched = _fetch_rss(
                src['url'],
                src['name'],
                weight=src.get('weight', 0.85),
                lang=src.get('lang', 'en'),
            )
            articles.extend(fetched)
            rss_count += len(fetched)
        except Exception as e:
            print(f"[Oman RSS] {src.get('name', 'unknown')} error: {str(e)[:80]}")
    print(f"[Oman RSS] 📊 Total RSS articles: {rss_count} from {len(RHETORIC_RSS_FEEDS)} feeds")

    # GDELT — all language queries
    gdelt_count = 0
    for language, query in GDELT_QUERIES.items():
        try:
            fetched = _fetch_gdelt(query, language=language)
            articles.extend(fetched)
            gdelt_count += len(fetched)
            time.sleep(0.5)  # polite spacing between languages
        except Exception as e:
            print(f"[Oman GDELT] {language} error: {str(e)[:80]}")

    # NewsAPI fallback if GDELT thin
    newsapi_count = 0
    if gdelt_count < 10:
        print(f"[Oman NewsAPI] GDELT returned only {gdelt_count} articles -- triggering fallback")
        newsapi_queries = [
            'Oman Sultan Haitham OR Muscat OR Salalah',
            '"Oman mediation" OR "Muscat channel" OR "Witkoff Oman"',
            'Duqm OR Dhofar OR "Sultan of Oman"',
        ]
        for q in newsapi_queries:
            try:
                fetched = _fetch_newsapi(query=q, language='en', max_records=20)
                articles.extend(fetched)
                newsapi_count += len(fetched)
                time.sleep(0.3)
            except Exception as e:
                print(f"[Oman NewsAPI] query error: {str(e)[:80]}")

    # ── Brave Search fallback (multi-language) ──
    # Per Rachel: EN + AR + FA + HE
    # v1.1 threshold: fires when RSS is starving OR primary sources are thin.
    # The RSS=0 condition catches scenarios where datacenter IPs are blocked
    # by major outlets but English news still works via NewsAPI.
    brave_count = 0
    primary_total = gdelt_count + newsapi_count
    brave_should_fire = (
        _BRAVE_AVAILABLE and _fetch_brave and (
            primary_total < 15 or
            (rss_count == 0 and primary_total < 30)  # RSS dead = need multilingual coverage
        )
    )
    if brave_should_fire:
        reason = f"primary={primary_total}, rss={rss_count}"
        print(f"[Oman Brave] Triggering Brave multi-lang fallback ({reason})")
        # English
        for q in ['Oman Sultan Haitham mediation', 'Salalah Duqm Oman security']:
            try:
                fetched = _fetch_brave(q, count=15, freshness='pw',
                                       search_lang='en', country='us')
                articles.extend(fetched)
                brave_count += len(fetched)
                time.sleep(1.1)
            except Exception as e:
                print(f"[Oman Brave EN] query error: {str(e)[:80]}")
        # Arabic
        for q in ['عمان السلطان هيثم وساطة', 'صلالة الدقم عمان']:
            try:
                fetched = _fetch_brave(q, count=10, freshness='pw',
                                       search_lang='ar', country='us')
                articles.extend(fetched)
                brave_count += len(fetched)
                time.sleep(1.1)
            except Exception as e:
                print(f"[Oman Brave AR] query error: {str(e)[:80]}")
        # Persian
        for q in ['عمان مسقط مذاکرات']:
            try:
                fetched = _fetch_brave(q, count=10, freshness='pw',
                                       search_lang='fa', country='ir')
                articles.extend(fetched)
                brave_count += len(fetched)
                time.sleep(1.1)
            except Exception as e:
                print(f"[Oman Brave FA] query error: {str(e)[:80]}")
        # Hebrew
        for q in ['עומאן תיווך איראן']:
            try:
                fetched = _fetch_brave(q, count=10, freshness='pw',
                                       search_lang='he', country='il')
                articles.extend(fetched)
                brave_count += len(fetched)
                time.sleep(1.1)
            except Exception as e:
                print(f"[Oman Brave HE] query error: {str(e)[:80]}")

    print(f"[Oman Rhetoric] Total articles fetched: {len(articles)} "
          f"(GDELT={gdelt_count}, NewsAPI={newsapi_count}, Brave={brave_count})")

    # Deduplicate by URL
    seen = set()
    unique = []
    for art in articles:
        key = art.get('url') or art.get('title', '')
        if key and key not in seen:
            seen.add(key)
            unique.append(art)

    print(f"[Oman Rhetoric] After dedup: {len(unique)} articles")
    return unique


# ============================================
# ARTICLE CLASSIFICATION
# ============================================
def _score_article_for_actor(article, actor_key, actor_def):
    """Score an article for a specific actor. Returns (level, trigger_phrase)."""
    title = (article.get('title') or '').lower()
    desc  = (article.get('description') or '').lower()
    text  = f"{title} {desc}"

    for kw in actor_def.get('keywords', []):
        if kw.lower() in text:
            for tw in actor_def.get('tripwires', []):
                if tw.lower() in text:
                    return 4, tw
            return 1, kw
    return 0, None


def _classify_articles(articles):
    """Classify each article against the 6 actors. Returns per-actor result dict."""
    actor_results = {
        actor_id: {
            'statement_count': 0,
            'max_level': 0,
            'top_articles': [],
            'trigger_phrases': [],
        }
        for actor_id in ACTORS.keys()
    }

    for article in articles:
        for actor_id, actor_def in ACTORS.items():
            level, phrase = _score_article_for_actor(article, actor_id, actor_def)
            if level > 0:
                weight = article.get('source_weight_override', 0.85)
                level = min(5, int(round(level * weight + 0.4)))
                actor_results[actor_id]['statement_count'] += 1
                actor_results[actor_id]['max_level'] = max(
                    actor_results[actor_id]['max_level'], level
                )
                if phrase and phrase not in actor_results[actor_id]['trigger_phrases']:
                    actor_results[actor_id]['trigger_phrases'].append(phrase)
                if len(actor_results[actor_id]['top_articles']) < 5:
                    art_copy = dict(article)
                    art_copy['escalation_level'] = level
                    art_copy['trigger_phrase']   = phrase
                    actor_results[actor_id]['top_articles'].append(art_copy)
    return actor_results


# ============================================
# COMPOSITE VECTOR COMPUTATION
# ============================================
def _compute_vectors(actor_results, cross_signals):
    """
    Compute composite threat and influence vectors.
    Apply cross-theater fingerprint boosts to actor levels first.
    """
    actor_levels = {aid: actor_results[aid]['max_level'] for aid in ACTORS.keys()}
    actor_levels, boosts = _apply_cross_theater_boosts(actor_levels, cross_signals)

    # Re-write boosted levels back into actor_results for display
    for aid in ACTORS.keys():
        actor_results[aid]['max_level'] = actor_levels.get(aid, 0)

    threat_actors = [aid for aid, a in ACTORS.items() if a.get('feeds_into') == 'threat']
    influence_actors = [aid for aid, a in ACTORS.items() if a.get('feeds_into') == 'influence']

    threat_level    = max((actor_levels.get(aid, 0) for aid in threat_actors),    default=0)
    influence_level = max((actor_levels.get(aid, 0) for aid in influence_actors), default=0)

    # Display banner determination (Rachel's spec)
    if threat_level >= 3:
        banner_mode  = 'THREAT'
        banner_color = '#dc2626' if threat_level >= 4 else '#ea580c'
        banner_label = 'THREAT MODE'
    elif influence_level >= 3:
        banner_mode  = 'INFLUENCE'
        banner_color = '#7c3aed'
        banner_label = 'INFLUENCE MODE'
    elif threat_level >= 1:
        banner_mode  = 'MONITORING'
        banner_color = '#0ea5e9'
        banner_label = 'MONITORING'
    else:
        banner_mode  = 'QUIET'
        banner_color = '#16a34a'
        banner_label = 'QUIET — STABLE'

    return {
        'threat_level':       threat_level,
        'influence_level':    influence_level,
        'banner_mode':        banner_mode,
        'banner_color':       banner_color,
        'banner_label':       banner_label,
        'cross_theater_boosts': boosts,
        'actor_results':      actor_results,
    }


# ============================================
# CROSS-THEATER FINGERPRINT WRITE
# ============================================
def _write_crosstheater_signal(result):
    """Oman writes its fingerprint for other trackers to read."""
    try:
        existing = _redis_get(CROSSTHEATER_KEY) or {}
        actors = result.get('actors', {})

        threat_level    = result.get('threat_level', 0)
        influence_level = result.get('influence_level', 0)

        existing['oman'] = {
            'ts':                       datetime.now(timezone.utc).isoformat(),
            'theatre':                  'Oman',
            'is_stability_anchor':      True,
            'threat_level':             threat_level,
            'influence_level':          influence_level,
            'mediation_active':         actors.get('mediation_activity', {}).get('max_level', 0) >= 3,
            'salalah_under_threat':     actors.get('external_threats_inbound', {}).get('max_level', 0) >= 3,
            'succession_watch_active':  actors.get('succession_watch', {}).get('max_level', 0) >= 2,
            'sultan_health_concern':    actors.get('succession_watch', {}).get('max_level', 0) >= 3,
            'banner_mode':              result.get('banner_mode', 'QUIET'),
            'actor_levels': {
                aid: actors.get(aid, {}).get('max_level', 0) for aid in ACTORS.keys()
            },
        }
        _redis_set(CROSSTHEATER_KEY, existing, ttl=8 * 3600)
        print(f"[Oman Rhetoric] ✅ Cross-theater fingerprint written "
              f"(threat={threat_level}, influence={influence_level})")
    except Exception as e:
        print(f"[Oman Rhetoric] Cross-theater write error: {e}")


# ============================================
# SOURCE COUNTS
# ============================================
def _compute_source_counts(articles):
    counts = {
        'gdelt':   0,
        'rss':     0,
        'newsapi': 0,
        'brave':   0,
    }
    for art in articles:
        ft = (art.get('feed_type') or '').lower()
        if ft in counts:
            counts[ft] += 1
        else:
            counts['rss'] += 1
    return counts


# ============================================
# MAIN SCAN
# ============================================
def run_oman_rhetoric_scan(force=False):
    global _rhetoric_running
    if _rhetoric_running and not force:
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if cached:
            cached['scan_in_progress'] = True
            return cached
    _rhetoric_running = True

    try:
        scan_start = time.time()
        articles = _fetch_all_articles()
        articles_classified = _classify_articles(articles)

        cross_signals = _read_cross_theater_signals()
        composite     = _compute_vectors(articles_classified, cross_signals)

        actors_out = {}
        for aid, defn in ACTORS.items():
            ar = articles_classified[aid]
            level = ar['max_level']
            actors_out[aid] = {
                'name':              defn['name'],
                'role':              defn['role'],
                'icon':              defn['icon'],
                'flag':              defn['flag'],
                'color':             defn['color'],
                'description':       defn['description'],
                'feeds_into':        defn['feeds_into'],
                'escalation_level':  level,
                'max_level':         level,
                'statement_count':   ar['statement_count'],
                'top_articles':      ar['top_articles'],
                'escalation_phrase': (ar['trigger_phrases'][0] if ar['trigger_phrases'] else None),
                'silence_alert':     ar['statement_count'] == 0,
            }

        result = {
            'success':              True,
            'theatre':              'Oman',
            'theatre_color':        '#0ea5e9',
            'version':              '1.0 - April 2026',

            # Composite scoring
            'threat_level':         composite['threat_level'],
            'influence_level':      composite['influence_level'],
            'banner_mode':          composite['banner_mode'],
            'banner_color':         composite['banner_color'],
            'banner_label':         composite['banner_label'],

            'actors':               actors_out,
            'articles_scanned':     len(articles),
            'source_counts':        _compute_source_counts(articles),
            'cross_theater_boosts': composite['cross_theater_boosts'],
            'cross_theater_signals': cross_signals,
            'scan_time_seconds':    round(time.time() - scan_start, 2),
            'scanned_at':           datetime.now(timezone.utc).isoformat(),
            'timestamp':            datetime.now(timezone.utc).isoformat(),
            'total_articles':       len(articles),
        }

        # Signal interpreter — Red Lines + So What
        if _INTERPRETER_AVAILABLE:
            try:
                result['red_lines']         = check_red_lines(result)
                result['so_what']           = build_so_what(result)
                result['historical_matches'] = build_historical_matches(result)
            except Exception as e:
                print(f"[Oman Interpreter] error: {str(e)[:120]}")
                result['red_lines'] = []
                result['so_what'] = None
        else:
            result['red_lines'] = []
            result['so_what'] = None

        # Cross-theater fingerprint write
        _write_crosstheater_signal(result)

        # Cache
        _redis_set(RHETORIC_CACHE_KEY, result, ttl=24 * 3600)

        return result
    except Exception as e:
        import traceback
        print(f"[Oman Rhetoric] scan error: {e}")
        traceback.print_exc()
        return {'success': False, 'error': str(e)[:200]}
    finally:
        _rhetoric_running = False


def get_oman_rhetoric_cache():
    return _redis_get(RHETORIC_CACHE_KEY)


# ============================================
# BACKGROUND REFRESH
# ============================================
def _background_refresh():
    time.sleep(90)  # boot delay
    while True:
        try:
            print("[Oman Rhetoric] Background refresh starting...")
            run_oman_rhetoric_scan(force=True)
        except Exception as e:
            print(f"[Oman Rhetoric] Background refresh error: {str(e)[:80]}")
        time.sleep(SCAN_INTERVAL_HOURS * 3600)


def start_background_refresh():
    t = threading.Thread(target=_background_refresh, daemon=True)
    t.start()
    print("[Oman Rhetoric] Background refresh thread started")


# ============================================
# FLASK ENDPOINTS
# ============================================
def register_oman_rhetoric_routes(app):
    """Register /api/rhetoric/oman endpoints on the Flask app."""

    @app.route('/api/rhetoric/oman', methods=['GET'])
    def oman_rhetoric():
        force = request.args.get('force', '').lower() in ('true', '1', 'yes')

        if not force:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                return jsonify(cached)

        # Non-blocking scan with 25s timeout — return cached if scan takes longer
        from concurrent.futures import ThreadPoolExecutor
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(run_oman_rhetoric_scan, True)
        executor.shutdown(wait=False)

        try:
            result = future.result(timeout=25)
            return jsonify(result)
        except Exception:
            cached = _redis_get(RHETORIC_CACHE_KEY)
            if cached:
                cached['from_cache'] = True
                cached['scan_triggered'] = True
                return jsonify(cached)
            return jsonify({'success': False, 'error': 'Scan timeout, no cache available'}), 503

    @app.route('/api/rhetoric/oman/summary', methods=['GET'])
    def oman_rhetoric_summary():
        cached = _redis_get(RHETORIC_CACHE_KEY)
        if not cached:
            return jsonify({'success': False, 'error': 'No data yet'}), 404
        actors = cached.get('actors', {})
        return jsonify({
            'success':                True,
            'threat_level':           cached.get('threat_level', 0),
            'influence_level':        cached.get('influence_level', 0),
            'banner_mode':            cached.get('banner_mode', 'QUIET'),
            'mediation_active':       actors.get('mediation_activity',       {}).get('escalation_level', 0) >= 3,
            'salalah_under_threat':   actors.get('external_threats_inbound', {}).get('escalation_level', 0) >= 3,
            'succession_watch_active': actors.get('succession_watch',         {}).get('escalation_level', 0) >= 2,
            'scanned_at':             cached.get('scanned_at'),
        })
