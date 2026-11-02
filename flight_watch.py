"""
Asifah Analytics -- Flight Watch  v1.0.0  (SHARED MODULE -- byte-identical on all five backends)
November 1, 2026

One file, five backends. Each backend calls
    register_flight_endpoints(app, '<backend>', legacy_routes=['/api/<x>/flights'])
with backend in: me | europe | asia | africa | wha
and gets ONLY its own destinations and its own Redis key -- the WHA page never
sees a Tel Aviv suspension.

WHAT IT WATCHES
  What airlines themselves declare: suspensions, cancellations, extensions,
  reroutes and resumptions, and above all the END DATES they announce
  ("suspended until December 15"). Airlines usually move before regulators do:
  an insurer pulls cover, the carrier suspends, the EASA bulletin comes later.
  That makes the airline layer an early read on how the commercial sector
  prices risk -- the companion to Airspace Watch, which reads the regulators
  and the traffic.

SOURCE (no key, no cost)
  Google News RSS search, grouped queries (verbs OR'd, destinations OR'd), about
  12 requests per scan, leader-only, every 6 h. Proven on ME since 2025.

RULES (lessons from ME rss_monitor v3.8.0, which this replaces)
  * The HEADLINE must name the destination. The search term never assigns it.
  * The headline must carry a disruption verb and an aviation context.
  * No readable publication date -> the story is dropped. Never stamped "now".
  * Resumptions are their own lane -- they point the other way.
  * A declared end date keeps a suspension on the board past the 30-day news
    window (up to 180 days old) until the date passes; once passed it is shown
    for 14 days as "declared end date passed -- no resumption reported".
  * Newest headline per airline + country wins, so "extends" supersedes
    "suspends" and "resumes" supersedes both.
  * Hub cities (Dubai, Frankfurt, Singapore...) are dropped as destinations when
    the headline also names a non-hub destination -- in "Lufthansa suspends
    Frankfurt-Tel Aviv", Frankfurt is the origin.

DOCTRINE
  Unread is not quiet. A read with nothing found says "nothing reported", not
  "safe". Descriptive states only -- no ladder level is asserted from flights.
"""

import os
import re
import json
import time
import threading
import calendar
import html as _html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus

import requests

FLIGHT_WATCH_VERSION = '1.0.0'
FLIGHT_USER_AGENT = (f'AsifahAnalytics-Flights/{FLIGHT_WATCH_VERSION} '
                     f'(OSINT monitoring tool; +https://asifahanalytics.com)')

UPSTASH_REDIS_URL = os.environ.get('UPSTASH_REDIS_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN')

GNEWS_URL = 'https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en'
SCAN_INTERVAL_SEC = 6 * 60 * 60
NEWS_WINDOW_DAYS = 30          # plain suspensions / cancellations / resumptions
DECLARED_WINDOW_DAYS = 180     # a suspension with a future end date stays this long
INDEFINITE_WINDOW_DAYS = 90    # "until further notice"
PASSED_GRACE_DAYS = 14         # end date passed, nothing newer: shown this long
CHUNK = 8                      # place names OR'd per query
MAX_DEST_PER_HEADLINE = 4
MAX_AIRLINES_PER_HEADLINE = 4


# ========================================
# DESTINATIONS
# Each entry: (country label, flag, [aliases]). An alias starting with '*' is a
# hub: dropped as a destination when the headline also names a non-hub place.
# 'exclude' aliases are blanked before matching (so 'South Sudan' never reads
# as 'Sudan', 'Equatorial Guinea' never as 'Guinea').
# ========================================
def _D(label, flag, aliases):
    return {'label': label, 'flag': flag, 'aliases': aliases}


PROFILES = {
    'me': {
        'name': 'Middle East',
        'destinations': [
            _D('Israel', '🇮🇱', ['Tel Aviv', 'Ben Gurion', 'Israel', 'Eilat']),
            _D('Lebanon', '🇱🇧', ['Beirut', 'Lebanon']),
            _D('Syria', '🇸🇾', ['Damascus', 'Aleppo', 'Syria']),
            _D('Iran', '🇮🇷', ['Tehran', 'Mashhad', 'Shiraz', 'Isfahan', 'Iran']),
            _D('Iraq', '🇮🇶', ['Baghdad', 'Basra', 'Erbil', 'Najaf', 'Sulaymaniyah', 'Iraq', 'Kurdistan']),
            _D('Yemen', '🇾🇪', ['Sanaa', "Sana'a", 'Aden', 'Yemen']),
            _D('Jordan', '🇯🇴', ['Amman', 'Aqaba', 'Jordan']),
            _D('UAE', '🇦🇪', ['*Dubai', '*Abu Dhabi', 'Sharjah', 'UAE', 'United Arab Emirates']),
            _D('Saudi Arabia', '🇸🇦', ['Riyadh', 'Jeddah', 'Dammam', 'Medina', 'Saudi Arabia', 'Saudi']),
            _D('Qatar', '🇶🇦', ['*Doha', 'Qatar']),
            _D('Kuwait', '🇰🇼', ['Kuwait']),
            _D('Bahrain', '🇧🇭', ['Bahrain', 'Manama']),
            _D('Oman', '🇴🇲', ['Muscat', 'Oman']),
            _D('Egypt', '🇪🇬', ['*Cairo', 'Sharm el-Sheikh', 'Sharm El Sheikh', 'Hurghada', 'Egypt']),
            _D('Turkey', '🇹🇷', ['*Istanbul', 'Ankara', 'Antalya', 'Turkey', 'Türkiye', 'Turkiye']),
            _D('Middle East (region-wide)', '🌍', ['Middle East', 'Gulf region', 'Mideast']),
        ],
        'exclude': ['Emirates airline', 'Michael Jordan', 'Persian Gulf War'],
    },
    'africa': {
        'name': 'Africa',
        'destinations': [
            _D('Sudan', '🇸🇩', ['Khartoum', 'Port Sudan', 'Sudan']),
            _D('South Sudan', '🇸🇸', ['Juba', 'South Sudan']),
            _D('Somalia', '🇸🇴', ['Mogadishu', 'Hargeisa', 'Somaliland', 'Somalia']),
            _D('Ethiopia', '🇪🇹', ['*Addis Ababa', 'Ethiopia', 'Tigray']),
            _D('Kenya', '🇰🇪', ['*Nairobi', 'Mombasa', 'Kenya']),
            _D('DR Congo', '🇨🇩', ['Kinshasa', 'Goma', 'Lubumbashi', 'DR Congo', 'DRC',
                                   'Democratic Republic of Congo', 'Democratic Republic of the Congo']),
            _D('Mali', '🇲🇱', ['Bamako', 'Mali']),
            _D('Burkina Faso', '🇧🇫', ['Ouagadougou', 'Burkina Faso']),
            _D('Niger', '🇳🇪', ['Niamey', 'Niger']),
            _D('Nigeria', '🇳🇬', ['*Lagos', 'Abuja', 'Kano', 'Port Harcourt', 'Nigeria']),
            _D('Chad', '🇹🇩', ["N'Djamena", 'Ndjamena', 'Chad']),
            _D('Central African Republic', '🇨🇫', ['Bangui', 'Central African Republic']),
            _D('Libya', '🇱🇾', ['Tripoli', 'Benghazi', 'Misrata', 'Libya']),
            _D('Tunisia', '🇹🇳', ['Tunis', 'Tunisia']),
            _D('Algeria', '🇩🇿', ['Algiers', 'Algeria']),
            _D('Morocco', '🇲🇦', ['*Casablanca', 'Marrakech', 'Morocco']),
            _D('Guinea', '🇬🇳', ['Conakry', 'Guinea']),
            _D('Equatorial Guinea', '🇬🇶', ['Malabo', 'Equatorial Guinea']),
            _D('Madagascar', '🇲🇬', ['Antananarivo', 'Madagascar']),
            _D('Mozambique', '🇲🇿', ['Maputo', 'Pemba', 'Mozambique']),
            _D('Rwanda', '🇷🇼', ['*Kigali', 'Rwanda']),
            _D('Uganda', '🇺🇬', ['Entebbe', 'Kampala', 'Uganda']),
            _D('Tanzania', '🇹🇿', ['Dar es Salaam', 'Zanzibar', 'Tanzania']),
            _D('South Africa', '🇿🇦', ['*Johannesburg', 'Cape Town', 'South Africa']),
            _D('Senegal', '🇸🇳', ['Dakar', 'Senegal']),
            _D('Ghana', '🇬🇭', ['Accra', 'Ghana']),
            _D('Zimbabwe', '🇿🇼', ['Harare', 'Zimbabwe']),
            _D('Eritrea', '🇪🇷', ['Asmara', 'Eritrea']),
            _D('Djibouti', '🇩🇯', ['Djibouti']),
        ],
        'exclude': ['Guinea-Bissau', 'Papua New Guinea', 'Niger Delta', 'Republic of Congo-Brazzaville'],
    },
    'asia': {
        'name': 'Asia-Pacific',
        'destinations': [
            _D('Taiwan', '🇹🇼', ['Taipei', 'Kaohsiung', 'Taiwan', 'Taiwan Strait']),
            _D('China', '🇨🇳', ['Beijing', 'Shanghai', 'Guangzhou', 'Shenzhen', 'Chengdu', 'China']),
            _D('Hong Kong', '🇭🇰', ['*Hong Kong']),
            _D('North Korea', '🇰🇵', ['Pyongyang', 'North Korea']),
            _D('South Korea', '🇰🇷', ['*Seoul', '*Incheon', 'Busan', 'South Korea', 'Korea']),
            _D('Japan', '🇯🇵', ['*Tokyo', 'Osaka', 'Okinawa', 'Naha', 'Japan']),
            _D('Philippines', '🇵🇭', ['Manila', 'Philippines']),
            _D('Vietnam', '🇻🇳', ['Hanoi', 'Ho Chi Minh City', 'Vietnam']),
            _D('Thailand', '🇹🇭', ['*Bangkok', 'Phuket', 'Thailand']),
            _D('Cambodia', '🇰🇭', ['Phnom Penh', 'Cambodia']),
            _D('Myanmar', '🇲🇲', ['Yangon', 'Mandalay', 'Naypyidaw', 'Myanmar']),
            _D('Bangladesh', '🇧🇩', ['Dhaka', 'Bangladesh']),
            _D('Nepal', '🇳🇵', ['Kathmandu', 'Nepal']),
            _D('India', '🇮🇳', ['*Delhi', '*New Delhi', '*Mumbai', 'Srinagar', 'Amritsar', 'Kashmir', 'India']),
            _D('Pakistan', '🇵🇰', ['Islamabad', 'Karachi', 'Lahore', 'Peshawar', 'Pakistan']),
            _D('Afghanistan', '🇦🇫', ['Kabul', 'Kandahar', 'Afghanistan']),
            _D('Sri Lanka', '🇱🇰', ['Colombo', 'Sri Lanka']),
            _D('Malaysia', '🇲🇾', ['*Kuala Lumpur', 'Malaysia']),
            _D('Indonesia', '🇮🇩', ['Jakarta', 'Bali', 'Indonesia']),
            _D('Singapore', '🇸🇬', ['*Singapore']),
            _D('Kazakhstan', '🇰🇿', ['Almaty', 'Astana', 'Kazakhstan']),
            _D('Kyrgyzstan', '🇰🇬', ['Bishkek', 'Kyrgyzstan']),
            _D('Tajikistan', '🇹🇯', ['Dushanbe', 'Tajikistan']),
            _D('Uzbekistan', '🇺🇿', ['Tashkent', 'Uzbekistan']),
            _D('Turkmenistan', '🇹🇲', ['Ashgabat', 'Turkmenistan']),
            _D('Mongolia', '🇲🇳', ['Ulaanbaatar', 'Mongolia']),
        ],
        'exclude': ['South China Sea', 'Indo-Pacific'],
    },
    'europe': {
        'name': 'Europe',
        'destinations': [
            _D('Ukraine', '🇺🇦', ['Kyiv', 'Kiev', 'Odesa', 'Odessa', 'Lviv', 'Kharkiv', 'Ukraine']),
            _D('Russia', '🇷🇺', ['Moscow', 'St Petersburg', 'St. Petersburg', 'Sochi', 'Kaliningrad', 'Russia']),
            _D('Belarus', '🇧🇾', ['Minsk', 'Belarus']),
            _D('Moldova', '🇲🇩', ['Chisinau', 'Chișinău', 'Moldova', 'Transnistria']),
            _D('Lithuania', '🇱🇹', ['Vilnius', 'Lithuania']),
            _D('Latvia', '🇱🇻', ['Riga', 'Latvia']),
            _D('Estonia', '🇪🇪', ['Tallinn', 'Estonia']),
            _D('Finland', '🇫🇮', ['*Helsinki', 'Finland']),
            _D('Poland', '🇵🇱', ['*Warsaw', 'Rzeszow', 'Rzeszów', 'Krakow', 'Poland']),
            _D('Georgia', '🇬🇪', ['Tbilisi']),
            _D('Armenia', '🇦🇲', ['Yerevan', 'Armenia']),
            _D('Azerbaijan', '🇦🇿', ['Baku', 'Azerbaijan', 'Nakhchivan']),
            _D('Serbia', '🇷🇸', ['Belgrade', 'Serbia']),
            _D('Kosovo', '🇽🇰', ['Pristina', 'Kosovo']),
            _D('Cyprus', '🇨🇾', ['Larnaca', 'Paphos', 'Cyprus']),
            _D('Greece', '🇬🇷', ['*Athens', 'Greece']),
            _D('Denmark', '🇩🇰', ['*Copenhagen', 'Aalborg', 'Billund', 'Denmark']),
            _D('Norway', '🇳🇴', ['*Oslo', 'Norway']),
            _D('Sweden', '🇸🇪', ['*Stockholm', 'Sweden']),
            _D('Germany', '🇩🇪', ['*Frankfurt', '*Munich', '*Berlin', 'Germany']),
            _D('Belgium', '🇧🇪', ['*Brussels', 'Liege', 'Liège', 'Belgium']),
            _D('Netherlands', '🇳🇱', ['*Amsterdam', '*Schiphol', 'Eindhoven', 'Netherlands']),
            _D('France', '🇫🇷', ['*Paris', 'France']),
            _D('United Kingdom', '🇬🇧', ['*London', '*Heathrow', '*Gatwick', 'United Kingdom', 'Britain']),
            _D('Hungary', '🇭🇺', ['Budapest', 'Hungary']),
            _D('Romania', '🇷🇴', ['Bucharest', 'Romania']),
        ],
        'exclude': ['Georgia Tech', 'New Mexico', 'Paris Hilton', 'Paris Agreement'],
    },
    'wha': {
        'name': 'Western Hemisphere',
        'destinations': [
            _D('Venezuela', '🇻🇪', ['Caracas', 'Maracaibo', 'Venezuela']),
            _D('Cuba', '🇨🇺', ['Havana', 'Cuba']),
            _D('Haiti', '🇭🇹', ['Port-au-Prince', 'Cap-Haitien', 'Cap-Haïtien', 'Haiti']),
            _D('Nicaragua', '🇳🇮', ['Managua', 'Nicaragua']),
            _D('Honduras', '🇭🇳', ['Tegucigalpa', 'San Pedro Sula', 'Roatan', 'Honduras']),
            _D('Guatemala', '🇬🇹', ['Guatemala']),
            _D('El Salvador', '🇸🇻', ['San Salvador', 'El Salvador']),
            _D('Colombia', '🇨🇴', ['*Bogota', '*Bogotá', 'Medellin', 'Medellín', 'Colombia']),
            _D('Ecuador', '🇪🇨', ['Quito', 'Guayaquil', 'Ecuador']),
            _D('Peru', '🇵🇪', ['*Lima', 'Cusco', 'Peru']),
            _D('Bolivia', '🇧🇴', ['La Paz', 'Santa Cruz', 'Bolivia']),
            _D('Chile', '🇨🇱', ['Chile']),
            _D('Argentina', '🇦🇷', ['Buenos Aires', 'Argentina']),
            _D('Brazil', '🇧🇷', ['*Sao Paulo', '*São Paulo', 'Rio de Janeiro', 'Brasilia', 'Brazil']),
            _D('Mexico', '🇲🇽', ['*Mexico City', 'Cancun', 'Cancún', 'Monterrey', 'Guadalajara', 'Tijuana', 'Mexico']),
            _D('Panama', '🇵🇦', ['*Panama City', 'Panama']),
            _D('Dominican Republic', '🇩🇴', ['Santo Domingo', 'Punta Cana', 'Dominican Republic']),
            _D('Jamaica', '🇯🇲', ['Kingston', 'Montego Bay', 'Jamaica']),
            _D('Puerto Rico', '🇵🇷', ['San Juan', 'Puerto Rico']),
            _D('Trinidad and Tobago', '🇹🇹', ['Port of Spain', 'Trinidad']),
            _D('Guyana', '🇬🇾', ['Georgetown', 'Guyana']),
            _D('Greenland', '🇬🇱', ['Nuuk', 'Greenland']),
            _D('Canada', '🇨🇦', ['*Toronto', '*Montreal', '*Vancouver', 'Canada']),
            _D('United States', '🇺🇸', ['*Miami', '*New York', '*Atlanta', 'U.S. airports', 'US airports',
                                        'U.S. flights', 'US flights', 'United States']),
        ],
        'exclude': ['New Mexico', 'Lima Peru Temple', 'Kingston upon Thames', 'Santa Cruz County'],
    },
}

# Africa's hand-kept list of long-running suspensions: true, but no newsroom
# will write about them this month, so a 30-day scan cannot see them. Shown as
# a separate "standing" strip with its review date. Each entry retires itself
# when the live scan sees a newer headline for the same airline + country.
STANDING = {
    'africa': {
        'reviewed': '2026-05-24',
        'items': [
            {'airline': 'Lufthansa', 'route': 'Frankfurt → Khartoum', 'country': 'Sudan', 'status': 'Suspended',
             'since': '2023-04-15', 'reason': 'Sudan war; airport non-operational', 'source_url': 'https://www.lufthansa.com/'},
            {'airline': 'EgyptAir', 'route': 'Cairo → Khartoum', 'country': 'Sudan', 'status': 'Suspended',
             'since': '2023-04-15', 'reason': 'Sudan war; humanitarian charters only', 'source_url': 'https://www.egyptair.com/'},
            {'airline': 'Air France', 'route': 'Paris → Bamako', 'country': 'Mali', 'status': 'Suspended',
             'since': '2024-01-10', 'reason': 'Security situation / political tensions', 'source_url': 'https://www.airfrance.fr/'},
            {'airline': 'Air France', 'route': 'Paris → Niamey', 'country': 'Niger', 'status': 'Suspended',
             'since': '2023-08-01', 'reason': 'Post-coup diplomatic rupture', 'source_url': 'https://www.airfrance.fr/'},
            {'airline': 'Kenya Airways', 'route': 'Nairobi → Goma', 'country': 'DR Congo', 'status': 'Suspended',
             'since': '2026-05-15', 'reason': 'Ebola quarantine zone + M23', 'source_url': 'https://www.kenya-airways.com/'},
            {'airline': 'RwandAir', 'route': 'Kigali → Goma', 'country': 'DR Congo', 'status': 'Suspended',
             'since': '2026-05-18', 'reason': 'Ebola + DRC-Rwanda tensions', 'source_url': 'https://www.rwandair.com/'},
            {'airline': 'Brussels Airlines', 'route': 'Brussels → Goma', 'country': 'DR Congo', 'status': 'Suspended',
             'since': '2026-05-15', 'reason': 'Ebola PHEIC (Kinshasa operating with screening)', 'source_url': 'https://www.brusselsairlines.com/'},
            {'airline': 'Ethiopian Airlines', 'route': 'Addis Ababa → Mogadishu', 'country': 'Somalia', 'status': 'Disrupted',
             'since': '2026-05-01', 'reason': 'Al-Shabaab threat; periodic schedule changes', 'source_url': 'https://www.ethiopianairlines.com/'},
        ],
    },
}


# ========================================
# AIRLINES
# Full names match anywhere. Ambiguous short names (Delta, United...) match only
# when followed by an airline-ish word ("Delta suspends", "United flights").
# ========================================
AIRLINES = [
    # Europe
    'Lufthansa Group', 'Lufthansa', 'Air France-KLM', 'Air France', 'KLM', 'British Airways', 'IAG',
    'Brussels Airlines', 'Swiss International', 'Austrian Airlines', 'Eurowings', 'ITA Airways',
    'Iberia', 'Vueling', 'Air Europa', 'TAP Air Portugal', 'TAP Portugal', 'Aer Lingus', 'Finnair',
    'Scandinavian Airlines', 'Norwegian Air', 'Icelandair', 'LOT Polish Airlines', 'LOT',
    'airBaltic', 'Air Baltic', 'Aegean Airlines', 'Croatia Airlines', 'Air Serbia',
    'Wizz Air', 'Ryanair', 'easyJet', 'EasyJet', 'Transavia', 'Volotea', 'Condor', 'TUI', 'Jet2',
    'Pegasus Airlines', 'SunExpress', 'AJet', 'AnadoluJet', 'Turkish Airlines',
    'Aeroflot', 'S7 Airlines', 'Pobeda', 'Rossiya', 'Ural Airlines', 'Belavia', 'Azerbaijan Airlines',
    'Georgian Airways', 'Air Moldova', 'Cyprus Airways', 'Ukraine International',
    # Middle East
    'Emirates', 'Etihad Airways', 'Etihad', 'flydubai', 'Air Arabia', 'Qatar Airways', 'Saudia',
    'flynas', 'flyadeal', 'Riyadh Air', 'Gulf Air', 'Kuwait Airways', 'Jazeera Airways', 'Oman Air',
    'SalamAir', 'Royal Jordanian', 'Middle East Airlines', 'El Al', 'Arkia', 'Israir', 'Iran Air',
    'Mahan Air', 'Iraqi Airways', 'Syrian Air', 'Cham Wings', 'Yemenia', 'EgyptAir', 'Egypt Air',
    'Air Cairo', 'Nile Air',
    # Africa
    'Ethiopian Airlines', 'Kenya Airways', 'RwandAir', 'Uganda Airlines', 'Air Tanzania', 'South African Airways',
    'Airlink', 'Royal Air Maroc', 'Air Algerie', 'Air Algérie', 'Tunisair', 'Air Senegal', 'Air Peace',
    'Arik Air', 'ASKY', 'Air Côte d\'Ivoire', 'TAAG', 'Air Zimbabwe', 'Badr Airlines', 'Tarco Aviation',
    # Asia-Pacific
    'Air China', 'China Eastern', 'China Southern', 'Hainan Airlines', 'Cathay Pacific', 'EVA Air',
    'China Airlines', 'Starlux', 'Korean Air', 'Asiana', 'Japan Airlines', 'All Nippon Airways',
    'Singapore Airlines', 'Scoot', 'Thai Airways', 'Malaysia Airlines', 'AirAsia', 'Garuda Indonesia',
    'Philippine Airlines', 'Cebu Pacific', 'Vietnam Airlines', 'VietJet', 'Air India Express', 'Air India',
    'IndiGo', 'SpiceJet', 'Akasa Air', 'Pakistan International Airlines', 'PIA', 'Airblue', 'Biman',
    'SriLankan Airlines', 'Ariana Afghan', 'Kam Air', 'Uzbekistan Airways', 'Air Astana', 'Qantas',
    'Jetstar', 'Air New Zealand', 'Air Koryo', 'Myanmar Airways',
    # Americas
    'American Airlines', 'United Airlines', 'Delta Air Lines', 'Delta Airlines', 'Southwest Airlines',
    'JetBlue', 'Spirit Airlines', 'Frontier Airlines', 'Alaska Airlines', 'Air Canada', 'WestJet',
    'Sunwing', 'Avianca', 'LATAM', 'Copa Airlines', 'Aeromexico', 'Aeroméxico', 'Volaris',
    'Viva Aerobus', 'Conviasa', 'Cubana', 'Arajet', 'Caribbean Airlines', 'Aerolineas Argentinas',
    'Aerolíneas Argentinas', 'Azul', 'GOL', 'Sky Airline', 'interJet', 'Laser Airlines',
]
AMBIGUOUS_AIRLINES = {'Delta': 'Delta Air Lines', 'United': 'United Airlines', 'American': 'American Airlines',
                      'Swiss': 'Swiss International', 'Spirit': 'Spirit Airlines', 'Frontier': 'Frontier Airlines',
                      'Southwest': 'Southwest Airlines', 'ANA': 'All Nippon Airways', 'JAL': 'Japan Airlines',
                      'MEA': 'Middle East Airlines', 'SAS': 'Scandinavian Airlines', 'Norwegian': 'Norwegian Air',
                      'Aegean': 'Aegean Airlines', 'Pegasus': 'Pegasus Airlines', 'Copa': 'Copa Airlines'}
CANONICAL = {'Egypt Air': 'EgyptAir', 'Air Baltic': 'airBaltic', 'Norwegian': 'Norwegian Air', 'Etihad': 'Etihad Airways',
             'Aegean': 'Aegean Airlines', 'Pegasus': 'Pegasus Airlines', 'Copa': 'Copa Airlines',
             'TAP Portugal': 'TAP Air Portugal', 'LOT': 'LOT Polish Airlines', 'Air Algérie': 'Air Algerie',
             'Aeroméxico': 'Aeromexico', 'Aerolíneas Argentinas': 'Aerolineas Argentinas', 'EasyJet': 'easyJet',
             'Delta Airlines': 'Delta Air Lines', 'AnadoluJet': 'AJet', 'PIA': 'Pakistan International Airlines'}

_AMBIG_RX = re.compile(r"\b(" + '|'.join(AMBIGUOUS_AIRLINES) + r")\b(?=(?:'s)?\s+(?:Airlines?|Air Lines|flights?|"
                       r"suspend|suspends|cancel|cancels|halts?|pauses?|resumes?|extends?|will|has|is|says|to resume|to suspend))")


_CS_RX = re.compile(r'\b[A-Z]{2,5}\b|[A-Z]\.[A-Z]\.')


def _alias_rx(name):
    """Word boundaries that also work around apostrophes, accents and hyphens.
    Names carrying an acronym (US, UAE, DRC, LOT, KLM...) match case-sensitively,
    so 'a lot of flights' is never LOT Polish and 'help us' is never the US."""
    flags = 0 if _CS_RX.search(name) else re.I
    return re.compile(r'(?<![\w])' + re.escape(name) + r'(?![\w])', flags)


_AIRLINE_RX = [(a, _alias_rx(a)) for a in sorted(AIRLINES, key=len, reverse=True)]


# ========================================
# CLASSIFICATION
# ========================================
_FLIGHT_CTX_RX = re.compile(r'\b(flights?|service|services|routes?|airlines?|carriers?|airports?|airspace|'
                            r'operations|aviation|air travel|air links?|planes?)\b', re.I)
_NEG_RESUME_RX = re.compile(r"\b(?:not|n't|no)\s+(?:\w+\s+){0,2}resum|\b(?:delays?|postpones?|pushes back|"
                            r"defers?)\s+(?:the\s+)?(?:\w+\s+){0,2}resumption", re.I)
_EXTEND_RX = re.compile(r'\bextend(?:s|ed|ing)?\b[^.]{0,40}\b(?:suspension|halt|pause|cancell?ation|ban|'
                        r'stoppage)s?\b|\b(?:suspension|halt|cancell?ation)s?\b[^.]{0,20}\bextended\b', re.I)
_RESUME_RX = re.compile(r'\b(?:resum(?:e|es|ed|ing|ption)|restart(?:s|ed|ing)?|reinstat(?:e|es|ed|ing)|'
                        r'reopen(?:s|ed|ing)?|returns? to|back to|to return to)\b', re.I)
_CANCEL_RX = re.compile(r'\bcancel(?:s|led|ed|ling|ing|lation|lations)?\b|\bscrap(?:s|ped)?\b|\baxes?\b', re.I)
_SUSPEND_RX = re.compile(r'\b(?:suspend(?:s|ed|ing)?|suspension|halt(?:s|ed|ing)?|paus(?:e|es|ed|ing)|'
                         r'ground(?:s|ed)|stops? (?:all )?flights|stopped flights|clos(?:e|es|ed|ure)\b[^.]{0,25}\b(?:airport|airspace)|'
                         r'(?:airport|airspace)\b[^.]{0,25}\bclos(?:e|es|ed|ure)|drops? (?:route|service)|'
                         r'ban(?:s|ned)? (?:flights|overflights))', re.I)
_REROUTE_RX = re.compile(r'\b(?:divert(?:s|ed|ing)?|reroute(?:s|d)?|rerouting|avoid(?:s|ing)? (?:\w+ )?airspace)\b', re.I)


def classify_status(title):
    if _NEG_RESUME_RX.search(title) or _EXTEND_RX.search(title):
        return 'Extended'
    if _RESUME_RX.search(title) and not _SUSPEND_RX.search(re.sub(_RESUME_RX, ' ', title)):
        return 'Resumed'
    if _RESUME_RX.search(title):
        # "resumes Dubai flights, suspends Tehran" -- mixed; the suspension is the news
        return 'Suspended'
    if _CANCEL_RX.search(title):
        return 'Cancelled'
    if _SUSPEND_RX.search(title):
        return 'Suspended'
    if _REROUTE_RX.search(title):
        return 'Rerouted'
    return None


# ---- end dates ----------------------------------------------------------------
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS['sept'] = 9
_MON = r'(January|February|March|April|May|June|July|August|September|October|November|December|' \
       r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec)\.?(?![A-Za-z])'
_UNTIL_RX = re.compile(r'\b(?:until|till|through|thru|to|into)\s+(?:at\s+least\s+)?(?:(the\s+)?(end|mid|early|late)'
                       r'(?:\s+of|-)?\s*)?' + _MON + r'(?:\s+(\d{1,2})(?!\d)(?:st|nd|rd|th)?)?(?:,?\s+(20\d{2}))?', re.I)
_UNTIL_DAY_FIRST_RX = re.compile(r'\b(?:until|till|through|to)\s+(?:at\s+least\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+'
                                 + _MON + r'(?:,?\s+(20\d{2}))?', re.I)
_UNTIL_YEAR_RX = re.compile(r'\b(?:until|till|through|into)\s+(?:at\s+least\s+)?(?:(end of|early|mid-?|late)\s+)?(20\d{2})\b', re.I)
_WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
_UNTIL_WEEKDAY_RX = re.compile(r'\b(?:until|till|through)\s+(?:at\s+least\s+)?(?:next\s+)?(' + '|'.join(_WEEKDAYS) + r')\b', re.I)
_FOR_RX = re.compile(r'\bfor\s+(?:another\s+|a further\s+|at least\s+)?(\d+|one|two|three|four|five|six|seven|eight|'
                     r'ten|twelve|a)\s+(day|week|month)s?\b', re.I)
_SEASON_RX = re.compile(r'\b(?:through|until|for)\s+(?:the\s+)?(winter|summer)(?:\s+(?:season|schedule))?\b', re.I)
_INDEF_RX = re.compile(r'\b(?:indefinite(?:ly)?|until further notice|until further|no end date)\b', re.I)
_WORDNUM = {'one': 1, 'a': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'ten': 10, 'twelve': 12}


def _roll(month, day, year, pub):
    """Build a date; with no year, choose the next occurrence on/after the publication date."""
    y = year or pub.year
    day = min(day, calendar.monthrange(y, month)[1])
    d = datetime(y, month, day, tzinfo=timezone.utc)
    if not year and d < pub - timedelta(days=7):
        y += 1
        d = datetime(y, month, min(day, calendar.monthrange(y, month)[1]), tzinfo=timezone.utc)
    return d


def parse_until(title, pub):
    """-> (until_datetime or None, label, kind) kind: date | indefinite | none"""
    if _INDEF_RX.search(title):
        return None, 'Indefinite', 'indefinite'
    m = _UNTIL_DAY_FIRST_RX.search(title)
    if m:
        mon = _MONTHS[m.group(2).lower().rstrip('.')]
        d = _roll(mon, int(m.group(1)), int(m.group(3)) if m.group(3) else None, pub)
        return d, f"Until {d.strftime('%b')} {d.day}, {d.year}", 'date'
    m = _UNTIL_RX.search(title)
    if m:
        qual = (m.group(2) or '').lower()
        mon = _MONTHS[m.group(3).lower().rstrip('.')]
        year = int(m.group(5)) if m.group(5) else None
        if m.group(4):
            d = _roll(mon, int(m.group(4)), year, pub)
            return d, f"Until {d.strftime('%b')} {d.day}, {d.year}", 'date'
        y_probe = year or pub.year
        last = calendar.monthrange(y_probe, mon)[1]
        day = {'end': last, 'late': min(25, last), 'mid': 15, 'early': 5}.get(qual, 1)
        d = _roll(mon, day, year, pub)
        if qual == 'end':
            d = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        prefix = {'end': 'end of ', 'mid': 'mid-', 'early': 'early ', 'late': 'late '}.get(qual, '')
        return d, f"Until {prefix}{d.strftime('%B')} {d.year}", 'date'
    m = _UNTIL_WEEKDAY_RX.search(title)
    if m:
        target = _WEEKDAYS.index(m.group(1).lower())
        ahead = (target - pub.weekday()) % 7 or 7
        d = (pub + timedelta(days=ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
        return d, f"Until {d.strftime('%a %b')} {d.day}, {d.year}", 'date'
    m = _SEASON_RX.search(title)
    if m:
        if m.group(1).lower() == 'winter':
            y = pub.year + 1 if pub.month >= 4 else pub.year
            d = datetime(y, 3, 28, tzinfo=timezone.utc)
        else:
            y = pub.year if pub.month <= 10 else pub.year + 1
            d = datetime(y, 10, 25, tzinfo=timezone.utc)
        return d, f"Through the {m.group(1).lower()} season (~{d.strftime('%b')} {d.day}, {d.year})", 'date'
    m = _FOR_RX.search(title)
    if m:
        n = _WORDNUM.get(m.group(1).lower()) or int(m.group(1))
        unit = m.group(2).lower()
        delta = timedelta(days=n * {'day': 1, 'week': 7, 'month': 30}[unit])
        d = (pub + delta).replace(hour=0, minute=0, second=0, microsecond=0)
        return d, f"For {n} {unit}{'s' if n != 1 else ''} (~{d.strftime('%b')} {d.day}, {d.year})", 'date'
    m = _UNTIL_YEAR_RX.search(title)
    if m:
        y = int(m.group(2))
        if y >= pub.year:
            qual = (m.group(1) or '').lower().rstrip('-')
            mon = {'end of': 12, 'late': 10, 'mid': 6, 'early': 2}.get(qual, 1)
            d = datetime(y, mon, 1, tzinfo=timezone.utc)
            if qual == 'end of':
                d = datetime(y, 12, 31, tzinfo=timezone.utc)
            return d, f"Until {(qual + ' ') if qual else ''}{y}".replace('  ', ' '), 'date'
    return None, 'Unknown', 'none'


# ---- destinations ----------------------------------------------------------------
_PROFILE = None
_DEST_RX = []          # [(entry, alias_display, rx, is_hub)] for the active backend, longest alias first
_GLOBAL_NONHUB = []    # [(country_label, rx)] non-hub aliases of ALL regions (for the hub rule)
_GLOBAL_ALL = []       # [(country_label, alias_display, rx)] for origin detection
_EXCLUDE_RX = []


def _build_tables(backend):
    global _PROFILE, _DEST_RX, _GLOBAL_NONHUB, _GLOBAL_ALL, _EXCLUDE_RX
    _PROFILE = PROFILES[backend]
    rows = []
    for e in _PROFILE['destinations']:
        for a in e['aliases']:
            hub = a.startswith('*')
            name = a.lstrip('*')
            rows.append((e, name, _alias_rx(name), hub))
    _DEST_RX = sorted(rows, key=lambda r: len(r[1]), reverse=True)
    g_nonhub, g_all, excl = [], [], set()
    for p in PROFILES.values():
        excl.update(p.get('exclude', []))
        for e in p['destinations']:
            for a in e['aliases']:
                name = a.lstrip('*')
                g_all.append((e['label'], name, _alias_rx(name)))
                if not a.startswith('*'):
                    g_nonhub.append((e['label'], _alias_rx(name)))
    _GLOBAL_NONHUB = g_nonhub
    _GLOBAL_ALL = sorted(g_all, key=lambda r: len(r[1]), reverse=True)
    # region-specific excludes plus the shared ones that prevent cross-reads
    excl.update(['South Sudan'] if backend != 'africa' else [])
    _EXCLUDE_RX = [_alias_rx(x) for x in sorted(excl, key=len, reverse=True)]


def _blank(text, rx):
    return rx.sub(lambda m: ' ' * len(m.group(0)), text)


_PROTECT_RX = [_alias_rx('United Arab Emirates')]   # a country name that contains an airline name


def _blank_spans(text, spans):
    chars = list(text)
    for a, b in spans:
        chars[a:b] = ' ' * (b - a)
    return ''.join(chars)


def find_airlines(title):
    """-> (airlines found, headline with airline names blanked out)"""
    probe = title
    for rx in _PROTECT_RX:
        probe = _blank(probe, rx)
    found, spans = [], []
    for name, rx in _AIRLINE_RX:
        hit = False
        for m in rx.finditer(probe):
            spans.append(m.span())
            hit = True
        if hit:
            found.append(CANONICAL.get(name, name))
            probe = _blank(probe, rx)
    for m in _AMBIG_RX.finditer(probe):
        found.append(AMBIGUOUS_AIRLINES[m.group(1)])
        spans.append(m.span())
    out = []
    for a in found:
        if a not in out:
            out.append(a)
    return out[:MAX_AIRLINES_PER_HEADLINE], _blank_spans(title, spans)


def find_destinations(text):
    """text: headline with airline names already blanked. -> [(entry, alias, pos)]"""
    for rx in _EXCLUDE_RX:
        text = _blank(text, rx)
    hits = {}
    work = text
    for entry, name, rx, hub in _DEST_RX:
        m = rx.search(work)
        if not m:
            continue
        lab = entry['label']
        h = hits.setdefault(lab, {'entry': entry, 'alias': name, 'pos': m.start(), 'all_hub': True})
        if m.start() < h['pos']:
            h['alias'], h['pos'] = name, m.start()
        if not hub:
            h['all_hub'] = False
        work = _blank(work, rx)
    if not hits:
        return []
    # hub rule: drop a hub-only destination if the headline names any non-hub place anywhere
    nonhub_elsewhere = set()
    for lab, rx in _GLOBAL_NONHUB:
        if rx.search(text):
            nonhub_elsewhere.add(lab)
    out = []
    for lab, h in hits.items():
        if h['all_hub'] and (nonhub_elsewhere - {lab}):
            continue
        out.append((h['entry'], h['alias'], h['pos']))
    out.sort(key=lambda r: r[2])
    return out[:MAX_DEST_PER_HEADLINE]


def find_origin(text, dest_label):
    for lab, name, rx in _GLOBAL_ALL:
        if lab != dest_label and rx.search(text):
            return name
    return None


# ========================================
# HELPERS
# ========================================
def _now():
    return datetime.now(timezone.utc)


def _parse_pub(s):
    if not s:
        return None
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        d = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _split_source(title):
    t = _html.unescape(title or '').replace('’', "'").replace('‘', "'").strip()
    if ' - ' in t:
        head, src = t.rsplit(' - ', 1)
        if 0 < len(src) <= 60:
            return head.strip(), src.strip()
    return t, ''


def _rget(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return None
    try:
        r = requests.get(f"{UPSTASH_REDIS_URL}/get/{key}",
                         headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}, timeout=8)
        res = r.json().get('result')
        return json.loads(res) if res else None
    except Exception as e:
        print(f"[Flights] Redis get {key} error: {str(e)[:120]}")
        return None


def _rset(key, value):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN):
        return False
    try:
        r = requests.post(f"{UPSTASH_REDIS_URL}/set/{key}",
                          headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}",
                                   "Content-Type": "application/json"},
                          data=json.dumps(value, default=str), timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Flights] Redis set {key} error: {str(e)[:120]}")
        return False


# ========================================
# HEADLINE -> RECORDS
# ========================================
def parse_headline(raw_title, link, pub_str, now=None):
    """One Google News item -> list of records (one per airline x destination). [] = not a flight item."""
    now = now or _now()
    pub = _parse_pub(pub_str)
    if not pub:
        return []                                   # no date, no record -- never stamped "now"
    if pub > now + timedelta(hours=6):
        return []
    title, source = _split_source(raw_title)
    status = classify_status(title)
    if not status:
        return []
    airlines, rest = find_airlines(title)
    if not airlines and not _FLIGHT_CTX_RX.search(title):
        return []
    if airlines and not (_FLIGHT_CTX_RX.search(title) or status in ('Suspended', 'Cancelled', 'Extended', 'Resumed')):
        return []
    dests = find_destinations(rest)
    if not dests:
        return []
    until, until_label, kind = parse_until(title, pub)
    if not airlines:
        airlines = ['Several carriers'] if re.search(r'\b(airlines|carriers)\b', title, re.I) else ['Not named']
    recs = []
    for entry, alias, _pos in dests:
        origin = find_origin(rest, entry['label'])
        for a in airlines:
            recs.append({
                'airline': a,
                'country': entry['label'],
                'flag': entry['flag'],
                'destination': alias,
                'origin': origin or 'Various',
                'route': f"{origin} → {alias}" if origin else f"→ {alias}",
                'status': status,
                'date': pub.isoformat(),
                'publishedAt': pub.isoformat(),
                'since': pub.strftime('%b %d, %Y'),
                'until': until.isoformat() if until else None,
                'until_kind': kind,
                'duration': until_label,
                'headline': title[:200],
                'title': title[:200],
                'source': source,
                'source_url': link,
                'url': link,
            })
    return recs


def _key(r):
    if r['airline'] in ('Not named', 'Several carriers'):
        return (r['airline'], r['country'], re.sub(r'\W+', '', r['headline'].lower())[:60])
    return (r['airline'].lower(), r['country'])


def curate(records, now=None):
    """Newest per airline+country, then apply the retention windows. -> (active, resumed)"""
    now = now or _now()
    newest = {}
    for r in sorted(records, key=lambda x: x['date'], reverse=True):
        k = _key(r)
        if k not in newest:
            newest[k] = r
    active, resumed = [], []
    for r in newest.values():
        pub = _parse_pub(r['date'])
        age = (now - pub).days
        if r['status'] == 'Resumed':
            if age <= NEWS_WINDOW_DAYS:
                r['deadline_state'] = 'none'
                resumed.append(r)
            continue
        until = _parse_pub(r['until']) if r.get('until') else None
        if until:
            if until >= now and age <= DECLARED_WINDOW_DAYS:
                r['deadline_state'] = 'active'
            elif until < now and (now - until).days <= PASSED_GRACE_DAYS and age <= DECLARED_WINDOW_DAYS:
                r['deadline_state'] = 'passed'
            elif age <= NEWS_WINDOW_DAYS and until < now and (now - until).days > PASSED_GRACE_DAYS:
                continue                            # short suspension that has long expired
            else:
                continue
        elif r.get('until_kind') == 'indefinite':
            if age > INDEFINITE_WINDOW_DAYS:
                continue
            r['deadline_state'] = 'indefinite'
        else:
            if age > NEWS_WINDOW_DAYS:
                continue
            r['deadline_state'] = 'none'
        active.append(r)
    active.sort(key=lambda x: x['date'], reverse=True)
    resumed.sort(key=lambda x: x['date'], reverse=True)
    return active, resumed


def standing_for(backend, live_records):
    """Standing entries not superseded by any live headline for the same airline + country."""
    st = STANDING.get(backend)
    if not st:
        return [], None
    reviewed = datetime.fromisoformat(st['reviewed']).replace(tzinfo=timezone.utc)
    seen = {}
    for r in live_records:
        pub = _parse_pub(r['date'])
        if pub and pub > reviewed:
            k = (r['airline'].lower(), r['country'])
            if k not in seen or r['date'] > seen[k]['date']:
                seen[k] = r
    out = []
    for s in st['items']:
        k = (s['airline'].lower(), s['country'])
        if k in seen:
            continue
        flag = next((e['flag'] for e in PROFILES[backend]['destinations'] if e['label'] == s['country']), '')
        out.append(dict(s, flag=flag, data_as_of=st['reviewed'], headline=f"{s['status']} since {s['since']} (hand-kept entry)",
                        destination=s['route'].split('→')[-1].strip(), duration='Standing (reviewed list)'))
    return out, st['reviewed']


# ========================================
# SO-WHAT LINES
# ========================================
def _fmt_d(iso):
    d = _parse_pub(iso)
    return f"{d.strftime('%b')} {d.day}" if d else '?'


def build_lines(active, resumed, state, now=None):
    now = now or _now()
    if state == 'unread':
        return ['Airline sources unread this cycle -- this is not the same as no disruptions.']
    lines = []
    recent = [r for r in active if (now - _parse_pub(r['date'])).days <= 14 and r['status'] != 'Rerouted']
    by_country = {}
    for r in recent:
        if r['airline'] in ('Not named',):
            continue
        by_country.setdefault(r['country'], set()).add(r['airline'])
    ranked = sorted(by_country.items(), key=lambda kv: len(kv[1]), reverse=True)
    if ranked and len(ranked[0][1]) >= 2:
        c, airs = ranked[0]
        names = ', '.join(sorted(airs)[:4]) + (' and others' if len(airs) > 4 else '')
        lines.append(f"{len(airs)} carriers have suspended, cancelled or extended {c} service in the last 14 days "
                     f"({names}) -- the commercial sector is pricing in risk there.")
    elif ranked:
        c, airs = ranked[0]
        r = next(x for x in recent if x['country'] == c)
        verb = {'Suspended': 'suspended', 'Cancelled': 'cancelled',
                'Extended': 'extended its suspension of'}.get(r['status'], 'disrupted')
        when = r['duration'] if r['duration'] != 'Unknown' else 'no end date given'
        lines.append(f"{r['airline']} has {verb} {r['destination']} service ({when}; reported {_fmt_d(r['date'])}).")
    declared = sorted([r for r in active if r.get('deadline_state') == 'active' and r.get('until')],
                      key=lambda x: x['until'])
    if declared:
        parts = [f"{r['airline']} → {r['destination']} {_fmt_d(r['until'])}" for r in declared[:3]]
        lines.append('Declared return dates: ' + '; '.join(parts) + '. Watch whether they hold or slip.')
    passed = [r for r in active if r.get('deadline_state') == 'passed']
    if passed:
        r = passed[0]
        lines.append(f"{r['airline']} → {r['destination']}: the declared end date ({_fmt_d(r['until'])}) has passed with "
                     f"no resumption reported -- the suspension may have been quietly extended.")
    if resumed:
        mixed = sorted({r['country'] for r in resumed} & {r['country'] for r in recent})
        if mixed:
            lines.append(f"Mixed signals on {', '.join(mixed[:3])}: some carriers suspending while others return.")
        else:
            parts = [f"{r['airline']} → {r['destination']}" for r in resumed[:3]]
            lines.append(f"Resumptions ({len(resumed)}): " + '; '.join(parts) +
                         ' -- a de-escalation signal, if it holds.')
    if not lines:
        if state == 'partial':
            lines.append('Airline sources partly read; no carrier suspensions found in what was read.')
        else:
            lines.append(f"No carrier suspensions, cancellations or resumptions reported for watched "
                         f"{_PROFILE['name']} destinations in the last {NEWS_WINDOW_DAYS} days.")
    return lines[:4]


# ========================================
# SCAN
# ========================================
def _q(name):
    return f'"{name}"' if ' ' in name else name


def build_queries(backend):
    """Grouped Google News queries: the first alias (usually the capital) plus the
    country name for each destination, CHUNK places OR'd per query, two verb sets."""
    names = []
    for e in PROFILES[backend]['destinations']:
        als = [a.lstrip('*') for a in e['aliases']]
        names.append(als[0])
        if e['label'] in als and e['label'] != als[0]:
            names.append(e['label'])
    names = list(dict.fromkeys(names))
    chunks = [names[i:i + CHUNK] for i in range(0, len(names), CHUNK)]
    verbs_out = '(suspend OR suspends OR suspended OR cancels OR cancelled OR halts OR extends)'
    verbs_back = '(resume OR resumes OR resumed OR restart OR restarts)'
    qs = []
    for ch in chunks:
        where = '(' + ' OR '.join(_q(n) for n in ch) + ')'
        qs.append(f'{verbs_out} flights {where}')
        qs.append(f'{verbs_back} flights {where}')
    return qs


def fetch_query(q, timeout=12):
    url = GNEWS_URL.format(q=quote_plus(q))
    r = requests.get(url, timeout=timeout, headers={'User-Agent': FLIGHT_USER_AGENT})
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    root = ET.fromstring(r.content)
    out = []
    for it in root.findall('.//item')[:40]:
        t = it.find('title')
        l = it.find('link')
        p = it.find('pubDate')
        out.append(((t.text if t is not None else '') or '',
                    (l.text if l is not None else '') or '',
                    (p.text if p is not None else '') or ''))
    return out


def run_scan(backend=None, fetch=fetch_query, sleep=1.0, now=None):
    backend = backend or BACKEND
    if _PROFILE is None or _PROFILE is not PROFILES[backend]:
        _build_tables(backend)
    now = now or _now()
    qs = build_queries(backend)
    ok = 0
    errors = []
    records, seen_links, raw = [], set(), 0
    for q in qs:
        try:
            items = fetch(q)
            ok += 1
        except Exception as e:
            errors.append(f'{type(e).__name__}: {str(e)[:80]}')
            items = []
        for title, link, pub in items:
            raw += 1
            if link in seen_links:
                continue
            seen_links.add(link)
            records.extend(parse_headline(title, link, pub, now=now))
        if sleep:
            time.sleep(sleep)
    state = 'read' if ok == len(qs) else ('partial' if ok >= max(1, len(qs) // 2) else 'unread')
    active, resumed = curate(records, now=now)
    standing, reviewed = standing_for(backend, records)
    lines = build_lines(active, resumed, state, now=now)
    feed = active + resumed
    return {
        'success': True,
        'version': FLIGHT_WATCH_VERSION,
        'backend': backend,
        'region': PROFILES[backend]['name'],
        'state': state,
        'scanned_at': now.isoformat(),
        'timestamp': now.isoformat(),
        'last_updated': now.isoformat(),
        'source': 'Google News search (live) -- airline announcements',
        'sources': {'google_news': {'state': state, 'queries': len(qs), 'ok': ok, 'errors': errors[:3]}},
        'windows': {'news_days': NEWS_WINDOW_DAYS, 'declared_days': DECLARED_WINDOW_DAYS,
                    'indefinite_days': INDEFINITE_WINDOW_DAYS, 'passed_grace_days': PASSED_GRACE_DAYS},
        'lines': lines,
        'counts': {s: sum(1 for r in active if r['status'] == s)
                   for s in ('Suspended', 'Cancelled', 'Extended', 'Rerouted')} | {'Resumed': len(resumed)},
        'active': active,
        'resumptions': resumed,
        'standing': standing,
        'standing_reviewed': reviewed,
        # compatibility: every existing page reads one of these
        'disruptions': feed,
        'cancellations': feed,
        'count': len(feed),
        'total_disruptions': len(feed),
        'raw_items': raw,
        'records_parsed': len(records),
        'cached': True,
    }


def _unread_payload(reason):
    return {'success': True, 'version': FLIGHT_WATCH_VERSION, 'backend': BACKEND, 'state': 'unread',
            'warming': True, 'reason': reason, 'lines': build_lines([], [], 'unread') if _PROFILE else [],
            'active': [], 'resumptions': [], 'standing': standing_for(BACKEND, [])[0] if BACKEND else [],
            'standing_reviewed': (STANDING.get(BACKEND) or {}).get('reviewed'),
            'disruptions': [], 'cancellations': [], 'count': 0, 'total_disruptions': 0,
            'sources': {'google_news': {'state': 'unread'}}}


# ========================================
# FLASK REGISTRATION
# ========================================
BACKEND = None
K_LATEST = None


def configure(backend):
    global BACKEND, K_LATEST
    if backend not in PROFILES:
        raise ValueError(f'unknown backend {backend!r}')
    BACKEND = backend
    K_LATEST = f'flights:{backend}:latest'
    _build_tables(backend)
    return PROFILES[backend]


def read_latest():
    data = _rget(K_LATEST)
    if not data:
        return _unread_payload('first scan not finished yet')
    age = (_now() - (_parse_pub(data.get('scanned_at')) or _now())).total_seconds()
    if age > 3 * SCAN_INTERVAL_SEC and data.get('state') != 'unread':
        data['state'] = 'stale'
        data['stale_hours'] = round(age / 3600, 1)
    return data


def register_flight_endpoints(app, backend, legacy_routes=None, job_name=None):
    """backend: me | europe | asia | africa | wha.
    legacy_routes: paths the existing page widget already calls (e.g. ['/api/europe/flights']).
    The old route of the same path must be removed from app.py (Flask serves the first rule registered)."""
    from flask import jsonify
    configure(backend)
    job = job_name or f'flight_watch_{backend}'

    def api_flights():
        # Public: never scans. Reads what the leader's scanner wrote.
        return jsonify(read_latest())

    def api_flights_health():
        d = _rget(K_LATEST) or {}
        return jsonify({'version': FLIGHT_WATCH_VERSION, 'backend': BACKEND, 'state': d.get('state', 'unread'),
                        'scanned_at': d.get('scanned_at'), 'sources': d.get('sources', {}),
                        'counts': d.get('counts', {}), 'raw_items': d.get('raw_items'),
                        'records_parsed': d.get('records_parsed'), 'interval_hours': SCAN_INTERVAL_SEC // 3600,
                        'destinations': [e['label'] for e in PROFILES[backend]['destinations']],
                        'queries': build_queries(backend)})

    app.add_url_rule('/api/flights', 'flight_watch_payload', api_flights, methods=['GET'])
    app.add_url_rule('/api/flights/health', 'flight_watch_health', api_flights_health, methods=['GET'])
    for i, route in enumerate(legacy_routes or []):
        app.add_url_rule(route, f'flight_watch_legacy_{i}', api_flights, methods=['GET'])
    print(f"[Flights:{backend}] ✅ /api/flights, /api/flights/health"
          f"{', ' + ', '.join(legacy_routes) + ' (compat)' if legacy_routes else ''} -- "
          f"{len(PROFILES[backend]['destinations'])} destinations")

    def _loop():
        time.sleep(90)
        try:
            from instance_lock import my_turn as _my_turn
        except ImportError:
            _my_turn = lambda j: True   # single-instance backends: no lock module, always run
        while True:
            if not _my_turn(job):
                continue
            try:
                prev = _rget(K_LATEST)
                fresh = run_scan(backend)
                if fresh['state'] == 'unread' and prev and prev.get('state') in ('read', 'partial'):
                    prev['state'] = 'stale'
                    prev['last_error'] = fresh['sources']['google_news'].get('errors')
                    _rset(K_LATEST, prev)          # keep the last good read, labelled as such
                else:
                    _rset(K_LATEST, fresh)
                print(f"[Flights:{backend}] scan {fresh['state']}: {len(fresh['active'])} active, "
                      f"{len(fresh['resumptions'])} resumed, {fresh['raw_items']} raw items")
            except Exception as e:
                print(f"[Flights:{backend}] scan error: {type(e).__name__}: {str(e)[:200]}")
            time.sleep(SCAN_INTERVAL_SEC)

    threading.Thread(target=_loop, daemon=True).start()
    print(f"[Flights:{backend}] ✅ Background thread (every {SCAN_INTERVAL_SEC // 3600} h, leader only)")
