"""Сборка ``out/graph.html`` — офлайн-схема сети (pyvis + инжектированный UI).

vis-network инлайнится в html (``cdn_resources="in_line"``) — интернет для
просмотра не требуется. Достаточно открыть ``out/graph.html`` в браузере.

Известный исторический баг («после ресайза граф визуально пропадает, видны
только orphan-узлы») чинится здесь явным пересчётом размера canvas и
повторным ``fit()`` при изменении размера контейнера — см. ``_inject_ui``,
блок ``ResizeObserver``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import networkx as nx
import pandas as pd
from pyvis.network import Network

from .config import ROLE_COLOR, ROLE_LABEL_RU


def _layout(graph: nx.DiGraph, orphans: list[int]) -> dict[int, tuple[float, float]]:
    # spring_layout считаем ТОЛЬКО на подграфе без орфанов (изолированные точки
    # без единого ребра могут внести дублирующиеся начальные координаты в
    # силовой алгоритм и испортить сходимость для всего графа) — орфаны кладём
    # на отдельную полосу ниже.
    core = graph.copy()
    core.remove_nodes_from(orphans)
    ug = core.to_undirected()
    raw = nx.spring_layout(ug, k=1.6 / max(len(ug) ** 0.5, 1), iterations=150, seed=42)

    pos: dict[int, tuple[float, float]] = {}
    for n, (x, y) in raw.items():
        if not (math.isfinite(x) and math.isfinite(y)):
            x, y = 0.0, 0.0  # защита от редкой численной нестабильности FR-алгоритма
        pos[n] = (float(x) * 2200, float(y) * 2200)

    cols = 5
    for i, gid in enumerate(orphans):
        pos[gid] = (2600 + (i % cols) * 90, 1400 + (i // cols) * 90)
    return pos


def build(df: pd.DataFrame, edges: pd.DataFrame, clusters: pd.DataFrame, out_dir: Path) -> None:
    """Строит и записывает ``out_dir/graph.html``."""
    graph = nx.DiGraph()
    for r in edges.itertuples(index=False):
        graph.add_edge(int(r.src), int(r.dst), sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx))

    all_gids = set(df.gid.astype(int))
    graph_gids = set(graph.nodes())
    orphans = sorted(all_gids - graph_gids)
    for gid in orphans:
        graph.add_node(gid)

    pos = _layout(graph, orphans)

    net = Network(height="100vh", width="100%", directed=True,
                  bgcolor="#0f1115", font_color="#e6e6e6", cdn_resources="in_line")
    net.toggle_physics(False)

    attrs = df.set_index("gid").to_dict(orient="index")
    for gid in graph.nodes():
        a = attrs.get(gid, {})
        role = a.get("role", "peripheral")
        is_seed = bool(a.get("is_seed", False))
        size = 8 + 32 * float(a.get("priority_score", 0.1))
        x, y = pos.get(gid, (0.0, 0.0))
        label = str(gid)[-6:]  # последние 6 цифр gid — читаемо на схеме
        tooltip = (
            f"gid {gid}\n"
            f"роль: {ROLE_LABEL_RU.get(role, role)} (score {a.get('role_score', 0):.2f})\n"
            f"кластер: {a.get('cluster_id', -1)}\n"
            f"priority: {a.get('priority_score', 0):.2f}\n"
            f"in: {a.get('in_deg', 0)} ({a.get('in_kzt', 0):,.0f} KZT)  "
            f"out: {a.get('out_deg', 0)} ({a.get('out_kzt', 0):,.0f} KZT)\n"
            f"seed: {'да' if is_seed else 'нет'}, depth: {a.get('depth', '?')}\n"
            f"— {a.get('evidence', '')}"
        )
        net.add_node(
            gid, label=label, title=tooltip, x=x, y=y, size=size, physics=False, fixed=True,
            color=dict(background=ROLE_COLOR.get(role, "#adb5bd"),
                       border="#ffffff" if is_seed else ROLE_COLOR.get(role, "#adb5bd"),
                       highlight=dict(background="#ffffff", border="#000000")),
            borderWidth=3 if is_seed else 1,
            shape="dot",
            role=role, cluster_id=int(a.get("cluster_id", -1)),
            priority_score=float(a.get("priority_score", 0.0)),
            role_score=float(a.get("role_score", 0.0)),
            evidence=str(a.get("evidence", "")),
            is_seed=is_seed, depth=int(a.get("depth", -1)),
            in_deg=int(a.get("in_deg", 0)), out_deg=int(a.get("out_deg", 0)),
            in_kzt=float(a.get("in_kzt", 0.0)), out_kzt=float(a.get("out_kzt", 0.0)),
        )

    for u, v, d in graph.edges(data=True):
        w = d.get("sum_kzt", 0.0)
        width = 0.6 + math.log10(max(w, 1)) * 0.5
        net.add_edge(u, v, value=w, width=width, color="#4a4f5a",
                     title=f"{w:,.0f} KZT, {d.get('n_tx', 1)} перев.", arrows="to")

    net.set_options(json.dumps({
        "nodes": {"font": {"color": "#e6e6e6", "size": 10}},
        "edges": {"smooth": {"enabled": True, "type": "dynamic"},
                  "arrows": {"to": {"enabled": True, "scaleFactor": 0.5}}},
        "interaction": {"hover": True, "tooltipDelay": 80, "navigationButtons": True,
                         "keyboard": True},
        "physics": {"enabled": False},
    }))

    html = net.generate_html(notebook=False)
    html = _inject_ui(html, df, clusters)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "graph.html").write_text(html, encoding="utf-8")
    print(f"  graph.html        : офлайн-схема сети ({graph.number_of_nodes()} узлов)")


def _inject_ui(html: str, df: pd.DataFrame, clusters: pd.DataFrame) -> str:
    role_counts = df.role.value_counts().to_dict()
    legend_rows = "".join(
        f'<div class="legend-row" data-role="{role}">'
        f'<span class="swatch" style="background:{ROLE_COLOR[role]}"></span>'
        f'<span>{ROLE_LABEL_RU[role]} ({role_counts.get(role, 0)})</span>'
        f'<input type="checkbox" checked data-role-toggle="{role}"></div>'
        for role in ROLE_COLOR
    )
    n_clusters = clusters.cluster_id.nunique()

    panel = f"""
<div id="ui-panel">
  <h2>Граф денег</h2>
  <p class="sub">HackAlem AI — {len(df)} узлов, {n_clusters} кластеров</p>

  <div class="block">
    <label>Поиск по gid</label>
    <div class="search-row">
      <input id="gidSearch" type="text" placeholder="например 100000003684369100">
      <button onclick="doSearch()">Найти</button>
    </div>
    <div id="searchMsg" class="msg"></div>
  </div>

  <div class="block">
    <label>Роли (клик — скрыть/показать)</label>
    {legend_rows}
  </div>

  <div class="block">
    <label>Кластер</label>
    <div class="search-row">
      <input id="clusterFilter" type="text" placeholder="номер кластера, пусто = все">
      <button onclick="applyClusterFilter()">OK</button>
    </div>
  </div>

  <div class="block" id="infoBlock" style="display:none">
    <label>Карточка узла</label>
    <div id="nodeInfo"></div>
  </div>
</div>
<style>
  html, body {{ margin: 0; height: 100%; background: #0f1115; }}
  #ui-panel {{
    position: fixed; top: 0; left: 0; width: 300px; height: 100vh; overflow-y: auto;
    background: #14161c; color: #e6e6e6; padding: 16px; box-sizing: border-box;
    font-family: -apple-system, Segoe UI, Roboto, sans-serif; z-index: 1000;
    border-right: 1px solid #2a2d36;
  }}
  #ui-panel h2 {{ margin: 0 0 2px 0; font-size: 18px; }}
  #ui-panel .sub {{ margin: 0 0 16px 0; font-size: 12px; color: #9aa0ab; }}
  #ui-panel .block {{ margin-bottom: 18px; }}
  #ui-panel label {{ display:block; font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
    color: #9aa0ab; margin-bottom: 6px; }}
  #ui-panel input[type=text] {{ width: 100%; box-sizing: border-box; padding: 6px 8px; border-radius: 6px;
    border: 1px solid #363a45; background: #0f1115; color: #e6e6e6; margin-bottom: 6px; }}
  #ui-panel button {{ width: 100%; padding: 6px 8px; border-radius: 6px; border: none;
    background: #2effc0; color: #0b0e13; font-weight: 600; cursor: pointer; }}
  #ui-panel .search-row {{ display:flex; flex-direction: column; gap:4px; }}
  #ui-panel .legend-row {{ display:flex; align-items:center; gap:8px; font-size: 13px; padding: 3px 0; }}
  #ui-panel .legend-row .swatch {{ width: 12px; height:12px; border-radius:50%; display:inline-block; }}
  #ui-panel .legend-row input {{ margin-left:auto; }}
  #ui-panel .msg {{ font-size: 12px; color: #f4a261; min-height: 14px; }}
  #nodeInfo {{ font-size: 12px; line-height: 1.5; white-space: pre-wrap; background:#0f1115;
    padding:8px; border-radius:6px; border:1px solid #363a45; }}
  #mynetwork {{ position: fixed !important; top: 0; left: 300px !important;
    width: calc(100% - 300px) !important; height: 100vh !important;
    border: none !important; }}
  .card {{ border: none !important; background: #0f1115 !important; }}
</style>
<script>
window.addEventListener('load', function () {{
  var tries = 0;
  var iv = setInterval(function () {{
    tries++;
    if (typeof network !== 'undefined' && typeof nodes !== 'undefined') {{
      clearInterval(iv);
      initUI();
    }} else if (tries > 100) {{
      clearInterval(iv);
    }}
  }}, 50);
}});

function initUI() {{
  // Первичный fit — на следующий кадр, чтобы canvas успел получить
  // реальные размеры контейнера (после того как #ui-panel сдвинул layout).
  requestAnimationFrame(function () {{
    resizeNetwork();
  }});

  network.on('click', function (params) {{
    if (params.nodes.length > 0) {{
      showNodeInfo(params.nodes[0]);
    }}
  }});

  document.querySelectorAll('[data-role-toggle]').forEach(function (cb) {{
    cb.addEventListener('change', function () {{
      var role = cb.getAttribute('data-role-toggle');
      var updates = [];
      nodes.forEach(function (n) {{
        if (n.role === role) {{
          updates.push({{ id: n.id, hidden: !cb.checked }});
        }}
      }});
      nodes.update(updates);
    }});
  }});

  document.getElementById('gidSearch').addEventListener('keydown', function (e) {{
    if (e.key === 'Enter') doSearch();
  }});

  // --- Фикс известного бага: после ресайза контейнера канвас vis-network
  // мог остаться со старым transform (масштаб/сдвиг), из-за чего был виден
  // только небольшой угол схемы (например, орфан-узлы в правом нижнем углу).
  // Явно пересчитываем размер канваса и делаем fit() при каждом ресайзе
  // контейнера/окна, с небольшим дебаунсом.
  var resizeTimer = null;
  function scheduleResize() {{
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(resizeNetwork, 120);
  }}
  window.addEventListener('resize', scheduleResize);
  var container = document.getElementById('mynetwork');
  if (window.ResizeObserver && container) {{
    new ResizeObserver(scheduleResize).observe(container);
  }}
}}

function resizeNetwork() {{
  var container = document.getElementById('mynetwork');
  if (!container) return;
  var w = container.clientWidth;
  var h = container.clientHeight || window.innerHeight;
  // setSize + redraw форсируют canvas.width/height (пиксельный буфер) в
  // соответствие с CSS-размером контейнера — без этого шага vis-network
  // иногда рисует по устаревшему pixelRatio/transform после ресайза.
  network.setSize(w + 'px', h + 'px');
  network.redraw();
  network.fit({{ animation: false }});
}}

function showNodeInfo(gid) {{
  var n = nodes.get(gid);
  if (!n) return;
  document.getElementById('infoBlock').style.display = 'block';
  document.getElementById('nodeInfo').textContent =
    'gid: ' + n.id + '\\n' +
    'роль: ' + n.role + ' (score ' + n.role_score.toFixed(2) + ')\\n' +
    'кластер: ' + n.cluster_id + '\\n' +
    'priority: ' + n.priority_score.toFixed(2) + '\\n' +
    'seed: ' + (n.is_seed ? 'да' : 'нет') + ', depth: ' + n.depth + '\\n' +
    'in: ' + n.in_deg + ' (' + Math.round(n.in_kzt).toLocaleString() + ' KZT)\\n' +
    'out: ' + n.out_deg + ' (' + Math.round(n.out_kzt).toLocaleString() + ' KZT)\\n\\n' +
    n.evidence;
}}

function doSearch() {{
  var raw = document.getElementById('gidSearch').value.trim();
  var msg = document.getElementById('searchMsg');
  if (!raw) return;
  var gid = parseInt(raw, 10);
  var n = nodes.get(gid);
  if (!n) {{
    msg.textContent = 'gid не найден';
    return;
  }}
  msg.textContent = '';
  network.selectNodes([gid]);
  network.focus(gid, {{ scale: 1.8, animation: {{ duration: 400 }} }});
  showNodeInfo(gid);
}}

function applyClusterFilter() {{
  var raw = document.getElementById('clusterFilter').value.trim();
  var updates = [];
  nodes.forEach(function (n) {{
    var hidden = raw !== '' && String(n.cluster_id) !== raw;
    updates.push({{ id: n.id, hidden: hidden }});
  }});
  nodes.update(updates);
}}
</script>
"""
    return html.replace("</body>", panel + "</body>")
