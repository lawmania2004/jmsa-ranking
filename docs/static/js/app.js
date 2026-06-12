let META = null;
let RECORDS = {};
let currentOffset = 0;
let currentRows = [];
let currentRecord = null;
const LIMIT = 50;
const dataCache = {};

document.addEventListener("DOMContentLoaded", async function () {
    try {
        const resp = await fetch("data/meta.json");
        META = await resp.json();
        const recResp = await fetch("data/records.json");
        if (recResp.ok) {
            RECORDS = (await recResp.json()).records || {};
        }
    } catch (e) {
        document.getElementById("resultInfo").textContent = "データの読み込みに失敗しました";
        return;
    }

    document.getElementById("lastUpdated").textContent =
        "最終更新: " + (META.generated_at || "未取得");

    const yearSelect = document.getElementById("year");
    META.years.forEach(function (y) {
        const opt = document.createElement("option");
        opt.value = y;
        opt.textContent = y + "年";
        yearSelect.appendChild(opt);
    });
    const allOpt = document.createElement("option");
    allOpt.value = "all";
    allOpt.textContent = "全期間";
    yearSelect.appendChild(allOpt);

    const ageSelect = document.getElementById("ageGroup");
    META.age_groups.forEach(function (a) {
        const opt = document.createElement("option");
        opt.value = a;
        opt.textContent = a + "歳区分";
        if (a === 40) opt.selected = true;
        ageSelect.appendChild(opt);
    });

    document.getElementById("courseType").addEventListener("change", updateEventList);
    document.getElementById("athleteName").addEventListener("keypress", function (e) {
        if (e.key === "Enter") searchRanking();
    });

    updateEventList();
    renderNotes();
});

function updateEventList() {
    const course = document.getElementById("courseType").value;
    const events = course === "SCM" ? META.events_scm : META.events_lcm;
    const eventSelect = document.getElementById("event");
    eventSelect.innerHTML = "";
    events.forEach(function (ev) {
        const opt = document.createElement("option");
        opt.value = ev;
        opt.textContent = ev;
        eventSelect.appendChild(opt);
    });
}

function renderNotes() {
    const area = document.getElementById("notesArea");
    const items = [];
    (META.notes || []).forEach(function (n) {
        items.push("※ " + n.name + "（" + n.date + "）: " + n.note);
    });
    (META.pending || []).forEach(function (p) {
        items.push("※ " + p.title + "（" + p.start + "）: 未集計（結果待ち・手動確認中）");
    });
    if (items.length === 0) {
        area.innerHTML = "";
        return;
    }
    area.innerHTML =
        '<div class="notes-title">集計に関する注意</div>' +
        items.map(function (t) { return '<div class="note-line">' + escapeHtml(t) + "</div>"; }).join("");
}

async function fetchData(course, ageLabel) {
    const key = course + "_" + ageLabel;
    if (!dataCache[key]) {
        const resp = await fetch("data/" + key + ".json");
        if (!resp.ok) {
            dataCache[key] = [];
        } else {
            dataCache[key] = await resp.json();
        }
    }
    return dataCache[key];
}

function normName(s) {
    return (s || "").replace(/[\s　]+/g, "");
}

function searchRanking() {
    currentOffset = 0;
    document.getElementById("rankingBody").innerHTML = "";
    runQuery();
}

function loadMore() {
    renderPage(true);
}

async function runQuery() {
    const event = document.getElementById("event").value;
    const course = document.getElementById("courseType").value;
    const gender = document.getElementById("gender").value;
    const ageVal = document.getElementById("ageGroup").value;
    const athlete = document.getElementById("athleteName").value.trim();
    const year = document.getElementById("year").value;

    const ageLabel = (gender === "M" ? "M" : "W") + ageVal;
    const loading = document.getElementById("loading");
    loading.style.display = "block";

    let rows;
    try {
        rows = await fetchData(course, ageLabel);
    } catch (e) {
        document.getElementById("resultInfo").textContent = "エラー: " + e.message;
        loading.style.display = "none";
        return;
    }

    // 選手名が入力されている場合は「選手サマリ」モード:
    // その選手の全種目の順位・タイム・大会を一覧表示する
    if (athlete) {
        loading.style.display = "none";
        renderAthleteSummary(rows, athlete, year, course, gender, ageLabel);
        return;
    }

    // 種目で絞る → 年度フィルタ → 選手ごとにベスト1件
    let filtered = rows.filter(function (r) { return r.e === event; });
    if (year !== "all") {
        filtered = filtered.filter(function (r) { return String(r.y) === String(year); });
    }
    const bestByAthlete = {};
    filtered.forEach(function (r) {
        const cur = bestByAthlete[r.n];
        if (!cur || r.s < cur.s) bestByAthlete[r.n] = r;
    });
    currentRows = Object.values(bestByAthlete).sort(function (a, b) { return a.s - b.s; });

    const genderLabel = gender === "M" ? "男子" : "女子";
    const courseLabel = course === "SCM" ? "短水路" : "長水路";
    const yearLabel = year === "all" ? "全期間" : year + "年度";
    let infoText =
        yearLabel + " " + courseLabel + " " + genderLabel + " " + event + " " +
        ageLabel + "歳区分 — " + currentRows.length + "件";

    currentRecord = RECORDS[course + "_" + ageLabel + "_" + event] || null;
    if (currentRecord) {
        infoText += "　｜　日本記録: " + currentRecord.n +
            (currentRecord.c ? "（" + currentRecord.c + "）" : "") +
            " " + currentRecord.t +
            (currentRecord.d ? " (" + currentRecord.d + ")" : "");
    }
    document.getElementById("resultInfo").textContent = infoText;

    loading.style.display = "none";
    renderPage(false);
}

function setTableHead(mode) {
    const thead = document.querySelector("#rankingTable thead tr");
    if (mode === "athlete") {
        thead.innerHTML =
            "<th>種目</th><th>順位</th><th>タイム</th><th>大会名</th><th>大会日</th>";
    } else {
        thead.innerHTML =
            "<th>順位</th><th>選手名</th><th>所属クラブ</th><th>タイム</th><th>大会名</th><th>大会日</th>";
    }
}

function renderAthleteSummary(rows, athlete, year, course, gender, ageLabel) {
    const table = document.getElementById("rankingTable");
    const tbody = document.getElementById("rankingBody");
    const info = document.getElementById("resultInfo");
    document.getElementById("loadMore").style.display = "none";

    let pool = rows;
    if (year !== "all") {
        pool = pool.filter(function (r) { return String(r.y) === String(year); });
    }
    // 選手×種目のベスト1件(全期間選択時は年をまたいで最速)
    const bests = {};
    pool.forEach(function (r) {
        const k = r.n + "|" + r.e;
        if (!bests[k] || r.s < bests[k].s) bests[k] = r;
    });
    // 種目ごとの順位表(同タイムは同順位)
    const perEvent = {};
    Object.values(bests).forEach(function (r) {
        (perEvent[r.e] = perEvent[r.e] || []).push(r);
    });
    const key = normName(athlete);
    const matchNames = [];
    Object.values(bests).forEach(function (r) {
        if (normName(r.n).indexOf(key) !== -1 && matchNames.indexOf(r.n) === -1) {
            matchNames.push(r.n);
        }
    });
    matchNames.sort();

    const genderLabel = gender === "M" ? "男子" : "女子";
    const courseLabel = course === "SCM" ? "短水路" : "長水路";
    const yearLabel = year === "all" ? "全期間" : year + "年度";
    info.textContent =
        yearLabel + " " + courseLabel + " " + genderLabel + " " + ageLabel +
        "歳区分 「" + athlete + "」 — " + matchNames.length + "選手";

    tbody.innerHTML = "";
    if (matchNames.length === 0) {
        info.textContent = "該当するデータがありません";
        table.style.display = "none";
        return;
    }

    setTableHead("athlete");
    const eventsOrder = course === "SCM" ? META.events_scm : META.events_lcm;
    const myKey = normName(localStorage.getItem("myName") || "");

    matchNames.slice(0, 10).forEach(function (name) {
        const entries = [];
        eventsOrder.forEach(function (ev) {
            const r = bests[name + "|" + ev];
            if (r) entries.push(r);
        });
        if (!entries.length) return;

        const headTr = document.createElement("tr");
        headTr.innerHTML =
            '<td colspan="5" class="athlete-head">' + escapeHtml(name) +
            (entries[0].c ? "　" + escapeHtml(entries[0].c) : "") +
            "（" + entries.length + "種目）</td>";
        tbody.appendChild(headTr);

        entries.forEach(function (r) {
            const list = perEvent[r.e];
            const rank = 1 + list.filter(function (o) { return o.s < r.s - 0.005; }).length;
            const rec = RECORDS[course + "_" + ageLabel + "_" + r.e] || null;
            let badge = "";
            if (rec) {
                if (r.s < rec.s - 0.005) badge = '<span class="jp-badge jp-new">日本新</span>';
                else if (Math.abs(r.s - rec.s) <= 0.005) badge = '<span class="jp-badge jp-tie">日本タイ</span>';
            }
            const rankClass =
                rank === 1 ? "rank-1" : rank === 2 ? "rank-2" : rank === 3 ? "rank-3" : "";
            const tr = document.createElement("tr");
            if (myKey && normName(r.n).indexOf(myKey) !== -1) tr.classList.add("highlight");
            tr.innerHTML =
                "<td>" + escapeHtml(r.e) + "</td>" +
                '<td class="rank-cell ' + rankClass + '">' + rank + "位/" + list.length + "人</td>" +
                '<td class="time-cell">' + escapeHtml(r.t) + badge + "</td>" +
                "<td>" + escapeHtml(r.m) + "</td>" +
                "<td>" + escapeHtml(r.d) + "</td>";
            tbody.appendChild(tr);
        });
    });
    table.style.display = "table";
}

function renderPage(append) {
    const table = document.getElementById("rankingTable");
    const tbody = document.getElementById("rankingBody");
    const loadMoreDiv = document.getElementById("loadMore");

    if (!append) {
        tbody.innerHTML = "";
        currentOffset = 0;
        setTableHead("ranking");
    }

    if (currentRows.length === 0) {
        document.getElementById("resultInfo").textContent = "該当するデータがありません";
        table.style.display = "none";
        loadMoreDiv.style.display = "none";
        return;
    }

    const myKey = normName(localStorage.getItem("myName") || "");
    const page = currentRows.slice(currentOffset, currentOffset + LIMIT);
    page.forEach(function (r, i) {
        const rank = currentOffset + i + 1;
        const tr = document.createElement("tr");
        if (myKey && normName(r.n).indexOf(myKey) !== -1) tr.classList.add("highlight");
        const rankClass =
            rank === 1 ? "rank-1" : rank === 2 ? "rank-2" : rank === 3 ? "rank-3" : "";
        let badge = "";
        if (currentRecord) {
            if (r.s < currentRecord.s - 0.005) {
                badge = '<span class="jp-badge jp-new">日本新</span>';
            } else if (Math.abs(r.s - currentRecord.s) <= 0.005) {
                badge = '<span class="jp-badge jp-tie">日本タイ</span>';
            }
        }
        tr.innerHTML =
            '<td class="rank-cell ' + rankClass + '">' + rank + "</td>" +
            "<td>" + escapeHtml(r.n) + "</td>" +
            "<td>" + escapeHtml(r.c) + "</td>" +
            '<td class="time-cell">' + escapeHtml(r.t) + badge + "</td>" +
            "<td>" + escapeHtml(r.m) + "</td>" +
            "<td>" + escapeHtml(r.d) + "</td>";
        tbody.appendChild(tr);
    });

    currentOffset += page.length;
    table.style.display = "table";
    loadMoreDiv.style.display = currentOffset < currentRows.length ? "block" : "none";
}

function setMyName() {
    const cur = localStorage.getItem("myName") || "";
    const v = prompt("ハイライトする選手名を入力してください（空欄で解除）", cur);
    if (v === null) return;
    if (v.trim()) {
        localStorage.setItem("myName", v.trim());
    } else {
        localStorage.removeItem("myName");
    }
    // 表示中なら再描画
    if (currentRows.length) renderPage(false);
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(String(str)));
    return div.innerHTML;
}
