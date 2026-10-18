const PAGE_SIZE = 20;
const ITD = "https://итд.com";
const IMAGE_RE = /\.(jpe?g|png|gif|webp|avif)(\?|$)/i;
const VIDEO_RE = /\.(mp4|webm|mov|m4v)(\?|$)/i;
const AUDIO_RE = /\.(ogg|oga|opus|wav|mp3|m4a|aac|flac)(\?|$)/i;

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

function icon_image(name) {
    const image = create("img");
    image.src = `/static/icons/${name}.svg`;
    image.alt = "";
    return image;
}

function escape_regexp(text) {
    return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// text with the matches of the content search wrapped in <mark>
function highlighted(text) {
    const fragment = document.createDocumentFragment();
    if (!state.q || !text) {
        fragment.append(text || "");
        return fragment;
    }
    let last = 0;
    for (const match of text.matchAll(
        new RegExp(escape_regexp(state.q), "giu"),
    )) {
        fragment.append(
            text.slice(last, match.index),
            create("mark", "search-match", match[0]),
        );
        last = match.index + match[0].length;
    }
    fragment.append(text.slice(last));
    return fragment;
}

function format_number(value) {
    return new Intl.NumberFormat("ru-RU").format(value);
}

const MONTHS = [
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
];

// 27 авг 2026 01:40:56
function format_date(value) {
    if (!value) {
        return "";
    }
    const date = new Date(value);
    const pad = (number) => String(number).padStart(2, "0");
    const time = [date.getHours(), date.getMinutes(), date.getSeconds()]
        .map(pad)
        .join(":");
    return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()} ${time}`;
}

// overflow: hidden on body resets the page scroll because html clips overflow-x,
// so the page is pinned in place like in the users dialog
let scroll_locks = 0;
let scroll_lock_offset = 0;

function lock_scroll() {
    if (scroll_locks++) {
        return;
    }
    scroll_lock_offset = window.scrollY;
    const scrollbar = window.innerWidth - document.documentElement.clientWidth;
    Object.assign(document.body.style, {
        position: "fixed",
        top: `-${scroll_lock_offset}px`,
        left: "0",
        right: "0",
        paddingRight: scrollbar > 0 ? `${scrollbar}px` : "",
    });
}

function unlock_scroll() {
    if (scroll_locks == 0 || --scroll_locks) {
        return;
    }
    Object.assign(document.body.style, {
        position: "",
        top: "",
        left: "",
        right: "",
        paddingRight: "",
    });
    window.scrollTo({ top: scroll_lock_offset, behavior: "instant" });
}

function format_duration(seconds) {
    if (!isFinite(seconds)) {
        return "0:00";
    }
    const total = Math.floor(seconds);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function profile_url(user) {
    return `https://итд.com/@${user.username}`;
}

function toggles() {
    return document.querySelectorAll("#feed-controls input[data-state]");
}

function read_url_state() {
    const params = new URLSearchParams(location.search);
    const sort = params.get("sort");
    // links from older versions may carry sorts that no longer exist
    const known = sort_options().some((option) => option.dataset.value == sort);
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

function apply_state_to_controls() {
    update_sort_dropdown();
    for (const toggle of toggles()) {
        toggle.checked = state[toggle.dataset.state];
    }
    get_el("user-input").value = state.user;
    get_el("query-input").value = state.q;
    update_clear_buttons();
}

function post_url(post_id, author, author_id) {
    return `https://итд.com/@${author ? author.username : author_id}/post/${post_id}`;
}

function comment_url(comment) {
    const post = post_url(
        comment.post_id,
        comment.post_author,
        comment.post_author?.user_id,
    );
    return `${post}?comment=${comment.comment_id}`;
}

// avatar, name, @username, the date and a button opening the item in ITD
function render_header(author, author_id, date, url) {
    const header = create("div", "post-header");
    const avatar = create(
        "div",
        "row-avatar",
        author ? author.avatar + "️" : "?",
    );
    header.append(avatar);

    const names = create("div", "post-names");
    const name = create("a", "post-display-name");
    name.target = "_blank";
    name.href = `https://итд.com/@${author ? author.username : author_id}`;
    name.append(
        create(
            "span",
            null,
            author ? author.display_name : "Неизвестный автор",
        ),
    );
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
    open.append(icon_image("open-in-new"));
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

let audio_decoder = null;

// peaks of the loudest sample per bucket, enough for the drawn bars
function audio_peaks(buffer, buckets = 600) {
    const data = buffer.getChannelData(0);
    const size = Math.max(1, Math.floor(data.length / buckets));
    const peaks = new Float32Array(Math.ceil(data.length / size));
    for (let i = 0; i < peaks.length; i++) {
        let max = 0;
        for (
            let j = i * size, end = Math.min(j + size, data.length);
            j < end;
            j++
        ) {
            max = Math.max(max, Math.abs(data[j]));
        }
        peaks[i] = max;
    }
    return peaks;
}

async function decode_audio(url) {
    const res = await fetch(url);
    if (!res.ok) {
        throw new Error(`status ${res.status}`);
    }
    const blob = await res.blob();
    // an offline context decodes without the autoplay restrictions
    audio_decoder ??= new OfflineAudioContext(1, 1, 44100);
    const buffer = await audio_decoder.decodeAudioData(
        await blob.arrayBuffer(),
    );
    return { blob, peaks: audio_peaks(buffer), duration: buffer.duration };
}

function show_audio_error(tile, url) {
    const link = create("a", null, "скачать");
    link.href = url;
    link.target = "_blank";
    const message = create(
        "div",
        "audio-error",
        "Не удалось воспроизвести голосовое, ",
    );
    message.append(link);
    tile.replaceChildren(message);
}

async function init_waveform(tile) {
    const { url } = tile.dataset;
    const wave = tile.querySelector(".audio-wave");
    const play = tile.querySelector(".audio-play");
    const time = tile.querySelector(".audio-time");
    if (typeof WaveSurfer == "undefined") {
        // the library did not load, the native player still plays the file
        const audio = create("audio", "audio-native");
        audio.controls = true;
        audio.preload = "metadata";
        audio.src = url;
        tile.replaceChildren(audio);
        return;
    }
    let decoded = null;
    try {
        decoded = await decode_audio(url);
    } catch (error) {
        // a forbidden cross-origin read or a codec web audio cannot decode,
        // the media element still gets a try with placeholder bars
        console.warn("audio decode failed", url, error);
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
        // decoded audio plays from memory, the media element may not support the codec
        backend: decoded ? "WebAudio" : "MediaElement",
    });
    let failed = false;
    const fail = () => {
        if (!failed) {
            failed = true;
            if (playing == player) {
                playing = null;
            }
            player.destroy();
            show_audio_error(tile, url);
        }
    };
    // without a decoded duration the player waits for metadata that never
    // comes when the media element cannot read the file
    player.on("error", fail);
    player.on(
        "ready",
        // decoders trim a few milliseconds, 3.99 s is shown as 0:04
        (duration) =>
            (time.textContent = format_duration(Math.round(duration))),
    );
    player.on(
        "timeupdate",
        (current) => (time.textContent = format_duration(current)),
    );
    player.on("play", () => {
        if (playing && playing != player) {
            playing.pause();
        }
        playing = player;
        play.src = "/static/icons/pause.svg";
    });
    player.on("pause", () => (play.src = "/static/icons/play.svg"));
    player.on("finish", () => (play.src = "/static/icons/play.svg"));
    play.addEventListener("click", () => player.playPause());
    try {
        if (decoded) {
            await player.loadBlob(
                decoded.blob,
                [decoded.peaks],
                decoded.duration,
            );
        } else {
            await player.load(url, [placeholder_peaks(url)]);
        }
    } catch (error) {
        console.warn("audio load failed", url, error);
        fail();
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
    const player = create("div", "audio-player");
    player.dataset.url = url;
    const play = create("img", "audio-play");
    play.src = "/static/icons/play.svg";
    player.append(
        play,
        create("div", "audio-wave"),
        create("span", "audio-time", "0:00"),
    );
    observe_waveform(player);
    return player;
}

// images make one row of equal tiles opening the viewer,
// videos, voice messages and other files follow at their own size
function render_attachments(urls) {
    const box = create("div", "post-attachments");
    const images = create("div", "post-images");
    const media = create("div", "post-media");
    urls = urls.filter((url) => /^https?:\/\//.test(url));
    const image_urls = urls.filter((url) => IMAGE_RE.test(url));
    for (const url of urls) {
        if (IMAGE_RE.test(url)) {
            const index = images.children.length;
            const tile = create("div", "attachment");
            tile.tabIndex = 0;
            tile.setAttribute("role", "button");
            tile.title = "Открыть изображение";
            const image = create("img", "attachment-image");
            image.loading = "lazy";
            image.alt = "";
            image.src = url;
            tile.append(image);
            tile.addEventListener("click", () =>
                open_lightbox(image_urls, index),
            );
            tile.addEventListener("keydown", (event) => {
                if (event.key == "Enter" || event.key == " ") {
                    event.preventDefault();
                    open_lightbox(image_urls, index);
                }
            });
            images.append(tile);
        } else if (VIDEO_RE.test(url)) {
            const video = create("video", "post-video");
            video.controls = true;
            video.playsInline = true;
            video.preload = "metadata";
            video.src = url;
            // a codec the browser cannot play leaves a link instead of a dead player
            video.addEventListener("error", () => {
                const link = create("a", "post-file", "Открыть видео");
                link.href = url;
                link.target = "_blank";
                video.replaceWith(link);
            });
            media.append(video);
        } else if (AUDIO_RE.test(url)) {
            media.append(render_audio(url));
        } else {
            const link = create("a", "post-file", "Вложение");
            link.href = url;
            link.target = "_blank";
            media.append(link);
        }
    }
    for (const part of [images, media]) {
        if (part.children.length) {
            box.append(part);
        }
    }
    return box;
}

let lightbox_urls = [];
let lightbox_index = 0;

function build_lightbox() {
    const box = create("dialog");
    box.id = "lightbox";
    const image = create("img");
    image.id = "lightbox-image";
    image.alt = "";
    image.draggable = false;
    const button = (class_name, icon, title, on_click) => {
        const node = create("button", class_name);
        node.type = "button";
        node.title = title;
        node.setAttribute("aria-label", title);
        node.append(icon_image(icon));
        node.addEventListener("click", on_click);
        return node;
    };
    const counter = create("div");
    counter.id = "lightbox-counter";
    box.append(
        image,
        button("lightbox-nav lightbox-prev", "arrow", "Предыдущее", () =>
            show_lightbox(lightbox_index - 1),
        ),
        button("lightbox-nav lightbox-next", "arrow", "Следующее", () =>
            show_lightbox(lightbox_index + 1),
        ),
        button("lightbox-close", "close", "Закрыть", () => box.close()),
        counter,
    );
    box.addEventListener("click", (event) => {
        if (event.target == box) {
            box.close();
        }
    });
    box.addEventListener("keydown", (event) => {
        if (event.key == "ArrowLeft" || event.key == "ArrowRight") {
            event.preventDefault();
            show_lightbox(
                lightbox_index + (event.key == "ArrowRight" ? 1 : -1),
            );
        }
    });
    // horizontal swipe flips the images on touch screens
    let swipe_x = null;
    image.addEventListener("pointerdown", (event) => (swipe_x = event.clientX));
    image.addEventListener("pointerup", (event) => {
        const dx = swipe_x == null ? 0 : event.clientX - swipe_x;
        swipe_x = null;
        if (Math.abs(dx) > 50) {
            show_lightbox(lightbox_index + (dx < 0 ? 1 : -1));
        }
    });
    box.addEventListener("close", unlock_scroll);
    document.body.append(box);
    return box;
}

function show_lightbox(index) {
    const count = lightbox_urls.length;
    lightbox_index = (index + count) % count;
    get_el("lightbox-image").src = lightbox_urls[lightbox_index];
    get_el("lightbox-counter").textContent = `${lightbox_index + 1} / ${count}`;
    get_el("lightbox").classList.toggle("lightbox-single", count < 2);
    // neighbours are fetched ahead so flipping does not wait for the network
    for (const step of [-1, 1]) {
        new Image().src =
            lightbox_urls[(lightbox_index + step + count) % count];
    }
}

function open_lightbox(urls, index) {
    lightbox_urls = urls;
    const box = get_el("lightbox") || build_lightbox();
    show_lightbox(index);
    if (!box.open) {
        lock_scroll();
        box.showModal();
    }
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

function render_stat(value, name) {
    const item = create("div", "post-stat");
    const icon = create("img");
    icon.src = `/static/icons/${name}.svg`;
    item.append(icon);
    item.append(create("span", null, format_number(value)));
    return item;
}

function render_stats(post) {
    const stats = create("div", "post-stats");
    stats.append(render_stat(post.likes_count, "like"));
    stats.append(render_stat(post.comments_count, "comment"));
    stats.append(render_stat(post.reposts_count, "repost"));

    const right = create("div", "post-stats-right");
    if (post.dominant) {
        const clan = create("div", "post-dominant", post.dominant + "️");
        clan.title = "Пост захвачен";
        right.append(clan);
    }
    right.append(render_stat(post.views_count, "view"));
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
        box.append(
            create(
                "span",
                "post-badge",
                `Изменён ${format_date(post.edited_at)}`,
            ),
        );
    }
    return box;
}

function render_post(post, nested = false, in_dialog = false) {
    const card = create(
        "article",
        nested ? "post-card post-original" : "post-card",
    );
    if (!in_dialog) {
        make_clickable(card, () =>
            open_post_dialog(post, { card: nested ? null : card }),
        );
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
        const content = create("div", "post-content");
        content.append(highlighted(post.content));
        card.append(content);
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
            card.append(
                create(
                    "div",
                    "post-original post-original-missing",
                    "Оригинальный пост не сохранён в базе",
                ),
            );
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
        if (
            target.closest(
                "a, button, video, audio, .attachment, .post-media, .comment-replies",
            ) ||
            target.closest(".clickable") != card
        ) {
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
function render_replies(
    comment,
    { preview = [], total = comment.replies_count, auto = false, root = null },
) {
    const box = create(
        "div",
        auto ? "comment-replies comment-replies-flat" : "comment-replies",
    );
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
    const empty = create("div", "post-dialog-empty", "Нет ответов");
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
            const params = new URLSearchParams({
                offset: loaded,
                limit: THREAD_BATCH,
            });
            const res = await fetch(
                `/api/ebdi/comments/${comment.comment_id}/replies?${params}`,
            );
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
            (entries) =>
                entries.some((entry) => entry.isIntersecting) && load(),
            { root, rootMargin: "400px" },
        );
        observer.observe(sentinel);
        dialog_observers.push(observer);
    }
    return box;
}

// likes sit in the bottom right corner: next to a text-only comment,
// under the attachments otherwise
function render_comment_body(comment, show_replies) {
    const text = create("div", "post-content comment-text");
    if (comment.parent_id && comment.reply_to) {
        const link = create(
            "a",
            "comment-reply-to",
            "@" + comment.reply_to.username,
        );
        link.href = profile_url(comment.reply_to);
        link.target = "_blank";
        text.append(link, " ");
    }
    text.append(highlighted(comment.content));

    const side = create("div", "comment-side");
    if (show_replies) {
        side.append(render_stat(comment.replies_count, "comment", "Ответы"));
    }
    side.append(render_stat(comment.likes_count, "like", "Лайки"));

    if (!comment.attachments.length) {
        const body = create("div", "comment-body");
        body.append(text, side);
        return [body];
    }
    side.classList.add("comment-side-bottom");
    const parts = [render_attachments(comment.attachments), side];
    return text.textContent ? [text, ...parts] : parts;
}

function render_context(label, preview, on_click) {
    const box = create("div", "comment-context");
    make_clickable(box, on_click);
    const head = create("div", "comment-context-head", label);
    if (preview.author) {
        head.append(
            " ",
            create(
                "span",
                "comment-context-author",
                "@" + preview.author.username,
            ),
        );
    }
    const text = preview.content
        ? preview.content + (preview.truncated ? "…" : "")
        : "Без текста";
    box.append(head, create("div", "comment-context-text", text));
    return box;
}

function render_comment(comment, in_thread = false, in_dialog = false) {
    const card = create("article", "post-card comment-card");
    card.dataset.commentId = comment.comment_id;
    const top_level = !comment.parent_id;
    // in the main list a comment opens a dialog with its replies
    if (!in_thread && !in_dialog && top_level) {
        make_clickable(card, () => open_comment_dialog(comment));
    }
    if (comment.author && !comment.author.exists) {
        card.classList.add("post-deleted-author");
    }
    card.append(
        render_header(
            comment.author,
            comment.author_id,
            comment.created_at || comment.found_at,
            comment_url(comment),
        ),
    );

    const badges = create("div", "post-badges");
    if (!comment.exists) {
        badges.append(
            create("span", "post-badge post-badge-deleted", "Удалён"),
        );
    }
    if (!comment.post_exists && !in_thread) {
        badges.append(
            create("span", "post-badge post-badge-deleted", "Пост удалён"),
        );
    }
    if (badges.children.length) {
        card.append(badges);
    }
    // in the feed a comment shows what it answers
    if (!in_thread && !in_dialog) {
        if (comment.post_preview) {
            card.append(
                render_context("Пост", comment.post_preview, () =>
                    open_post_by_id(comment.post_id),
                ),
            );
        }
        if (comment.parent_preview) {
            card.append(
                render_context(
                    "Ответ на комментарий",
                    comment.parent_preview,
                    () => open_post_by_id(comment.post_id, comment.parent_id),
                ),
            );
        }
    }
    card.append(...render_comment_body(comment, top_level && !in_thread));
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
    const close = create("button");
    close.type = "button";
    close.id = "post-dialog-close";
    close.title = "Закрыть";
    close.setAttribute("aria-label", "Закрыть");
    close.append(icon_image("close"));
    close.addEventListener("click", close_dialog);
    const refresh = create("button");
    refresh.type = "button";
    refresh.id = "post-dialog-refresh";
    refresh.title = "Обновить пост";
    refresh.setAttribute("aria-label", "Обновить пост");
    refresh.append(icon_image("refresh"));
    const status = create("span");
    status.id = "post-dialog-status";
    const header = create("div", "post-dialog-header");
    header.append(status, refresh, close);
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
        unlock_scroll();
        stop_playing();
    });
    document.body.append(dialog);
    return dialog;
}

// empties the dialog, drops loaders of the previous content and shows it
function open_dialog(on_refresh = null) {
    const dialog = get_el("post-dialog") || build_dialog();
    const token = ++dialog_token;
    for (const observer of dialog_observers) {
        observer.disconnect();
    }
    dialog_observers = [];
    stop_playing();
    const scroll = get_el("post-dialog-scroll");
    scroll.replaceChildren();
    const refresh = get_el("post-dialog-refresh");
    refresh.hidden = !on_refresh;
    refresh.disabled = false;
    refresh.onclick = on_refresh;
    get_el("post-dialog-status").textContent = "";
    if (!dialog.open) {
        lock_scroll();
        dialog.showModal();
    }
    return { scroll, token };
}

function open_comment_dialog(comment) {
    const { scroll } = open_dialog();
    scroll.append(render_comment(comment, false, true));
    scroll.append(
        create(
            "div",
            "dialog-section-title",
            `Ответы (${format_number(comment.replies_count)})`,
        ),
    );
    // replies count from ITD may be 0 while some replies are stored, so ask anyway
    scroll.append(
        render_replies(comment, { total: Infinity, auto: true, root: scroll }),
    );
    scroll.scrollTop = 0;
}

async function refresh_post(post, card) {
    const token = dialog_token;
    const button = get_el("post-dialog-refresh");
    const status = get_el("post-dialog-status");
    button.disabled = true;
    status.textContent = "Обновление...";
    try {
        const res = await fetch(`/api/ebdi/posts/${post.post_id}/refresh`, {
            method: "POST",
        });
        if (res.status == 429) {
            throw new Error("Слишком много обновлений, подождите минуту");
        }
        if (!res.ok) {
            throw new Error(`Не удалось обновить пост: ${res.status}`);
        }
        const fresh = await res.json();
        let fresh_card = null;
        if (card?.isConnected) {
            fresh_card = render_post(fresh);
            card.replaceWith(fresh_card);
        }
        if (token == dialog_token) {
            open_post_dialog(fresh, { card: fresh_card });
        }
    } catch (error) {
        console.warn("post refresh failed", error);
        if (token == dialog_token) {
            status.textContent =
                error instanceof TypeError
                    ? "Не удалось связаться с сервером"
                    : error.message;
            button.disabled = false;
        }
    }
}

async function open_post_by_id(post_id, focus = null) {
    const { scroll, token } = open_dialog();
    scroll.append(create("div", "loader-spinner comment-replies-loader"));
    try {
        const res = await fetch(`/api/ebdi/posts/${post_id}`);
        if (!res.ok) {
            throw new Error(`status ${res.status}`);
        }
        const post = await res.json();
        if (token == dialog_token) {
            open_post_dialog(post, { focus });
        }
    } catch (error) {
        console.warn("post request failed", error);
        if (token == dialog_token) {
            scroll.replaceChildren(
                create("div", "post-dialog-empty", "Не удалось загрузить пост"),
            );
        }
    }
}

// comments are loaded by THREAD_BATCH while scrolling down; with a focused comment
// the thread starts from its batch, scrolls to it and loads earlier batches upwards
function open_post_dialog(post, { card = null, focus = null } = {}) {
    const { scroll, token } = open_dialog(() => refresh_post(post, card));
    scroll.append(render_post(post, false, true));
    scroll.append(
        create(
            "div",
            "dialog-section-title",
            `Комментарии (${format_number(post.comments_count)})`,
        ),
    );
    const top_sentinel = create("div", "sentinel");
    const list = create("div", "post-dialog-comments");
    const empty = create("div", "post-dialog-empty", "Комментариев в базе нет");
    empty.hidden = true;
    const loader = create("div", "loader-spinner comment-replies-loader");
    const sentinel = create("div", "sentinel");
    scroll.append(top_sentinel, list, empty, loader, sentinel);

    let first = 0; // offset of the first loaded comment
    let next = 0; // offset of the next batch
    let has_more = true;
    let loading = false;
    let ready = false;

    const fetch_batch = async (from, limit) => {
        const params = new URLSearchParams({ offset: from, limit });
        const res = await fetch(
            `/api/ebdi/comments/post/${post.post_id}?${params}`,
        );
        if (!res.ok) {
            throw new Error(`status ${res.status}`);
        }
        return res.json();
    };
    const render_thread = (comments) =>
        comments.map((comment) => {
            const item = render_comment(comment, true);
            if (comment.replies_total) {
                item.append(
                    render_replies(comment, {
                        preview: comment.replies,
                        total: comment.replies_total,
                    }),
                );
            }
            return item;
        });

    const load_next = async () => {
        if (loading || !has_more || token != dialog_token) {
            return;
        }
        loading = true;
        loader.hidden = false;
        try {
            const comments = await fetch_batch(next, THREAD_BATCH);
            if (token != dialog_token) {
                return;
            }
            list.append(...render_thread(comments));
            next += comments.length;
            has_more = comments.length == THREAD_BATCH;
            empty.hidden = next > 0;
        } catch (error) {
            console.warn("post comments request failed", error);
            has_more = false;
            empty.textContent = "Не удалось загрузить комментарии";
            empty.hidden = false;
        } finally {
            loading = false;
            loader.hidden = true;
        }
        if (ready && has_more && token == dialog_token) {
            observer.unobserve(sentinel);
            observer.observe(sentinel);
        }
    };

    const load_previous = async () => {
        if (loading || first == 0 || token != dialog_token) {
            return;
        }
        loading = true;
        try {
            const from = Math.max(0, first - THREAD_BATCH);
            const comments = await fetch_batch(from, first - from);
            if (token != dialog_token) {
                return;
            }
            const height = scroll.scrollHeight;
            list.prepend(...render_thread(comments));
            // the comments in view stay where they were
            scroll.scrollTop += scroll.scrollHeight - height;
            first = from;
        } catch (error) {
            console.warn("post comments request failed", error);
            first = 0;
        } finally {
            loading = false;
        }
        if (first > 0 && token == dialog_token) {
            observer.unobserve(top_sentinel);
            observer.observe(top_sentinel);
        }
    };

    const observer = new IntersectionObserver(
        (entries) => {
            for (const entry of entries) {
                if (entry.isIntersecting) {
                    (entry.target == sentinel ? load_next : load_previous)();
                }
            }
        },
        { root: scroll, rootMargin: "600px" },
    );
    dialog_observers.push(observer);
    scroll.scrollTop = 0;

    const start = async () => {
        let thread_id = null;
        if (focus) {
            try {
                const res = await fetch(`/api/ebdi/comments/${focus}/place`);
                if (res.ok) {
                    const place = await res.json();
                    first = next =
                        Math.floor(place.offset / THREAD_BATCH) * THREAD_BATCH;
                    thread_id = place.comment_id;
                }
            } catch (error) {
                console.warn("comment place request failed", error);
            }
        }
        await load_next();
        if (token != dialog_token) {
            return;
        }
        if (focus) {
            const target =
                list.querySelector(`[data-comment-id="${focus}"]`) ||
                list.querySelector(`[data-comment-id="${thread_id}"]`);
            if (target) {
                // scrollIntoView would also move the pinned page behind the dialog
                const box = scroll.getBoundingClientRect();
                const rect = target.getBoundingClientRect();
                scroll.scrollTop +=
                    rect.top - box.top - (box.height - rect.height) / 2;
                target.classList.add("comment-focus");
            }
        }
        ready = true;
        observer.observe(sentinel);
        observer.observe(top_sentinel);
    };
    start();
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
        const params = new URLSearchParams({
            ...state,
            offset,
            limit: PAGE_SIZE,
        });
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

function sort_options() {
    return [...document.querySelectorAll("#sort-options [role=option]")];
}

function update_sort_dropdown() {
    for (const option of sort_options()) {
        const selected = option.dataset.value == state.sort;
        option.setAttribute("aria-selected", selected);
        if (selected) {
            get_el("sort-value").textContent = option.textContent;
        }
    }
}

function toggle_sort_dropdown(open) {
    get_el("sort-options").hidden = !open;
    get_el("sort-button").setAttribute("aria-expanded", open);
    if (open) {
        sort_options()
            .find((option) => option.dataset.value == state.sort)
            ?.focus();
    }
}

function setup_sort_dropdown() {
    const button = get_el("sort-button");
    const list = get_el("sort-options");
    button.addEventListener("click", () => toggle_sort_dropdown(list.hidden));
    const pick = (option) => {
        toggle_sort_dropdown(false);
        button.focus();
        if (option.dataset.value != state.sort) {
            state.sort = option.dataset.value;
            update_sort_dropdown();
            apply();
        }
    };
    for (const option of sort_options()) {
        option.tabIndex = -1;
        option.addEventListener("click", () => pick(option));
    }
    list.addEventListener("keydown", (event) => {
        const options = sort_options();
        const index = options.indexOf(document.activeElement);
        if (event.key == "ArrowDown" || event.key == "ArrowUp") {
            event.preventDefault();
            const step = event.key == "ArrowDown" ? 1 : -1;
            options[(index + step + options.length) % options.length].focus();
        } else if (event.key == "Enter" || event.key == " ") {
            event.preventDefault();
            if (index >= 0) {
                pick(options[index]);
            }
        } else if (event.key == "Escape" || event.key == "Tab") {
            toggle_sort_dropdown(false);
            button.focus();
        }
    });
    document.addEventListener("click", (event) => {
        if (!get_el("sort-dropdown").contains(event.target)) {
            toggle_sort_dropdown(false);
        }
    });
}

function update_clear_buttons() {
    for (const box of document.querySelectorAll(".feed-search-box")) {
        box.querySelector(".feed-search-clear").hidden =
            !box.querySelector("input").value;
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
    get_el("user-input").value = username;
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
        box.append(
            create(
                "div",
                "feed-candidate feed-candidate-empty",
                "Никого не найдено",
            ),
        );
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
        const res = await fetch(
            "/api/ebdi/users/search?" + new URLSearchParams({ query }),
        );
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
        candidates_timer = setTimeout(
            () => fetch_candidates(query),
            SEARCH_DELAY,
        );
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
            input.value = state.user;
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
        clear.append(icon_image("close"));
        input.addEventListener("input", update_clear_buttons);
        clear.addEventListener("click", () => {
            input.value = "";
            input.dispatchEvent(new Event("input"));
            input.focus();
        });
    }
}

// https://css-tricks.com/how-to-detect-when-a-sticky-element-gets-pinned/
function observe_controls_stick() {
    const observer = new IntersectionObserver(
        ([e]) => e.target.classList.toggle("pinned", e.intersectionRatio < 1),
        { threshold: [1] },
    );

    observer.observe(get_el("controls-box"));
}

document.addEventListener("DOMContentLoaded", () => {
    read_url_state();
    apply_state_to_controls();

    setup_sort_dropdown();
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
    observe_controls_stick();
});
