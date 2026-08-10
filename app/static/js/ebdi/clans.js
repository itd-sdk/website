let clan_template = null;
let clans = [];
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

function render_clan(clan) {
    const node = clan_template.cloneNode(true);
    node.removeAttribute("id");
    node.dataset.clan = clan.clan;
    node.querySelector(".clan-name").href =
        "/ebdi/users?clan=" + encodeURIComponent(clan.clan);
    node.querySelector(".row-place").textContent = clan.rank + ".";
    node.querySelector(".row-avatar").textContent = clan.clan;
    node.querySelector(".clan-name").textContent =
        clan_names.get(normalize_emoji(clan.clan)) || "-";
    node.querySelector(".clan-count").textContent =
        new Intl.NumberFormat().format(clan.users_count);
    return node;
}

function render_clans() {
    const container = get_el("rows");
    for (const node of container.querySelectorAll(".clan-row")) {
        node.remove();
    }
    const fragment = document.createDocumentFragment();
    for (const clan of clans) {
        const node = render_clan(clan);
        node.classList.add("clan-row");
        fragment.appendChild(node);
    }
    container.insertBefore(fragment, get_el("list-empty"));
    get_el("list-empty").hidden = clans.length > 0;
}

function find_clan_node(clan) {
    return document.querySelector(`.clan-row[data-clan="${clan}"]`);
}

function jump_to_clan(clan) {
    const node = find_clan_node(clan);
    if (!node) {
        console.warn(`clan ${clan} not found`);
        get_el("clan-error").hidden = false;
        return;
    }
    get_el("clan-error").hidden = true;
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    node.classList.add("row-highlighted");
    setTimeout(() => node.classList.remove("row-highlighted"), 3000);
}

function show_error(message) {
    get_el("error-text").textContent = message;
    get_el("list-error").hidden = false;
}

async function load_clan_names() {
    const res = await fetch(
        "https://cdn.jsdelivr.net/npm/emoji-picker-element-data@1/ru/cldr/data.json",
    );
    if (!res.ok) {
        show_error(`Ошибка получения названий кланов: ${res.status}`);
        return;
    }

    for (const clan of await res.json()) {
        clan_names.set(
            normalize_emoji(clan.emoji),
            clan.annotation.charAt(0).toUpperCase() + clan.annotation.slice(1),
        );
    }
}

async function load_clans() {
    get_el("list-loader").hidden = false;
    get_el("list-error").hidden = true;
    try {
        const res = await fetch("/api/ebdi/clans");
        if (!res.ok) {
            show_error(`Ошибка получения кланов: ${res.status}`);
            return;
        }
        clans = await res.json();
        render_clans();
    } catch (error) {
        console.warn("clans request failed", error);
        show_error("Не удалось связаться с сервером");
    } finally {
        get_el("list-loader").hidden = true;
    }
}

function set_clan(clan) {
    if (clan) {
        jump_to_clan(clan);
    }
}

function init_clan_picker() {
    const picker_box = get_el("clan-picker");
    get_el("clan-button").addEventListener("click", () => {
        picker_box.hidden = !picker_box.hidden;
    });
    document
        .querySelector("emoji-picker")
        .addEventListener("emoji-click", (event) => {
            set_clan(normalize_emoji(event.detail.unicode));
            picker_box.hidden = true;
        });
    document.addEventListener("click", (event) => {
        // composedPath sees through shadow DOM of emoji-picker
        const path = event.composedPath();
        if (
            !path.includes(get_el("clan-button")) &&
            !path.includes(get_el("clan-picker")) &&
            !picker_box.hidden
        ) {
            picker_box.hidden = true;
        }
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    clan_template = get_el("clan-template");
    clan_template.remove();
    init_clan_picker();
    get_el("retry-button").addEventListener("click", load_clans);
    await load_clan_names();
    await load_clans();
});
