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

const TREE_TOP_N = 5;
function _cwr(n,c){var w=c==="w"?n.white_wins:n.black_wins,t=c==="w"?n.whites:n.blacks;return t>0?Math.round(w/t*100)+"%":"-";}
function _tn(m,n){var s=document.createElement('span');s.className='tree-node';var ms=document.createElement('span');ms.className='tree-move';ms.textContent=m;s.appendChild(ms);var st=document.createElement('span');st.className='tree-stats';var wr=n.games>0?Math.round(n.wins/n.games*100)+"%":"-";st.textContent="("+n.games+", "+wr+", \u25A1:"+_cwr(n,"w")+" \u25A0:"+_cwr(n,"b")+")";s.appendChild(st);return s;}
function renderTree(tree){if(!tree||!tree.children)return document.createTextNode('No moves');var ul=document.createElement('ul');ul.className='tree-level';var e=Object.entries(tree.children);for(var i=0;i<TREE_TOP_N&&i<e.length;i++){var li=document.createElement('li');li.appendChild(_tn(e[i][0],e[i][1]));if(e[i][1].children&&Object.keys(e[i][1].children).length>0)li.appendChild(renderTree(e[i][1]));ul.appendChild(li);}if(e.length>TREE_TOP_N){var co=document.createElement('li'),d=document.createElement('details');d.className='tree-collapsed';var su=document.createElement('summary');su.textContent="... and "+(e.length-TREE_TOP_N)+" more";d.appendChild(su);var su2=document.createElement('ul');su2.className='tree-level';for(var j=TREE_TOP_N;j<e.length;j++){var li2=document.createElement('li');li2.appendChild(_tn(e[j][0],e[j][1]));if(e[j][1].children&&Object.keys(e[j][1].children).length>0)li2.appendChild(renderTree(e[j][1]));su2.appendChild(li2);}d.appendChild(su2);co.appendChild(d);ul.appendChild(co);}return ul;}

function renderStatsRows(data) {
    statsTableBody.innerHTML = '';
    data.forEach(s => {
        const tr = document.createElement('tr');
        const openingCell = s.opening === '?'
            ? '<td>Non-standard (i.e. Chess960)</td>'
            : `<td class="opening-cell"><span class="tree-triangle" data-tree='${JSON.stringify(s.tree).replace(/'/g, "&#39;")}'>\u25B6</span> <a href="https://lichess.org/opening?q=${encodeURIComponent(s.opening)}" target="_blank" rel="noopener">${escapeHtml(s.opening)}</a></td>`;
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
    document.querySelectorAll('.tree-triangle').forEach(function(tri) {
        tri.addEventListener('click', function(e) {
            e.stopPropagation();
            var row = this.closest('tr');
            var nextRow = row.nextElementSibling;
            if (nextRow && nextRow.classList.contains('tree-row')) {
                nextRow.remove();
                this.textContent = '\u25B6';
                this.classList.remove('expanded');
            } else {
                var tree = JSON.parse(this.dataset.tree);
                var tr2 = document.createElement('tr');
                tr2.className = 'tree-row';
                var td = document.createElement('td');
                td.colSpan = 10;
                var con = document.createElement('div');
                con.className = 'tree-content';
                con.appendChild(renderTree(tree));
                td.appendChild(con);
                tr2.appendChild(td);
                row.parentNode.insertBefore(tr2, row.nextElementSibling);
                this.textContent = '\u25BC';
                this.classList.add('expanded');
            }
        });
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

// Search autocomplete elements
const searchResults = document.getElementById('searchResults');
let searchTimeout = null;
let activeSearchIndex = -1;
let currentSearchResults = [];

function isUrl(str) {
    return /^(https?:\/\/)?lichess\.org\//i.test(str);
}

function debounceSearch(value) {
    if (searchTimeout) {
        clearTimeout(searchTimeout);
    }
    if (isUrl(value) || value.length < 2) {
        hideSearchDropdown();
        return;
    }
    searchTimeout = setTimeout(function() {
        fetch("/search?q=" + encodeURIComponent(value))
            .then(function(res) { return res.json(); })
            .then(function(data) {
                if (Array.isArray(data)) {
                    currentSearchResults = data;
                    activeSearchIndex = -1;
                    renderSearchDropdown();
                }
            })
            .catch(function() {
                hideSearchDropdown();
            });
    }, 1500);
}

function renderSearchDropdown() {
    if (!currentSearchResults || currentSearchResults.length === 0) {
        searchResults.innerHTML = '<div class="search-no-results">No players found</div>';
        searchResults.classList.add('visible');
        urlInput.setAttribute("aria-expanded", "true");
        return;
    }

    searchResults.innerHTML = '';
    currentSearchResults.forEach(function(player, index) {
        var div = document.createElement('div');
        div.className = 'search-result';
        div.setAttribute("role", "option");
        div.setAttribute("id", "searchResult_" + index);
        div.setAttribute("aria-selected", "false");
        div.dataset.fideId = player.fide_id;
        div.dataset.slug = player.slug;
        div.dataset.url = 'https://lichess.org/fide/' + player.fide_id + '/' + player.slug;

        var nameSpan = document.createElement('span');
        nameSpan.className = 'player-name';
        nameSpan.textContent = player.name;

        var fideSpan = document.createElement('span');
        fideSpan.className = 'player-fide';
        fideSpan.textContent = '(FIDE ' + player.fide_id + ')';

        div.appendChild(nameSpan);
        div.appendChild(fideSpan);

        div.addEventListener('mouseenter', function() {
            updateActiveSearchItem(index);
        });

        div.addEventListener('click', function() {
            selectSearchResult(div.dataset.url);
        });

        searchResults.appendChild(div);
    });

    searchResults.classList.add('visible');
    urlInput.setAttribute("aria-expanded", "true");
}

function hideSearchDropdown() {
    searchResults.classList.remove('visible');
    searchResults.innerHTML = '';
    activeSearchIndex = -1;
    currentSearchResults = [];
    urlInput.setAttribute("aria-expanded", "false");
    urlInput.setAttribute("aria-activedescendant", "");
}

function updateActiveSearchItem(index) {
    var items = searchResults.querySelectorAll('.search-result');
    items.forEach(function(item, i) {
        if (i === index) {
            item.classList.add('active');
            item.setAttribute("aria-selected", "true");
            urlInput.setAttribute("aria-activedescendant", item.id);
        } else {
            item.classList.remove('active');
            item.setAttribute("aria-selected", "false");
        }
    });
    activeSearchIndex = index;
}

function selectSearchResult(url) {
    urlInput.value = url;
    hideSearchDropdown();
}

function handleSearchKeydown(e) {
    var items = searchResults.querySelectorAll('.search-result');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (activeSearchIndex < items.length - 1) {
            updateActiveSearchItem(activeSearchIndex + 1);
            items[activeSearchIndex].scrollIntoView({ block: 'nearest' });
        }
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (activeSearchIndex > 0) {
            updateActiveSearchItem(activeSearchIndex - 1);
            items[activeSearchIndex].scrollIntoView({ block: 'nearest' });
        }
    } else if (e.key === 'Enter') {
        if (activeSearchIndex >= 0 && items[activeSearchIndex]) {
            e.preventDefault();
            selectSearchResult(items[activeSearchIndex].dataset.url);
        }
    } else if (e.key === 'Escape') {
        hideSearchDropdown();
    }
}

// Wire up input event for debounced search
urlInput.addEventListener('input', function() {
    debounceSearch(urlInput.value.trim());
});

// Wire up keydown for keyboard navigation
urlInput.addEventListener('keydown', handleSearchKeydown);

// Close dropdown when clicking outside
document.addEventListener('click', function(e) {
    if (!urlInput.contains(e.target) && !searchResults.contains(e.target)) {
        hideSearchDropdown();
    }
});
