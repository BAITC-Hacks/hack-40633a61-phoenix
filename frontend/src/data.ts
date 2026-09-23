// Контракт данных фронтенда — определён здесь по реальному контракту
// backend/schemas.py (роли, шкала риска, структура узла/кластера/кейса).
// Ничего не мокается: значения приходят из ./api.ts <- backend <- out/*.csv
// (пайплайн src/moneygraph, см. корневой README.md).

// Роли — ровно те шесть, что присваивает src/moneygraph/roles.py
// (пороговые правила по in_deg/out_deg/pass_through, см. README «Критерии
// ролей»). Оставлены как есть (не переименованы в абстрактные Hub/Broker/...)
// — это осознанный выбор: аналитику важна точная методологическая метка.
export type Role = 'coordinator' | 'consolidator' | 'distributor' | 'transit' | 'terminal' | 'peripheral'
export type Risk = 'Critical' | 'High' | 'Medium' | 'Low'

export const roleLabels: Record<Role, string> = {
  coordinator: 'Coordinator',
  consolidator: 'Consolidator',
  distributor: 'Distributor',
  transit: 'Transit',
  terminal: 'Terminal',
  peripheral: 'Peripheral',
}

export const roleColors: Record<Role, string> = {
  coordinator: '#64edc3',
  consolidator: '#7fb9ec',
  distributor: '#f4b97e',
  transit: '#b2a8ed',
  terminal: '#7297a3',
  peripheral: '#5c6b73',
}

export interface GraphNode {
  gid: string
  name: string
  role: Role
  cluster: string
  risk: Risk
  score: number
  volume: string
  transactions: number
  location: string
  note: string
  // Позиция намеренно не проставляется здесь: backend (graph_export.json)
  // не хранит XY-координаты, раскладка считается на клиенте (см. Graph()
  // в App.tsx — layout: 'concentric' по priority, а не 'preset').
  position: { x: number; y: number }
}

export interface Transfer {
  id: string
  source: string
  target: string
  amount: string
  n_tx: number
}

export interface Cluster {
  name: string
  id: string
  members: number
  volume: string
  risk: Risk
  description: string
}

export interface CaseFile {
  id: string
  title: string
  status: string
  owner: string
  updated: string
  entities: number
  priority: Risk
  gid: string
}

export interface Summary {
  n_nodes: number
  n_edges: number
  n_seed: number
  n_components: number
  n_clusters: number
  n_high_priority: number
  high_priority_threshold: number
  generatedAt: string
}

/** priority_score (0..1) -> 0..100 очков, как ожидает UI (GraphNode.score). */
export function scoreFromPriority(priorityScore: number): number {
  return Math.round(priorityScore * 100)
}

/** priority_score (0..1) -> категория риска для бейджей/фильтров. */
export function riskFromScore(score: number): Risk {
  if (score >= 90) return 'Critical'
  if (score >= 75) return 'High'
  if (score >= 50) return 'Medium'
  return 'Low'
}

/** Сумма в KZT -> компактная человекочитаемая строка ("4.2M ₸", "178K ₸"). */
export function formatKzt(value: number): string {
  if (!Number.isFinite(value)) return '—'
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M ₸`
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}K ₸`
  return `${Math.round(value)} ₸`
}
