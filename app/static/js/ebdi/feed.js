const PAGE_SIZE = 20;
const ITD = "https://итд.com";
const IMAGE_RE = /\.(jpe?g|png|gif|webp|avif)(\?|$)/i;
const VIDEO_RE = /\.(mp4|webm|mov|m4v)(\?|$)/i;
const AUDIO_RE = /\.(ogg|oga|opus|wav|mp3|m4a|aac|flac)(\?|$)/i;
const WAVESURFER_URL = "https://cdn.jsdelivr.net/npm/wavesurfer.js@7.12.12/dist/wavesurfer.esm.js";
const ICONS = {
    likes: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" width="20" height="20"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 4.6a3.7 3.7 0 0 0-5.2-.9C3.2 5 2.4 7.6 3.6 10.2 4.8 12.7 10 17 10 17s5.3-4.3 6.5-6.8c1.2-2.6 0-5.2-1.6-6.5s-4-.8-4.9.9"></path></svg>',
    comments: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 20" width="20" height="20"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.0" d="M10 17a7 7 0 1 0-6.2-3.7L3 17l3.7-.8a7 7 0 0 0 3.3.8"></path></svg>',
    reposts: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 20 20" width="20" height="20"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.0" d="M4 9V8a3 3 0 0 1 3-3h9m-3 3 3-3-3-3M16 11v1a3 3 0 0 1-3 3H4m3-3-3 3 3 3"></path></svg>',
    close: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" width="16" height="16"><path stroke="currentColor" stroke-linecap="round" stroke-width="2" d="m5 5 10 10M15 5 5 15"></path></svg>',
    views: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 20 20"><path stroke="currentColor" stroke-width="1.5" d="M2 10s2.91-6 8-6 8 6 8 6-2.91 6-8 6-8-6-8-6Z"></path><path stroke="currentColor" stroke-width="1.5" d="M10 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z"></path></svg>',
    open: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" width="16" height="16"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M11 3h6v6M17 3l-8 8M15 12v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h3"></path></svg>',
    play: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="18" height="18"><path fill="currentColor" d="M6 4.2v11.6a.8.8 0 0 0 1.2.7l9.2-5.8a.8.8 0 0 0 0-1.4L7.2 3.5a.8.8 0 0 0-1.2.7"></path></svg>',
    pause: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" width="18" height="18"><rect fill="currentColor" x="5" y="4" width="3.5" height="12" rx="1"></rect><rect fill="currentColor" x="11.5" y="4" width="3.5" height="12" rx="1"></rect></svg>',
};

// posts and comments tabs share this file, the script tag tells which one it is
const KIND = document.currentScript.dataset.kind;
const FEEDS = {
    posts: {
        api: "/api/ebdi/posts",
        error: "постов",
        defaults: { deleted: false },
        render: (item) => render_post(item),
    },
    comments: {
        api: "/api/ebdi/comments",
        error: "комментариев",
        defaults: { deleted: false, deleted_posts: false },
        render: (item) => render_comment(item),
    },
};
const FEED = FEEDS[KIND];
const DEFAULT_STATE = { sort: "found", q: "", user: "", ...FEED.defaults };
const SEARCH_DELAY = 300;
const THREAD_BATCH = 100;

let state = { ...DEFAULT_STATE };
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

// icons are constants from this file, never data from the api
function icon_button(class_name, icon, title) {
    const button = create("button", class_name);
    button.type = "button";
    button.title = title;
    button.setAttribute("aria-label", title);
    button.innerHTML = ICONS[icon];
    return button;
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

function format_duration(seconds) {
    if (!isFinite(seconds)) {
        return "0:00";
    }
    const total = Math.floor(seconds);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function profile_url(user) {
    return `${ITD}/@${user.username}`;
}

function toggles() {
    return document.querySelectorAll("#feed-controls input[data-state]");
}

function read_url_state() {
    const params = new URLSearchParams(location.search);
    const sort = params.get("sort");
    // links from older versions may carry sorts that no longer exist
    const known = [...get_el("sort-select").options].some((o) => o.value == sort);
    state.sort = known ? sort : DEFAULT_STATE.sort;
    state.q = params.get("q") || "";
    state.user = (params.get("user") || "").replace(/^@/, "");
    for (const key of Object.keys(FEED.defaults)) {
        state[key] = params.get(key) == "true";
    }
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

function user_input_text() {
    return state.user ? "@" + state.user : "";
}

function apply_state_to_controls() {
    get_el("sort-select").value = state.sort;
    for (const toggle of toggles()) {
        toggle.checked = state[toggle.dataset.state];
    }
    get_el("user-input").value = user_input_text();
    get_el("query-input").value = state.q;
    update_clear_buttons();
}

function post_url(post_id, author, author_id) {
    return `${ITD}/@${author ? author.username : author_id}/post/${post_id}`;
}

function comment_url(comment) {
    const post = post_url(comment.post_id, comment.post_author, comment.post_author?.user_id);
    return `${post}?comment=${comment.comment_id}`;
}

// avatar, name, @username, the date and a button opening the item in ITD
function render_header(author, author_id, date, url) {
    const header = create("div", "post-header");
    const avatar = create("div", "row-avatar", author ? author.avatar + "️" : "?");
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

    header.append(create("span", "post-date", format_date(date)));
    const open = create("a", "post-open");
    open.href = url;
    open.target = "_blank";
    open.title = "Открыть в ИТД";
    open.setAttribute("aria-label", "Открыть в ИТД");
    open.innerHTML = ICONS.open;
    header.append(open);
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

let playing = null;
let waveform_observer = null;

// deterministic bars for files the browser is not allowed to decode
function placeholder_peaks(url) {
    let seed = 0;
    for (const char of url) {
        seed = (seed * 31 + char.charCodeAt(0)) >>> 0;
    }
    const peaks = [];
    for (let i = 0; i < 80; i++) {
        seed = (seed * 1103515245 + 12345) >>> 0;
        peaks.push(0.25 + ((seed >>> 16) % 1000) / 1333);
    }
    return peaks;
}

async function init_waveform(tile) {
    const { url } = tile.dataset;
    const wave = tile.querySelector(".audio-wave");
    const play = tile.querySelector(".audio-play");
    const time = tile.querySelector(".audio-time");
    let WaveSurfer;
    try {
        WaveSurfer = (await import(WAVESURFER_URL)).default;
    } catch (error) {
        // without the library the native player still plays the file
        console.warn("wavesurfer import failed", error);
        const audio = create("audio", "audio-native");
        audio.controls = true;
        audio.preload = "none";
        audio.src = url;
        tile.replaceChildren(audio);
        return;
    }
    const player = WaveSurfer.create({
        container: wave,
        height: 44,
        waveColor: "#6a5e50",
        progressColor: "#ed6a2d",
        cursorWidth: 0,
        barWidth: 2,
        barGap: 2,
        barRadius: 2,
        normalize: true,
    });
    const set_icon = (name) => (play.innerHTML = ICONS[name]);
    player.on("ready", (duration) => (time.textContent = format_duration(duration)));
    player.on("timeupdate", (current) => (time.textContent = format_duration(current)));
    player.on("play", () => {
        if (playing && playing != player) {
            playing.pause();
        }
        playing = player;
        set_icon("pause");
    });
    player.on("pause", () => set_icon("play"));
    player.on("finish", () => set_icon("play"));
    play.addEventListener("click", () => player.playPause());
    play.disabled = false;
    try {
        await player.load(url);
    } catch (error) {
        // the file host may not allow cross-origin reads, the media element plays it anyway
        console.warn("audio decode failed, drawing placeholder", error);
        await player.load(url, [placeholder_peaks(url)]).catch(() => {});
    }
}

// waveforms are fetched only when the attachment gets close to the viewport
function observe_waveform(tile) {
    waveform_observer ??= new IntersectionObserver(
        (entries) => {
            for (const entry of entries) {
                if (entry.isIntersecting) {
                    waveform_observer.unobserve(entry.target);
                    init_waveform(entry.target);
                }
            }
        },
        { rootMargin: "300px" },
    );
    waveform_observer.observe(tile);
}

function stop_playing() {
    playing?.pause();
}

function render_audio(url) {
    const tile = create("div", "attachment attachment-audio");
    tile.dataset.url = url;
    const play = icon_button("audio-play", "play", "Воспроизвести");
    play.disabled = true;
    tile.append(play, create("div", "audio-wave"), create("span", "audio-time", "0:00"));
    observe_waveform(tile);
    return tile;
}

// every attachment is a tile of the same size in one horizontally scrolled row
function render_attachments(urls) {
    const box = create("div", "post-attachments");
    for (const url of urls) {
        if (!/^https?:\/\//.test(url)) {
            continue;
        }
        if (IMAGE_RE.test(url)) {
            const link = create("a", "attachment");
            link.href = url;
            link.target = "_blank";
            const image = create("img", "attachment-image");
            image.loading = "lazy";
            image.src = url;
            link.append(image);
            box.append(link);
        } else if (VIDEO_RE.test(url)) {
            const video = create("video", "attachment attachment-video");
            video.controls = true;
            video.preload = "metadata";
            video.src = url;
            box.append(video);
        } else if (AUDIO_RE.test(url)) {
            box.append(render_audio(url));
        } else {
            const link = create("a", "attachment attachment-file", "Вложение");
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
        const clan = create("div", "post-dominant", post.dominant + "️");
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

function render_post(post, nested = false, in_dialog = false) {
    const card = create("article", nested ? "post-card post-original" : "post-card");
    if (!in_dialog) {
        make_clickable(card, () => open_post_dialog(post));
    }
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
            card.append(render_post(post.original, true, in_dialog));
        } else {
            card.append(create("div", "post-original post-original-missing", "Оригинальный пост не сохранён в базе"));
        }
    }
    card.append(render_stats(post));
    return card;
}

// clicks on links, controls, attachments, nested clickable cards or a text selection are not card clicks
function make_clickable(card, on_click) {
    card.classList.add("clickable");
    card.addEventListener("click", (event) => {
        const target = event.target;
        if (target.closest("a, button, video, audio, .attachment, .comment-replies") || target.closest(".clickable") != card) {
            return;
        }
        if (window.getSelection().toString()) {
            return;
        }
        on_click(event);
    });
}

// replies of a comment, loaded by THREAD_BATCH; under a comment of the post
// dialog with a button, in the comment dialog automatically while scrolling
function render_replies(comment, { preview = [], total = comment.replies_count, auto = false, root = null }) {
    const box = create("div", auto ? "comment-replies comment-replies-flat" : "comment-replies");
    const list = create("div", "comment-replies-list");
    box.append(list);
    let loaded = 0;
    let loading = false;

    const add = (replies) => {
        for (const reply of replies) {
            list.append(render_comment(reply, true));
        }
        loaded += replies.length;
    };
    add(preview);

    const more = create("button", "comment-replies-more");
    const sentinel = create("div", "sentinel");
    const loader = create("div", "loader-spinner comment-replies-loader");
    loader.hidden = true;
    const empty = create("div", "post-dialog-empty", "Ответов в базе нет");
    empty.hidden = true;
    const update = () => {
        const left = total - loaded;
        more.hidden = auto || left <= 0;
        more.textContent = `Показать ещё ${format_number(Math.min(THREAD_BATCH, left))} ответов (всего ${format_number(total)})`;
        empty.hidden = !auto || loaded > 0 || left > 0;
    };

    let observer = null;
    const load = async () => {
        if (loading || loaded >= total) {
            return;
        }
        loading = true;
        more.disabled = true;
        loader.hidden = false;
        try {
            const params = new URLSearchParams({ offset: loaded, limit: THREAD_BATCH });
            const res = await fetch(`/api/ebdi/comments/${comment.comment_id}/replies?${params}`);
            if (!res.ok) {
                throw new Error(`status ${res.status}`);
            }
            const replies = await res.json();
            add(replies);
            if (replies.length < THREAD_BATCH) {
                total = loaded;
            }
            update();
        } catch (error) {
            console.warn("replies request failed", error);
            more.hidden = false;
            more.textContent = "Не удалось загрузить ответы, попробовать снова";
            observer?.disconnect();
            observer = null;
        } finally {
            loading = false;
            more.disabled = false;
            loader.hidden = true;
        }
        if (observer && loaded < total) {
            // re-observing reports the current state, the sentinel may still be in view
            observer.unobserve(sentinel);
            observer.observe(sentinel);
        }
    };
    more.addEventListener("click", load);
    box.append(empty, loader, more);
    update();

    if (auto) {
        box.append(sentinel);
        observer = new IntersectionObserver(
            (entries) => entries.some((entry) => entry.isIntersecting) && load(),
            { root, rootMargin: "400px" },
        );
        observer.observe(sentinel);
        dialog_observers.push(observer);
    }
    return box;
}

// @reply_to text .............. likes
function render_comment_body(comment, show_replies) {
    const body = create("div", "comment-body");
    const text = create("div", "post-content comment-text");
    if (comment.parent_id && comment.reply_to) {
        const link = create("a", "comment-reply-to", "@" + comment.reply_to.username);
        link.href = profile_url(comment.reply_to);
        link.target = "_blank";
        text.append(link, " ");
    }
    text.append(comment.content);
    body.append(text);

    const side = create("div", "comment-side");
    side.append(render_stat(comment.likes_count, "likes", "Лайки"));
    if (show_replies) {
        side.append(render_stat(comment.replies_count, "comments", "Ответы"));
    }
    body.append(side);
    return body;
}

function render_comment(comment, in_thread = false, in_dialog = false) {
    const card = create("article", "post-card comment-card");
    const top_level = !comment.parent_id;
    // in the main list a comment opens a dialog with its replies
    if (!in_thread && !in_dialog && top_level) {
        make_clickable(card, () => open_comment_dialog(comment));
    }
    if (comment.author && !comment.author.exists) {
        card.classList.add("post-deleted-author");
    }
    card.append(render_header(comment.author, comment.author_id, comment.created_at || comment.found_at, comment_url(comment)));

    const badges = create("div", "post-badges");
    if (!comment.exists) {
        badges.append(create("span", "post-badge post-badge-deleted", "Удалён"));
    }
    if (!comment.post_exists && !in_thread) {
        badges.append(create("span", "post-badge post-badge-deleted", "Пост удалён"));
    }
    if (badges.children.length) {
        card.append(badges);
    }
    card.append(render_comment_body(comment, top_level && !in_thread));
    if (comment.attachments.length) {
        card.append(render_attachments(comment.attachments));
    }
    return card;
}

let dialog_token = 0;
let dialog_observers = [];

function close_dialog() {
    get_el("post-dialog")?.close();
}

function build_dialog() {
    const dialog = create("dialog");
    dialog.id = "post-dialog";
    const close = icon_button(null, "close", "Закрыть");
    close.id = "post-dialog-close";
    close.addEventListener("click", close_dialog);
    const header = create("div", "post-dialog-header");
    header.append(close);
    const scroll = create("div");
    scroll.id = "post-dialog-scroll";
    dialog.append(header, scroll);
    // a click on the backdrop lands on the dialog element itself
    dialog.addEventListener("click", (event) => {
        if (event.target == dialog) {
            close_dialog();
        }
    });
    dialog.addEventListener("close", () => {
        dialog_token += 1;
        document.body.style.overflow = "";
        stop_playing();
    });
    document.body.append(dialog);
    return dialog;
}

// empties the dialog, drops loaders of the previous content and shows it
function open_dialog() {
    const dialog = get_el("post-dialog") || build_dialog();
    const token = ++dialog_token;
    for (const observer of dialog_observers) {
        observer.disconnect();
    }
    dialog_observers = [];
    stop_playing();
    const scroll = get_el("post-dialog-scroll");
    scroll.replaceChildren();
    if (!dialog.open) {
        document.body.style.overflow = "hidden";
        dialog.showModal();
    }
    return { scroll, token };
}

function open_comment_dialog(comment) {
    const { scroll } = open_dialog();
    scroll.append(render_comment(comment, false, true));
    scroll.append(create("div", "dialog-section-title", `Ответы (${format_number(comment.replies_count)})`));
    // replies count from ITD may be 0 while some replies are stored, so ask anyway
    scroll.append(render_replies(comment, { total: Infinity, auto: true, root: scroll }));
    scroll.scrollTop = 0;
}

function open_post_dialog(post) {
    const { scroll, token } = open_dialog();
    scroll.append(render_post(post, false, true));
    scroll.append(create("div", "dialog-section-title", `Комментарии (${format_number(post.comments_count)})`));
    const list = create("div", "post-dialog-comments");
    const empty = create("div", "post-dialog-empty", "Комментариев в базе нет");
    empty.hidden = true;
    const loader = create("div", "loader-spinner comment-replies-loader");
    const sentinel = create("div", "sentinel");
    scroll.append(list, empty, loader, sentinel);

    let offset = 0;
    let has_more = true;
    let loading = false;
    const load = async () => {
        if (loading || !has_more || token != dialog_token) {
            return;
        }
        loading = true;
        loader.hidden = false;
        try {
            const params = new URLSearchParams({ offset, limit: THREAD_BATCH });
            const res = await fetch(`/api/ebdi/comments/post/${post.post_id}?${params}`);
            if (!res.ok) {
                throw new Error(`status ${res.status}`);
            }
            const comments = await res.json();
            if (token != dialog_token) {
                return;
            }
            for (const comment of comments) {
                const card = render_comment(comment, true);
                if (comment.replies_total) {
                    card.append(render_replies(comment, { preview: comment.replies, total: comment.replies_total }));
                }
                list.append(card);
            }
            offset += comments.length;
            has_more = comments.length == THREAD_BATCH;
            empty.hidden = offset > 0;
        } catch (error) {
            console.warn("post comments request failed", error);
            has_more = false;
            empty.textContent = "Не удалось загрузить комментарии";
            empty.hidden = false;
        } finally {
            loading = false;
            loader.hidden = true;
        }
        if (has_more && token == dialog_token) {
            observer.unobserve(sentinel);
            observer.observe(sentinel);
        }
    };
    const observer = new IntersectionObserver((entries) => entries.some((entry) => entry.isIntersecting) && load(), {
        root: scroll,
        rootMargin: "600px",
    });
    dialog_observers.push(observer);
    scroll.scrollTop = 0;
    observer.observe(sentinel);
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
    stop_playing();
    waveform_observer?.disconnect();
    waveform_observer = null;
    get_el("feed").replaceChildren();
    get_el("list-empty").hidden = true;
    load_page();
}

function apply() {
    write_url_state();
    reload();
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

function update_clear_buttons() {
    for (const box of document.querySelectorAll(".feed-search-box")) {
        box.querySelector(".feed-search-clear").hidden = !box.querySelector("input").value;
    }
}

// the user filter is applied only when a suggestion is picked
let candidates_timer = null;
let candidates_token = 0;
let candidates = [];

function hide_candidates() {
    clearTimeout(candidates_timer);
    candidates_token += 1;
    candidates = [];
    const box = get_el("user-candidates");
    box.hidden = true;
    box.replaceChildren();
}

function set_user(username) {
    hide_candidates();
    get_el("user-input").value = username ? "@" + username : "";
    update_clear_buttons();
    if (username != state.user) {
        state.user = username;
        apply();
    }
}

function render_candidates(users) {
    candidates = users;
    const box = get_el("user-candidates");
    box.replaceChildren();
    if (!users.length) {
        box.append(create("div", "feed-candidate feed-candidate-empty", "Никого не найдено"));
    }
    for (const user of users) {
        const item = create("div", "feed-candidate");
        item.append(
            create("div", "feed-candidate-avatar", user.avatar + "️"),
            create("div", "feed-candidate-name", user.display_name),
            create("div", "feed-candidate-username", "@" + user.username),
        );
        if (!user.exists) {
            item.append(create("div", "feed-candidate-note", "удалён"));
        }
        // mousedown keeps the focus in the input, click would blur it first
        item.addEventListener("mousedown", (event) => event.preventDefault());
        item.addEventListener("click", () => set_user(user.username));
        box.append(item);
    }
    box.hidden = false;
}

async function fetch_candidates(query) {
    const token = ++candidates_token;
    try {
        const res = await fetch("/api/ebdi/users/search?" + new URLSearchParams({ query }));
        if (!res.ok) {
            console.warn(`user search failed status=${res.status}`);
            return;
        }
        const json = await res.json();
        if (token == candidates_token) {
            render_candidates(json.results);
        }
    } catch (error) {
        console.warn("user search failed", error);
    }
}

function setup_user_search() {
    const input = get_el("user-input");
    input.addEventListener("input", () => {
        clearTimeout(candidates_timer);
        const query = input.value.trim().replace(/^@/, "");
        if (!query) {
            // an emptied field drops the filter
            set_user("");
            return;
        }
        candidates_timer = setTimeout(() => fetch_candidates(query), SEARCH_DELAY);
    });
    input.addEventListener("keydown", (event) => {
        if (event.key == "Enter" && candidates.length) {
            set_user(candidates[0].username);
        } else if (event.key == "Escape") {
            hide_candidates();
        }
    });
    document.addEventListener("click", (event) => {
        if (!get_el("user-search-box").contains(event.target)) {
            // text that was typed but not picked does not stay in the field
            hide_candidates();
            input.value = user_input_text();
            update_clear_buttons();
        }
    });
}

function setup_query_search() {
    let timer = null;
    const input = get_el("query-input");
    input.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            const value = input.value.trim();
            if (value != state.q) {
                state.q = value;
                apply();
            }
        }, SEARCH_DELAY);
    });
}

function setup_clear_buttons() {
    for (const box of document.querySelectorAll(".feed-search-box")) {
        const input = box.querySelector("input");
        const clear = box.querySelector(".feed-search-clear");
        clear.innerHTML = ICONS.close;
        input.addEventListener("input", update_clear_buttons);
        clear.addEventListener("click", () => {
            input.value = "";
            input.dispatchEvent(new Event("input"));
            input.focus();
        });
    }
}

document.addEventListener("DOMContentLoaded", () => {
    read_url_state();
    apply_state_to_controls();

    get_el("sort-select").addEventListener("change", (event) => {
        state.sort = event.target.value;
        apply();
    });
    for (const toggle of toggles()) {
        toggle.addEventListener("change", () => {
            state[toggle.dataset.state] = toggle.checked;
            apply();
        });
    }
    setup_clear_buttons();
    setup_user_search();
    setup_query_search();
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
