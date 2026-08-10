import { Graph } from "https://esm.sh/@cosmos.gl/graph@3?bundle";

const SEARCH_DELAY = 250;
const SPACE_SIZE = 8192;

// cosmos.gl v3 expects normalized rgba channels (0..1)
const COLOR_DEFAULT = [0.29, 0.28, 0.27, 1];
const COLOR_VERIFIED = [0.79, 0.3, 0.08, 1];
const LINK_HIDDEN = [0, 0, 0, 0];
const LINK_IDLE = [0.19, 0.18, 0.16, 1];
const LINK_DIM = [0.3, 0.28, 0.26, 0.12];
const LINK_ACTIVE = [0.93, 0.42, 0.18, 1];
const LINK_FAR = [0.22, 0.2, 0.18, 1];
const DEPTH_FALLOFF = 0.45;
const MAX_DEPTH = 3;
const HUB_DEGREE = 50;

function get_el(id) {
    return document.getElementById(id);
}

function mix_color(a, b, t) {
    return [
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
        a[3] + (b[3] - a[3]) * t,
    ];
}

// display names come from a scraped social network, never trust them in innerHTML
function escape_html(value) {
    return String(value ?? "").replace(
        /[&<>"']/g,
        (char) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[char],
    );
}

function point_size(followers) {
    return Math.max(4, Math.min(16, 4 + Math.log10(1 + followers) * 2.6));
}

(async () => {
    const container = get_el("graph-canvas");
    const loading = get_el("graph-loading");
    const loading_text = get_el("graph-loading-text");
    const progress = get_el("graph-progress-fill");
    const tooltip = get_el("graph-tooltip");
    const search_input = get_el("graph-search-input");
    const search_results = get_el("graph-search-results");

    let graph = null;
    let nodes = [];
    let point_links = [];
    let index_by_id = new Map();
    let selected_index = null;
    let hovered_index = null;
    let show_edges = false;
    let search_timer = null;

    loading_text.textContent = "Загрузка данных...";
    progress.style.width = "10%";

    const res = await fetch("/api/ebdi/users/graph");
    if (!res.ok) {
        alert("Ошибка при получении пользователей");
        return;
    }
    const data = await res.json();

    nodes = data.nodes;
    index_by_id = new Map(nodes.map((node, i) => [node.id, i]));

    loading_text.textContent = "Построение графа...";
    progress.style.width = "20%";

    const positions = new Float32Array(nodes.length * 2);
    const colors = new Float32Array(nodes.length * 4);
    const sizes = new Float32Array(nodes.length);
    for (let i = 0; i < nodes.length; i++) {
        positions[i * 2] = Math.random() * SPACE_SIZE;
        positions[i * 2 + 1] = Math.random() * SPACE_SIZE;
        colors.set(nodes[i].verified ? COLOR_VERIFIED : COLOR_DEFAULT, i * 4);
        sizes[i] = point_size(nodes[i].followers || 0);
    }

    // link indices per point, so a selection highlights only its own edges
    point_links = nodes.map(() => []);
    const links = new Float32Array(data.edges.length * 2);
    let link_count = 0;
    for (const edge of data.edges) {
        const source = index_by_id.get(edge.source);
        const target = index_by_id.get(edge.target);
        if (source === undefined || target === undefined) {
            continue;
        }
        links[link_count * 2] = source;
        links[link_count * 2 + 1] = target;
        point_links[source].push(link_count);
        point_links[target].push(link_count);
        link_count++;
    }

    function collect_depths(index) {
        const depths = new Map([[index, 0]]);
        let frontier = [index];
        for (let depth = 1; depth <= MAX_DEPTH; depth++) {
            const next = [];
            for (const point of frontier) {
                for (const link of point_links[point]) {
                    for (const side of [0, 1]) {
                        const neighbour = link_pairs[link * 2 + side];
                        if (depths.has(neighbour)) {
                            continue;
                        }
                        depths.set(neighbour, depth);
                        // hubs are reachable but not traversable, they connect everything
                        if (point_links[neighbour].length < HUB_DEGREE) {
                            next.push(neighbour);
                        }
                    }
                }
            }
            frontier = next;
        }
        return depths;
    }

    let visible_links = null;

    function apply_links(indices) {
        if (indices === null) {
            graph.setLinks(link_pairs);
            graph.setLinkColors(link_colors);
            graph.render();
            return;
        }
        // upload only the links that must be drawn, the rest never reach the GPU
        const pairs = new Float32Array(indices.length * 2);
        const colors_subset = new Float32Array(indices.length * 4);
        for (let i = 0; i < indices.length; i++) {
            const link = indices[i];
            pairs[i * 2] = link_pairs[link * 2];
            pairs[i * 2 + 1] = link_pairs[link * 2 + 1];
            colors_subset.set(
                link_colors.subarray(link * 4, link * 4 + 4),
                i * 4,
            );
        }
        graph.setLinks(pairs);
        graph.setLinkColors(colors_subset);
        graph.render();
    }

    // per-link colors, repainted on selection instead of relying on greyout config
    const link_colors = new Float32Array(link_count * 4);

    function paint_links(index) {
        if (index === null) {
            if (!show_edges) {
                graph.setConfigPartial({ renderLinks: false });
                return;
            }
            for (let i = 0; i < link_count; i++) {
                link_colors.set(LINK_IDLE, i * 4);
            }
            graph.setConfigPartial({ renderLinks: true });
            apply_links(null);
            return;
        }

        const depths = collect_depths(index);
        const visible = [];
        for (const [point, depth] of depths) {
            if (depth >= MAX_DEPTH) {
                continue;
            }
            for (const link of point_links[point]) {
                const link_depth = Math.max(
                    depths.get(link_pairs[link * 2]) ?? Infinity,
                    depths.get(link_pairs[link * 2 + 1]) ?? Infinity,
                );
                if (link_depth > MAX_DEPTH) {
                    continue;
                }
                const t = Math.pow(
                    MAX_DEPTH > 1 ? (link_depth - 1) / (MAX_DEPTH - 1) : 0,
                    DEPTH_FALLOFF,
                );
                link_colors.set(mix_color(LINK_ACTIVE, LINK_FAR, t), link * 4);
                visible.push(link);
            }
        }

        if (show_edges) {
            const highlighted = new Set(visible);
            for (let i = 0; i < link_count; i++) {
                if (!highlighted.has(i)) {
                    link_colors.set(LINK_DIM, i * 4);
                    visible.push(i);
                }
            }
        }

        graph.setConfigPartial({ renderLinks: true });
        apply_links(visible);
    }

    function update_links() {
        paint_links(selected_index);
    }

    get_el("graph-stats").textContent =
        `${nodes.length} узлов | ${link_count} связей`;

    function position_tooltip(client_x, client_y) {
        const rect = container.getBoundingClientRect();
        const box = tooltip.getBoundingClientRect();
        let x = client_x - rect.left + 14;
        let y = client_y - rect.top - 10;
        if (x + box.width > rect.width) {
            x = client_x - rect.left - box.width - 14;
        }
        if (y + box.height > rect.height) {
            y = rect.height - box.height - 8;
        }
        tooltip.style.left = Math.max(0, x) + "px";
        tooltip.style.top = Math.max(0, y) + "px";
    }

    function show_tooltip(index, client_x, client_y) {
        const node = nodes[index];
        const check = node.verified
            ? '<img src="/static/icons/verified.svg">'
            : "";
        tooltip.innerHTML =
            `<div class="tt-name">${escape_html(node.avatar)} ${escape_html(node.display_name)}${check}</div>` +
            `<div class="tt-username">@${escape_html(node.username)}</div>` +
            `<div class="tt-stats">` +
            `<span>${(node.followers || 0).toLocaleString("ru-RU")} подписчиков</span>` +
            `<span>${(node.following || 0).toLocaleString("ru-RU")} подписок</span>` +
            `</div>`;
        tooltip.hidden = false;
        position_tooltip(client_x, client_y);
    }

    function select_point(index) {
        selected_index = index;
        if (index === null) {
            graph.setConfigPartial({
                highlightedPointIndices: undefined,
                highlightedLinkIndices: undefined,
                outlinedPointIndices: undefined,
            });
            update_links();
            return;
        }
        paint_links(index);
        graph.setConfigPartial({
            // points: direct neighbours only, links still fade out over MAX_DEPTH
            highlightedPointIndices: [
                index,
                ...graph.getNeighboringPointIndices(index),
            ],
            outlinedPointIndices: [index],
            renderLinks: true,
        });
    }

    function on_click(index) {
        const is_background = index === undefined || index === null;
        select_point(is_background || index === selected_index ? null : index);
    }

    let loading_hidden = false;

    function hide_loading() {
        if (loading_hidden) {
            return;
        }
        loading_hidden = true;
        progress.style.width = "100%";
        setTimeout(() => {
            loading.classList.add("fade");
            setTimeout(() => {
                loading.hidden = true;
            }, 450);
        }, 150);
        get_el("graph-search").hidden = false;
        get_el("graph-other").hidden = false;
    }

    function on_tick(alpha) {
        progress.style.width = 20 + Math.round((1 - alpha) * 75) + "%";
        if (alpha < 0.15) {
            hide_loading();
        }
    }

    function on_end() {
        hide_loading();
    }

    let clamping_zoom = false;

    function clamp_zoom() {
        // setZoomLevel triggers onZoom again, guard against the feedback loop
        if (clamping_zoom) {
            return;
        }
        const level = graph.getZoomLevel();
        const clamped = Math.min(Math.max(level, 0.05), 8);
        if (clamped === level) {
            return;
        }
        clamping_zoom = true;
        graph.setZoomLevel(clamped, 0);
        requestAnimationFrame(() => {
            clamping_zoom = false;
        });
    }

    graph = new Graph(container, {
        spaceSize: SPACE_SIZE,
        backgroundColor: "#1e1c1a",
        pointDefaultColor: "#4a4744",
        pointGreyoutColor: "#2a2724",
        linkDefaultColor: "rgba(100, 90, 80, 0.35)",
        linkGreyoutOpacity: 0.08,
        renderLinks: show_edges,
        linkBlending: false,
        simulationRepulsion: 0.8,
        simulationGravity: 0.25,
        simulationLinkSpring: 0.03,
        simulationLinkDistance: 80,
        simulationFriction: 0.9,
        simulationDecay: 1000,
        fitViewOnInit: true,
        fitViewDelay: 1500,
        fitViewPadding: 0.2,
        scalePointsOnZoom: true,
        enableDrag: false,
        renderHoveredPointRing: false,
        // transitions auto-pause the simulation in v3, keep snap updates instead
        transitionDuration: 0,
        linkDefaultWidth: 1.5,
        linkOpacity: 0.5,
        linkVisibilityDistanceRange: [50, 5000],
        onClick: on_click,
        onPointMouseOver: on_point_over,
        onPointMouseOut: on_point_out,
        onSimulationTick: on_tick,
        onSimulationEnd: on_end,
        onZoom: clamp_zoom,
    });

    graph.setPointPositions(positions);
    graph.setPointColors(colors);
    graph.setPointSizes(sizes);
    const link_pairs = links.subarray(0, link_count * 2);
    graph.setLinks(link_pairs);
    update_links();
    graph.render();

    let last_mouse = null;

    function on_point_over(index) {
        hovered_index = index;
        container.classList.add("hovering");
        if (selected_index === null) {
            graph.setConfigPartial({ outlinedPointIndices: [index] });
        }
        if (last_mouse) {
            show_tooltip(index, last_mouse.x, last_mouse.y);
        }
    }

    function on_point_out() {
        hovered_index = null;
        container.classList.remove("hovering");
        if (selected_index === null) {
            graph.setConfigPartial({ outlinedPointIndices: undefined });
        }
        tooltip.hidden = true;
    }

    container.addEventListener("mousemove", (event) => {
        last_mouse = { x: event.clientX, y: event.clientY };
        if (hovered_index !== null) {
            position_tooltip(event.clientX, event.clientY);
        }
    });

    function show_search_results(results) {
        search_results.hidden = false;
        const found = results.filter((user) => index_by_id.has(user.id));
        if (!found.length) {
            search_results.innerHTML =
                '<div class="search-result-text">Ничего не найдено</div>';
            return;
        }
        search_results.innerHTML = found
            .map((user) => {
                const check = user.verified
                    ? '<img src="/static/icons/verified.svg">'
                    : "";
                return `<div class="search-result" data-id="${user.id}">
                    <span class="search-result-avatar">${escape_html(user.avatar || "?")}</span>
                    <div>
                        <div class="search-result-name">${escape_html(user.display_name)}${check}</div>
                        <div class="search-result-username">@${escape_html(user.username)}</div>
                    </div>
                </div>`;
            })
            .join("");

        for (const el of search_results.children) {
            el.addEventListener("click", () => {
                const index = index_by_id.get(Number(el.dataset.id));
                select_point(index);
                graph.zoomToPointByIndex(index, 500, 4, false);
                search_input.value = "";
                search_results.hidden = true;
            });
        }
    }

    search_input.addEventListener("input", () => {
        clearTimeout(search_timer);
        const query = search_input.value.trim();
        if (!query) {
            search_results.hidden = true;
            return;
        }
        search_timer = setTimeout(async () => {
            search_results.hidden = false;
            search_results.innerHTML =
                '<div class="search-result-text">Загрузка...</div>';
            const response = await fetch(
                `/api/ebdi/users/search?query=${encodeURIComponent(query)}`,
            );
            if (!response.ok) {
                search_results.innerHTML =
                    '<div class="search-result-text">Ошибка поиска</div>';
                return;
            }
            show_search_results((await response.json()).results || []);
        }, SEARCH_DELAY);
    });

    search_input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            search_input.value = "";
            search_results.hidden = true;
        }
    });

    get_el("graph-edges").checked = false;
    get_el("graph-edges").addEventListener("click", () => {
        show_edges = !show_edges;
        update_links();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && selected_index !== null) {
            select_point(null);
        }
    });

    document.addEventListener("click", (event) => {
        if (!get_el("graph-search").contains(event.target)) {
            search_results.hidden = true;
        }
    });
    const degrees = point_links.map((l) => l.length).sort((a, b) => a - b);
    console.log(
        "median",
        degrees[Math.floor(degrees.length / 2)],
        "p95",
        degrees[Math.floor(degrees.length * 0.95)],
    );
})();
