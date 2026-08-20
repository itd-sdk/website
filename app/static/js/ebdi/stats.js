const COLORS = [
    "#ed6a2d",
    "#fbeadb",
    // "#565350",
    "#E05340",
    "#88B369",
    "#e3b343",
    "#4b86f3",
    "#e067ed",
    "#65b8c9",
];

const GRID = "#3a3532";
const TEXT = "#bbb";
const ACCENT = "#ed6a2d";

Chart.defaults.font.family = "Jost";
Chart.defaults.plugins.legend.labels.usePointStyle = true;
Chart.defaults.plugins.legend.labels.pointStyle = "dash";
Chart.defaults.plugins.tooltip.usePointStyle = true;
Chart.defaults.plugins.tooltip.caretPadding = 16;

const crosshair = {
    id: "crosshair",
    afterDatasetsDraw(chart) {
        if (!chart.scales.x) {
            return;
        }
        const active = chart.getActiveElements();
        if (!active.length) {
            return;
        }
        const { ctx, chartArea } = chart;
        const x = active[0].element.x;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.lineWidth = 1;
        ctx.strokeStyle = TEXT;
        ctx.setLineDash([4, 4]);
        ctx.stroke();
        ctx.restore();
    },
};

Chart.register(crosshair);

Chart.Tooltip.positioners.cursor = function (items, position) {
    if (!items.length) {
        return false;
    }
    return { x: position.x, y: position.y };
};

let clan_names = new Map();

function get_el(id) {
    const element = document.getElementById(id);
    if (!element) {
        console.warn(`element ${id} not found`);
    }
    return element;
}

function normalize_emoji(value) {
    return value.replace(/[\uFE0E\uFE0F]/g, "");
}

// FE0F forces emoji presentation, stripped in storage but needed for display
function display_emoji(value) {
    return value + "\uFE0F";
}

function strip_skin_tone(value) {
    return value.replace(/[\u{1F3FB}-\u{1F3FF}]/gu, "");
}

function clan_label(clan) {
    const key = normalize_emoji(clan);
    const name = clan_names.get(key) || clan_names.get(strip_skin_tone(key));
    return name ? `${display_emoji(clan)} ${name}` : display_emoji(clan);
}

function format_number(value) {
    return new Intl.NumberFormat("ru-RU").format(value);
}

function format_month(timestamp) {
    return new Date(timestamp).toLocaleString("ru-RU", {
        year: "numeric",
        month: "long",
    });
}

function format_date(timestamp) {
    return new Date(timestamp).toLocaleString("ru-RU", {
        year: "numeric",
        month: "long",
        day: "numeric",
    });
}

function follower_bucket_label(bucket, next) {
    if (next === undefined) {
        return `${format_number(bucket)}+`;
    }
    if (next - bucket === 1) {
        return format_number(bucket);
    }
    return `${format_number(bucket)}–${format_number(next - 1)}`;
}

function ratio_bucket_label(bucket, next) {
    if (next === undefined) {
        return `${bucket}+`;
    }
    return `${bucket}–${next}`;
}

const base_options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: "index" },
    plugins: {
        legend: {
            labels: { color: TEXT, boxWidth: 12, font: { size: 12 } },
        },
        tooltip: {
            backgroundColor: "#2c2a27",
            borderColor: GRID,
            borderWidth: 1,
            titleColor: "#fff",
            bodyColor: TEXT,
            padding: 10,
            position: "cursor",
            yAlign: "center",
            caretPadding: 16,
        },
    },
    scales: {
        x: {
            grid: { color: GRID },
            ticks: { color: TEXT, maxRotation: 0, autoSkipPadding: 20 },
        },
        y: {
            grid: { color: GRID },
            ticks: { color: TEXT },
        },
    },
};

// deep merge is overkill here, scales and plugins are the only nested keys
function merge_options(overrides) {
    return {
        ...base_options,
        ...overrides,
        plugins: { ...base_options.plugins, ...(overrides.plugins || {}) },
        scales: overrides.scales ?? base_options.scales,
    };
}

function render_total(data) {
    new Chart(get_el("chart-total"), {
        data: {
            labels: data.map((row) => format_month(row.month)),
            datasets: [
                {
                    type: "line",
                    data: data.map((row) => row.total),
                    borderColor: ACCENT,
                    backgroundColor: "transparent",
                    borderWidth: 2,
                    pointRadius: 0,
                    yAxisID: "y",
                    pointStyle: "line",
                },
            ],
        },
        options: merge_options({
            plugins: {
                tooltip: base_options.plugins.tooltip,
                legend: { display: false },
            },
        }),
    });
}

function render_registrations(data) {
    new Chart(get_el("chart-registrations"), {
        data: {
            labels: data.map((row) => format_month(row.month)),
            datasets: [
                {
                    type: "bar",
                    data: data.map((row) => row.count),
                    backgroundColor: ACCENT,
                    yAxisID: "y",
                    pointStyle: "line",
                },
            ],
        },
        options: merge_options({
            plugins: { legend: { display: false } },
        }),
    });
}

function render_followers_distribution(data) {
    new Chart(get_el("chart-followers-distribution"), {
        type: "bar",
        data: {
            labels: data.map((row, i) =>
                follower_bucket_label(row.bucket, data[i + 1]?.bucket),
            ),
            datasets: [
                {
                    label: "Пользователей",
                    data: data.map((row) => row.count),
                    backgroundColor: ACCENT,
                    pointStyle: "line",
                },
            ],
        },
        options: merge_options({
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: { display: true, text: "Подписчиков", color: TEXT },
                },
                y: {
                    // type: "logarithmic",
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                },
            },
        }),
    });
}

function render_followers_by_age(data) {
    new Chart(get_el("chart-followers-by-age"), {
        type: "scatter",
        data: {
            datasets: [
                {
                    label: "Пользователь",
                    data: data,
                    backgroundColor: "rgba(237, 106, 45, 0.4)",
                    pointRadius: 2,
                },
            ],
        },
        options: merge_options({
            interaction: { intersect: true, mode: "nearest" },
            plugins: {
                legend: { display: false },
                tooltip: {
                    ...base_options.plugins.tooltip,
                    callbacks: {
                        label: (item) =>
                            `${format_month(item.parsed.x)}: ${format_number(item.parsed.y)}`,
                    },
                },
            },
            scales: {
                x: {
                    type: "time",
                    time: { unit: "month" },
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: {
                        display: true,
                        text: "Дата регистрации",
                        color: TEXT,
                    },
                },
                y: {
                    type: "logarithmic",
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: { display: true, text: "Подписчики", color: TEXT },
                },
            },
        }),
    });
}

function render_posts_vs_followers(data) {
    new Chart(get_el("chart-posts-vs-followers"), {
        type: "scatter",
        data: {
            datasets: [
                {
                    label: "Пользователь",
                    data: data,
                    backgroundColor: "rgba(237, 106, 45, 0.4)",
                    pointRadius: 2,
                },
            ],
        },
        options: merge_options({
            interaction: { intersect: true, mode: "nearest" },
            plugins: {
                legend: { display: false },
                tooltip: {
                    ...base_options.plugins.tooltip,
                    callbacks: {
                        label: (item) =>
                            `${format_number(item.parsed.x)} постов, ${format_number(item.parsed.y)} подписчиков`,
                    },
                },
            },
            scales: {
                x: {
                    type: "logarithmic",
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: { display: true, text: "Посты", color: TEXT },
                },
                y: {
                    type: "logarithmic",
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: { display: true, text: "Подписчики", color: TEXT },
                },
            },
        }),
    });
}

function render_clans_over_time(data) {
    new Chart(get_el("chart-clans"), {
        type: "line",
        data: {
            datasets: data.map((clan, i) => ({
                label: clan_label(clan.clan),
                data: clan.points,
                borderColor: COLORS[i % COLORS.length],
                backgroundColor: "transparent",
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.3,
                pointStyle: "line",
            })),
        },
        options: merge_options({
            scales: {
                x: {
                    type: "time",
                    time: { unit: "month" },
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                },
                y: {
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: {
                        display: true,
                        text: "Регистраций",
                        color: TEXT,
                    },
                },
            },
            plugins: {
                tooltip: {
                    ...base_options.plugins.tooltip,
                    callbacks: {
                        title: (items) => format_date(items[0].parsed.x),
                    },
                },
            },
        }),
    });
}

function render_last_seen(data) {
    new Chart(get_el("chart-last-seen"), {
        type: "doughnut",
        data: {
            labels: data.map((row) => row.last_seen || "Скрыто"),
            datasets: [
                {
                    data: data.map((row) => row.count),
                    backgroundColor: data.map(
                        (_, i) => COLORS[i % COLORS.length],
                    ),
                    borderColor: "#1e1c1a",
                    borderWidth: 2,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: "right",
                    labels: {
                        color: TEXT,
                        boxWidth: 12,
                        usePointStyle: false,
                    },
                },
                tooltip: base_options.plugins.tooltip,
            },
        },
    });
}

function render_cohorts(data) {
    new Chart(get_el("chart-cohorts"), {
        type: "line",
        data: {
            labels: data.map((row) => format_month(row.month)),
            datasets: [
                {
                    label: "Верифицированные",
                    data: data.map((row) =>
                        row.total ? (row.verified / row.total) * 100 : 0,
                    ),
                    borderColor: COLORS[0],
                    backgroundColor: "transparent",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    pointStyle: "line",
                },
                {
                    label: "С ИТД+",
                    data: data.map((row) =>
                        row.total ? (row.has_itdp / row.total) * 100 : 0,
                    ),
                    borderColor: COLORS[4],
                    backgroundColor: "transparent",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    pointStyle: "line",
                },
                {
                    label: "Удалённые",
                    data: data.map((row) =>
                        row.total ? (row.deleted / row.total) * 100 : 0,
                    ),
                    borderColor: "#e35b4c",
                    backgroundColor: "transparent",
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.3,
                    pointStyle: "line",
                },
            ],
        },
        options: merge_options({
            plugins: {
                tooltip: {
                    ...base_options.plugins.tooltip,
                    callbacks: {
                        label: (item) =>
                            `${item.dataset.label}: ${item.parsed.y.toFixed(1)}%`,
                    },
                },
            },
            scales: {
                x: base_options.scales.x,
                y: {
                    grid: { color: GRID },
                    ticks: { color: TEXT, callback: (value) => value + "%" },
                },
            },
        }),
    });
}

function render_follow_ratio(data) {
    new Chart(get_el("chart-follow-ratio"), {
        type: "bar",
        data: {
            labels: data.map((row, i) =>
                ratio_bucket_label(row.bucket, data[i + 1]?.bucket),
            ),
            datasets: [
                {
                    label: "Пользователей",
                    data: data.map((row) => row.count),
                    backgroundColor: COLORS[4],
                    pointStyle: "line",
                },
            ],
        },
        options: merge_options({
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                    title: {
                        display: true,
                        text: "Подписок на одного подписчика",
                        color: TEXT,
                    },
                },
                y: {
                    type: "logarithmic",
                    grid: { color: GRID },
                    ticks: { color: TEXT },
                },
            },
        }),
    });
}

async function load_clan_names() {
    try {
        const res = await fetch(
            "https://cdn.jsdelivr.net/npm/emoji-picker-element-data@1/ru/cldr/data.json",
        );
        if (!res.ok) {
            return;
        }
        for (const item of await res.json()) {
            const name =
                item.annotation.charAt(0).toUpperCase() +
                item.annotation.slice(1);
            clan_names.set(normalize_emoji(item.emoji), name);
            for (const skin of item.skins || []) {
                clan_names.set(normalize_emoji(skin.emoji), name);
            }
        }
    } catch (error) {
        console.warn("emoji names request failed", error);
    }
}

function show_error(message) {
    get_el("error-text").textContent = message;
    get_el("list-error").hidden = false;
}

async function load_stats() {
    get_el("list-loader").hidden = false;
    get_el("list-error").hidden = true;
    try {
        const res = await fetch("/api/ebdi/stats/");
        if (!res.ok) {
            show_error(`Ошибка получения статистики: ${res.status}`);
            return;
        }
        const data = await res.json();
        get_el("charts").hidden = false;
        render_registrations(data.registrations);
        render_total(data.registrations);
        render_followers_distribution(data.followers_distribution);
        render_followers_by_age(data.followers_by_age);
        render_posts_vs_followers(data.posts_vs_followers);
        render_clans_over_time(data.clans_over_time);
        render_last_seen(data.last_seen);
        render_cohorts(data.cohorts);
        render_follow_ratio(data.follow_ratio);
    } catch (error) {
        console.warn("stats request failed", error);
        show_error("Не удалось связаться с сервером");
    } finally {
        get_el("list-loader").hidden = true;
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    get_el("retry-button").addEventListener("click", load_stats);
    await load_clan_names();
    await load_stats();
});
