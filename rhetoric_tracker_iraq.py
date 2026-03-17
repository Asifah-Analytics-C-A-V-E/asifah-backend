<!-- Asifah Analytics - Iraq Rhetoric Tracker v1.0.0 - March 2026 -->
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Iraq Rhetoric Tracker — Asifah Analytics</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
    /* ── THEME VARIABLES ── */
    :root {
        --bg-color: #f5f5f5;
        --container-bg: #ffffff;
        --card-bg: #ffffff;
        --card-border: #e1e8ed;
        --text-primary: #1a1a2e;
        --text-secondary: #4a5568;
        --text-muted: #718096;
        --article-bg: #f8f9fa;
        --accent: #c17f3a;
        --accent-glow: rgba(193,127,58,0.3);
        --card-glow: none;
        --card-hover-glow: 0 8px 20px rgba(0,0,0,0.12);
        --watermark-opacity: 0.07;
        --watermark-filter: none;
    }

    [data-theme="dark"] {
        --bg-color: #0d0b08;
        --container-bg: #111209;
        --card-bg: #111209;
        --card-border: #00c8d4;
        --text-primary: #e8d5a3;
        --text-secondary: #c4a96d;
        --text-muted: #8a7048;
        --article-bg: #0c0f0a;
        --accent: #d4943f;
        --accent-glow: rgba(212,148,63,0.25);
        --cyber-cyan: #00c8d4;
        --cyber-cyan-glow: rgba(0,200,212,0.18);
        --card-glow: 0 0 6px rgba(0,200,212,0.12), 0 0 1px rgba(0,200,212,0.25);
        --card-hover-glow: 0 0 22px rgba(0,200,212,0.28), 0 8px 25px rgba(0,0,0,0.5);
        --watermark-opacity: 0.22;
        --watermark-filter: saturate(5) brightness(0.9) hue-rotate(170deg);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
        font-family: 'Times New Roman', Times, serif;
        background-color: var(--bg-color);
        color: var(--text-primary);
        min-height: 100vh;
        transition: background-color 0.3s ease, color 0.3s ease;
    }

    /* Watermark */
    body::before {
        content: '';
        position: fixed;
        top: 50%; left: 50%;
        transform: translate(-50%, -50%);
        width: 110vmin; height: 110vmin;
        min-width: 800px; min-height: 800px;
        max-width: 1400px; max-height: 1400px;
        background-image: url('https://raw.githubusercontent.com/SassAndSweet/asifah-analytics/main/Asifah_Analytics_1_25_26_V1_LOGO.png');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        opacity: var(--watermark-opacity);
        filter: var(--watermark-filter);
        z-index: 0;
        pointer-events: none;
        user-select: none;
    }

    .container {
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
        position: relative;
        z-index: 1;
    }

    /* ── HEADER ── */
    header {
        background: linear-gradient(135deg, var(--bg-color), #1a1a0a);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 20px 25px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        gap: 18px;
        flex-wrap: wrap;
        position: relative;
    }
    [data-theme="dark"] header {
        background: linear-gradient(135deg, #0a0e08, #12160a);
        box-shadow: 0 6px 20px rgba(0,0,0,0.5), 0 0 40px var(--accent-glow), 0 0 60px rgba(0,200,212,0.08);
        border-bottom: 1px solid rgba(0,200,212,0.25);
    }
    .header-logo { width: 52px; height: 52px; border-radius: 50%; border: 2px solid var(--card-border); flex-shrink: 0; }
    .header-center { flex: 1; text-align: center; }
    .header-flag { font-size: 0.75rem; font-weight: 700; letter-spacing: 3px; color: var(--text-muted); text-transform: uppercase; }
    .header-title { font-family: 'Times New Roman', Times, serif; font-size: clamp(1.3rem, 3vw, 1.9rem); font-weight: 700; letter-spacing: 3px; text-transform: uppercase; color: var(--text-primary); margin: 4px 0; }
    .header-subtitle { font-size: 0.75rem; color: var(--text-muted); letter-spacing: 1px; }
    .header-timestamp { font-size: 0.65rem; color: var(--text-muted); margin-top: 4px; letter-spacing: 0.5px; }
    .header-right { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }

    /* Back link */
    .back-link {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 6px 14px; border-radius: 8px;
        border: 1px solid var(--card-border);
        color: var(--text-muted); font-size: 0.7rem; font-weight: 700;
        letter-spacing: 1px; text-decoration: none; text-transform: uppercase;
        transition: all 0.2s;
    }
    .back-link:hover { border-color: var(--accent); color: var(--accent); }

    /* Lang buttons */
    .lang-group { display: flex; gap: 4px; }
    .lang-btn {
        font-family: 'Times New Roman', Times, serif;
        padding: 4px 10px; border-radius: 6px;
        border: 1px solid var(--card-border);
        background: transparent; color: var(--text-muted);
        font-size: 0.7rem; font-weight: 700; cursor: pointer;
        transition: all 0.2s; letter-spacing: 0.5px;
    }
    .lang-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    [data-theme="dark"] .lang-btn.active { color: #0d0b08; }

    /* Theme toggle */
    .theme-row { display: flex; align-items: center; gap: 8px; }
    .theme-label { font-size: 0.6rem; color: var(--text-muted); letter-spacing: 1.5px; text-transform: uppercase; }
    .theme-toggle { position: relative; width: 48px; height: 24px; cursor: pointer; }
    .theme-toggle input { opacity: 0; width: 0; height: 0; }
    .theme-toggle-slider {
        position: absolute; inset: 0; border-radius: 12px;
        background: #ccc; transition: 0.3s;
        display: flex; align-items: center; padding: 2px;
    }
    [data-theme="dark"] .theme-toggle-slider { background: var(--accent); transform: none; }
    .theme-toggle-slider::before {
        content: '☀️'; width: 20px; height: 20px;
        border-radius: 50%; background: white;
        display: flex; align-items: center; justify-content: center;
        font-size: 12px; transition: 0.3s; margin-left: 0;
    }
    [data-theme="dark"] .theme-toggle-slider::before { content: '🌙'; margin-left: 24px; }

    /* ── HISTORY CHART (gold standard) ── */
    .history-chart-card { background: var(--container-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 22px; margin-bottom: 18px; box-shadow: var(--card-glow); }
    .history-chart-header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
    .history-chart-title { font-size: 0.7rem; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; color: var(--accent); }
    .history-toggle-group { display: flex; gap: 4px; background: rgba(0,0,0,0.2); border-radius: 6px; padding: 3px; }
    .history-toggle-btn { font-family: 'Times New Roman', Times, serif; font-size: 0.65rem; font-weight: 700; letter-spacing: 1px; padding: 4px 12px; border-radius: 4px; border: 1px solid transparent; cursor: pointer; text-transform: uppercase; background: transparent; color: var(--text-muted); transition: all 0.2s; }
    .history-toggle-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
    .history-toggle-btn:hover:not(.active) { border-color: var(--card-border); color: var(--text-primary); }
    [data-theme="dark"] .history-toggle-btn.compare.active { background: #00c8d4; border-color: #00c8d4; color: #0d0b08; }
    .history-chart-wrap { position: relative; height: 180px; }
    .history-empty { text-align: center; padding: 40px 20px; color: var(--text-muted); font-size: 0.75rem; letter-spacing: 1px; }
    .history-legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 10px; }
    .history-legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.6rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; }
    .history-legend-dot { width: 10px; height: 3px; border-radius: 2px; }

    /* ── SECTION CARDS ── */
    .section-card {
        background: var(--container-bg);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 22px;
        margin-bottom: 18px;
        box-shadow: var(--card-glow);
        transition: background 0.3s, border-color 0.3s, box-shadow 0.3s;
    }
    .section-card:hover { box-shadow: var(--card-hover-glow); }

    [data-theme="dark"] .section-card { box-shadow: var(--card-glow); border-color: var(--card-border); }
    [data-theme="dark"] .history-chart-card { box-shadow: var(--card-glow); border-color: var(--card-border); }

    .section-title {
        font-size: 0.7rem; font-weight: 700; letter-spacing: 2px;
        text-transform: uppercase; color: var(--accent);
        margin-bottom: 18px; padding-bottom: 10px;
        border-bottom: 1px solid var(--card-border);
    }

    /* ── THEATRE BANNER ── */
    .theatre-banner {
        background: var(--container-bg);
        border: 1px solid var(--card-border);
        border-radius: 12px;
        padding: 22px 28px;
        margin-bottom: 18px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 16px;
        box-shadow: var(--card-glow);
    }
    .theatre-score-big { font-size: clamp(3rem, 8vw, 5rem); font-weight: 900; line-height: 1; color: var(--accent); }
    .theatre-score-label { font-size: 0.65rem; letter-spacing: 2px; text-transform: uppercase; color: var(--text-muted); margin-top: 4px; }
    .theatre-badge { display: inline-block; padding: 5px 16px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: white; margin-top: 8px; }
    .theatre-right { text-align: right; }
    .theatre-escalation-label-text { font-size: 0.6rem; letter-spacing: 2px; text-transform: uppercase; color: var(--text-muted); }
    .theatre-level-display { font-size: clamp(1.2rem, 3vw, 1.6rem); font-weight: 700; margin: 4px 0; }
    .theatre-level-desc { font-size: 0.7rem; color: var(--text-muted); }
    .theatre-scan-info { font-size: 0.6rem; color: var(--text-muted); font-style: italic; margin-top: 4px; }

    /* ── VECTOR TABS ── */
    .vector-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 18px; }
    .vector-tab {
        background: var(--article-bg);
        border: 2px solid var(--card-border);
        border-radius: 8px;
        padding: 10px 16px;
        cursor: pointer;
        transition: all 0.2s;
        flex: 1;
        min-width: 140px;
        text-align: center;
    }
    .vector-tab:hover { box-shadow: var(--card-hover-glow); }
    .vector-tab.active { border-color: var(--accent); background: rgba(212,148,63,0.08); }
    [data-theme="dark"] .vector-tab.active { border-color: var(--cyber-cyan); background: rgba(0,200,212,0.08); }
    .vector-tab-icon { font-size: 1.2rem; margin-bottom: 4px; }
    .vector-tab-label { font-size: 0.6rem; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: var(--text-muted); }
    .vector-tab-level { font-size: 0.75rem; font-weight: 700; margin-top: 2px; }

    /* ── ESCALATION LADDER ── */
    .ladder-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
    .ladder-step {
        flex: 1; min-width: 70px;
        text-align: center; padding: 12px 6px;
        border-radius: 8px;
        border: 2px solid var(--card-border);
        background: var(--article-bg);
        transition: all 0.3s;
    }
    .ladder-step.active {
        background: rgba(212,148,63,0.1);
        box-shadow: 0 0 16px rgba(212,148,63,0.3);
    }
    [data-theme="dark"] .ladder-step.active { box-shadow: 0 0 16px rgba(0,200,212,0.25); }
    .ladder-step-num { font-size: 1.25rem; font-weight: 900; }
    .ladder-step-label { font-size: 0.55rem; letter-spacing: 1px; text-transform: uppercase; margin-top: 4px; }

    /* ── ACTORS GRID ── */
    .actors-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
    .actor-card {
        background: var(--article-bg);
        border: 1px solid var(--card-border);
        border-radius: 10px;
        padding: 16px;
        transition: all 0.3s;
    }
    .actor-card:hover { box-shadow: var(--card-hover-glow); transform: translateY(-2px); }
    .actor-header { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
    .actor-flag { font-size: 1.4rem; flex-shrink: 0; }
    .actor-name { font-size: 0.85rem; font-weight: 700; letter-spacing: 0.5px; }
    .actor-role { font-size: 0.6rem; color: var(--text-muted); letter-spacing: 0.5px; text-transform: uppercase; margin-top: 1px; }
    .actor-level-badge { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 0.6rem; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: white; margin-left: auto; flex-shrink: 0; }
    .actor-stats { display: flex; gap: 12px; font-size: 0.65rem; color: var(--text-muted); margin-bottom: 8px; }
    .actor-silence-alert {
        background: rgba(212,148,63,0.15);
        border: 1px solid rgba(212,148,63,0.4);
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 0.65rem;
        color: var(--accent);
        margin-top: 8px;
    }
    .vector-pills { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 8px; }
    .vector-pill {
        font-size: 0.55rem; font-weight: 700;
        padding: 2px 8px; border-radius: 3px;
        color: white; letter-spacing: 0.5px;
    }

    /* ── COORDINATION SIGNALS ── */
    .coord-item {
        background: var(--article-bg);
        border-left: 3px solid var(--accent);
        border-radius: 6px;
        padding: 10px 14px;
        margin-bottom: 10px;
        font-size: 0.75rem;
    }
    .coord-item.critical { border-left-color: #dc2626; background: rgba(220,38,38,0.08); }

    /* ── ARTICLES ── */
    .article-item {
        padding: 10px 0;
        border-bottom: 1px solid var(--card-border);
        font-size: 0.75rem;
    }
    .article-item:last-child { border-bottom: none; }
    .article-link { color: var(--accent); text-decoration: none; font-weight: 600; }
    .article-link:hover { text-decoration: underline; }
    .article-meta { font-size: 0.6rem; color: var(--text-muted); margin-top: 2px; }

    /* ── FOOTER ── */
    .page-footer { text-align: center; padding: 20px 0 30px; font-size: 0.6rem; color: var(--text-muted); letter-spacing: 1px; }

    /* ── RESPONSIVE ── */
    @media (max-width: 600px) {
        header { flex-direction: column; align-items: center; text-align: center; }
        .header-right { align-items: center; }
        .theatre-banner { flex-direction: column; text-align: center; }
        .theatre-right { text-align: center; }
        .vector-tab { min-width: 100px; padding: 8px 10px; }
        .actors-grid { grid-template-columns: 1fr; }
    }

    /* ── RTL ── */
    [dir="rtl"] .back-link { flex-direction: row-reverse; }
    [dir="rtl"] .coord-item { border-left: none; border-right: 3px solid var(--accent); }
    [dir="rtl"] .coord-item.critical { border-right-color: #dc2626; }
</style>
</head>
<body>
<div class="container">

    <!-- HEADER -->
    <header>
        <a href="index.html" class="back-link" data-i18n="backLink">← Back to Dashboard</a>
        <img src="https://raw.githubusercontent.com/SassAndSweet/asifah-analytics/main/Asifah_Analytics_1_25_26_V1_LOGO.png"
             class="header-logo" alt="Asifah Analytics"/>
        <div class="header-center">
            <div class="header-flag">🇮🇶 <span data-i18n="pageFlag">IRAQ</span></div>
            <div class="header-title" data-i18n="pageTitle">IRAQ RHETORIC TRACKER</div>
            <div class="header-subtitle" data-i18n="pageSubtitle">PMF · Kata'ib · Sadr · KRG · Iran · CENTCOM · ISIS Watch</div>
            <div class="header-timestamp">Last updated: <span id="lastUpdated" data-i18n="loading">Loading...</span></div>
        </div>
        <div class="header-right">
            <div class="lang-group">
                <button class="lang-btn active" onclick="setLanguage('en')">EN</button>
                <button class="lang-btn" onclick="setLanguage('ar')">ع</button>
                <button class="lang-btn" onclick="setLanguage('he')">עב</button>
                <button class="lang-btn" onclick="setLanguage('fa')">ف</button>
            </div>
            <div class="theme-row">
                <span class="theme-label" data-i18n="themeLabel">THEME</span>
                <label class="theme-toggle">
                    <input type="checkbox" id="themeToggle" onchange="toggleTheme()"/>
                    <span class="theme-toggle-slider"></span>
                </label>
            </div>
        </div>
    </header>

    <!-- THEATRE BANNER -->
    <div class="theatre-banner" id="theatreBanner">
        <div>
            <div class="theatre-score-big" id="theatreScore">--</div>
            <div class="theatre-score-label" data-i18n="scoreLabel">RHETORIC SCORE / 100</div>
            <div class="theatre-badge" id="theatreBadge" style="background:#6b7280;">--</div>
        </div>
        <div class="theatre-right">
            <div class="theatre-escalation-label-text" data-i18n="escalationLabel">THEATRE ESCALATION LEVEL</div>
            <div class="theatre-level-display" id="theatreLevelDisplay">--</div>
            <div class="theatre-level-desc" id="theatreLevelDesc">--</div>
            <div class="theatre-scan-info" id="theatreScanInfo" data-i18n="loading">Loading...</div>
        </div>
    </div>

    <!-- VECTOR TABS -->
    <div class="section-card">
        <div class="section-title" data-i18n="vectorTitle">⚡ THREAT VECTORS</div>
        <div class="vector-tabs" id="vectorTabs">
            <div class="vector-tab active" data-vector="pmf" onclick="setVector('pmf')">
                <div class="vector-tab-icon">⚔️</div>
                <div class="vector-tab-label" data-i18n="vecPMF">PMF Mobilization</div>
                <div class="vector-tab-level" id="vecLevelPMF">--</div>
            </div>
            <div class="vector-tab" data-vector="iran" onclick="setVector('iran')">
                <div class="vector-tab-icon">🚀</div>
                <div class="vector-tab-label" data-i18n="vecIran">Iran Direct Strikes</div>
                <div class="vector-tab-level" id="vecLevelIran">--</div>
            </div>
            <div class="vector-tab" data-vector="base" onclick="setVector('base')">
                <div class="vector-tab-icon">🛡️</div>
                <div class="vector-tab-label" data-i18n="vecBase">US Base Strikes</div>
                <div class="vector-tab-level" id="vecLevelBase">--</div>
            </div>
            <div class="vector-tab" data-vector="kurdish" onclick="setVector('kurdish')">
                <div class="vector-tab-icon">🏔️</div>
                <div class="vector-tab-label" data-i18n="vecKurd">Kurdish Tensions</div>
                <div class="vector-tab-level" id="vecLevelKurd">--</div>
            </div>
            <div class="vector-tab" data-vector="isis" onclick="setVector('isis')">
                <div class="vector-tab-icon">☠️</div>
                <div class="vector-tab-label" data-i18n="vecISIS">ISIS Resurgence</div>
                <div class="vector-tab-level" id="vecLevelISIS">--</div>
            </div>
        </div>
    </div>

    <!-- ESCALATION LADDER -->
    <div class="section-card">
        <div class="section-title" data-i18n="ladderTitle">🪜 ESCALATION LADDER</div>
        <div class="ladder-row" id="ladderRow"></div>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-top:15px;flex-wrap:wrap;gap:10px;">
            <div style="font-size:11px;color:var(--text-muted);" id="articlesClassified" data-i18n="articlesClassified">📰 Corresponding articles in Top Articles by Actor below</div>
            <button onclick="triggerScan()" id="scanBtn" style="
                background: var(--accent); color: white; border: none;
                padding: 8px 20px; border-radius: 8px; cursor: pointer;
                font-family: 'Times New Roman', Times, serif;
                font-size: 0.7rem; font-weight: 700; letter-spacing: 1px;
                display: flex; align-items: center; gap: 6px;
                transition: opacity 0.2s;
            ">
                🔄 <span data-i18n="refreshScan">Refresh Scan</span>
            </button>
        </div>
    </div>

    <!-- RHETORIC HISTORY CHART -->
    <div class="history-chart-card" id="historyCard">
        <div class="history-chart-header">
            <span class="history-chart-title">📈 <span data-i18n="trendTitle">RHETORIC TREND</span></span>
            <div class="history-toggle-group">
                <button class="history-toggle-btn active" id="btn7d" onclick="setHistoryView('7d')">7 DAY</button>
                <button class="history-toggle-btn" id="btn30d" onclick="setHistoryView('30d')">30 DAY</button>
                <button class="history-toggle-btn compare" id="btnCompare" onclick="setHistoryView('compare')">COMPARE</button>
            </div>
        </div>
        <div class="history-chart-wrap">
            <canvas id="historyChart"></canvas>
            <div class="history-empty" id="historyEmpty" style="display:none;">📡 <span data-i18n="chartEmpty">Collecting data — first snapshot saves on next scan cycle</span></div>
        </div>
        <div class="history-legend" id="historyLegend">
            <div class="history-legend-item"><div class="history-legend-dot" style="background:#22c55e;"></div> Iraq</div>
        </div>
    </div>

    <!-- COORDINATION SIGNALS -->
    <div class="section-card" id="coordCard" style="display:none;">
        <div class="section-title" data-i18n="coordTitle">⚡ COORDINATION SIGNALS</div>
        <div id="coordList"></div>
    </div>

    <!-- ACTOR STATUS GRID -->
    <div class="section-card">
        <div class="section-title" data-i18n="actorTitle">🎯 ACTOR STATUS</div>
        <div class="actors-grid" id="actorsGrid"></div>
    </div>

    <!-- TOP ARTICLES -->
    <div class="section-card" id="articlesSection">
        <div class="section-title" data-i18n="articlesTitle">📰 TOP ARTICLES BY ACTOR</div>
        <div id="articlesList"></div>
    </div>

    <!-- FOOTER -->
    <div class="page-footer">
        © 2025-2026 ASIFAH ANALYTICS — ALL RIGHTS RESERVED — v1.0.0-iraq |
        <a href="https://www.buymeacoffee.com/asifahanalytics" target="_blank" style="color:var(--accent);text-decoration:none;">☕ buy me a coffee</a>
    </div>

</div><!-- /container -->

<script>
    const API_BASE = 'https://asifah-backend.onrender.com';

    // ══════════════════════════════════════════════════════════════
    // RHETORIC HISTORY CHART — Gold Standard v1.0
    // ══════════════════════════════════════════════════════════════
    let _historyChart = null;
    let _historyView  = '7d';

    const HISTORY_CONFIG = {
        theatre:    'Iraq',
        historyUrl: API_BASE + '/api/rhetoric/iraq/history',
        color:      '#22c55e',  // Iraq: green
        compareTheatres: [
            { label: 'Iraq',    url: API_BASE + '/api/rhetoric/iraq/history',    color: '#22c55e' },
            { label: 'Syria',   url: API_BASE + '/api/rhetoric/syria/history',   color: '#d4943f' },
            { label: 'Lebanon', url: 'https://lebanon-stability-backend.onrender.com/api/rhetoric/lebanon/history', color: '#6495ed' },
            { label: 'Yemen',   url: API_BASE + '/api/rhetoric/yemen/history',   color: '#f97316' },
        ]
    };

    const LEVEL_ZONES = [
        { yMin: 0,  yMax: 20,  color: 'rgba(107,114,128,0.08)' },
        { yMin: 20, yMax: 40,  color: 'rgba(59,130,246,0.08)'  },
        { yMin: 40, yMax: 60,  color: 'rgba(245,158,11,0.10)'  },
        { yMin: 60, yMax: 80,  color: 'rgba(249,115,22,0.12)'  },
        { yMin: 80, yMax: 100, color: 'rgba(220,38,38,0.14)'   },
    ];

    const zoneBandPlugin = {
        id: 'zoneBands',
        beforeDraw(chart) {
            const { ctx, chartArea: { left, right }, scales: { y } } = chart;
            LEVEL_ZONES.forEach(zone => {
                const yTop = y.getPixelForValue(zone.yMax);
                const yBottom = y.getPixelForValue(zone.yMin);
                ctx.save(); ctx.fillStyle = zone.color;
                ctx.fillRect(left, Math.min(yTop,yBottom), right-left, Math.abs(yBottom-yTop));
                ctx.restore();
            });
        }
    };

    function _sliceEntries(entries, view) {
        if (!entries || entries.length === 0) return [];
        return view === '7d' ? entries.slice(-28) : entries;
    }
    function _fmtLabel(ts) {
        try { return new Date(ts).toLocaleDateString('en-US', { month:'short', day:'numeric' }); }
        catch { return ts; }
    }

    function renderHistoryChart(datasets, labels) {
        const canvas = document.getElementById('historyChart');
        const emptyEl = document.getElementById('historyEmpty');
        if (!canvas) return;
        if (!datasets || !datasets.length || !datasets[0].data.length) {
            canvas.style.display='none'; if(emptyEl) emptyEl.style.display='block'; return;
        }
        canvas.style.display='block'; if(emptyEl) emptyEl.style.display='none';
        if (_historyChart) { _historyChart.destroy(); _historyChart=null; }
        const isDark = document.documentElement.getAttribute('data-theme')==='dark';
        const gridColor = isDark?'rgba(255,255,255,0.05)':'rgba(0,0,0,0.06)';
        const tickColor = isDark?'#8a7048':'#8c7a5a';
        const fontFam = "'Times New Roman', Times, serif";
        _historyChart = new Chart(canvas.getContext('2d'), {
            type:'line', plugins:[zoneBandPlugin], data:{labels,datasets},
            options:{
                responsive:true, maintainAspectRatio:false, animation:{duration:400},
                interaction:{mode:'index',intersect:false},
                plugins:{
                    legend:{display:datasets.length>1, labels:{color:tickColor,font:{family:fontFam,size:10},boxWidth:20,boxHeight:2,usePointStyle:true,pointStyle:'line'}},
                    tooltip:{
                        backgroundColor:isDark?'#0d1b2e':'#fff',
                        borderColor:isDark?'rgba(0,200,212,0.3)':'rgba(0,0,0,0.1)',
                        borderWidth:1, titleColor:isDark?'#e8d5a3':'#2c2416', bodyColor:isDark?'#c4a96d':'#5c4a2a',
                        titleFont:{family:fontFam,size:11,weight:'bold'}, bodyFont:{family:fontFam,size:10},
                        callbacks:{label(ctx){const l=['Baseline','Rhetoric','Tension','Confrontation','Incident','Active Conflict']; return ` ${ctx.dataset.label||'Score'}: ${ctx.parsed.y} — ${l[Math.min(Math.floor(ctx.parsed.y/20),5)]||''}`;}}
                    }
                },
                scales:{
                    x:{grid:{color:gridColor},ticks:{color:tickColor,font:{family:fontFam,size:9},maxTicksLimit:8,maxRotation:0}},
                    y:{min:0,max:100,grid:{color:gridColor},ticks:{color:tickColor,font:{family:fontFam,size:9},stepSize:20,callback:v=>['BL','RH','TN','CF','IC','AC'][v/20]||v}}
                }
            }
        });
    }

    async function loadHistoryData() {
        try {
            const resp = await fetch(HISTORY_CONFIG.historyUrl+'?limit=120');
            if(!resp.ok) return;
            const data = await resp.json();
            const entries = _sliceEntries(data.entries||[], _historyView);
            const legendEl = document.getElementById('historyLegend');
            if(legendEl) legendEl.innerHTML=`<div class="history-legend-item"><div class="history-legend-dot" style="background:${HISTORY_CONFIG.color};"></div> ${HISTORY_CONFIG.theatre}</div>`;
            renderHistoryChart([{
                label:HISTORY_CONFIG.theatre, data:entries.map(e=>e.score??0),
                borderColor:HISTORY_CONFIG.color, backgroundColor:'rgba(34,197,94,0.07)',
                borderWidth:2, pointRadius:entries.length<15?3:0, pointHoverRadius:4, fill:true, tension:0.35
            }], entries.map(e=>_fmtLabel(e.ts)));
        } catch(e){ console.warn('[HistoryChart]',e); }
    }

    async function loadCompareData() {
        try {
            const results = await Promise.allSettled(
                HISTORY_CONFIG.compareTheatres.map(t=>fetch(t.url+'?limit=120').then(r=>r.ok?r.json():null))
            );
            let maxEntries=[];
            results.forEach(r=>{const e=r.status==='fulfilled'&&r.value?.entries?_sliceEntries(r.value.entries,_historyView):[];if(e.length>maxEntries.length)maxEntries=e;});
            const labels=maxEntries.map(e=>_fmtLabel(e.ts));
            const datasets=HISTORY_CONFIG.compareTheatres.map((t,i)=>{
                const e=results[i].status==='fulfilled'&&results[i].value?.entries?_sliceEntries(results[i].value.entries,_historyView):[];
                return{label:t.label,data:e.map(x=>x.score??0),borderColor:t.color,backgroundColor:'transparent',borderWidth:2,pointRadius:e.length<15?3:0,pointHoverRadius:4,fill:false,tension:0.35};
            });
            const legendEl=document.getElementById('historyLegend');
            if(legendEl) legendEl.innerHTML=HISTORY_CONFIG.compareTheatres.map(t=>`<div class="history-legend-item"><div class="history-legend-dot" style="background:${t.color};"></div> ${t.label}</div>`).join('');
            renderHistoryChart(datasets,labels);
        } catch(e){ console.warn('[HistoryChart compare]',e); }
    }

    function setHistoryView(mode) {
        _historyView=mode;
        document.getElementById('btn7d').classList.toggle('active',mode==='7d');
        document.getElementById('btn30d').classList.toggle('active',mode==='30d');
        document.getElementById('btnCompare').classList.toggle('active',mode==='compare');
        if(mode==='compare') loadCompareData(); else loadHistoryData();
    }

    // ══════════════════════════════════════════════════════════════
    // ESCALATION LEVELS — Gold Standard
    // ══════════════════════════════════════════════════════════════
    const ESCALATION_LEVELS = {
        0: { label:'Baseline',       color:'#6b7280', description:'No significant signals' },
        1: { label:'Rhetoric',       color:'#3b82f6', description:'Standard factional statements' },
        2: { label:'Tension',        color:'#f59e0b', description:'Warnings, mobilization language' },
        3: { label:'Confrontation',  color:'#f97316', description:'Direct threats, troop movements' },
        4: { label:'Incident',       color:'#ef4444', description:'Attacks confirmed, strikes reported' },
        5: { label:'Active Conflict',color:'#dc2626', description:'Ongoing operations, multiple fronts' },
    };

    // ══════════════════════════════════════════════════════════════
    // TRANSLATIONS
    // ══════════════════════════════════════════════════════════════
    const T = {
        en: {
            backLink:'← Back to Dashboard', pageFlag:'IRAQ', pageTitle:'IRAQ RHETORIC TRACKER',
            pageSubtitle:"PMF · Kata'ib · Sadr · KRG · Iran · CENTCOM · ISIS Watch",
            loading:'Loading...', scoreLabel:'RHETORIC SCORE / 100',
            escalationLabel:'THEATRE ESCALATION LEVEL',
            vectorTitle:'⚡ THREAT VECTORS',
            vecPMF:'PMF Mobilization', vecIran:'Iran Direct Strikes',
            vecBase:'US Base Strikes', vecKurd:'Kurdish Tensions', vecISIS:'ISIS Resurgence',
            ladderTitle:'🪜 ESCALATION LADDER',
            articlesClassified:'📰 Corresponding articles in Top Articles by Actor below',
            refreshScan:'Refresh Scan',
            trendTitle:'RHETORIC TREND',
            chartEmpty:'Collecting data — first snapshot saves on next scan cycle',
            coordTitle:'⚡ COORDINATION SIGNALS',
            actorTitle:'🎯 ACTOR STATUS',
            articlesTitle:'📰 TOP ARTICLES BY ACTOR',
            themeLabel:'THEME',
            silence:'⚠️ UNUSUAL SILENCE — below baseline activity',
            articles:'articles', maxLevel:'Max Level',
            pmfVec:'PMF', iranVec:'Iran', baseVec:'Base', kurdVec:'Kurd', isisVec:'ISIS',
        },
        ar: {
            backLink:'→ العودة للوحة التحكم', pageFlag:'العراق', pageTitle:'متتبع الخطاب العراقي',
            pageSubtitle:'الحشد الشعبي · كتائب · الصدر · إقليم كردستان · إيران · سنتكوم · مراقبة داعش',
            loading:'جارٍ التحميل...', scoreLabel:'نقاط الخطاب / 100',
            escalationLabel:'مستوى التصعيد المسرحي',
            vectorTitle:'⚡ محاور التهديد',
            vecPMF:'تعبئة الحشد', vecIran:'ضربات إيران المباشرة',
            vecBase:'ضربات القواعد الأمريكية', vecKurd:'التوترات الكردية', vecISIS:'تنامي داعش',
            ladderTitle:'🪜 سلم التصعيد',
            articlesClassified:'📰 المقالات المقابلة في قسم المقالات أدناه',
            refreshScan:'تحديث المسح',
            trendTitle:'اتجاه الخطاب',
            chartEmpty:'جمع البيانات — أول لقطة تُحفظ في دورة المسح القادمة',
            coordTitle:'⚡ إشارات التنسيق',
            actorTitle:'🎯 حالة الأطراف',
            articlesTitle:'📰 أبرز المقالات حسب الطرف',
            themeLabel:'المظهر',
            silence:'⚠️ صمت غير معتاد — نشاط أقل من المعتاد',
            articles:'مقالات', maxLevel:'أعلى مستوى',
            pmfVec:'الحشد', iranVec:'إيران', baseVec:'قاعدة', kurdVec:'كردي', isisVec:'داعش',
        },
        he: {
            backLink:'← חזרה ללוח הבקרה', pageFlag:'עיראק', pageTitle:'עוקב רטוריקה עיראק',
            pageSubtitle:"PMF · כתאיב · סאדר · KRG · איראן · CENTCOM · מעקב דאע\"ש",
            loading:'טוען...', scoreLabel:'ציון רטוריקה / 100',
            escalationLabel:'רמת הסלמה מחזאית',
            vectorTitle:'⚡ ממדי איום',
            vecPMF:'גיוס PMF', vecIran:'מתקפות ישירות איראן',
            vecBase:'מתקפות בסיסי ארה"ב', vecKurd:'מתחים כורדים', vecISIS:'עלייה מחדש של דאע"ש',
            ladderTitle:'🪜 סולם ההסלמה',
            articlesClassified:'📰 מאמרים תואמים בסעיף מאמרים מובילים למטה',
            refreshScan:'רענן סריקה',
            trendTitle:'מגמת רטוריקה',
            chartEmpty:'אוסף נתונים — תמונת מצב ראשונה נשמרת במחזור הסריקה הבא',
            coordTitle:'⚡ אותות תיאום',
            actorTitle:'🎯 סטטוס שחקנים',
            articlesTitle:'📰 מאמרים מובילים לפי שחקן',
            themeLabel:'ערכת נושא',
            silence:'⚠️ שתיקה חריגה — פעילות נמוכה מהבסיס',
            articles:'מאמרים', maxLevel:'רמה מקסימלית',
            pmfVec:'PMF', iranVec:'איראן', baseVec:'בסיס', kurdVec:'כורדי', isisVec:'דאע"ש',
        },
        fa: {
            backLink:'→ بازگشت به داشبورد', pageFlag:'عراق', pageTitle:'ردیاب خطاب عراق',
            pageSubtitle:'حشد شعبی · کتائب · صدر · کردستان · ایران · سنتکام · پایش داعش',
            loading:'در حال بارگذاری...', scoreLabel:'امتیاز خطاب / ۱۰۰',
            escalationLabel:'سطح تشدید تئاتر',
            vectorTitle:'⚡ بردارهای تهدید',
            vecPMF:'بسیج حشد', vecIran:'حملات مستقیم ایران',
            vecBase:'حملات به پایگاه‌های آمریکا', vecKurd:'تنش‌های کردی', vecISIS:'احیای داعش',
            ladderTitle:'🪜 نردبان تشدید',
            articlesClassified:'📰 مقالات مرتبط در بخش مقالات برتر',
            refreshScan:'بازخوانی اسکن',
            trendTitle:'روند خطاب',
            chartEmpty:'در حال جمع‌آوری داده‌ها — اولین اسنپ‌شات در چرخه بعدی ذخیره می‌شود',
            coordTitle:'⚡ سیگنال‌های هماهنگی',
            actorTitle:'🎯 وضعیت بازیگران',
            articlesTitle:'📰 مقالات برتر بر اساس بازیگر',
            themeLabel:'تم',
            silence:'⚠️ سکوت غیرمعمول — فعالیت کمتر از حد پایه',
            articles:'مقالات', maxLevel:'حداکثر سطح',
            pmfVec:'حشد', iranVec:'ایران', baseVec:'پایگاه', kurdVec:'کردی', isisVec:'داعش',
        },
    };

    // ══════════════════════════════════════════════════════════════
    // STATE
    // ══════════════════════════════════════════════════════════════
    let currentLang = 'en';
    let currentVector = 'pmf';
    let currentData = null;
    let retryInterval = null;
    let retryCount = 0;

    // ══════════════════════════════════════════════════════════════
    // LANGUAGE
    // ══════════════════════════════════════════════════════════════
    function setLanguage(lang) {
        currentLang = lang;
        const rtl = ['ar','fa'];
        document.documentElement.dir = rtl.includes(lang) ? 'rtl' : 'ltr';
        document.documentElement.lang = lang;
        const t = T[lang] || T.en;
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (t[key] !== undefined) el.textContent = t[key];
        });
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.textContent.trim() === lang.toUpperCase() ||
                (lang === 'he' && btn.textContent.trim() === 'עב') ||
                (lang === 'ar' && btn.textContent.trim() === 'ع') ||
                (lang === 'fa' && btn.textContent.trim() === 'ف'));
        });
        if (currentData) renderAll(currentData);
    }

    // ══════════════════════════════════════════════════════════════
    // THEME
    // ══════════════════════════════════════════════════════════════
    function toggleTheme() {
        const isDark = document.getElementById('themeToggle').checked;
        document.documentElement.setAttribute('data-theme', isDark ? 'light' : 'dark');
        localStorage.setItem('iq_rhetoric_theme', isDark ? 'light' : 'dark');
        if (_historyChart) {
            _historyChart.destroy(); _historyChart = null;
            if (_historyView === 'compare') loadCompareData();
            else loadHistoryData();
        }
    }
    function loadTheme() {
        const saved = localStorage.getItem('iq_rhetoric_theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        document.getElementById('themeToggle').checked = saved === 'light';
    }

    // ══════════════════════════════════════════════════════════════
    // VECTOR TABS
    // ══════════════════════════════════════════════════════════════
    function setVector(v) {
        currentVector = v;
        document.querySelectorAll('.vector-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.vector === v);
        });
    }

    function renderVectors(data) {
        const map = {
            pmf:    { id:'vecLevelPMF',  level: data.pmf_level    || 0 },
            iran:   { id:'vecLevelIran', level: data.iran_strike_level || 0 },
            base:   { id:'vecLevelBase', level: data.us_base_level || 0 },
            kurdish:{ id:'vecLevelKurd', level: data.kurdish_level || 0 },
            isis:   { id:'vecLevelISIS', level: data.isis_level    || 0 },
        };
        Object.entries(map).forEach(([key, cfg]) => {
            const el = document.getElementById(cfg.id);
            if (!el) return;
            const lv = ESCALATION_LEVELS[cfg.level] || ESCALATION_LEVELS[0];
            el.textContent = `L${cfg.level} — ${lv.label}`;
            el.style.color = lv.color;
        });
    }

    // ══════════════════════════════════════════════════════════════
    // ESCALATION LADDER
    // ══════════════════════════════════════════════════════════════
    function renderLadder(activeLevel) {
        const row = document.getElementById('ladderRow');
        if (!row) return;
        row.innerHTML = '';
        for (let i = 0; i <= 5; i++) {
            const lv = ESCALATION_LEVELS[i];
            const div = document.createElement('div');
            div.className = 'ladder-step' + (i === activeLevel ? ' active' : '');
            if (i === activeLevel) {
                div.style.borderColor = lv.color;
                div.style.boxShadow = `0 0 16px ${lv.color}55`;
            }
            div.innerHTML = `<div class="ladder-step-num" style="color:${lv.color}">${i}</div>
                             <div class="ladder-step-label" style="color:${lv.color}">${lv.label}</div>`;
            row.appendChild(div);
        }
    }

    // ══════════════════════════════════════════════════════════════
    // THEATRE BANNER
    // ══════════════════════════════════════════════════════════════
    function renderTheatre(data) {
        const level = data.theatre_escalation_level || 0;
        const lv = ESCALATION_LEVELS[level] || ESCALATION_LEVELS[0];
        const score = data.theatre_score || 0;

        document.getElementById('theatreScore').textContent = score;
        document.getElementById('theatreScore').style.color = lv.color;

        const badge = document.getElementById('theatreBadge');
        badge.textContent = lv.label;
        badge.style.background = lv.color;

        document.getElementById('theatreLevelDisplay').textContent = `Level ${level} — ${lv.label}`;
        document.getElementById('theatreLevelDisplay').style.color = lv.color;
        document.getElementById('theatreLevelDesc').textContent = lv.description;

        if (data.scanned_at || data.timestamp) {
            const ts = new Date(data.scanned_at || data.timestamp);
            const ago = Math.round((Date.now() - ts.getTime()) / 60000);
            const agoTxt = ago < 60 ? `${ago}m ago` : `${Math.round(ago/60)}h ago`;
            document.getElementById('theatreScanInfo').textContent =
                `Last scan: ${agoTxt} · ${data.total_articles || 0} articles analyzed`;
        }
        document.getElementById('lastUpdated').textContent =
            new Date(data.scanned_at || data.timestamp || Date.now()).toLocaleString();
    }

    // ══════════════════════════════════════════════════════════════
    // COORDINATION SIGNALS
    // ══════════════════════════════════════════════════════════════
    function renderCoordination(signals) {
        const card = document.getElementById('coordCard');
        const list = document.getElementById('coordList');
        if (!signals || signals.length === 0) { card.style.display='none'; return; }
        card.style.display='block';
        list.innerHTML = '';
        signals.forEach(sig => {
            const div = document.createElement('div');
            div.className = 'coord-item' + (sig.severity === 'critical' ? ' critical' : '');
            div.innerHTML = `<strong>⚡ ${sig.message}</strong>`;
            list.appendChild(div);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // ACTOR STATUS GRID
    // ══════════════════════════════════════════════════════════════
    function renderActors(actors) {
        const grid = document.getElementById('actorsGrid');
        if (!grid || !actors) return;
        grid.innerHTML = '';

        const ORDER = ['pmf_hashd','kataib','iran_iraq','us_centcom','sadr','iraqi_gov','krg','isis_iraq'];
        const t = T[currentLang] || T.en;

        ORDER.forEach(id => {
            const a = actors[id];
            if (!a) return;
            const maxLv = a.max_level || a.escalation_level || 0;
            const lv = ESCALATION_LEVELS[maxLv] || ESCALATION_LEVELS[0];

            const pills = [];
            if ((a.pmf_score||0) > 0)         pills.push(`<span class="vector-pill" style="background:${ESCALATION_LEVELS[a.pmf_score]?.color||'#6b7280'}">${t.pmfVec} L${a.pmf_score}</span>`);
            if ((a.iran_strike_score||0) > 0)  pills.push(`<span class="vector-pill" style="background:${ESCALATION_LEVELS[a.iran_strike_score]?.color||'#6b7280'}">${t.iranVec} L${a.iran_strike_score}</span>`);
            if ((a.us_base_score||0) > 0)      pills.push(`<span class="vector-pill" style="background:${ESCALATION_LEVELS[a.us_base_score]?.color||'#6b7280'}">${t.baseVec} L${a.us_base_score}</span>`);
            if ((a.kurdish_score||0) > 0)      pills.push(`<span class="vector-pill" style="background:${ESCALATION_LEVELS[a.kurdish_score]?.color||'#6b7280'}">${t.kurdVec} L${a.kurdish_score}</span>`);
            if ((a.isis_score||0) > 0)         pills.push(`<span class="vector-pill" style="background:${ESCALATION_LEVELS[a.isis_score]?.color||'#6b7280'}">${t.isisVec} L${a.isis_score}</span>`);

            const card = document.createElement('div');
            card.className = 'actor-card';
            card.innerHTML = `
                <div class="actor-header">
                    <div class="actor-flag">${a.flag||''} ${a.icon||''}</div>
                    <div>
                        <div class="actor-name">${a.name}</div>
                        <div class="actor-role">${a.role||''}</div>
                    </div>
                    <div class="actor-level-badge" style="background:${lv.color}">${lv.label}</div>
                </div>
                <div class="actor-stats">
                    <span>📰 ${a.statement_count||0} ${t.articles}</span>
                    <span>📊 ${t.maxLevel} ${maxLv}</span>
                </div>
                ${pills.length ? `<div class="vector-pills">${pills.join('')}</div>` : ''}
                ${a.silence_alert ? `<div class="actor-silence-alert">⚠️ ${t.silence}</div>` : ''}
            `;
            grid.appendChild(card);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // TOP ARTICLES
    // ══════════════════════════════════════════════════════════════
    function renderArticles(actors) {
        const list = document.getElementById('articlesList');
        if (!list || !actors) return;
        list.innerHTML = '';

        const ORDER = ['pmf_hashd','kataib','iran_iraq','us_centcom','sadr','iraqi_gov','krg','isis_iraq'];
        ORDER.forEach(id => {
            const a = actors[id];
            if (!a || !a.top_articles || a.top_articles.length === 0) return;

            const section = document.createElement('div');
            section.style.marginBottom = '18px';
            section.innerHTML = `<div style="font-size:0.7rem;font-weight:700;color:var(--accent);letter-spacing:1px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--card-border);">${a.flag||''} ${a.name}</div>`;

            a.top_articles.slice(0,3).forEach(art => {
                const item = document.createElement('div');
                item.className = 'article-item';
                const dt = art.published ? new Date(art.published).toLocaleDateString('en-US', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
                item.innerHTML = `
                    <a href="${art.url||'#'}" target="_blank" rel="noopener" class="article-link">${art.title||'Untitled'}</a>
                    <div class="article-meta">${art.source||''} ${dt ? '· '+dt : ''}</div>
                `;
                section.appendChild(item);
            });
            list.appendChild(section);
        });
    }

    // ══════════════════════════════════════════════════════════════
    // RENDER ALL
    // ══════════════════════════════════════════════════════════════
    function renderAll(data) {
        currentData = data;
        const level = data.theatre_escalation_level || 0;
        renderTheatre(data);
        renderLadder(level);
        renderVectors(data);
        renderCoordination(data.coordination_signals || []);
        renderActors(data.actors || {});
        renderArticles(data.actors || {});

        const artCount = document.getElementById('articlesClassified');
        if (artCount) artCount.textContent = `📰 ${data.total_articles || 0} articles analyzed · Corresponding articles below`;

        // Load history chart
        loadHistoryData();
    }

    // ══════════════════════════════════════════════════════════════
    // DATA LOADING
    // ══════════════════════════════════════════════════════════════
    async function loadRhetoricData(forceRefresh=false) {
        try {
            const url = API_BASE + '/api/rhetoric/iraq' + (forceRefresh ? '?force=true' : '');
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            if (data.awaiting_scan) {
                document.getElementById('theatreScanInfo').textContent = 'Scan in progress — first scan takes 2-3 minutes...';
                renderLadder(0);
                if (!retryInterval) {
                    retryInterval = setInterval(async () => {
                        retryCount++;
                        try {
                            const r = await fetch(API_BASE + '/api/rhetoric/iraq');
                            const d = await r.json();
                            if (!d.awaiting_scan) {
                                clearInterval(retryInterval); retryInterval=null; retryCount=0;
                                renderAll(d);
                            } else {
                                document.getElementById('theatreScanInfo').textContent = `Scan in progress — retry ${retryCount}/8...`;
                                if (retryCount >= 8) { clearInterval(retryInterval); retryInterval=null; }
                            }
                        } catch(e) { if(retryCount>=8){clearInterval(retryInterval);retryInterval=null;} }
                    }, 60000);
                }
                return;
            }
            renderAll(data);
        } catch(err) {
            console.error('[Iraq Rhetoric] Load error:', err);
            document.getElementById('theatreScanInfo').textContent = 'Error loading data — retrying...';
            setTimeout(() => loadRhetoricData(), 30000);
        }
    }

    async function triggerScan() {
        const btn = document.getElementById('scanBtn');
        if (btn) { btn.style.opacity='0.5'; btn.disabled=true; }
        document.getElementById('theatreScanInfo').textContent = 'Scan triggered — this takes 2-3 minutes...';
        try {
            await loadRhetoricData(true);
        } finally {
            if (btn) { btn.style.opacity='1'; btn.disabled=false; }
        }
    }

    // ══════════════════════════════════════════════════════════════
    // INIT
    // ══════════════════════════════════════════════════════════════
    document.addEventListener('DOMContentLoaded', function() {
        loadTheme();
        loadRhetoricData();
    });
</script>
</body>
</html>
