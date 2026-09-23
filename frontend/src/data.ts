export function formatKzt(value: number): string {
  if (!Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('ru-RU', {
    notation: Math.abs(value) >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(value) + ' ₸'
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type Role = 'coordinator' | 'consolidator' | 'distributor' | 'transit' | 'terminal' | 'peripheral'
export type Risk = 'Critical' | 'High' | 'Medium' | 'Low'

export const riskColors: Record<RiskLevel, string> = {
  low: '#51d6ae',
  medium: '#f4c76b',
  high: '#f58a52',
  critical: '#ef4e5f',
}

export const roleLabelsByLanguage: Record<string, Record<'ru' | 'kk', string>> = {
  coordinator: { ru: 'координатор', kk: 'үйлестіруші' },
  consolidator: { ru: 'консолидатор', kk: 'шоғырландырушы' },
  distributor: { ru: 'распределитель', kk: 'таратушы' },
  transit: { ru: 'транзит', kk: 'транзит' },
  terminal: { ru: 'терминальный', kk: 'терминалдық' },
  peripheral: { ru: 'периферийный', kk: 'перифериялық' },
  cluster: { ru: 'кластер', kk: 'кластер' },
}

// Compatibility presentation types retained for the CSV export adapters.
export const roleLabels: Record<Role, string> = {
  coordinator: 'Coordinator',
  consolidator: 'Consolidator',
  distributor: 'Distributor',
  transit: 'Transit',
  terminal: 'Terminal',
  peripheral: 'Peripheral',
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
  position: { x: number; y: number }
}

export interface Transfer { id: string; source: string; target: string; amount: string; n_tx: number }
export interface Cluster { name: string; id: string; members: number; volume: string; risk: Risk; description: string }
export interface CaseFile { id: string; title: string; status: string; owner: string; updated: string; entities: number; priority: Risk; gid: string }
export interface Summary { n_nodes: number; n_edges: number; n_seed: number; n_components: number; n_clusters: number; n_high_priority: number; high_priority_threshold: number; generatedAt: string }

export function scoreFromPriority(value: number) { return Math.round(value * 100) }
export function riskFromScore(score: number): Risk {
  if (score >= 90) return 'Critical'
  if (score >= 75) return 'High'
  if (score >= 50) return 'Medium'
  return 'Low'
}
