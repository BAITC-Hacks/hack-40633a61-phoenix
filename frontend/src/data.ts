// Presentation model only. Populate this snapshot from verified analysis output
// once the project's data contract is defined.
export type Role = 'Hub' | 'Broker' | 'Receiver' | 'Source' | 'Watchlist'
export type Risk = 'Critical' | 'High' | 'Medium' | 'Low'

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

export interface Transfer {
  id: string
  source: string
  target: string
  amount: string
  date: string
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

export const roleColors: Record<Role, string> = {
  Hub: '#64edc3', Broker: '#7fb9ec', Receiver: '#b2a8ed',
  Source: '#b8c9d3', Watchlist: '#f4b97e',
}

// No records are supplied with the frontend. Empty means unavailable, not zero.
export const nodes: GraphNode[] = []
export const transfers: Transfer[] = []
export const clusters: Cluster[] = []
export const cases: CaseFile[] = []
