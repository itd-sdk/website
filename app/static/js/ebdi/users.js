const PAGE_SIZE = 100;
const SEARCH_DELAY = 500;

const DEFAULT_STATE = {
    order: "followers_count",
    descending: true,
    verified: "",
    has_itdp: "",
    clan: "",
    show_deleted: false,
};

const URL_KEYS = Object.keys(DEFAULT_STATE);
const BOOL_KEYS = ["descending", "show_deleted"];
const RADIO_FILTERS = ["verified", "has_itdp"];
const LIST_FILTERS = ["verified", "has_itdp", "clan"];

const state = {
    ...DEFAULT_STATE,
    finished: false,
    cooldown_until: 0,
    failed_offset: null,
    loaded_offsets: new Set(),
    loading: false,
};

let user_template = null;
let gap_observer = null;

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

function read_url_state() {
    const params = new URLSearchParams(location.search);
    for (const key of URL_KEYS) {
        if (!params.has(key)) {
            continue;
        }
        const value = params.get(key);
        state[key] = BOOL_KEYS.includes(key) ? value === "true" : value;
    }
    console.info("restored state from url", location.search);
}

function write_url_state() {
    const params = new URLSearchParams();
    for (const key of URL_KEYS) {
        if (state[key] !== "" && state[key] !== DEFAULT_STATE[key]) {
            params.set(key, state[key]);
        }
    }
    const query = params.toString();
    history.replaceState(null, "", query ? "?" + query : location.pathname);
}

function update_sort_headers() {
    for (const cell of document.querySelectorAll(".row-sortable")) {
        const active = cell.dataset.order === state.order;
        cell.classList.toggle("sort-active", active);
        const arrow = cell.querySelector(".sort-arrow");
        arrow.src = active ? "/static/icons/arrow.svg" : "";
        if (active) {
            if (state.descending) {
                arrow.classList.add("desc");
            } else {
                arrow.classList.remove("desc");
            }
        }
    }
}

function apply_state_to_controls() {
    for (const name of RADIO_FILTERS) {
        const input = document.querySelector(
            `input[name="${name}"][value="${state[name]}"]`,
        );
        if (input) {
            input.checked = true;
        }
    }
    get_el("clan-text").textContent = `Клан: ${state.clan + "\uFE0F" || "Все"}`;
    if (state.clan) {
        get_el("clan-remove").hidden = false;
    }
    get_el("deleted-checkbox").checked = state.show_deleted;
    update_sort_headers();
}

function build_params(extra = {}) {
    const params = new URLSearchParams({
        order: state.order,
        descending: state.descending,
        ...extra,
    });
    for (const key of LIST_FILTERS) {
        if (state[key] !== "") {
            params.set(key, state[key]);
        }
    }
    if (!state.show_deleted) {
        params.set("exists", true);
    }
    return params;
}

function show_loader(show) {
    const loader = get_el("list-loader");
    loader.hidden = !show;
    if (show) {
        get_el("rows").appendChild(loader);
    }
}

function hide_error() {
    get_el("list-error").hidden = true;
    state.failed_offset = null;
}

function show_error(offset, message) {
    state.failed_offset = offset;
    get_el("error-text").textContent = message;
    const error = get_el("list-error");
    error.hidden = false;
    get_el("rows").appendChild(error);
}

async function fetch_count() {
    const res = await fetch("/api/ebdi/users/count");

    if (!res.ok) {
        alert(`Ошибка получения количества пользователей: ${res.stat}`);
        return;
    }
    get_el("total-objects").hidden = false;
    get_el("total-objects-value").textContent = (await res.json()).count;
}

async function fetch_users(offset) {
    const params = build_params({ offset: offset });
    try {
        const res = await fetch("/api/ebdi/users?" + params);
        if (res.status === 429) {
            state.cooldown_until = Date.now() + 10000;
            show_error(offset, "Слишком много запросов, подождите немного");
            return null;
        }
        if (!res.ok) {
            show_error(offset, `Ошибка получения пользователей: ${res.status}`);
            return null;
        }
        const json = await res.json();
        console.info(`fetched users offset=${offset} count=${json.length}`);
        return json;
    } catch (error) {
        console.warn("users request failed", error);
        show_error(offset, "Не удалось связаться с сервером");
        return null;
    }
}

function render_place(node, user) {
    const place = node.querySelector(".row-place");
    if (user.filtered_rank === null) {
        place.textContent = "—";
        return;
    }
    place.textContent = user.filtered_rank + ".";
    if (user.global_rank !== user.filtered_rank) {
        const global_place = document.createElement("div");
        global_place.className = "row-global-place";
        global_place.title = "Место в глобальном топе";
        global_place.textContent = "#" + user.global_rank;
        place.appendChild(global_place);
    }
}

function render_user(user) {
    const node = user_template.cloneNode(true);
    node.removeAttribute("id");
    node.dataset.userId = user.user_id;
    node.dataset.position = user.position;
    if (!user.exists) {
        node.classList.add("row-deleted");
    }
    render_place(node, user);
    node.querySelector(".row-avatar").textContent = user.avatar + "\uFE0F";
    const display_name = node.querySelector(".user-display-name");
    const name = document.createElement("span");
    name.textContent = user.display_name;
    display_name.textContent = "";
    display_name.appendChild(name);
    display_name.href = "https://итд.com/@" + user.user_id;
    if (user.verified && user.has_itdp) {
        const icon = document.createElement("img");
        icon.src = "/static/icons/itdp_verified.svg";
        display_name.appendChild(icon);
    } else if (user.verified) {
        const icon = document.createElement("img");
        icon.src = "/static/icons/verified.svg";
        display_name.appendChild(icon);
    } else if (user.has_itdp) {
        const icon = document.createElement("img");
        icon.src = "/static/icons/itdp.svg";
        display_name.appendChild(icon);
    }
    node.querySelector(".user-username").textContent = "@" + user.username;
    node.querySelector(".user-followers").textContent =
        new Intl.NumberFormat().format(user.followers_count);
    node.querySelector(".user-following").textContent =
        new Intl.NumberFormat().format(user.following_count);
    node.querySelector(".user-posts").textContent =
        new Intl.NumberFormat().format(user.posts_count);
    node.querySelector(".user-created-at").textContent = new Date(
        user.created_at,
    )
        .toLocaleString("ru-RU", {
            year: "numeric",
            month: "long",
            day: "numeric",
        })
        .replace(" г.", "");
    return node;
}

function update_gaps() {
    const container = get_el("rows");
    for (const gap of container.querySelectorAll(".row-gap")) {
        gap.remove();
    }
    const batches = [...container.querySelectorAll(".row-batch")];
    for (let i = 1; i < batches.length; i++) {
        const prev_offset = Number(batches[i - 1].dataset.offset);
        const offset = Number(batches[i].dataset.offset);
        if (offset <= prev_offset + PAGE_SIZE) {
            continue;
        }
        const gap = document.createElement("div");
        gap.className = "row row-gap";
        gap.dataset.offset = prev_offset + PAGE_SIZE;
        const spinner = document.createElement("div");
        spinner.className = "loader-spinner";
        gap.appendChild(spinner);
        container.insertBefore(gap, batches[i]);
        gap_observer.observe(gap);
    }
}

function get_scroll_anchor() {
    return [...document.querySelectorAll("#rows .row")].find(
        (node) => node.getBoundingClientRect().bottom > 0,
    );
}

function insert_batch(offset, users) {
    const container = get_el("rows");
    const batch = document.createElement("div");
    batch.className = "row-batch";
    batch.dataset.offset = offset;
    for (const user of users) {
        batch.appendChild(render_user(user));
    }
    const batches = [...container.querySelectorAll(".row-batch")];
    const next = batches.find((el) => Number(el.dataset.offset) > offset);
    const anchor = get_scroll_anchor();
    const anchor_top = anchor ? anchor.getBoundingClientRect().top : 0;
    container.insertBefore(batch, next ?? get_el("list-loader"));
    update_gaps();
    if (anchor) {
        const delta = anchor.getBoundingClientRect().top - anchor_top;
        if (delta) {
            window.scrollBy(0, delta);
        }
    }
}

async function load_batch(offset) {
    if (offset < 0 || state.loaded_offsets.has(offset) || state.loading) {
        return;
    }
    state.loading = true;
    hide_error();
    const gap = document.querySelector(`.row-gap[data-offset="${offset}"]`);
    if (!gap) {
        show_loader(true);
    }
    const users = await fetch_users(offset);
    show_loader(false);
    state.loading = false;
    if (users === null) {
        return;
    }
    const is_last = !state.loaded_offsets.size || offset > max_loaded_offset();
    state.loaded_offsets.add(offset);
    if (is_last && users.length < PAGE_SIZE) {
        state.finished = true;
    }
    if (users.length) {
        insert_batch(offset, users);
    } else {
        update_gaps();
    }
    get_el("list-empty").hidden = Boolean(document.querySelector(".row-batch"));
}

function reset_list() {
    for (const el of document.querySelectorAll(".row-batch, .row-gap")) {
        el.remove();
    }
    state.loaded_offsets.clear();
    state.finished = false;
    hide_error();
    get_el("list-empty").hidden = true;
}

async function reload() {
    write_url_state();
    reset_list();
    await load_batch(0);
}

function min_loaded_offset() {
    return Math.min(...state.loaded_offsets);
}

function max_loaded_offset() {
    return Math.max(...state.loaded_offsets);
}

function can_load() {
    return (
        !state.loading &&
        state.failed_offset === null &&
        state.loaded_offsets.size > 0 &&
        Date.now() >= state.cooldown_until
    );
}

function init_infinite_scroll() {
    gap_observer = new IntersectionObserver(async (entries) => {
        for (const entry of entries) {
            if (!entry.isIntersecting || !can_load()) {
                continue;
            }
            await load_batch(Number(entry.target.dataset.offset));
        }
    });
    const bottom_observer = new IntersectionObserver(async (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
            return;
        }
        if (!can_load() || state.finished) {
            return;
        }
        await load_batch(max_loaded_offset() + PAGE_SIZE);
    });
    bottom_observer.observe(get_el("sentinel-bottom"));
    const top_observer = new IntersectionObserver(async (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) {
            return;
        }
        if (!can_load() || min_loaded_offset() === 0) {
            return;
        }
        await load_batch(min_loaded_offset() - PAGE_SIZE);
    });
    top_observer.observe(get_el("sentinel-top"));
}

let search_timer = null;
let last_query = "";

function hide_candidates() {
    const candidates = get_el("search-candidates");
    candidates.hidden = true;
    candidates.replaceChildren();
}

function render_candidates(users) {
    const candidates = get_el("search-candidates");
    candidates.replaceChildren();
    if (!users.length) {
        const empty = document.createElement("div");
        empty.className = "search-candidate search-candidate-empty";
        empty.textContent = "Ничего не найдено";
        candidates.appendChild(empty);
    }
    for (const user of users) {
        const item = document.createElement("div");
        item.className = "search-candidate";
        const avatar = document.createElement("div");
        avatar.className = "search-candidate-avatar";
        avatar.textContent = user.avatar;
        const name = document.createElement("div");
        name.className = "search-candidate-name";
        name.textContent = user.display_name;
        const username = document.createElement("div");
        username.className = "search-candidate-username";
        username.textContent = "@" + user.username;
        const place = document.createElement("div");
        place.className = "search-candidate-place";
        place.textContent =
            user.global_rank !== null ? "#" + user.global_rank : "удалён";
        item.append(avatar, name, username, place);
        item.addEventListener("click", () => jump_to_user(user));
        candidates.appendChild(item);
    }
    candidates.hidden = false;
}

async function fetch_candidates(query) {
    const params = new URLSearchParams({
        query: query,
        order: state.order,
        descending: state.descending,
    });
    try {
        const res = await fetch("/api/ebdi/users/search?" + params);
        if (!res.ok) {
            console.warn(`search request failed status=${res.status}`);
            return;
        }
        const json = await res.json();
        render_candidates(json.results);
    } catch (error) {
        console.warn("search request failed", error);
    }
}

function on_search_input(event) {
    clearTimeout(search_timer);
    const query = event.target.value.trim();
    if (!query) {
        last_query = "";
        hide_candidates();
        return;
    }
    if (query === last_query) {
        return;
    }
    search_timer = setTimeout(() => {
        last_query = query;
        fetch_candidates(query);
    }, SEARCH_DELAY);
}

function find_user_node(user_id) {
    return document.querySelector(`.row[data-user-id="${user_id}"]`);
}

function page_offset(place) {
    return Math.max(Math.floor((place - 1) / PAGE_SIZE) * PAGE_SIZE, 0);
}

function has_active_filters() {
    return LIST_FILTERS.some((key) => state[key] !== DEFAULT_STATE[key]);
}

function clear_filters() {
    for (const key of LIST_FILTERS) {
        state[key] = DEFAULT_STATE[key];
    }
    apply_state_to_controls();
    write_url_state();
}

async function wait_loading() {
    while (state.loading) {
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
}

async function jump_to_user(user) {
    hide_candidates();
    let needs_reset = has_active_filters();
    if (needs_reset) {
        clear_filters();
    }
    if (user.global_rank === null && !state.show_deleted) {
        state.show_deleted = true;
        get_el("deleted-checkbox").checked = true;
        write_url_state();
        needs_reset = true;
    }
    if (needs_reset) {
        reset_list();
    }
    await wait_loading();
    const place = state.show_deleted ? user.position : user.global_rank;
    for (const offset of [
        page_offset(place),
        page_offset(place) + PAGE_SIZE,
        page_offset(place) - PAGE_SIZE,
    ]) {
        await load_batch(offset);
        if (find_user_node(user.user_id)) {
            break;
        }
    }
    const node = find_user_node(user.user_id);
    if (!node) {
        console.warn(`user ${user.user_id} not found in loaded batches`);
        return;
    }
    node.scrollIntoView({ behavior: "smooth", block: "center" });
    node.classList.add("row-highlighted");
    setTimeout(() => node.classList.remove("row-highlighted"), 3000);
}

function init_sort_headers() {
    for (const cell of document.querySelectorAll(".row-sortable")) {
        cell.addEventListener("click", () => {
            if (cell.dataset.order === state.order) {
                state.descending = !state.descending;
            } else {
                state.order = cell.dataset.order;
                state.descending = true;
            }
            update_sort_headers();
            reload();
        });
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
            state.clan = normalize_emoji(event.detail.unicode);
            get_el("clan-text").textContent = `Клан: ${state.clan}\uFE0F`;
            get_el("clan-remove").hidden = false;
            picker_box.hidden = true;
            reload();
        });

    get_el("clan-remove").addEventListener("click", () => {
        state.clan = "";
        get_el("clan-remove").hidden = true;
        get_el("clan-text").textContent = "Клан: Все";
        reload();
    });
}

function init_controls() {
    init_sort_headers();
    init_clan_picker();
    for (const name of RADIO_FILTERS) {
        for (const input of document.querySelectorAll(
            `input[name="${name}"]`,
        )) {
            input.addEventListener("change", (event) => {
                state[name] = event.target.value;
                reload();
            });
        }
    }
    get_el("deleted-checkbox").addEventListener("change", (event) => {
        state.show_deleted = event.target.checked;
        reload();
    });
    get_el("retry-button").addEventListener("click", () => {
        const offset = state.failed_offset;
        hide_error();
        load_batch(offset);
    });
    const search_input = get_el("search-input");
    search_input.addEventListener("input", on_search_input);
    document.addEventListener("click", (event) => {
        // composedPath sees through shadow DOM of emoji-picker
        const path = event.composedPath();
        if (!path.includes(get_el("search-box"))) {
            hide_candidates();
        }
        if (
            !path.includes(get_el("clan-button")) &&
            !path.includes(get_el("clan-picker")) &&
            !get_el("clan-picker").hidden
        ) {
            get_el("clan-picker").hidden = true;
        }
    });
}

// https://css-tricks.com/how-to-detect-when-a-sticky-element-gets-pinned/
function observe_controls_stick() {
    const observer = new IntersectionObserver(
        ([e]) => e.target.classList.toggle("pinned", e.intersectionRatio < 1),
        { threshold: [1] },
    );

    observer.observe(get_el("controls-box"));
}

document.addEventListener("DOMContentLoaded", async () => {
    user_template = get_el("user-template");
    user_template.remove();
    read_url_state();
    apply_state_to_controls();
    init_controls();
    init_infinite_scroll();
    observe_controls_stick();
    await load_batch(0);
    await fetch_count();
});
