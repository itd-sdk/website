function get_el(el) {
    return document.getElementById(el);
}

// ai begin ---
function dpr() {
    return window.devicePixelRatio || 1;
}

function node_radius(d) {
    return Math.max(2, Math.min(6, 1.5 + Math.log10(1 + (d.followers || 0)) * 0.9));
}


(async () => {
    const canvas = get_el('graph-canvas');
    const ctx = canvas.getContext('2d');
    const loading = get_el('graph-loading');
    const loading_text = get_el('graph-loading-text');
    const progress = get_el('graph-progress-fill');
    const tooltip = get_el('graph-tooltip');
    const search_input = get_el('graph-search-input');
    const search_results = get_el('graph-search-results');

    let transform = d3.zoomIdentity;
    let nodes, edges, quadtree;
    let hovered_node = null;
    let hovered_edge = null;
    let selected_node = null;
    let selected_neighbour_ids = null;
    let selected_edges = null;
    let fit_done = false;
    let search_timer = null;
    let show_edges = false; // non-ai

    function resize() {
        canvas.width = canvas.clientWidth * dpr();
        canvas.height = canvas.clientHeight * dpr();
        render();
    }

    function select_node(node) {
        selected_node = node;
        if (!node) {
            selected_neighbour_ids = null;
            selected_edges = null;
        } else {
            selected_neighbour_ids = new Set([node.id]);
            selected_edges = new Set();
            for (const e of edges) {
                if (e.source === node) {
                    selected_neighbour_ids.add(e.target.id);
                    selected_edges.add(e);
                } else if (e.target === node) {
                    selected_neighbour_ids.add(e.source.id);
                    selected_edges.add(e);
                }
            }
        }
        render();
    }

    function render() {
        const w = canvas.width;
        const h = canvas.height;
        const d = dpr();
        const has_selection = selected_node != null;

        ctx.clearRect(0, 0, w, h);
        ctx.save();
        ctx.translate(transform.x * d, transform.y * d);
        ctx.scale(transform.k * d, transform.k * d);

        const lw = 0.6 / transform.k;

        if (has_selection) { // non-ai
            // Dim edges
            if (show_edges) {
                ctx.beginPath();
                ctx.strokeStyle = 'rgba(185, 135, 103, 0.06)';
                ctx.lineWidth = lw;
                for (const e of edges) {
                    if (selected_edges.has(e) || e.source.x == null) continue;
                    ctx.moveTo(e.source.x, e.source.y);
                    ctx.lineTo(e.target.x, e.target.y);
                }
                ctx.stroke();
            }

            // Highlighted edges
            ctx.beginPath();
            ctx.strokeStyle = 'rgba(237,106,45,0.75)';
            ctx.lineWidth = 1.2 / transform.k;
            for (const e of selected_edges) {
                if (e.source.x == null) continue;
                ctx.moveTo(e.source.x, e.source.y);
                ctx.lineTo(e.target.x, e.target.y);
            }
            ctx.stroke();
          } else if (show_edges) { // non-ai
            ctx.beginPath();
            ctx.strokeStyle = 'rgba(100,90,80,0.18)';
            ctx.lineWidth = lw;
            for (const e of edges) {
                if (e.source.x == null) continue;
                ctx.moveTo(e.source.x, e.source.y);
                ctx.lineTo(e.target.x, e.target.y);
            }
            ctx.stroke();
        }

        // Hovered edge highlight
        // if (hovered_edge && hovered_edge.source.x != null) {
        //     ctx.beginPath();
        //     ctx.strokeStyle = 'rgba(251, 230, 219, 0.7)';
        //     ctx.lineWidth = 1.5 / transform.k;
        //     ctx.moveTo(hovered_edge.source.x, hovered_edge.source.y);
        //     ctx.lineTo(hovered_edge.target.x, hovered_edge.target.y);
        //     ctx.stroke();
        // }

        // Nodes
        for (const n of nodes) {
            if (n.x == null) continue;
            const r = node_radius(n);
            const is_selected = n === selected_node;
            const is_dimmed = has_selection && !selected_neighbour_ids.has(n.id);

            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, Math.PI * 2);

            if (is_selected) {
                ctx.fillStyle = '#FF854D';
            } else if (is_dimmed) {
                ctx.fillStyle = 'rgba(74,71,68,0.2)';
            } else if (n === hovered_node) {
                ctx.fillStyle = '#FF854D';
            } else if (n.verified) {
                ctx.fillStyle = '#c94d14';
            } else {
                ctx.fillStyle = '#4a4744';
            }
            ctx.fill();

            if (is_selected) {
                ctx.beginPath();
                ctx.arc(n.x, n.y, r + 2.5 / transform.k, 0, Math.PI * 2);
                ctx.strokeStyle = '#FF854D';
                ctx.lineWidth = 1 / transform.k;
                ctx.stroke();
            }
        }

        ctx.restore();
    }

    function rebuild_quadtree() {
        quadtree = d3.quadtree()
            .x(d => d.x)
            .y(d => d.y)
            .addAll(nodes.filter(n => n.x != null));
    }

    function find_node(mx, my, radius = 14) {
        const [wx, wy] = transform.invert([mx, my]);
        return quadtree.find(wx, wy, radius / transform.k);
    }

    // function find_edge(mx, my) {
    //     const [wx, wy] = transform.invert([mx, my]);
    //     const threshold = 4 / transform.k;
    //     let best = null, bestDist = threshold;
    //     for (const e of edges) {
    //         const s = e.source, t = e.target;
    //         if (s.x == null) continue;
    //         const dx = t.x - s.x, dy = t.y - s.y;
    //         const len2 = dx * dx + dy * dy;
    //         if (len2 === 0) continue;
    //         const tt = Math.max(0, Math.min(1, ((wx - s.x) * dx + (wy - s.y) * dy) / len2));
    //         const dist = Math.hypot(wx - (s.x + tt * dx), wy - (s.y + tt * dy));
    //         if (dist < bestDist) { bestDist = dist; best = e; }
    //     }
    //     return best;
    // }

    function fit_view() {
        const valid_nodes = nodes.filter(n => n.x != null);
        const xs = valid_nodes.map(n => n.x);
        const ys = valid_nodes.map(n => n.y);
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const cw = canvas.clientWidth, ch = canvas.clientHeight;
        const k = Math.min(0.85 * cw / (maxX - minX || 1), 0.85 * ch / (maxY - minY || 1), 3);
        const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
        d3.select(canvas).call(
            zoom.transform,
            d3.zoomIdentity.translate(cw / 2, ch / 2).scale(k).translate(-cx, -cy)
        );
    }

    function position_tooltip(clientX, clientY) {
        const rect = canvas.getBoundingClientRect();
        let tx = clientX - rect.left + 14;
        let ty = clientY - rect.top - 10;
        if (tx + 250 > canvas.clientWidth) tx = clientX - rect.left - 256;
        tooltip.style.left = tx + 'px';
        tooltip.style.top = ty + 'px';
    }

    function show_tooltip(node, clientX, clientY) {
        tooltip.hidden = false;
        position_tooltip(clientX, clientY);
        tooltip.innerHTML =
            `<div class="tt-name">${node.avatar} ${node.display_name}${node.verified ? '<img src="/static/icons/verified.svg">' : ''}</div>` +
            `<div class="tt-username">@${node.username}</div>` +
            `<div class="tt-stats">` +
            `<span>${(node.followers || 0).toLocaleString('ru-RU')} подписчиков</span>` +
            `<span>${(node.following || 0).toLocaleString('ru-RU')} подписок</span>` +
            `</div>`;
    }

    function show_edge_tooltip(edge, clientX, clientY) {
        tooltip.hidden = false;
        position_tooltip(clientX, clientY);
        const s = edge.source, t = edge.target;
        const rel = edge.mutual
            ? `<b>@${s.username}</b> <=> <b>@${t.username}</b>`
            : `<b>@${s.username}</b> => <b>@${t.username}</b>`;
        tooltip.innerHTML = `<div class="tt-stats edge" style="color:#FBEADB">${rel}</div>`;
    }

    // Fetch
    loading_text.textContent = 'Загрузка данных...';
    progress.style.width = '10%';

    const res = await fetch('/api/users/graph');
    // -- ai end
    if (!res.ok) {
        alert('Ошибка при получении пользователей');
        return;
    }
    const data = await res.json();
    // ai begin --

    nodes = data.nodes;
    edges = data.edges;

    get_el('graph-stats').textContent = `${nodes.length} узлов | ${edges.length} связей`;
    loading_text.textContent = 'Построение графа...';
    progress.style.width = '20%';

    const alpha_min = 0.001;

    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id(d => d.id).distance(100).strength(0.3))
        .force('charge', d3.forceManyBody().strength(-70).distanceMax(350))
        .force('collide', d3.forceCollide().radius(d => node_radius(d) + 1.5).strength(1))
        .force('center', d3.forceCenter(0, 0).strength(0.05))
        .velocityDecay(0.45)
        .alphaDecay(0.05)
        .alphaMin(alpha_min)
        .on('tick', () => {
            const alpha = simulation.alpha();
            progress.style.width = (20 + Math.round((1 - (alpha - alpha_min) / (1 - alpha_min)) * 75)) + '%';

            if (!fit_done && alpha < 0.25) {
                fit_done = true;
                fit_view();
            }

            rebuild_quadtree();
            render();
        })
        .on('end', () => {
            progress.style.width = '100%';
            rebuild_quadtree();
            render();
            setTimeout(() => {
                loading.classList.add('fade');
                setTimeout(() => { loading.hidden = true; }, 450);
            }, 150);
            get_el('graph-search').hidden = false;
            get_el('graph-other').hidden = false; // non-ai
        });

    const zoom = d3.zoom()
        .scaleExtent([0.02, 12])
        .on('zoom', e => {
            transform = e.transform;
            render();
        });

    d3.select(canvas)
        .call(zoom)
        .on('dblclick.zoom', null)
        .on('click.select', e => {
            const rect = canvas.getBoundingClientRect();
            const node = find_node(e.clientX - rect.left, e.clientY - rect.top);
            select_node(node === selected_node ? null : (node || null));
        });

    canvas.addEventListener('mousedown', () => canvas.classList.add('dragging'));
    canvas.addEventListener('mouseup', () => canvas.classList.remove('dragging'));

    // Hover / tooltip
    canvas.addEventListener('mousemove', e => {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left, my = e.clientY - rect.top;
        // Hover: use tight radius (~= visual node size) so edges behind nodes are reachable
        const node = find_node(mx, my);
        const edge = null //node ? null : find_edge(mx, my);

        if (node !== hovered_node || edge !== hovered_edge) {
            hovered_node = node;
            hovered_edge = edge;
            render();
        }

        if (node) {
            show_tooltip(node, e.clientX, e.clientY);
        } else if (edge) {
            show_edge_tooltip(edge, e.clientX, e.clientY);
        } else {
            tooltip.hidden = true;
        }
    });

    canvas.addEventListener('mouseleave', () => {
        tooltip.hidden = true;
        hovered_node = null;
        hovered_edge = null;
        render();
    });

    // Search
    function pan_to_node(node) {
        const cw = canvas.clientWidth, ch = canvas.clientHeight;
        d3.select(canvas).transition().duration(500).call(
            zoom.transform,
            d3.zoomIdentity.translate(cw / 2, ch / 2).scale(Math.max(transform.k, 1)).translate(-node.x, -node.y)
        );
    }

    function show_search_results(results) {
        search_results.hidden = false; // non-ai

        if (!results.length) {
            search_results.innerHTML = '<div class="search-result-text">Ничего не найдено</div>';
            return;
        }

        search_results.innerHTML = results.map(u => {
            if (nodes.some(n => n.id === u.id)) { // non-ai
                return `<div class="search-result" data-id="${u.id}">
                    <span class="search-result-avatar">${u.avatar || '?'}</span>
                    <div>
                        <div class="search-result-name">${u.display_name}${u.verified ? '<img src="/static/icons/verified.svg">' : ''}</div>
                        <div class="search-result-username">@${u.username}</div>
                    </div>
                </div>`;
            }
        }).join('');

        search_results.childNodes.forEach(el => {
            el.addEventListener('click', () => {
                const id = parseInt(el.dataset.id);
                const node = nodes.find(n => n.id === id);
                if (node) {
                    select_node(node);
                    pan_to_node(node);
                }
                search_input.value = '';
                search_results.hidden = true;
            });
        });
    }

    search_input.addEventListener('input', () => {
        clearTimeout(search_timer);

        const q = search_input.value.trim();
        if (!q) {
            search_results.hidden = true;
            return;
        }

        search_timer = setTimeout(async () => {
            search_results.hidden = false;
            search_results.innerHTML = '<div class="search-result-text">Заугрзка...</div>'; // non-ai
            const data = await fetch(`/api/users/search?query=${encodeURIComponent(q)}`);
            if (!data.ok) {
                alert('Ошибка при получении результатов поиска.');
                return;
            }
            show_search_results((await data.json()).results || []);
        }, 250);
    });

    search_input.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            search_input.value = '';
            search_results.hidden = true;
        }
    });

    // --- ai end
    get_el('graph-edges').addEventListener('click', () => {
        show_edges = !show_edges;
        render();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key == 'Escape' && selected_node != null) {
        select_node(null);
      }
    });
    // ai begin ---

    document.addEventListener('click', e => {
        if (!get_el('graph-search').contains(e.target)) {
            search_results.hidden = true;
        }
    });

    window.addEventListener('resize', resize);
    resize();
})();
