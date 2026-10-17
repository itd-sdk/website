const PAGE_SIZE = 20;
const ITD = "https://итд.com";
const IMAGE_RE = /\.(jpe?g|png|gif|webp|avif)(\?|$)/i;
const ICONS = {
    likes: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" width="20" height="20"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 4.6a3.7 3.7 0 0 0-5.2-.9C3.2 5 2.4 7.6 3.6 10.2 4.8 12.7 10 17 10 17s5.3-4.3 6.5-6.8c1.2-2.6 0-5.2-1.6-6.5s-4-.8-4.9.9"></path></svg>',
    comments: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 20" width="20" height="20"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.0" d="M10 17a7 7 0 1 0-6.2-3.7L3 17l3.7-.8a7 7 0 0 0 3.3.8"></path></svg>',
    reposts: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 20" width="20" height="20"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.0" d="M4 9V8a3 3 0 0 1 3-3h9m-3 3 3-3-3-3M16 11v1a3 3 0 0 1-3 3H4m3-3-3 3 3 3"></path></svg>',
    views: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 20 20"><path stroke="currentColor" stroke-width="1.5" d="M2 10s2.91-6 8-6 8 6 8 6-2.91 6-8 6-8-6-8-6Z"></path><path stroke="currentColor" stroke-width="1.5" d="M10 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"></path></svg>',
};

// posts and comments tabs share this file, the script tag tells which one it is
const KIND = document.currentScript.dataset.kind;
const FEEDS = {
    posts: { api: "/api/ebdi/posts", error: "постов", render: (item) => render_post(item) },
    comments: { api: "/api/ebdi/comments", error: "комментариев", render: (item) => render_comment(item) },
};
const FEED = FEEDS[KIND];
const DEFAULT_STATE = { sort: "found", q: "", user: "", deleted: false };
const SEARCH_DELAY = 300;

let state = { ...DEFAULT_STATE };
let search_timer = null;
let offset = 0;
let has_more = true;
let loading = false;
let request_token = 0;

function get_el(id) {
    return document.getElementById(id);
}

function create(tag, class_name, text) {
    const node = document.createElement(tag);
    if (class_name) {
        node.className = class_name;
    }
    if (text != undefined) {
        node.textContent = text;
    }
    return node;
}

function format_number(value) {
    return new Intl.NumberFormat("ru-RU").format(value);
}

function format_date(value) {
    if (!value) {
        return "";
    }
    return new Date(value)
        .toLocaleString("ru-RU", {
            year: "numeric",
            month: "long",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
        })
        .replace(" г.", "");
}

function profile_url(user) {
    return `${ITD}/@${user.username}`;
}

function read_url_state() {
    const params = new URLSearchParams(location.search);
    const sort = params.get("sort");
    // links from older versions may carry sorts that no longer exist
    const known = [...get_el("sort-select").options].some((o) => o.value == sort);
    state.sort = known ? sort : DEFAULT_STATE.sort;
    state.q = params.get("q") || "";
    state.user = params.get("user") || "";
    state.deleted = params.get("deleted") == "true";
}

function write_url_state() {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(state)) {
        if (value != DEFAULT_STATE[key]) {
            params.set(key, value);
        }
    }
    const query = params.toString();
    history.replaceState(null, "", query ? `?${query}` : location.pathname);
}

function apply_state_to_controls() {
    get_el("sort-select").value = state.sort;
    get_el("deleted-checkbox").checked = state.deleted;
    get_el("user-input").value = state.user;
    get_el("query-input").value = state.q;
}

function post_url(post_id, author, author_id) {
    return `${ITD}/@${author ? author.username : author_id}/post/${post_id}`;
}

// avatar, name, @username and the date linking to the post in ITD
function render_header(author, author_id, date, url) {
    const header = create("div", "post-header");
    const avatar = create("div", "row-avatar", author ? author.avatar + "\uFE0F" : "?");
    header.append(avatar);

    const names = create("div", "post-names");
    const name = create("a", "post-display-name");
    name.target = "_blank";
    name.href = `${ITD}/@${author ? author.username : author_id}`;
    name.append(create("span", null, author ? author.display_name : "Неизвестный автор"));
    if (author?.verified) {
        const icon = create("img", "post-verified");
        icon.src = "/static/icons/verified.svg";
        name.append(icon);
    }
    names.append(name);
    if (author) {
        names.append(create("div", "post-username", "@" + author.username));
    }
    header.append(names);

    const link = create("a", "post-date", format_date(date));
    link.target = "_blank";
    link.href = url;
    link.title = "Открыть в ИТД";
    header.append(link);
    return header;
}

function render_author(post) {
    return render_header(
        post.author,
        post.author_id,
        post.created_at || post.found_at,
        post_url(post.post_id, post.author, post.author_id),
    );
}

function render_attachments(urls) {
    const box = create("div", "post-attachments");
    for (const url of urls) {
        if (!/^https?:\/\//.test(url)) {
            continue;
        }
        if (IMAGE_RE.test(url)) {
            const link = create("a");
            link.href = url;
            link.target = "_blank";
            const image = create("img", "post-image");
            image.loading = "lazy";
            image.src = url;
            link.append(image);
            box.append(link);
        } else {
            const link = create("a", "post-file", "Вложение");
            link.href = url;
            link.target = "_blank";
            box.append(link);
        }
    }
    return box;
}

function render_poll(post) {
    const poll = create("div", "post-poll");
    poll.append(create("div", "post-poll-question", post.poll_question));
    for (const option of post.poll_options || []) {
        poll.append(create("div", "post-poll-option", option));
    }
    if (post.poll_multiple) {
        poll.append(create("div", "post-poll-note", "Можно выбрать несколько"));
    }
    return poll;
}

function render_stat(value, icon, title) {
    const item = create("div", "post-stat");
    item.title = title;
    // icons are constants from this file, never data from the api
    item.innerHTML = ICONS[icon];
    item.append(create("span", null, format_number(value)));
    return item;
}

// likes comments reposts ........ clan views
function render_stats(post) {
    const stats = create("div", "post-stats");
    stats.append(render_stat(post.likes_count, "likes", "Лайки"));
    stats.append(render_stat(post.comments_count, "comments", "Комментарии"));
    stats.append(render_stat(post.reposts_count, "reposts", "Репосты"));

    const right = create("div", "post-stats-right");
    if (post.dominant) {
        const clan = create("div", "post-dominant", post.dominant + "\uFE0F");
        clan.title = "Доминирующий клан";
        right.append(clan);
    }
    right.append(render_stat(post.views_count, "views", "Просмотры"));
    stats.append(right);
    return stats;
}

function render_badges(post) {
    const box = create("div", "post-badges");
    if (!post.exists) {
        box.append(create("span", "post-badge post-badge-deleted", "Удалён"));
    }
    if (post.original_post_id) {
        box.append(create("span", "post-badge", "Репост"));
    }
    if (post.wall_recipient_id && post.wall_recipient_id != post.author_id) {
        const badge = create("span", "post-badge", "На стене ");
        if (post.wall_recipient) {
            const link = create("a", null, "@" + post.wall_recipient.username);
            link.href = profile_url(post.wall_recipient);
            link.target = "_blank";
            badge.append(link);
        } else {
            badge.append("другого пользователя");
        }
        box.append(badge);
    }
    if (post.edited_at) {
        box.append(create("span", "post-badge", `Изменён ${format_date(post.edited_at)}`));
    }
    return box;
}

function render_post(post, nested = false) {
    const card = create("article", nested ? "post-card post-original" : "post-card");
    if (post.author && !post.author.exists) {
        card.classList.add("post-deleted-author");
    }
    card.append(render_author(post));

    const badges = render_badges(post);
    if (badges.children.length) {
        card.append(badges);
    }
    if (post.content) {
        card.append(create("div", "post-content", post.content));
    }
    if (post.attachments.length) {
        card.append(render_attachments(post.attachments));
    }
    if (post.poll_question) {
        card.append(render_poll(post));
    }
    if (post.original_post_id && !nested) {
        if (post.original) {
            card.append(render_post(post.original, true));
        } else {
            card.append(create("div", "post-original post-original-missing", "Оригинальный пост не сохранён в базе"));
        }
    }
    card.append(render_stats(post));
    return card;
}

function render_comment(comment) {
    const card = create("article", "post-card comment-card");
    if (comment.author && !comment.author.exists) {
        card.classList.add("post-deleted-author");
    }
    card.append(
        render_header(
            comment.author,
            comment.author_id,
            comment.created_at || comment.found_at,
            post_url(comment.post_id, comment.post_author, comment.post_author?.user_id),
        ),
    );

    const badges = create("div", "post-badges");
    if (!comment.post_exists) {
        badges.append(create("span", "post-badge post-badge-deleted", "Пост удалён"));
    }
    if (comment.parent_id) {
        const badge = create("span", "post-badge", "Ответ");
        if (comment.reply_to) {
            badge.append(" ");
            const link = create("a", null, "@" + comment.reply_to.username);
            link.href = profile_url(comment.reply_to);
            link.target = "_blank";
            badge.append(link);
        }
        badges.append(badge);
    }
    if (badges.children.length) {
        card.append(badges);
    }
    if (comment.content) {
        card.append(create("div", "post-content", comment.content));
    }
    if (comment.attachments.length) {
        card.append(render_attachments(comment.attachments));
    }

    const stats = create("div", "post-stats");
    stats.append(render_stat(comment.likes_count, "likes", "Лайки"));
    if (!comment.parent_id) {
        stats.append(render_stat(comment.replies_count, "comments", "Ответы"));
    }
    card.append(stats);
    return card;
}

function show_error(message) {
    get_el("error-text").textContent = message;
    get_el("list-error").hidden = false;
}

async function load_page() {
    if (loading || !has_more) {
        return;
    }
    loading = true;
    const token = request_token;
    get_el("list-loader").hidden = false;
    get_el("list-error").hidden = true;
    try {
        const params = new URLSearchParams({ ...state, offset, limit: PAGE_SIZE });
        const res = await fetch(`${FEED.api}?${params}`);
        if (token != request_token) {
            return;
        }
        if (res.status == 429) {
            show_error("Слишком много запросов, подождите немного");
            return;
        }
        if (!res.ok) {
            show_error(`Ошибка получения ${FEED.error}: ${res.status}`);
            return;
        }
        const items = await res.json();
        if (token != request_token) {
            return;
        }
        const list = get_el("feed");
        for (const item of items) {
            list.append(FEED.render(item));
        }
        offset += items.length;
        has_more = items.length == PAGE_SIZE;
        get_el("list-empty").hidden = offset > 0;
        // the observer only fires on changes, a short page keeps the sentinel visible
        requestAnimationFrame(load_if_visible);
    } catch (error) {
        console.warn("feed request failed", error);
        if (token == request_token) {
            show_error("Не удалось связаться с сервером");
        }
    } finally {
        if (token == request_token) {
            loading = false;
            get_el("list-loader").hidden = true;
        }
    }
}

function load_if_visible() {
    const rect = get_el("sentinel-bottom").getBoundingClientRect();
    if (rect.top < window.innerHeight + 800) {
        load_page();
    }
}

function reload() {
    // responses of the previous filter are dropped by the token check
    request_token += 1;
    loading = false;
    offset = 0;
    has_more = true;
    get_el("feed").replaceChildren();
    get_el("list-empty").hidden = true;
    load_page();
}

async function load_count() {
    try {
        const res = await fetch(`${FEED.api}/count`);
        if (!res.ok) {
            return;
        }
        const json = await res.json();
        get_el("total-objects-value").textContent = format_number(json.count);
        get_el("total-objects").hidden = false;
    } catch (error) {
        console.warn("count request failed", error);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    read_url_state();
    apply_state_to_controls();

    const apply = () => {
        write_url_state();
        reload();
    };
    get_el("sort-select").addEventListener("change", (event) => {
        state.sort = event.target.value;
        apply();
    });
    get_el("deleted-checkbox").addEventListener("change", (event) => {
        state.deleted = event.target.checked;
        apply();
    });
    // the list follows the search fields as they are typed in
    for (const [id, key] of [
        ["user-input", "user"],
        ["query-input", "q"],
    ]) {
        get_el(id).addEventListener("input", (event) => {
            clearTimeout(search_timer);
            search_timer = setTimeout(() => {
                const value = event.target.value.trim();
                if (value != state[key]) {
                    state[key] = value;
                    apply();
                }
            }, SEARCH_DELAY);
        });
    }
    get_el("retry-button").addEventListener("click", load_page);

    new IntersectionObserver(
        (entries) => {
            if (entries.some((entry) => entry.isIntersecting)) {
                load_page();
            }
        },
        { rootMargin: "800px" },
    ).observe(get_el("sentinel-bottom"));

    load_count();
    load_page();
});
