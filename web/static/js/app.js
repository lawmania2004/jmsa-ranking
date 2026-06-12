let currentOffset = 0;
let currentTotal = 0;
const LIMIT = 50;

document.addEventListener("DOMContentLoaded", function () {
    const courseSelect = document.getElementById("courseType");
    courseSelect.addEventListener("change", updateEventList);

    const genderSelect = document.getElementById("gender");
    genderSelect.addEventListener("change", updateAgeGroupPrefix);

    document.getElementById("athleteName").addEventListener("keypress", function (e) {
        if (e.key === "Enter") searchRanking();
    });
});

function updateEventList() {
    const course = document.getElementById("courseType").value;
    const eventSelect = document.getElementById("event");
    const events = course === "SCM" ? EVENTS_SCM : EVENTS_LCM;

    eventSelect.innerHTML = "";
    events.forEach(function (ev) {
        const opt = document.createElement("option");
        opt.value = ev;
        opt.textContent = ev;
        eventSelect.appendChild(opt);
    });
}

function updateAgeGroupPrefix() {
    // no-op: age_group prefix is computed server-side from gender
}

function searchRanking() {
    currentOffset = 0;
    document.getElementById("rankingBody").innerHTML = "";
    fetchRanking(false);
}

function loadMore() {
    fetchRanking(true);
}

async function fetchRanking(append) {
    const event = document.getElementById("event").value;
    const course = document.getElementById("courseType").value;
    const gender = document.getElementById("gender").value;
    const ageVal = document.getElementById("ageGroup").value;
    const athlete = document.getElementById("athleteName").value.trim();
    const year = document.getElementById("year").value;

    const agePrefix = gender === "M" ? "M" : "W";
    const ageGroup = agePrefix + ageVal;

    const loading = document.getElementById("loading");
    const table = document.getElementById("rankingTable");
    const loadMoreDiv = document.getElementById("loadMore");
    const info = document.getElementById("resultInfo");

    loading.style.display = "block";
    loadMoreDiv.style.display = "none";

    const params = new URLSearchParams({
        event: event,
        course: course,
        gender: gender,
        age_group: ageGroup,
        limit: LIMIT,
        offset: currentOffset,
        year: year,
    });
    if (athlete) params.set("athlete", athlete);

    try {
        const resp = await fetch("/api/ranking?" + params.toString());
        const data = await resp.json();

        currentTotal = data.total;
        const results = data.results;

        const tbody = document.getElementById("rankingBody");

        if (!append) {
            tbody.innerHTML = "";
        }

        if (results.length === 0 && !append) {
            info.textContent = "該当するデータがありません";
            table.style.display = "none";
            loading.style.display = "none";
            return;
        }

        const genderLabel = gender === "M" ? "男子" : "女子";
        const courseLabel = course === "SCM" ? "短水路" : "長水路";
        const yearLabel = year === "all" ? "全期間" : year + "年度";
        let infoText =
            yearLabel + " " + courseLabel + " " + genderLabel + " " + event + " " +
            ageGroup + "歳区分 — " + currentTotal + "件";
        const rec = data.japan_record;
        if (rec) {
            infoText += "　｜　日本記録: " + rec.holder +
                (rec.club ? "（" + rec.club + "）" : "") +
                " " + rec.time_display +
                (rec.record_date ? " (" + rec.record_date + ")" : "");
        }
        info.textContent = infoText;

        results.forEach(function (r) {
            const tr = document.createElement("tr");
            if (r.is_me) tr.classList.add("highlight");

            const rankClass =
                r.display_rank === 1 ? "rank-1" :
                r.display_rank === 2 ? "rank-2" :
                r.display_rank === 3 ? "rank-3" : "";

            let badge = "";
            if (r.is_jp_new) {
                badge = '<span class="jp-badge jp-new">日本新</span>';
            } else if (r.is_jp_tie) {
                badge = '<span class="jp-badge jp-tie">日本タイ</span>';
            }
            tr.innerHTML =
                '<td class="rank-cell ' + rankClass + '">' + r.display_rank + "</td>" +
                "<td>" + escapeHtml(r.athlete_name) + "</td>" +
                "<td>" + escapeHtml(r.club || "") + "</td>" +
                '<td class="time-cell">' + escapeHtml(r.time_display) + badge + "</td>" +
                "<td>" + escapeHtml(r.meeting_name || "") + "</td>" +
                "<td>" + escapeHtml(r.meeting_date || "") + "</td>";

            tbody.appendChild(tr);
        });

        currentOffset += results.length;
        table.style.display = "table";

        if (currentOffset < currentTotal) {
            loadMoreDiv.style.display = "block";
        } else {
            loadMoreDiv.style.display = "none";
        }
    } catch (e) {
        info.textContent = "エラーが発生しました: " + e.message;
    } finally {
        loading.style.display = "none";
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}
