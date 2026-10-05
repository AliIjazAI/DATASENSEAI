// ======================================================
// LEAD OWNER AI V2
// SaaS Dashboard JS
// ======================================================

let globalData = [];

// ======================================================
// START SCRAPING
// ======================================================

async function startLeadSearch() {

    const textarea = document.getElementById("urls");
    const btn = document.getElementById("startBtn");

    const urls = textarea.value
        .split("\n")
        .map(x => x.trim())
        .filter(Boolean);

    if (!urls.length) {
        alert("Enter website URLs first");
        return;
    }

    globalData = [];

    document.getElementById("resultsBody").innerHTML = "";
    document.getElementById("logs").innerHTML = "";
    document.getElementById("totalLeads").innerText = "0";
    document.getElementById("dmCount").innerText = "0";
    document.getElementById("emailCount").innerText = "0";
    document.getElementById("avgScore").innerText = "0";

    const progress = document.getElementById("progressFill");

    progress.style.width = "0%";

    btn.disabled = true;

    btn.innerHTML = `
        <i class="fas fa-spinner fa-spin mr-2"></i>
        Running...
    `;

    setStatus("Starting Lead Intelligence Engine");

    log("🚀 Lead scan started");

    try {

        const response = await fetch(
            "/lead-owner-stream",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ urls })
            }
        );

        if (!response.ok) {
            throw new Error("Server Error");
        }

        const reader = response.body.getReader();

        const decoder = new TextDecoder();

        let buffer = "";

        while (true) {

            const { done, value } =
                await reader.read();

            if (done) break;

            buffer += decoder.decode(
                value,
                { stream: true }
            );

            const chunks =
                buffer.split("\n\n");

            buffer = chunks.pop();

            for (const chunk of chunks) {

                if (!chunk.startsWith("data:"))
                    continue;

                try {

                    const payload =
                        JSON.parse(
                            chunk.replace(
                                "data: ",
                                ""
                            )
                        );

                    // ==========================
                    // PROGRESS
                    // ==========================
                    if (
                        payload.type ===
                        "progress"
                    ) {

                        const percent =
                            (
                                payload.current /
                                payload.total
                            ) * 100;

                        progress.style.width =
                            percent + "%";

                        setStatus(
                            `Scanning ${payload.current}/${payload.total}`
                        );

                        log(
                            `⚡ ${payload.current}/${payload.total}`
                        );
                    }

                    // ==========================
                    // DATA
                    // ==========================
                    if (
                        payload.type ===
                        "data"
                    ) {

                        globalData.push(
                            payload.row
                        );

                        appendRow(
                            payload.row
                        );

                        updateMetrics();

                        updateInsights();

                        log(
                            `✅ ${payload.row.company || "Lead"}`
                        );
                    }

                    // ==========================
                    // DONE
                    // ==========================
                    if (
                        payload.type ===
                        "done"
                    ) {

                        progress.style.width =
                            "100%";

                        setStatus(
                            "Completed"
                        );

                        log(
                            "🎉 Scan Completed"
                        );

                        btn.disabled =
                            false;

                        btn.innerHTML =
                            '<i class="fas fa-search mr-2"></i>Start Scan';
                    }

                } catch (e) {
                    console.log(e);
                }
            }
        }

    } catch (err) {

        console.log(err);

        setStatus("Failed");

        log("❌ Scan Failed");

        btn.disabled = false;

        btn.innerHTML =
            '<i class="fas fa-search mr-2"></i>Start Scan';
    }
}

// ======================================================
// TABLE
// ======================================================

function appendRow(row) {

    const tbody =
        document.getElementById(
            "resultsBody"
        );

    const owner =
        row.owner || "-";

    const role =
        row.role || "-";

    const email =
        row.emails &&
        row.emails.length
            ? row.emails[0]
            : "-";

    const phone =
        row.phones &&
        row.phones.length
            ? row.phones[0]
            : "-";

    const score =
        row.lead_score || 0;

    const html = `
    <tr class="border-b border-slate-800 hover:bg-slate-900/40">

        <td class="px-4 py-3">
            ${row.company || "-"}
        </td>

        <td class="px-4 py-3">
            ${owner}
        </td>

        <td class="px-4 py-3">
            ${role}
        </td>

        <td class="px-4 py-3">
            ${email}
        </td>

        <td class="px-4 py-3">
            ${phone}
        </td>

        <td class="px-4 py-3">

            <span class="
                px-2 py-1 rounded-lg
                bg-purple-500/20
                text-purple-300
            ">
                ${score}
            </span>

        </td>

    </tr>
    `;

    tbody.insertAdjacentHTML(
        "beforeend",
        html
    );
}

// ======================================================
// METRICS
// ======================================================

function updateMetrics() {

    document.getElementById(
        "totalLeads"
    ).innerText =
        globalData.length;

    const dmCount =
        globalData.filter(
            x => x.owner
        ).length;

    document.getElementById(
        "dmCount"
    ).innerText = dmCount;

    let emailCount = 0;

    globalData.forEach(r => {

        if (
            r.emails &&
            r.emails.length
        ) {
            emailCount +=
                r.emails.length;
        }
    });

    document.getElementById(
        "emailCount"
    ).innerText =
        emailCount;

    let avg = 0;

    if (globalData.length) {

        avg =
            globalData.reduce(
                (a, b) =>
                    a +
                    (
                        b.lead_score ||
                        0
                    ),
                0
            ) /
            globalData.length;
    }

    document.getElementById(
        "avgScore"
    ).innerText =
        Math.round(avg);
}

// ======================================================
// INSIGHTS
// ======================================================

function updateInsights() {

    const box =
        document.getElementById(
            "insights"
        );

    const best =
        [...globalData]
            .sort(
                (a, b) =>
                    (b.lead_score || 0)
                    -
                    (a.lead_score || 0)
            )[0];

    box.innerHTML = `

        <div class="space-y-2">

            <div>
                Total Leads:
                <b>${globalData.length}</b>
            </div>

            <div>
                Decision Makers:
                <b>
                    ${
                        globalData.filter(
                            x => x.owner
                        ).length
                    }
                </b>
            </div>

            <div>
                Best Lead:
                <b>
                    ${
                        best
                        ? best.company
                        : "-"
                    }
                </b>
            </div>

            <div>
                Lead Score:
                <b>
                    ${
                        best
                        ? best.lead_score
                        : "-"
                    }
                </b>
            </div>

        </div>
    `;
}

// ======================================================
// STATUS
// ======================================================

function setStatus(msg) {

    const el =
        document.getElementById(
            "statusBox"
        );

    if (el)
        el.innerText = msg;
}

// ======================================================
// LOGS
// ======================================================

function log(text) {

    const logs =
        document.getElementById(
            "logs"
        );

    const now =
        new Date()
        .toLocaleTimeString();

    logs.innerHTML += `
        <div class="py-1 border-b border-slate-800">
            <span class="text-slate-500">
                ${now}
            </span>
            ${text}
        </div>
    `;

    logs.scrollTop =
        logs.scrollHeight;
}

// ======================================================
// SEARCH TABLE
// ======================================================

function filterResults() {

    const q =
        document
            .getElementById(
                "searchInput"
            )
            .value
            .toLowerCase();

    const rows =
        document.querySelectorAll(
            "#resultsBody tr"
        );

    rows.forEach(r => {

        const txt =
            r.innerText.toLowerCase();

        r.style.display =
            txt.includes(q)
                ? ""
                : "none";
    });
}

// ======================================================
// COPY
// ======================================================

function copyData() {

    if (!globalData.length)
        return;

    let text =
        "Company\tOwner\tRole\tEmail\tPhone\tScore\n";

    globalData.forEach(r => {

        text += [
            r.company || "",
            r.owner || "",
            r.role || "",
            r.emails?.[0] || "",
            r.phones?.[0] || "",
            r.lead_score || ""
        ].join("\t");

        text += "\n";
    });

    navigator.clipboard
        .writeText(text);

    log("📋 Copied");
}

// ======================================================
// CSV
// ======================================================

function exportCSV() {

    if (!globalData.length)
        return;

    const headers = [
        "company",
        "legal",
        "owner",
        "role",
        "emails",
        "phones",
        "facebook",
        "instagram",
        "linkedin",
        "lead_score",
        "confidence",
        "source",
        "mode"
    ];

    const rows = [];

    rows.push(headers);

    globalData.forEach(r => {

        rows.push([

            r.company || "",
            r.legal || "",
            r.owner || "",
            r.role || "",

            (r.emails || [])
                .join(";"),

            (r.phones || [])
                .join(";"),

            r.facebook || "",
            r.instagram || "",
            r.linkedin || "",

            r.lead_score || "",
            r.confidence || "",

            r.source || "",
            r.mode || ""

        ]);
    });

    const csv =
        rows
        .map(
            row =>
            row.map(
                x =>
                `"${String(x)
                    .replace(/"/g,'""')}"`
            ).join(",")
        )
        .join("\n");

    const blob =
        new Blob(
            [csv],
            {
                type:
                "text/csv;charset=utf-8;"
            }
        );

    const url =
        URL.createObjectURL(blob);

    const a =
        document.createElement("a");

    a.href = url;

    a.download =
        "lead_intelligence.csv";

    a.click();

    URL.revokeObjectURL(url);
}