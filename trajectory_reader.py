"""
trajectory_reader.py
Asifah Analytics -- SHARED MODULE (deploy byte-identical to ALL backends)
v1.0.1 -- July 26, 2026

One reader for the directional question every spoke tracker now has to answer:

    IS THIS HUB GAINING OR LOSING GROUND HERE?

────────────────────────────────────────────────────────────────────────────
WHY THIS IS SHARED RATHER THAN PASTED
────────────────────────────────────────────────────────────────────────────
Four trackers need it today (Mali, Libya, Syria, Sudan) and every future spoke
will. Pasting it four times means four copies drifting apart, and the evidence
vocabulary is exactly the thing that must NOT drift -- a phrase that counts as
'territory_lost' in Mali has to count as 'territory_lost' in Syria or the
cross-spoke rollup compares nothing to nothing.

Same deployment discipline as gdelt_gateway.py and spoke_wheel_reader.py:
one file, byte-identical, all five backends, matching md5.

────────────────────────────────────────────────────────────────────────────
PER-HUB, NOT PER-COUNTRY
────────────────────────────────────────────────────────────────────────────
Mali watches one wheel. The others do not:

    Libya   dual-wheel -- Russia holds the east (Haftar), Turkey the west (GNU)
    Syria   four hubs  -- Turkey, Iran, Russia, Israel
    Sudan   three      -- Russia plug, UAE axis, SAF patron composite

A single country-level trajectory would force Libya to say one thing while it
is watching two wheels argue. So the reader is parameterised by hub, and a
tracker calls it once per hub it carries.

────────────────────────────────────────────────────────────────────────────
DIRECTION COMES FROM EVIDENCE, NEVER FROM A LEVEL
────────────────────────────────────────────────────────────────────────────
"Russia is lit in Libya" is true whether Russia is consolidating Benghazi or
losing it. Those are opposite reads. So direction is read from EVIDENCE CLASSES:

  CONTRACTING  territory_lost · materiel_loss · casualties · withdrawal ·
               client_hedging · agreement_lapsed · expulsion · partner_defection
  EXPANDING    agreement_signed · new_basing · rival_expelled ·
               concession_granted · dependency_deepening

Class BREADTH decides before volume. Four mentions of one lost convoy is one
event; four different evidence classes is a trend.

────────────────────────────────────────────────────────────────────────────
CLAIM DISCIPLINE
────────────────────────────────────────────────────────────────────────────
These corpora are claim-heavy -- insurgent and partisan-OSINT assertions,
unconfirmed by the parties involved. A trajectory built on an interested
party's claims will read whatever that party wants. Every read therefore
carries a `confidence` field, and a claim-only run stays labelled as such no
matter how many times it repeats.

KNOWN LIMIT, stated rather than hidden: a hub losing ground that NOBODY reports
reads as 'holding'. Quiet is not the same as stable and this sensor cannot tell
them apart. Surfaced in every payload as `caveat`.

USAGE:
    from trajectory_reader import read_trajectory
    tr = read_trajectory(articles, hub='russia', country='libya')
    # -> {'hub','country','direction','level','confidence','evidence_classes',...}

COPYRIGHT (c) 2025-2026 Asifah Analytics. All rights reserved.
"""

from datetime import datetime, timezone

__version__ = '1.0.1'


# ============================================================
# EVIDENCE VOCABULARY  (hub-agnostic core + per-hub extensions)
# ============================================================
# Core phrases work for any hub. {HUB} is substituted at read time so a single
# vocabulary serves Russia, Turkey, Iran, China, Israel and the US without
# maintaining five near-identical lists.
CORE_EVIDENCE = {
    'contracting': {
        'territory_lost': [
            'withdrew from', 'abandoned position', 'lost control of',
            'rebels entered', 'rebels control', 'seized from', 'fell to',
            'perte de', 'abandonn\u00e9 la position', 'rebelles contr\u00f4lent',
        ],
        'materiel_loss': [
            'helicopter shot down', 'aircraft downed', 'jet shot down',
            'vehicles destroyed', 'convoy destroyed', 'equipment lost',
            'drone shot down', 'h\u00e9licopt\u00e8re abattu', 'v\u00e9hicules d\u00e9truits',
        ],
        'casualties': [
            '{HUB} casualties', '{HUB} soldiers killed', '{HUB} killed',
            '{HUB} prisoners', 'pertes {HUB}', 'soldats {HUB} tu\u00e9s',
        ],
        'withdrawal': [
            '{HUB} withdraws', '{HUB} withdrawal', 'drawdown',
            '{HUB} reduces presence', 'pulled back', 'retrait {HUB}',
            'r\u00e9duction des effectifs', 'evacuat',
        ],
        'client_hedging': [
            'seeks alternatives', 'diversifies partners', 'new security partner',
            'turns to turkey', 'turns to china', 'turns to the west',
            'cherche partenaires', 'diversification',
        ],
        'agreement_lapsed': [
            'agreement not renewed', 'deal expired', 'contract lapsed',
            'accord non renouvel\u00e9', 'lease not renewed',
        ],
        'expulsion': [
            'expels {HUB}', '{HUB} expelled', 'orders {HUB} to leave',
            'expulsion des {HUB}', 'ordered out',
        ],
        'partner_defection': [
            'defects from', 'switches allegiance', 'breaks with {HUB}',
            'rompt avec', 'severs ties with {HUB}',
        ],
    },
    'expanding': {
        'agreement_signed': [
            '{HUB} agreement signed', 'new {HUB} deal', 'signed with {HUB}',
            'military cooperation signed', 'accord sign\u00e9', '25-year deal',
        ],
        'new_basing': [
            '{HUB} base', 'new {HUB} facility', 'base {HUB}', 'naval base',
            'air base agreement', 'port access granted',
        ],
        'rival_expelled': [
            'france expelled', 'us troops leave', 'minusma withdrawal',
            'western forces expelled', 'expulsion fran\u00e7aise',
            'd\u00e9part des forces occidentales', 'american forces withdraw',
        ],
        'concession_granted': [
            'mining concession', 'concession granted', 'oil concession',
            'concession mini\u00e8re', 'granted rights to',
        ],
        'dependency_deepening': [
            'more {HUB} troops', '{HUB} reinforcements', 'expanded {HUB} presence',
            'renforts {HUB}', 'pr\u00e9sence {HUB} accrue', 'additional deployment',
        ],
    },
}

# Hub name variants for {HUB} substitution — a corpus says "Wagner" and
# "Africa Corps" far more often than it says "Russia".
HUB_ALIASES = {
    'russia':  ['russia', 'russian', 'wagner', 'africa corps', 'russe', 'russes'],
    'turkey':  ['turkey', 'turkish', 'sadat', 'turquie', 'turc', 'turcs'],
    'iran':    ['iran', 'iranian', 'irgc', 'quds force', 'iranien'],
    'china':   ['china', 'chinese', 'chine', 'chinois'],
    'israel':  ['israel', 'israeli', 'idf', 'isra\u00e9lien'],
    'us':      ['us ', 'u.s.', 'american', 'africom', 'centcom'],
    'uae':     ['uae', 'emirati', 'emirates', '\u00e9mirats'],
}

CONFIRMING_SOURCE_HINTS = [
    'reuters', 'afp', 'associated press', 'bbc', 'le monde', 'rfi',
    'jeune afrique', 'crisis group', 'acled', 'un panel', 'human rights watch',
    'al jazeera', 'financial times',
]
CLAIM_SOURCE_HINTS = [
    'claimed', 'claim', 'rebels say', 'according to', 'osint', 'telegram',
    'unconfirmed', 'revendiqu\u00e9', 'selon', 'alleged',
]

# Evidence classes that describe the CLIENT rather than the hub. These are
# exempt from hub-name gating: the client acting is itself the evidence, and
# the useful cases are precisely the ones where the hub goes unmentioned.
CLIENT_SIDE_CLASSES = {'client_hedging', 'expulsion', 'partner_defection',
                       'agreement_lapsed', 'rival_expelled'}

MIN_CLASSES_FOR_DIRECTION = 1
VOLUME_BONUS_THRESHOLD    = 4


def _phrases_for(hub):
    """Expand {HUB} across that hub's aliases."""
    aliases = HUB_ALIASES.get(str(hub).lower(), [str(hub).lower()])
    out = {'contracting': {}, 'expanding': {}}
    for direction, classes in CORE_EVIDENCE.items():
        for cls, templates in classes.items():
            expanded = []
            for t in templates:
                if '{HUB}' in t:
                    expanded.extend(t.replace('{HUB}', a) for a in aliases)
                else:
                    expanded.append(t)
            out[direction][cls] = expanded
    return out


def read_trajectory(articles, hub='russia', country='', extra_evidence=None):
    """Directional read for ONE hub in ONE country.

    articles        list of {'title','description','source'} dicts
    hub             'russia' | 'turkey' | 'iran' | 'china' | 'israel' | 'us' | 'uae'
    country         slug, for the payload only
    extra_evidence  optional {'contracting': {cls: [phrases]}, 'expanding': {...}}
                    for theatre-specific language (Tartus, Benghazi, Kidal...)

    Never raises. Returns a payload with direction, magnitude, evidence
    classes, confidence and the standing caveat.
    """
    vocab = _phrases_for(hub)
    if isinstance(extra_evidence, dict):
        for direction, classes in extra_evidence.items():
            if direction not in vocab:
                continue
            for cls, phrases in (classes or {}).items():
                vocab[direction].setdefault(cls, [])
                vocab[direction][cls].extend(phrases)

    hub_tokens = HUB_ALIASES.get(str(hub).lower(), [str(hub).lower()])
    found = {'contracting': {}, 'expanding': {}}
    confirming = claim_only = 0

    for a in (articles or []):
        if not isinstance(a, dict):
            continue
        text = f"{a.get('title','')} {a.get('description','')}".lower()
        if not text.strip():
            continue
        # The article must actually be ABOUT this hub -- otherwise a generic
        # "vehicles destroyed" headline registers against every hub a tracker
        # carries.
        #
        # EXCEPT for client-side classes. `client_hedging` is definitionally
        # about the CLIENT shopping for alternatives -- "Bamako in talks over
        # Turkish drones" is evidence about Russia's position precisely because
        # it does NOT mention Russia. Requiring the hub to be named would gate
        # out the single most useful leading indicator we have: a regime whose
        # survival depends on one patron does not shop casually.
        hub_named = any(tok in text for tok in hub_tokens)

        hit = False
        for direction, classes in vocab.items():
            for cls, phrases in classes.items():
                if not hub_named and cls not in CLIENT_SIDE_CLASSES:
                    continue
                for p in phrases:
                    if p and p in text:
                        found[direction].setdefault(cls, [])
                        if len(found[direction][cls]) < 4:
                            found[direction][cls].append({
                                'phrase': p,
                                'title': str(a.get('title', ''))[:120],
                                'url': a.get('url', ''),
                                'source': a.get('source', ''),
                            })
                        hit = True
                        break
        if hit:
            blob = text + ' ' + str(a.get('source', '')).lower()
            if any(h in blob for h in CONFIRMING_SOURCE_HINTS):
                confirming += 1
            elif any(h in blob for h in CLAIM_SOURCE_HINTS):
                claim_only += 1

    n_c = sum(len(v) for v in found['contracting'].values())
    n_e = sum(len(v) for v in found['expanding'].values())
    c_cls, e_cls = len(found['contracting']), len(found['expanding'])

    # Class BREADTH before volume: four mentions of one lost convoy is one
    # event; four different evidence classes is a trend.
    if c_cls > e_cls or (c_cls == e_cls and n_c > n_e):
        direction = 'contracting' if c_cls >= MIN_CLASSES_FOR_DIRECTION else 'holding'
        magnitude = min(5, c_cls + (1 if n_c >= VOLUME_BONUS_THRESHOLD else 0))
    elif e_cls > c_cls or n_e > n_c:
        direction = 'expanding' if e_cls >= MIN_CLASSES_FOR_DIRECTION else 'holding'
        magnitude = min(5, e_cls + (1 if n_e >= VOLUME_BONUS_THRESHOLD else 0))
    else:
        direction, magnitude = 'holding', 0

    if confirming >= 2:
        confidence = 'multi_source'
    elif confirming >= 1:
        confidence = 'confirmed_partial'
    elif claim_only or n_c or n_e:
        confidence = 'claim_sourced'
    else:
        confidence = 'no_evidence'

    return {
        'hub': str(hub).lower(),
        'country': str(country).lower(),
        'direction': direction,
        'level': magnitude if direction != 'holding' else 0,
        'confidence': confidence,
        'evidence': found,
        'evidence_classes': {'contracting': sorted(found['contracting']),
                             'expanding': sorted(found['expanding'])},
        'confirming_sources': confirming,
        'claim_only_sources': claim_only,
        'caveat': ('Trajectory reads reporting, not ground truth. A hub losing '
                   'ground unreported registers as HOLDING -- quiet is not the '
                   'same as stable, and this sensor cannot tell them apart.'),
        'reader_version': __version__,
        'ts': datetime.now(timezone.utc).isoformat(),
    }


def read_multi_hub(articles, hubs, country='', extra_evidence=None):
    """Trajectory for SEVERAL hubs in one country.

    Libya is dual-wheel, Syria carries four hubs, Sudan three. Returns
    {hub: trajectory_payload} plus a `_contested` flag when two hubs are
    moving in OPPOSITE directions in the same theatre -- which is the read
    Libya exists to produce and a single country-level trajectory could
    never express.
    """
    out = {}
    for h in (hubs or []):
        extra = (extra_evidence or {}).get(h) if isinstance(extra_evidence, dict) else None
        out[h] = read_trajectory(articles, hub=h, country=country, extra_evidence=extra)
    dirs = {h: t['direction'] for h, t in out.items()}
    contracting = [h for h, d in dirs.items() if d == 'contracting']
    expanding   = [h for h, d in dirs.items() if d == 'expanding']
    out['_contested'] = {
        'active': bool(contracting and expanding),
        'contracting': contracting,
        'expanding': expanding,
        'note': ('One hub gaining while another loses in the same theatre is a '
                 'displacement read, not two unrelated country stories.')
                if (contracting and expanding) else '',
    }
    return out
