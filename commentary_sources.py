"""
Asifah Analytics -- Commentary & Analysis SOURCES  (v1.0.1, Nov 5 2026 -- census: ISW + Chatham House via Google News)

The ONLY file to edit to add, drop or re-label a newsletter, institute or
YouTube channel. Read by think_tank_feeds.py v2.0.0.

THE COMMENTARY LANE (doctrine)
  These are people with opinions. They are shown, counted and compared --
  never scored. Nothing here can raise or lower an Asifah level. Their job:
    1. Context on a country page ("what the analysts are saying").
    2. The Cross-Spectrum Balance card: is one side of the spectrum talking
       about a country far more than the other this week? Lopsided attention
       is itself a signal -- it often runs ahead of policy.

HOW TO READ AN ENTRY
  id      short unique name
  name    display name
  kind    'newsletter' (Substack etc.), 'outlet' (magazine / site),
          'institute' (think tank), 'video' (YouTube channel)
  lean    'left', 'center-left', 'center', 'center-right', 'right',
          or 'nonpartisan' (institutes that do not take a side).
          Approximate editorial / audience lean, from widely used public
          media-bias ratings and the outlet's own self-description. It is a
          BALANCE label so the card can show both sides -- not a judgment of
          quality or truth. Disagree with one? Change it here.
  feed    the RSS / Atom URL (newsletters, outlets, institutes)
  youtube a channel handle ('@Perun') or a channel id ('UC...') -- videos only.
          Titles come from YouTube's free public channel feed: no key needed.
  focus   what they mostly cover: 'us', 'global', 'me', 'europe', 'asia',
          'africa', 'wha', 'defense', 'economy', 'china'
  verify  True = the feed address is a best guess; the debug link will say
          within one cycle whether it works. Fix or drop dead ones.

Balance check (count by lean, Nov 5 2026):
  left 4 · center-left 4 · center 8 · center-right 3 · right 6 · nonpartisan 3
  (left side 8, right side 9). The balance endpoint reports these counts live,
  so a dead feed on one side shows up as a lopsided card, not a silent one.
"""

COMMENTARY_SOURCES = [
    # ── Newsletters (Substack and similar; every Substack has /feed) ────
    {'id': 'letters_american', 'name': 'Letters from an American (Heather Cox Richardson)',
     'kind': 'newsletter', 'lean': 'left', 'focus': ['us'],
     'feed': 'https://heathercoxrichardson.substack.com/feed'},
    {'id': 'popular_info', 'name': 'Popular Information',
     'kind': 'newsletter', 'lean': 'left', 'focus': ['us'],
     'feed': 'https://popular.info/feed'},
    {'id': 'drop_site', 'name': 'Drop Site News',
     'kind': 'newsletter', 'lean': 'left', 'focus': ['me', 'global'],
     'feed': 'https://www.dropsitenews.com/feed'},
    {'id': 'slow_boring', 'name': 'Slow Boring (Matthew Yglesias)',
     'kind': 'newsletter', 'lean': 'center-left', 'focus': ['us', 'economy'],
     'feed': 'https://www.slowboring.com/feed'},
    {'id': 'noahpinion', 'name': 'Noahpinion (Noah Smith)',
     'kind': 'newsletter', 'lean': 'center-left', 'focus': ['economy', 'china', 'global'],
     'feed': 'https://www.noahpinion.blog/feed'},
    {'id': 'silver_bulletin', 'name': 'Silver Bulletin (Nate Silver)',
     'kind': 'newsletter', 'lean': 'center', 'focus': ['us'],
     'feed': 'https://www.natesilver.net/feed'},
    {'id': 'persuasion', 'name': 'Persuasion (Yascha Mounk)',
     'kind': 'newsletter', 'lean': 'center', 'focus': ['us', 'europe', 'global'],
     'feed': 'https://www.persuasion.community/feed'},
    {'id': 'pobrien', 'name': 'Phillips P. O\'Brien (war studies)',
     'kind': 'newsletter', 'lean': 'center', 'focus': ['defense', 'europe'],
     'feed': 'https://phillipspobrien.substack.com/feed'},
    {'id': 'chinatalk', 'name': 'ChinaTalk',
     'kind': 'newsletter', 'lean': 'center', 'focus': ['china', 'asia'],
     'feed': 'https://www.chinatalk.media/feed'},
    {'id': 'free_press', 'name': 'The Free Press',
     'kind': 'newsletter', 'lean': 'center-right', 'focus': ['us', 'me', 'global'],
     'feed': 'https://www.thefp.com/feed'},
    {'id': 'dispatch', 'name': 'The Dispatch',
     'kind': 'newsletter', 'lean': 'center-right', 'focus': ['us', 'global'],
     'feed': 'https://thedispatch.com/feed/'},   # census: healthy

    # ── Outlets (magazines / sites with an opinion line) ───────────────
    {'id': 'responsible_statecraft', 'name': 'Responsible Statecraft (Quincy Institute)',
     'kind': 'outlet', 'lean': 'center-left', 'focus': ['global', 'me', 'defense'],
     'feed': 'https://responsiblestatecraft.org/feed/',
     'note': 'Restraint school; draws writers from left and libertarian right.'},
    {'id': 'war_on_the_rocks', 'name': 'War on the Rocks',
     'kind': 'outlet', 'lean': 'center', 'focus': ['defense', 'global'],
     'feed': 'https://warontherocks.com/feed/'},
    {'id': 'american_conservative', 'name': 'The American Conservative',
     'kind': 'outlet', 'lean': 'right', 'focus': ['us', 'global'],
     'feed': 'https://www.theamericanconservative.com/feed/',
     'note': 'Restraint wing of the right.'},
    {'id': 'national_review', 'name': 'National Review',
     'kind': 'outlet', 'lean': 'right', 'focus': ['us', 'global'],
     'feed': 'https://www.nationalreview.com/feed/'},
    {'id': 'commentary_mag', 'name': 'Commentary',
     'kind': 'outlet', 'lean': 'right', 'focus': ['me', 'us', 'global'],
     'feed': 'https://www.commentary.org/feed/',
     'note': 'Hawkish wing of the right.'},
    {'id': 'free_beacon', 'name': 'Washington Free Beacon',
     'kind': 'outlet', 'lean': 'right', 'focus': ['us', 'me', 'china'],
     'feed': 'https://freebeacon.com/feed/'},

    # ── Institutes (nonpartisan analysis) ──────────────────────────────
    {'id': 'isw', 'name': 'Institute for the Study of War',
     'kind': 'institute', 'lean': 'nonpartisan', 'focus': ['europe', 'me', 'defense'],
     'feed': 'https://news.google.com/rss/search?q=site:understandingwar.org&hl=en&gl=US&ceid=US:en'},   # census: own feed 403
    {'id': 'csis', 'name': 'CSIS',
     'kind': 'institute', 'lean': 'nonpartisan', 'focus': ['global', 'defense', 'asia'],
     'feed': 'https://www.csis.org/rss.xml'},   # census: healthy
    {'id': 'chatham_house', 'name': 'Chatham House',
     'kind': 'institute', 'lean': 'nonpartisan', 'focus': ['europe', 'global', 'me'],
     'feed': 'https://news.google.com/rss/search?q=site:chathamhouse.org&hl=en&gl=US&ceid=US:en'},   # census: own feed 403

    # ── YouTube channels (titles + descriptions; keyless channel feed) ──
    {'id': 'yt_democracy_now', 'name': 'Democracy Now!',
     'kind': 'video', 'lean': 'left', 'focus': ['us', 'global', 'me'],
     'youtube': '@DemocracyNow'},
    {'id': 'yt_breaking_points', 'name': 'Breaking Points',
     'kind': 'video', 'lean': 'center', 'focus': ['us', 'global'],
     'youtube': '@breakingpoints',
     'note': 'Populist left + populist right hosts on one show.'},
    {'id': 'yt_perun', 'name': 'Perun (defence economics)',
     'kind': 'video', 'lean': 'center', 'focus': ['defense', 'europe'],
     'youtube': '@PerunAU'},
    {'id': 'yt_caspian', 'name': 'CaspianReport',
     'kind': 'video', 'lean': 'center', 'focus': ['global', 'me', 'asia'],
     'youtube': '@CaspianReport'},
    {'id': 'yt_pbs_newshour', 'name': 'PBS NewsHour',
     'kind': 'video', 'lean': 'center-left', 'focus': ['us', 'global'],
     'youtube': '@PBSNewsHour'},
    {'id': 'yt_tucker', 'name': 'Tucker Carlson Network',
     'kind': 'video', 'lean': 'right', 'focus': ['us', 'global'],
     'youtube': '@TuckerCarlson'},
    {'id': 'yt_megyn_kelly', 'name': 'The Megyn Kelly Show',
     'kind': 'video', 'lean': 'center-right', 'focus': ['us'],
     'youtube': '@MegynKelly'},
    {'id': 'yt_ben_shapiro', 'name': 'Ben Shapiro (Daily Wire)',
     'kind': 'video', 'lean': 'right', 'focus': ['us', 'me'],
     'youtube': '@BenShapiro'},
]
