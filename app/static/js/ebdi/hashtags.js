let comments = false;
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

function render_hashtag(row, place) {
    const node = create("div", "row");
    const left = create("div", "row-left");
    const name = create("a", "hashtag-name", "#" + row.tag);
    // a tag opens the feed searched by it
    const feed = comments && row.posts == 0 ? "comments" : "posts";
    name.href = `/ebdi/${feed}?` + new URLSearchParams({ q: "#" + row.tag });
    left.append(create("div", "row-place", place + "."), name);
    const right = create("div", "row-right");
    right.append(
        create("div", "hashtag-count", format_number(row.posts)),
        create(
            "div",
            "hashtag-count hashtag-comments",
            format_number(row.comments),
        ),
    );
    node.append(left, right);
    return node;
}

async function load_hashtags() {
    const token = ++request_token;
    const list = get_el("hashtags");
    list.replaceChildren();
    get_el("list-empty").hidden = true;
    get_el("list-error").hidden = true;
    get_el("list-loader").hidden = false;
    get_el("rows").classList.toggle("with-comments", comments);
    try {
        const res = await fetch(
            "/api/ebdi/hashtags?" + new URLSearchParams({ comments }),
        );
        if (token != request_token) {
            return;
        }
        if (!res.ok) {
            get_el("error-text").textContent =
                `Ошибка получения хэштегов: ${res.status}`;
            get_el("list-error").hidden = false;
            return;
        }
        const rows = await res.json();
        if (token != request_token) {
            return;
        }
        list.append(...rows.map((row, i) => render_hashtag(row, i + 1)));
        get_el("list-empty").hidden = rows.length > 0;
    } catch (error) {
        console.warn("hashtags request failed", error);
        if (token == request_token) {
            get_el("error-text").textContent =
                "Не удалось связаться с сервером";
            get_el("list-error").hidden = false;
        }
    } finally {
        if (token == request_token) {
            get_el("list-loader").hidden = true;
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    comments = new URLSearchParams(location.search).get("comments") == "true";
    const checkbox = get_el("comments-checkbox");
    checkbox.checked = comments;
    checkbox.addEventListener("change", () => {
        comments = checkbox.checked;
        history.replaceState(
            null,
            "",
            comments ? "?comments=true" : location.pathname,
        );
        load_hashtags();
    });
    get_el("retry-button").addEventListener("click", load_hashtags);
    load_hashtags();
});
