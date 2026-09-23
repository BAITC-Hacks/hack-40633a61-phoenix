// Тонкий клиент к backend/app.py (см. backend/schemas.py — источник правды
// для этих типов) + адаптеры backend-JSON -> presentation-модель из data.ts.
//
// Все запросы идут на относительный путь `/api/...`: в dev-режиме Vite
// проксирует их на backend (см. vite.config.ts), в проде они попадают на
// тот же самый uvicorn-процесс, что отдал frontend/dist (см. backend/app.py).
import {
  formatKzt,
  riskFromScore,
  roleLabels,
  scoreFromPriority,
  type CaseFile,
  type Cluster,
  type GraphNode,
  type Risk,
  type Role,
  type Summary,
  type Transfer,
} from './data'

// ---------------------------------------------------------------------------
// Сырые типы ответов backend (зеркало backend/schemas.py).
// ---------------------------------------------------------------------------

export interface ApiRoleCount {
  role: string
  count: number
}

export interface ApiSummary {
  n_nodes: number
  n_edges: number
  n_seed: number
  n_components: number
  n_clusters: number
  n_high_priority: number
  high_priority_threshold: number
  role_counts: ApiRoleCount[]
  generated_at: string
  status: string
}

export interface ApiGraphNode {
  id: string
  role: Role
  role_score: number
  cluster_id: number
  priority_score: number
  is_seed: boolean
  depth: number
  in_deg: number
  out_deg: number
  in_kzt: number
  out_kzt: number
}

export interface ApiGraphEdge {
  source: string
  target: string
  sum_kzt: number
  n_tx: number
}

export interface ApiGraphResponse {
  nodes: ApiGraphNode[]
  edges: ApiGraphEdge[]
  truncated: boolean
}

export interface ApiCluster {
  cluster_id: number
  n_nodes: number
  n_seed: number
  sum_kzt_internal: number
  top_gids: string[]
  hypothesis: string
}

export interface ApiTopNode {
  rank: number
  gid: string
  role: Role
  priority_score: number
  why: string
}

export interface ApiNeighborEdge {
  gid: string
  role: string
  sum_kzt: number
  n_tx: number
  direction: 'in' | 'out'
}

export interface ApiNodeDetail extends ApiGraphNode {
  gid: string
  evidence: string
  in_tx: number | null
  out_tx: number | null
  pagerank: number | null
  betweenness: number | null
  pass_through: number | null
  truncated_by_depth: boolean | null
  in_cycle: boolean | null
  median_lag_days: number | null
  max_same_day_payers: number | null
  fast_transit: boolean | null
  synchronized_burst: boolean | null
  neighbors: ApiNeighborEdge[]
}

export interface ApiAiStatus {
  configured: boolean
  model: string
  base_url: string
}

export interface ApiAiCitation {
  gid: string
  role: string
  priority_score: number
}

export interface ApiAiAskResponse {
  answer: string
  citations: ApiAiCitation[]
  model: string
}

export interface AnalysisResponse {
  analysis_id: string
  status: string
  files: Array<{
    name: string
    kind: string
    rows: number
    size: number
    columns: string[]
    column_mapping: Record<string, string>
    preview: Array<Record<string, unknown>>
  }>
  results: {
    nodes: number
    edges: number
    transactions: number
    ids_remapped: boolean
    date_min: string
    date_max: string
  }
  signals: string[]
  confidence: string
  limitations: string[]
}

// ---------------------------------------------------------------------------
// HTTP-клиент.
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

let activeAnalysisId: string | null = null

export function setActiveAnalysisId(value: string | null) {
  activeAnalysisId = value
}

async function request<T>(path: string, init?: RequestInit, scoped = true): Promise<T> {
  const separator = path.includes('?') ? '&' : '?'
  const scopedPath = scoped && activeAnalysisId
    ? `${path}${separator}analysis_id=${encodeURIComponent(activeAnalysisId)}`
    : path
  const res = await fetch(`/api${scopedPath}`, {
    headers: { Accept: 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body?.detail ?? detail
    } catch {
      // тело не JSON — оставляем statusText
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function fetchSummary(): Promise<ApiSummary> {
  return request<ApiSummary>('/summary')
}

export function fetchGraph(params: { limit?: number } = {}): Promise<ApiGraphResponse> {
  const qs = new URLSearchParams()
  qs.set('limit', String(params.limit ?? 4000))
  return request<ApiGraphResponse>(`/graph?${qs.toString()}`)
}

export function fetchClusters(): Promise<ApiCluster[]> {
  return request<ApiCluster[]>('/clusters')
}

export function fetchTopNodes(): Promise<ApiTopNode[]> {
  return request<ApiTopNode[]>('/top')
}

export function fetchNodeDetail(gid: string): Promise<ApiNodeDetail> {
  return request<ApiNodeDetail>(`/nodes/${gid}`)
}

export function fetchAiStatus(): Promise<ApiAiStatus> {
  return request<ApiAiStatus>('/ai/status')
}

export function askAi(question: string): Promise<ApiAiAskResponse> {
  return request<ApiAiAskResponse>('/ai/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
}

export async function uploadAnalysis(files: File[]): Promise<AnalysisResponse> {
  const form = new FormData()
  files.forEach((file) => form.append('files', file))
  return request<AnalysisResponse>('/analyses', { method: 'POST', body: form }, false)
}

// ---------------------------------------------------------------------------
// Адаптеры backend-JSON -> presentation-модель (data.ts).
// ---------------------------------------------------------------------------

function nodeName(n: ApiGraphNode): string {
  const label = roleLabels[n.role] ?? n.role
  return n.is_seed ? `Seed · ${label}` : label
}

export function toGraphNodes(nodes: ApiGraphNode[]): GraphNode[] {
  return nodes.map((n) => {
    const score = scoreFromPriority(n.priority_score)
    return {
      gid: n.id,
      name: nodeName(n),
      role: n.role,
      cluster: `Cluster ${n.cluster_id}`,
      risk: riskFromScore(score),
      score,
      volume: formatKzt(n.in_kzt + n.out_kzt),
      // in_deg/out_deg — число уникальных контрагентов (граф не отдаёт
      // счётчики транзакций в bulk-выдаче /api/graph, только в карточке
      // узла /api/nodes/{gid}); честная замена, не выдуманное число.
      transactions: n.in_deg + n.out_deg,
      location: `Depth ${n.depth} from seed`,
      note: '',
      position: { x: 0, y: 0 },
    }
  })
}

export function toTransfers(edges: ApiGraphEdge[]): Transfer[] {
  return edges.map((e, i) => ({
    id: `${e.source}-${e.target}-${i}`,
    source: e.source,
    target: e.target,
    amount: formatKzt(e.sum_kzt),
    n_tx: e.n_tx,
  }))
}

/** Кол-во seed-клиентов в кластере -> категория риска.
 * См. README.md: «9 кластеров содержат 2+ seed-клиентов — кандидаты в
 * инфраструктуру одной группы» — чем больше известных курьеров пересекается
 * в одном кластере, тем выше приоритет его целиком проверить. */
function clusterRisk(c: ApiCluster): Risk {
  if (c.n_seed >= 3) return 'Critical'
  if (c.n_seed >= 2) return 'High'
  if (c.n_seed >= 1) return 'Medium'
  return 'Low'
}

export function toClusters(clusters: ApiCluster[]): Cluster[] {
  return clusters
    .slice()
    .sort((a, b) => b.n_nodes - a.n_nodes)
    .map((c) => ({
      name: `Cluster ${c.cluster_id}`,
      id: `#${c.cluster_id}`,
      members: c.n_nodes,
      volume: formatKzt(c.sum_kzt_internal),
      risk: clusterRisk(c),
      description: c.hypothesis,
    }))
}

/** /api/top (top_nodes.csv) — уже готовый ранжированный список «кого
 * смотреть первым» от пайплайна; естественно превращается в список кейсов
 * расследования, ничего не выдумываем. entities — степень узла из уже
 * загруженного /api/graph (без лишних N+1 запросов по каждому top-gid). */
export function toCaseFiles(top: ApiTopNode[], graphNodes: ApiGraphNode[], generatedAt: string): CaseFile[] {
  const byId = new Map(graphNodes.map((n) => [n.id, n]))
  const updated = new Date(generatedAt)
  const updatedLabel = Number.isNaN(updated.getTime())
    ? '—'
    : updated.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  return top.map((t) => {
    const n = byId.get(t.gid)
    const score = scoreFromPriority(t.priority_score)
    return {
      id: `CASE-${String(t.rank).padStart(3, '0')}`,
      title: `${roleLabels[t.role] ?? t.role} candidate — GID ${t.gid}`,
      // top_nodes.csv не содержит статуса расследования — 10 самых
      // приоритетных отмечены как уже взятые в разбор, остальные в очереди.
      status: t.rank <= 10 ? 'In review' : 'Open',
      owner: 'AML Analyst',
      updated: updatedLabel,
      entities: n ? n.in_deg + n.out_deg : 0,
      priority: riskFromScore(score),
      gid: t.gid,
    }
  })
}

export function toSummary(s: ApiSummary): Summary {
  return {
    n_nodes: s.n_nodes,
    n_edges: s.n_edges,
    n_seed: s.n_seed,
    n_components: s.n_components,
    n_clusters: s.n_clusters,
    n_high_priority: s.n_high_priority,
    high_priority_threshold: s.high_priority_threshold,
    generatedAt: s.generated_at,
  }
}
