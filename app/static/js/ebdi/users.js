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

const users_by_id = new Map();
let dialog_user = null;
let dialog_token = 0;
let scroll_lock_offset = 0;

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
    if (user.rank == null) {
        place.textContent = "-";
        return;
    }
    place.textContent = user.rank + ".";
}

function render_badge_icon(user) {
    let src = null;
    if (user.verified && user.has_itdp) {
        src = "/static/icons/itdp_verified.svg";
    } else if (user.verified) {
        src = "/static/icons/verified.svg";
    } else if (user.has_itdp) {
        src = "/static/icons/itdp.svg";
    }
    if (!src) {
        return null;
    }
    const icon = document.createElement("img");
    icon.src = src;
    return icon;
}

function render_user(user) {
    const node = user_template.cloneNode(true);
    node.removeAttribute("id");
    node.dataset.userId = user.user_id;
    node.dataset.position = user.position;
    users_by_id.set(user.user_id, user);
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
    const icon = render_badge_icon(user);
    if (icon) {
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
    users_by_id.clear();
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
        !get_el("user-dialog").open &&
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
        place.textContent = user.rank != null ? "#" + user.rank : "удалён";
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
    if (user.rank === null && !state.show_deleted) {
        state.show_deleted = true;
        get_el("deleted-checkbox").checked = true;
        write_url_state();
        needs_reset = true;
    }
    if (needs_reset) {
        reset_list();
    }
    await wait_loading();
    const place = state.show_deleted ? user.position : user.rank;
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

function format_number(value) {
    return new Intl.NumberFormat().format(value);
}

function format_date(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return String(value);
    }
    return date
        .toLocaleString("ru-RU", {
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        })
        .replace(" г.", "");
}

function create(tag, class_name, text) {
    const node = document.createElement(tag);
    if (class_name) {
        node.className = class_name;
    }
    if (text !== undefined) {
        node.textContent = text;
    }
    return node;
}

function show_dialog_error(message) {
    const error = get_el("dialog-error");
    error.textContent = message;
    error.hidden = !message;
}

function render_dialog_header(user) {
    const banner = get_el("dialog-banner");
    const has_banner =
        typeof user.banner === "string" && /^https?:\/\//.test(user.banner);
    banner.style.backgroundImage = has_banner
        ? `linear-gradient(to bottom, #1e1c1a00, #1e1c1a88), url("${encodeURI(user.banner)}")`
        : "";

    const avatar = get_el("dialog-avatar");
    avatar.textContent = user.avatar + "\uFE0F";
    avatar.title = "Клан";

    const display_name = get_el("dialog-display-name");
    display_name.replaceChildren(create("span", null, user.display_name));
    const icon = render_badge_icon(user);
    if (icon) {
        display_name.appendChild(icon);
    }
    display_name.href = "https://итд.com/@" + user.user_id;
    get_el("dialog-username").textContent = "@" + user.username;

    const badges = get_el("dialog-badges");
    badges.replaceChildren();

    if (user.exists == false) {
        badges.appendChild(
            create("div", "dialog-user-deleted", "Удален из ИТД"),
        );
    }
    badges.hidden = !badges.children.length;

    const bio = get_el("dialog-bio");
    bio.textContent = user.bio ?? "";
    bio.hidden = !user.bio;
}

function render_gap(label, amount) {
    const line = create("div");
    line.append(label + ": ");
    line.append(create("b", null, "+" + format_number(Math.max(1, amount))));
    return line;
}

function render_rank_card(label, rank) {
    const card = create("div", "rank-card");

    const head = create("div", "rank-head");
    head.append(create("div", "rank-label", label));
    head.append(
        create(
            "div",
            "rank-place",
            rank.place == null ? "-" : `#${rank.place}`,
        ),
    );
    card.append(head);
    card.append(create("div", "rank-value", format_number(rank.total)));
    card.append(create("div", "rank-bar"));

    const gaps = create("div", "rank-gaps");
    if (rank.place == 1) {
        gaps.append(create("div", "gap-done", "Первое место"));
    } else if (rank.to_next) {
        gaps.append(render_gap("До следующего места", rank.to_next));
    }
    if (rank.place != null && rank.to_top_100 == null) {
        gaps.append(create("div", "gap-done", `В топ-100`));
    } else if (rank.to_top_100 != null) {
        gaps.append(render_gap(`До топ-100`, rank.to_top_100));
    }
    card.append(gaps);
    return card;
}

function render_dialog_ranks(ranks) {
    const container = get_el("dialog-ranks");
    container.append(render_rank_card("Подписчики", ranks.followers));
    container.append(render_rank_card("Подписки", ranks.following));
    container.append(render_rank_card("Посты", ranks.posts));
}

function render_dialog_dates(user) {
    const container = get_el("dialog-dates");
    container.replaceChildren();
    for (const entry of [
        { field: "created_at", label: "Дата регистрации" },
        { field: "last_seen", label: "Последняя активность" },
        { field: "found_at", label: "Добавлен в ЕБДИ" },
        { field: "updated_at", label: "Последняя синхронизация с ИТД" },
    ]) {
        if (!user[entry.field]) {
            continue;
        }
        let value;
        if (entry.field == "last_seen") {
            if (
                ["recently", "minutes", "hours", "just_now"].includes(
                    user[entry.field],
                )
            ) {
                value = "~1 день назад";
            } else if (user[entry.field] == "this_week") {
                value = "~7 дней назад";
            } else if (user[entry.field] == "this_month") {
                value = "~30 дней назад";
            } else if (user[entry.field] == "long_ago") {
                value = "Давно";
            } else {
                value = "Скрыто";
            }
        } else {
            value = format_date(user[entry.field]);
            if (!value) {
                console.warn(
                    `failed to format date ${user[entry.field]} field=${entry.field}`,
                );
            }
        }
        const item = create("div", "dialog-date");
        item.append(create("div", "dialog-date-label", entry.label));
        item.append(create("div", "dialog-date-value", value));
        container.append(item);
    }
}

function render_dialog(user) {
    render_dialog_header(user);
    render_dialog_dates(user);
}

async function load_dialog_ranks(user, token) {
    const loader = get_el("dialog-ranks-loader-container");
    loader.hidden = false;
    get_el("dialog-ranks").replaceChildren();
    try {
        const res = await fetch(`/api/ebdi/users/${user.id}/ranks`);
        if (!res.ok) {
            throw new Error(`status ${res.status}`);
        }
        const json = await res.json();
        if (token != dialog_token) {
            return;
        }
        render_dialog_ranks(json);
        show_dialog_error("");
    } catch (error) {
        console.warn("ranks request failed", error);
        if (token == dialog_token) {
            show_dialog_error("Не удалось загрузить места в рейтинге");
        }
    } finally {
        loader.hidden = true;
    }
}

// body overflow would reset the scroll position, so the page is pinned instead
function lock_scroll() {
    scroll_lock_offset = window.scrollY;
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.position = "fixed";
    document.body.style.top = `-${scroll_lock_offset}px`;
    document.body.style.left = "0";
    document.body.style.right = "0";
    if (scrollbar > 0) {
        document.body.style.paddingRight = `${scrollbar}px`;
    }
}

function unlock_scroll() {
    document.body.style.position = "";
    document.body.style.top = "";
    document.body.style.left = "";
    document.body.style.right = "";
    document.body.style.paddingRight = "";
    window.scrollTo({ top: scroll_lock_offset, behavior: "instant" });
}

function open_user_dialog(user) {
    if (!user) {
        return;
    }
    dialog_token += 1;
    dialog_user = user;
    show_dialog_error("");
    render_dialog(user);
    const dialog = get_el("user-dialog");
    if (!dialog.open) {
        lock_scroll();
        dialog.showModal();
    }
    get_el("dialog-scroll").scrollTop = 0;
    load_dialog_ranks(user, dialog_token);
}

function close_user_dialog() {
    dialog_token += 1;
    const dialog = get_el("user-dialog");
    if (dialog.open) {
        dialog.close();
    }
}

async function refresh_dialog_user() {
    const button = get_el("dialog-refresh");
    button.classList.add("load");
    button.disabled = true;
    const user = dialog_user;
    const token = dialog_token;
    try {
        const res = await fetch(`/api/ebdi/users/${user.id}/refresh`, {
            method: "POST",
        });
        if (!res.ok) {
            show_dialog_error(`Ошибка обновления: ${res.status}`);
            return;
        }
        const json = await res.json();
        if (token != dialog_token) {
            return;
        }
        users_by_id.set(json.user_id, json);
        dialog_user = json;
        show_dialog_error("");
        render_dialog(json);
        await load_dialog_ranks(json, token);
    } catch (error) {
        console.warn("user refresh failed", error);
        show_dialog_error("Не удалось связаться с сервером");
    } finally {
        button.classList.remove("load");
        button.disabled = false;
    }
}

async function download_dialog_card() {
    const button = get_el("dialog-download");
    button.classList.add("load");
    button.disabled = true;
    try {
        const res = await fetch(`/api/ebdi/users/${dialog_user.id}/card`);
        if (!res.ok) {
            show_dialog_error(`Ошибка получения карточки: ${res.status}`);
            return;
        }
        const json = await res.json();
        const url = typeof json === "string" ? json : json.url;
        if (!url) {
            show_dialog_error("Сервер не вернул ссылку на карточку");
            return;
        }
        const link = document.createElement("a");
        link.href = url;
        link.download = dialog_user.username + ".png";
        link.target = "_blank";
        link.rel = "noopener";
        document.body.appendChild(link);
        link.click();
        link.remove();
    } catch (error) {
        console.warn("card request failed", error);
        show_dialog_error("Не удалось связаться с сервером");
    } finally {
        button.classList.remove("load");
        button.disabled = false;
    }
}

function init_user_dialog() {
    const dialog = get_el("user-dialog");
    get_el("rows").addEventListener("click", (event) => {
        if (event.target.closest("a, button")) {
            return;
        }
        const node = event.target.closest(".row[data-user-id]");
        if (node) {
            open_user_dialog(users_by_id.get(node.dataset.userId));
        }
    });
    get_el("dialog-close").addEventListener("click", close_user_dialog);
    // get_el("dialog-refresh").addEventListener("click", refresh_dialog_user);
    // get_el("dialog-download").addEventListener("click", download_dialog_card);
    dialog.addEventListener("click", (event) => {
        if (event.target == dialog) {
            close_user_dialog();
        }
    });
    dialog.addEventListener("close", unlock_scroll);
}

function init_sort_headers() {
    for (const cell of document.querySelectorAll(".row-sortable")) {
        cell.addEventListener("click", () => {
            if (cell.dataset.order == state.order) {
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
    init_user_dialog();
    init_infinite_scroll();
    observe_controls_stick();
    await load_batch(0);
    await fetch_count();
});
