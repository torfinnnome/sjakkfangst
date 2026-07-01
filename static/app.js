const form = document.getElementById('fetch-form');
const urlInput = document.getElementById('url');
const submitBtn = document.getElementById('submit-btn');
const progressContainer = document.getElementById('progress-container');
const progressBarFill = document.getElementById('progress-bar-fill');
const statusText = document.getElementById('status-text');
const errorText = document.getElementById('error-text');
const tournamentList = document.getElementById('tournament-list');
const tournamentDetails = document.getElementById('tournament-details');
const statsContainer = document.getElementById('stats-container');
const statsOverview = document.getElementById('stats-overview');
const statsTableBody = document.querySelector('#stats-table tbody');
const downloadBtn = document.getElementById('download-btn');

let currentEventSource = null;
let currentStats = [];
let statsSortCol = null;
let statsSortDir = 'desc';
let rateLimitTimer = null;
let retryCount = 0;
let retryTimer = null;
let fetchUrl = null;

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;',
        '"': '&quot;', "'": '&#39;'
    }[c]));
}

function startRateLimitCountdown(seconds) {
    submitBtn.disabled = true;
    let remaining = seconds;

    function tick() {
        submitBtn.disabled = true;
        submitBtn.value = `Wait ${remaining}s...`;
        errorText.innerText = 'Rate limited — please wait.';
        errorText.style.display = 'block';

        if (remaining <= 0) {
            clearInterval(rateLimitTimer);
            rateLimitTimer = null;
            submitBtn.disabled = false;
            submitBtn.value = 'Fetch Games';
            errorText.style.display = 'none';
            return;
        }
        remaining--;
    }

    tick();
    rateLimitTimer = setInterval(tick, 1000);
}

form.onsubmit = function(e) {
    e.preventDefault();
    if (submitBtn.disabled) return;

    const url = urlInput.value.trim();
    if (!url) return;

    // Close any existing connection
    if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
    }
    if (rateLimitTimer) {
        clearInterval(rateLimitTimer);
        rateLimitTimer = null;
    }

    // Reset UI
    errorText.style.display = 'none';
    progressContainer.style.display = 'block';
    submitBtn.disabled = true;
    progressBarFill.style.width = '0%';
    statusText.innerText = 'Fetching tournament list...';
    tournamentList.innerHTML = '';
    tournamentDetails.open = true;
    statsContainer.style.display = 'none';
    statsContainer.open = false;
    statsTableBody.innerHTML = '';
    downloadBtn.style.display = 'none';

    // Reset retry state
    retryCount = 0;
    if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
    }

    // Start SSE connection with cache-buster
    fetchUrl = `/fetch_stream?url=${encodeURIComponent(url)}&t=${Date.now()}`;
    currentEventSource = new EventSource(fetchUrl);

    currentEventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.rate_limit) {
            currentEventSource.close();
            currentEventSource = null;
            startRateLimitCountdown(data.wait);
            return;
        }

        if (data.error) {
            showError(data.error);
            currentEventSource.close();
            currentEventSource = null;
            return;
        }

        if (data.tournaments) {
            const hash = data.player_hash || '';
            data.tournaments.forEach((t, index) => {
                const li = document.createElement('li');
                li.className = 'tournament-item';
                const href = t.url ? t.url + hash : '#';
                const safeName = escapeHtml(t.name);
                const safeHref = escapeHtml(href);
                li.innerHTML = `<a href="${safeHref}" target="_blank" rel="noopener" class="tournament-link" title="${safeName}"><span class="status-icon">○</span> <span class="tournament-name">${safeName}</span></a>`;
                tournamentList.appendChild(li);
            });
        }

        if (data.progress !== undefined) {
            progressBarFill.style.width = data.progress + '%';
        }

        if (data.index !== undefined) {
            statusText.innerText = (data.cached ? 'Using cached: ' : 'Fetching: ') + data.name;

            const items = tournamentList.querySelectorAll('.tournament-item');
            items.forEach((item, idx) => {
                if (idx === data.index) {
                    item.classList.add('active');
                    item.classList.remove('done');
                    const link = item.querySelector('.tournament-link');
                    if (link) {
                        link.querySelector('.status-icon').innerText = '▶';
                    }

                    // Add cached label if applicable
                    if (data.cached && !item.querySelector('.cached-label')) {
                        const cachedSpan = document.createElement('span');
                        cachedSpan.className = 'cached-label';
                        cachedSpan.innerText = '(cached)';
                        item.appendChild(cachedSpan);
                    }

                    item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else if (item.classList.contains('active')) {
                    item.classList.remove('active');
                    item.classList.add('done');
                    const link = item.querySelector('.tournament-link');
                    if (link) {
                        link.querySelector('.status-icon').innerText = '✓';
                    }
                }
            });
        }

        if (data.done) {
            statusText.innerText = 'Done!';
            progressBarFill.style.width = '100%';

            // Render opening stats
            if (data.stats && data.stats.length > 0) {
                renderStats(data.stats, data.player_name || urlInput.value.split('/').pop());
            }

            // Mark all remaining items as done
            const items = tournamentList.querySelectorAll('.tournament-item');
            items.forEach(item => {
                if (item.classList.contains('active')) {
                    item.classList.remove('active');
                }
                item.classList.add('done');
                item.querySelector('.status-icon').innerText = '✓';
            });

            currentEventSource.close();
            currentEventSource = null;

            // Show download button
            downloadBtn.href = `/download/${data.id}`;
            downloadBtn.download = '';
            downloadBtn.style.display = 'inline-block';

            submitBtn.disabled = false;
        }
    };

    currentEventSource.onerror = function() {
        if (currentEventSource) {
            currentEventSource.close();
            currentEventSource = null;
        }

        if (retryCount < 3) {
            retryCount++;
            statusText.innerText = `Connection error — retrying (${retryCount}/3)...`;
            retryTimer = setTimeout(function() {
                fetchUrl = `/fetch_stream?url=${encodeURIComponent(urlInput.value.trim())}&t=${Date.now()}`;
                currentEventSource = new EventSource(fetchUrl);
            }, 2000);
        } else {
            showError('Connection error or server failure.');
            submitBtn.disabled = false;
        }
    };
};

function renderStats(stats, playerName) {
    currentStats = stats;
    statsSortCol = null;
    statsSortDir = 'desc';

    const total = stats.reduce((sum, s) => sum + s.games, 0);
    const wins = stats.reduce((sum, s) => sum + s.wins, 0);
    const draws = stats.reduce((sum, s) => sum + s.draws, 0);
    const losses = stats.reduce((sum, s) => sum + s.losses, 0);
    const winPct = Math.round(wins / total * 100);

    statsContainer.querySelector('summary').innerText = `Opening Statistics — ${decodeURIComponent(playerName)}`;

    statsOverview.innerHTML =
        `<span>${total} games</span> ` +
        `<span class="win">W:${wins}</span> ` +
        `<span class="draw">D:${draws}</span> ` +
        `<span class="loss">L:${losses}</span> ` +
        `<span>Win rate: ${winPct}%</span>`;

    renderStatsRows(currentStats);
    wireSortHeaders();

    statsContainer.style.display = 'block';
    statsContainer.open = true;
}

function renderStatsRows(data) {
    statsTableBody.innerHTML = '';
    data.forEach(s => {
        const tr = document.createElement('tr');
        const openingCell = s.opening === '?'
            ? '<td>Non-standard (i.e. Chess960)</td>'
            : `<td><a href="https://lichess.org/opening?q=${encodeURIComponent(s.opening)}" target="_blank" rel="noopener">${escapeHtml(s.opening)}</a></td>`;
        tr.innerHTML =
            openingCell +
            `<td class="num">${s.games}</td>` +
            `<td class="num">${s.whites}</td>` +
            `<td class="num">${s.blacks}</td>` +
            `<td class="num win">${s.wins}</td>` +
            `<td class="num draw">${s.draws}</td>` +
            `<td class="num loss">${s.losses}</td>` +
            `<td class="num">${s.win_pct}%</td>` +
            `<td class="num">${s.avg_elo || '-'}</td>` +
            `<td class="eco-cell">${escapeHtml(s.eco || '-')}</td>`;
        statsTableBody.appendChild(tr);
    });
}

function wireSortHeaders() {
    const headers = document.querySelectorAll('#stats-table thead th');
    headers.forEach((th, colIndex) => {
        th.onclick = () => sortStatsBy(colIndex);
    });
}

function sortStatsBy(colIndex) {
    const headers = document.querySelectorAll('#stats-table thead th');
    const cols = [
        { key: 'opening', numeric: false },
        { key: 'games', numeric: true },
        { key: 'whites', numeric: true },
        { key: 'blacks', numeric: true },
        { key: 'wins', numeric: true },
        { key: 'draws', numeric: true },
        { key: 'losses', numeric: true },
        { key: 'win_pct', numeric: true },
        { key: 'avg_elo', numeric: true },
        { key: 'eco', numeric: false },
    ];

    if (statsSortCol === colIndex) {
        statsSortDir = statsSortDir === 'asc' ? 'desc' : 'asc';
    } else {
        statsSortCol = colIndex;
        statsSortDir = 'desc';
    }

    headers.forEach((th, i) => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (i === statsSortCol) {
            th.classList.add(statsSortDir === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });

    const col = cols[colIndex];
    currentStats.sort((a, b) => {
        let va = a[col.key];
        let vb = b[col.key];
        if (va == null) va = col.numeric ? -Infinity : '';
        if (vb == null) vb = col.numeric ? -Infinity : '';
        if (col.numeric) {
            return statsSortDir === 'asc' ? va - vb : vb - va;
        }
        va = String(va).toLowerCase();
        vb = String(vb).toLowerCase();
        if (va < vb) return statsSortDir === 'asc' ? -1 : 1;
        if (va > vb) return statsSortDir === 'asc' ? 1 : -1;
        return 0;
    });

    renderStatsRows(currentStats);
}

function showError(msg) {
    errorText.innerText = 'Error: ' + msg;
    errorText.style.display = 'block';
    progressContainer.style.display = 'none';
    submitBtn.disabled = false;
}
