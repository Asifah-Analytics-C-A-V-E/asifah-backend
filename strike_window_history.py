"""
strike_window_history.py
================================================================
ASIFAH ANALYTICS — Strike Window Pattern Memory v1.0.0
================================================================

Built May 22 2026 as companion to iran_strike_window_detector.py.

PURPOSE
-------
Post-hoc pattern recording + similarity matching for strike-window
detector. Three things this does:

  1. SNAPSHOT — every detection that hits elevated+ auto-snapshots its
     full signal state. Builds a passive baseline of "what convergence
     looks like over time."

  2. LABEL — when an actual event occurs (or notably doesn't), Coco
     manually labels it via /api/iran-strike-window/log-event. This
     associates a snapshot with ground truth:
       - kinetic_action     (strike actually happened)
       - averted            (signals there, action didn't happen)
       - diplomatic_pivot   (signals shifted to negotiation)
       - false_positive     (signals were noise)

  3. SIMILARITY MATCH — when current scan completes, compares its
     signal-set against all historical labeled events using Jaccard
     similarity. Returns top-N most similar past events with their
     outcomes.

NOT MACHINE LEARNING
--------------------
This is post-hoc pattern memory + structural similarity matching.
No model training. No probability scoring. Simply:
  "Your current 5-signal pattern is 80% similar to event X
   (which was a kinetic action) and 60% similar to event Y
   (which was a false positive)."

The reader does the analysis. The platform shows the dots.

FUTURE-PROOFING
---------------
Snapshot schema is designed to support ML feature extraction later.
Each snapshot has structured features (active_signals as set, weights,
multipliers, composite). When/if we have 20+ labeled events, we can
train a model on this data. But we don't need to do that now.

================================================================
"""

import os
import json
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None


UPSTASH_REDIS_URL   = os.environ.get('UPSTASH_REDIS_URL')   or os.environ.get('UPSTASH_REDIS_REST_URL')
UPSTASH_REDIS_TOKEN = os.environ.get('UPSTASH_REDIS_TOKEN') or os.environ.get('UPSTASH_REDIS_REST_TOKEN')

# Redis key patterns
SNAPSHOT_INDEX_KEY = 'strike_window:snapshots:index'   # List of snapshot IDs
LABELED_EVENTS_KEY = 'strike_window:labeled_events'    # Hash of labeled events
SNAPSHOT_TTL_SECONDS = 365 * 24 * 3600   # 1 year — long-term pattern memory


# ════════════════════════════════════════════════════════════════════════
# REDIS HELPERS
# ════════════════════════════════════════════════════════════════════════

def _redis_get(key):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN and requests):
        return None
    try:
        resp = requests.get(
            f"{UPSTASH_REDIS_URL}/get/{key}",
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        data = resp.json()
        if data.get("result"):
            return json.loads(data["result"])
    except Exception as e:
        print(f"[Strike History] Redis get error: {str(e)[:100]}")
    return None


def _redis_set(key, value, ttl=SNAPSHOT_TTL_SECONDS):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN and requests):
        return False
    try:
        from urllib.parse import quote
        payload = quote(json.dumps(value), safe='')
        url = f"{UPSTASH_REDIS_URL}/set/{key}/{payload}"
        if ttl:
            url += f"?EX={ttl}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        return resp.status_code == 200
    except Exception as e:
        print(f"[Strike History] Redis set error: {str(e)[:100]}")
        return False


def _redis_lpush(key, value, max_entries=200):
    """LPUSH a value to a list, trim to max_entries."""
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN and requests):
        return False
    try:
        from urllib.parse import quote
        payload = quote(json.dumps(value), safe='')
        url = f"{UPSTASH_REDIS_URL}/lpush/{key}/{payload}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        if resp.status_code != 200:
            return False

        # Trim list to max_entries
        trim_url = f"{UPSTASH_REDIS_URL}/ltrim/{key}/0/{max_entries - 1}"
        requests.post(
            trim_url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        return True
    except Exception as e:
        print(f"[Strike History] Redis lpush error: {str(e)[:100]}")
        return False


def _redis_lrange(key, start=0, stop=49):
    if not (UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN and requests):
        return []
    try:
        url = f"{UPSTASH_REDIS_URL}/lrange/{key}/{start}/{stop}"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"},
            timeout=5,
        )
        if resp.status_code != 200:
            return []
        result = resp.json().get('result', [])
        from urllib.parse import unquote
        parsed = []
        for entry in result or []:
            try:
                decoded = unquote(entry) if isinstance(entry, str) else entry
                parsed.append(json.loads(decoded))
            except Exception:
                continue
        return parsed
    except Exception as e:
        print(f"[Strike History] Redis lrange error: {str(e)[:100]}")
        return []


# ════════════════════════════════════════════════════════════════════════
# SNAPSHOT MANAGEMENT
# ════════════════════════════════════════════════════════════════════════

def save_snapshot(detection_result):
    """Save a detection result snapshot to the historical index.

    Auto-called by the detector when severity >= elevated. Stored in a
    Redis list (newest-first) with 1-year TTL.

    Returns the snapshot_id.
    """
    if not detection_result:
        return None

    # Build minimal-but-useful snapshot
    timestamp = detection_result.get('timestamp') or datetime.now(timezone.utc).isoformat()
    snapshot_id = f"swsnap_{timestamp.replace(':', '').replace('-', '').replace('T', '_').split('.')[0]}"

    snapshot = {
        'snapshot_id':           snapshot_id,
        'timestamp':             timestamp,
        'severity':              detection_result.get('severity', 'unknown'),
        'composite_score':       detection_result.get('composite_score', 0),
        'base_score':            detection_result.get('base_score', 0),
        'multiplier_total':      detection_result.get('multiplier_total', 1.0),
        'active_signals':        detection_result.get('active_signals', []),
        'active_multipliers':    detection_result.get('active_multipliers', []),
        'active_signal_count':   detection_result.get('active_signal_count', 0),
        'articles_analyzed':     detection_result.get('articles_analyzed', 0),
        # Compact rationale string for human-readable history scanning
        'rationale':             (detection_result.get('rationale') or '')[:300],
        # ML-friendly feature vector (boolean signal presence per type)
        'feature_vector': {
            'iran_airspace':       'iran_airspace'       in detection_result.get('active_signals', []),
            'regional_notams':     'regional_notams'     in detection_result.get('active_signals', []),
            'pre_strike_posture':  'pre_strike_posture'  in detection_result.get('active_signals', []),
            'embassy_posture':     'embassy_posture'     in detection_result.get('active_signals', []),
            'adversary_defensive': 'adversary_defensive' in detection_result.get('active_signals', []),
            'principal_friction':  'principal_friction'  in detection_result.get('active_signals', []),
            'rumored':             'rumored'             in detection_result.get('active_signals', []),
            'us_long_weekend':     'us_long_weekend'     in detection_result.get('active_multipliers', []),
            'religious_window':    'religious_window'    in detection_result.get('active_multipliers', []),
            'dark_lunar_window':   'dark_lunar_window'   in detection_result.get('active_multipliers', []),
            'potus_anomaly':       'potus_anomaly'       in detection_result.get('active_multipliers', []),
        },
        # Labels (filled in later when an event is logged)
        'labeled': False,
        'event_id': None,
        'event_type': None,
        'event_label': None,
    }

    # Push to the snapshot list (newest-first, capped at 200)
    success = _redis_lpush(SNAPSHOT_INDEX_KEY, snapshot, max_entries=200)
    if success:
        print(f"[Strike History] Snapshot saved: {snapshot_id} (severity: {snapshot['severity']})")
    return snapshot_id


def get_all_snapshots(limit=50):
    """Return historical snapshots, newest-first."""
    return _redis_lrange(SNAPSHOT_INDEX_KEY, 0, limit - 1)


def get_labeled_events():
    """Return all labeled events (manual ground-truth labels).

    Stored as a dict keyed by event_id.
    """
    events = _redis_get(LABELED_EVENTS_KEY) or {}
    return events


def log_labeled_event(event_id, event_label='', event_type='kinetic_action',
                       notes='', snapshot_id=None):
    """Manually label an event (kinetic_action, averted, etc).

    If snapshot_id is provided, also associates the snapshot with this label.
    Otherwise, attempts to find the most recent snapshot within ±48h of
    the current time and associates it.

    Args:
      event_id:     unique ID (e.g., "iran_strike_2026_05_25")
      event_label:  human description ("US/Israel strike on Iran nuclear facilities")
      event_type:   "kinetic_action" | "averted" | "diplomatic_pivot" |
                    "false_positive" | "convergence_observed"
      notes:        free text — Coco's analytical notes
      snapshot_id:  optional, associate a specific snapshot

    Returns the saved event dict.
    """
    events = get_labeled_events()
    now = datetime.now(timezone.utc).isoformat()

    event = {
        'event_id':       event_id,
        'event_label':    event_label,
        'event_type':     event_type,
        'notes':          notes,
        'logged_at':      now,
        'snapshot_id':    snapshot_id,
    }

    # If no specific snapshot, try to find a recent one
    if not snapshot_id:
        snapshots = get_all_snapshots(limit=10)
        if snapshots:
            event['snapshot_id'] = snapshots[0].get('snapshot_id')
            event['snapshot_data'] = snapshots[0]

    events[event_id] = event

    # Persist
    _redis_set(LABELED_EVENTS_KEY, events, ttl=SNAPSHOT_TTL_SECONDS)
    print(f"[Strike History] Event logged: {event_id} ({event_type})")
    return event


# ════════════════════════════════════════════════════════════════════════
# SIMILARITY MATCHING
# ════════════════════════════════════════════════════════════════════════

def _jaccard_similarity(set_a, set_b):
    """Standard Jaccard: |A intersect B| / |A union B|. Range 0.0 - 1.0."""
    a = set(set_a or [])
    b = set(set_b or [])
    if not a and not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def find_similar_events(current_active_signals, limit=5, min_similarity=0.3):
    """Find historical LABELED events most similar to the current signal pattern.

    Only considers events that have been manually labeled (have an event_type).
    Returns list of (event, similarity_score) pairs sorted by similarity desc.

    Args:
      current_active_signals:  list of active signal names from current detection
      limit:                   max results to return
      min_similarity:          minimum Jaccard score to include (default 0.3)
    """
    events = get_labeled_events()
    if not events:
        return []

    results = []
    for event_id, event in events.items():
        # Only consider labeled events that have a snapshot attached
        snap = event.get('snapshot_data')
        if not snap:
            continue
        past_signals = snap.get('active_signals', [])
        similarity = _jaccard_similarity(current_active_signals, past_signals)
        if similarity >= min_similarity:
            results.append({
                'event_id':       event_id,
                'event_label':    event.get('event_label', ''),
                'event_type':     event.get('event_type', 'unknown'),
                'logged_at':      event.get('logged_at', ''),
                'similarity':     round(similarity, 3),
                'past_signals':   past_signals,
                'past_severity':  snap.get('severity', 'unknown'),
                'past_composite': snap.get('composite_score', 0),
                'notes':          event.get('notes', ''),
            })

    # Sort by similarity descending
    results.sort(key=lambda r: r['similarity'], reverse=True)
    return results[:limit]


# ════════════════════════════════════════════════════════════════════════
# ANALYTICAL SUMMARY
# ════════════════════════════════════════════════════════════════════════

def get_history_summary():
    """Return high-level summary of historical data.

    Used by /api/iran-strike-window/history endpoint.
    """
    snapshots = get_all_snapshots(limit=200)
    events = get_labeled_events()

    # Snapshot severity distribution
    severity_counts = {'elevated': 0, 'high': 0, 'critical': 0}
    for s in snapshots:
        sev = s.get('severity', 'normal')
        if sev in severity_counts:
            severity_counts[sev] += 1

    # Event type distribution
    event_type_counts = {}
    for ev in events.values():
        et = ev.get('event_type', 'unknown')
        event_type_counts[et] = event_type_counts.get(et, 0) + 1

    return {
        'total_snapshots':       len(snapshots),
        'severity_distribution': severity_counts,
        'total_labeled_events':  len(events),
        'event_type_distribution': event_type_counts,
        'earliest_snapshot':     snapshots[-1].get('timestamp') if snapshots else None,
        'latest_snapshot':       snapshots[0].get('timestamp') if snapshots else None,
    }


# ════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("[Strike History] Self-test")
    print(f"  Summary: {get_history_summary()}")
    print(f"  Snapshots (latest 3): {len(get_all_snapshots(limit=3))}")
    print(f"  Labeled events: {len(get_labeled_events())}")
