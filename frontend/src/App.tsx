import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import cytoscape, { type Core } from 'cytoscape'
import {
  Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Bell, ChevronDown,
  ChevronRight, CircleHelp, Database, Download, Filter,
  Fingerprint, Focus, Home, Layers3, Menu, MoreHorizontal, Network,
  Search, ShieldAlert, SlidersHorizontal, Sparkles, X,
} from 'lucide-react'
import { cases, clusters, nodes, roleColors, transfers, type GraphNode, type Risk, type Role } from './data'

type Page = 'Overview' | 'Network' | 'Priority' | 'Clusters' | 'Investigation'
const pages: { name: Page; icon: typeof Home }[] = [
  { name: 'Overview', icon: Home }, { name: 'Network', icon: Network },
  { name: 'Priority', icon: Activity }, { name: 'Clusters', icon: Layers3 },
  { name: 'Investigation', icon: Search },
]
const roles: Role[] = ['Hub', 'Broker', 'Receiver', 'Source', 'Watchlist']
const clusterNames = clusters.map((cluster) => cluster.name)

class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (this.state.failed) return <div className="page-error"><ShieldAlert size={30} /><h2>Unable to display this view</h2><p>Something interrupted the workspace. Reload the page to try again.</p><button className="button button-primary" onClick={() => window.location.reload()}>Reload workspace <ArrowRight size={16} /></button></div>
    return this.props.children
  }
}

function BrandMark({ small = false }: { small?: boolean }) {
  return <svg className={small ? 'brand-mark small' : 'brand-mark'} viewBox="0 0 76 76" fill="none" aria-hidden="true">
    <path d="M38 5 64 20v34L38 70 12 54V20L38 5Z" stroke="#7CA5B0" strokeWidth="1.4" />
    <path d="m12 20 26 18 26-18M38 5v33m0 0v32M12 54l26-16 26 16" stroke="#607D88" strokeWidth="1.2" />
    <circle cx="38" cy="5" r="5" fill="#67E8BF" /><circle cx="64" cy="20" r="5" fill="#67E8BF" />
    <circle cx="64" cy="54" r="5" fill="#7297A3" /><circle cx="38" cy="70" r="5" fill="#67E8BF" />
    <circle cx="12" cy="54" r="5" fill="#7297A3" /><circle cx="12" cy="20" r="5" fill="#92C9CB" />
    <circle cx="38" cy="38" r="9" fill="#E3F2F2" />
  </svg>
}

function RiskBadge({ risk }: { risk: Risk }) { return <span className={`risk risk-${risk.toLowerCase()}`}><i />{risk}</span> }
function RoleDot({ role }: { role: Role }) { return <span className="role-dot" style={{ background: roleColors[role] }} /> }
function Kicker({ children }: { children: React.ReactNode }) { return <div className="kicker">{children}</div> }
function EmptyData({ title, children }: { title: string; children: ReactNode }) { return <div className="data-empty"><Database size={27} /><h3>{title}</h3><p>{children}</p></div> }

function Graph({ selected, onSelect, roleFilter, clusterFilter, compact = false }: {
  selected: string | null; onSelect: (gid: string) => void; roleFilter: Role | 'All'; clusterFilter: string; compact?: boolean
}) {
  const container = useRef<HTMLDivElement>(null)
  const graph = useRef<Core | null>(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  useEffect(() => {
    if (!container.current) return
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...nodes.map((node) => ({ data: { id: node.gid, label: node.name, role: node.role, color: roleColors[node.role] }, position: node.position })),
        ...transfers.map((transfer) => ({ data: { id: transfer.id, source: transfer.source, target: transfer.target } })),
      ],
      layout: { name: 'preset', fit: true, padding: compact ? 38 : 65 },
      style: [
        { selector: 'node', style: { 'background-color': 'data(color)', width: compact ? 17 : 24, height: compact ? 17 : 24, 'border-width': 4, 'border-color': '#111d22', label: compact ? '' : 'data(label)', color: '#b6c4ca', 'font-size': 11, 'font-family': 'DM Sans, sans-serif', 'text-valign': 'bottom', 'text-margin-y': 12, 'text-outline-color': '#10191d', 'text-outline-width': 2, 'overlay-opacity': 0, 'transition-property': 'width, height, opacity, border-color', 'transition-duration': 200 } },
        { selector: 'node[role = "Hub"]', style: { width: compact ? 31 : 40, height: compact ? 31 : 40, 'border-width': 6, 'border-color': '#164b42' } },
        { selector: 'edge', style: { width: compact ? 1.3 : 1.7, 'line-color': '#66818b', 'target-arrow-color': '#82a9af', 'target-arrow-shape': 'triangle', 'arrow-scale': .85, 'curve-style': 'bezier', opacity: .68 } },
        { selector: '.muted', style: { opacity: .12 } },
        { selector: '.selected', style: { 'border-color': '#ffffff', 'border-width': 4, width: 39, height: 39, opacity: 1 } },
      ],
      userZoomingEnabled: !compact,
      userPanningEnabled: !compact,
      boxSelectionEnabled: false,
      minZoom: .5, maxZoom: 2.2,
    })
    cy.on('tap', 'node', (event) => onSelectRef.current(event.target.id()))
    graph.current = cy
    return () => { cy.destroy(); graph.current = null }
  }, [compact])

  useEffect(() => {
    const cy = graph.current
    if (!cy) return
    cy.elements().removeClass('muted selected')
    const allowed = new Set(nodes.filter((node) => (roleFilter === 'All' || node.role === roleFilter) && (clusterFilter === 'All' || node.cluster === clusterFilter)).map((node) => node.gid))
    cy.nodes().forEach((node) => { if (!allowed.has(node.id())) node.addClass('muted') })
    cy.edges().forEach((edge) => { if (!allowed.has(edge.source().id()) || !allowed.has(edge.target().id())) edge.addClass('muted') })
    if (selected) cy.getElementById(selected).addClass('selected')
  }, [selected, roleFilter, clusterFilter])

  const focus = () => graph.current?.animate({ fit: { eles: graph.current.elements(), padding: compact ? 38 : 65 }, duration: 350 })
  return <div className={`graph-shell ${compact ? 'graph-compact' : ''}`}>
    <div className="graph-grid" /><div ref={container} className="cytoscape" />
    {!compact && <button className="graph-focus" type="button" onClick={focus} title="Fit network"><Focus size={17} /></button>}
  </div>
}

function DetailsPanel({ node, onClose, goToInvestigation }: { node: GraphNode; onClose: () => void; goToInvestigation: () => void }) {
  const connections = transfers.filter((transfer) => transfer.source === node.gid || transfer.target === node.gid)
  return <aside className="details-panel">
    <div className="details-top"><span className="eyebrow">NODE DETAILS</span><button className="icon-button" onClick={onClose} aria-label="Close details"><X size={18} /></button></div>
    <div className="details-identity"><span className="details-avatar" style={{ color: roleColors[node.role], borderColor: roleColors[node.role] }}><Fingerprint size={26} /></span><div><h2>{node.name}</h2><span className="mono">{node.gid}</span></div></div>
    <div className="details-tags"><span className="role-pill"><RoleDot role={node.role} />{node.role}</span><RiskBadge risk={node.risk} /></div>
    <p className="details-note">{node.note}</p>
    <div className="details-score"><div><span>Risk score</span><strong>{node.score}<small>/100</small></strong></div><div className="score-track"><span style={{ width: `${node.score}%` }} /></div></div>
    <div className="details-section"><span className="eyebrow">ENTITY PROFILE</span><dl><div><dt>Cluster</dt><dd>{node.cluster}</dd></div><div><dt>Total volume</dt><dd>{node.volume}</dd></div><div><dt>Transactions</dt><dd>{node.transactions}</dd></div><div><dt>Location</dt><dd>{node.location}</dd></div></dl></div>
    <div className="details-section"><span className="eyebrow">CONNECTED TRANSFERS</span><div className="connection-list">{connections.slice(0, 3).map((transfer) => <div key={transfer.id}><span className="connection-direction">{transfer.source === node.gid ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}</span><span>{transfer.source === node.gid ? transfer.target : transfer.source}<small>{transfer.date}</small></span><strong>{transfer.amount}</strong></div>)}</div></div>
    <button className="button button-primary details-action" onClick={goToInvestigation}>Open investigation <ArrowRight size={16} /></button>
  </aside>
}

function Overview({ onNavigate, onSelect }: { onNavigate: (page: Page) => void; onSelect: (gid: string) => void }) {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 60_000); return () => window.clearInterval(timer) }, [])
  const date = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric', timeZone: 'Asia/Almaty' }).format(now)
  const time = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Almaty' }).format(now)
  return <div className="overview">
    <div className="hero-scene"><div className="hero-glow" /><div className="mountain mountain-left" /><div className="mountain mountain-right" />
      <div className="hero-topline"><div className="hero-motto">FINANCIAL NETWORKS<br />GREATER TRANSPARENCY<br />SAFER SOCIETIES<span /></div><div className="hero-date">{date}<br /><strong>{time}</strong><br />Astana, Kazakhstan</div></div>
      <div className="hero-core"><div className="hero-orbit orbit-one" /><div className="hero-orbit orbit-two" /><div className="hero-orbit orbit-three" /><div className="hero-graph">{nodes.length ? <Graph selected={null} onSelect={(gid) => { onSelect(gid); onNavigate('Network') }} roleFilter="All" clusterFilter="All" compact /> : <div className="hero-empty-mark"><BrandMark /></div>}</div></div>
      <div className="hero-label left-top">DETECT<br />PATTERNS</div><div className="hero-label left-bottom">IDENTIFY<br />KEY ACTORS</div><div className="hero-label right-top">FOLLOW<br />THE MONEY</div><div className="hero-label right-bottom">ENABLE<br />INVESTIGATIONS</div>
      <div className="hero-statement"><span>M O N E Y&nbsp;&nbsp; G R A P H</span><h1>{nodes.length ? 'READY' : 'PENDING'}</h1><p>{nodes.length ? <>Explore connected entities, trace transfers,<br />and uncover patterns across the network.</> : <>Analysis results will appear here<br />when project data is available.</>}</p><button className="button button-primary" onClick={() => onNavigate('Network')}>View network <ArrowRight size={16} /></button></div>
      <div className="hero-quote">“From data<br />to safer financial<br />systems.”<span /></div>
    </div>
    <div className="overview-bottom"><div className="analysis-card"><div className="analysis-heading"><span>Analysis status</span><span className="analysis-status">{nodes.length ? 'Results available' : 'Waiting for project data'}</span></div><div className="analysis-content"><div className="analysis-segment dataset"><span className="analysis-icon"><Database size={25} /></span><span><strong>Network dataset</strong><small>{nodes.length ? 'Analysis loaded' : 'No analysis loaded'}</small></span></div><div className="analysis-segment metric-pair"><span><strong>{nodes.length ? nodes.length : '—'}</strong><small>entities</small></span><span><strong>{nodes.length ? transfers.length : '—'}</strong><small>transfers</small></span></div><div className="analysis-segment"><Network size={24} /><span><strong>NETWORK ANALYSIS</strong><small>{nodes.length ? `${clusters.length} clusters` : 'Results unavailable'}</small></span></div><div className="analysis-segment summary"><span className="complete">{nodes.length ? 'AVAILABLE' : 'PENDING'}</span><small>{nodes.length ? `${nodes.filter((node) => node.risk === 'High' || node.risk === 'Critical').length} high-priority entities` : 'No risk results yet'}</small></div><button className="analysis-open" onClick={() => onNavigate('Investigation')}>View investigations <ChevronRight size={19} /></button></div></div></div>
  </div>
}

function NetworkPage({ selected, setSelected, roleFilter, setRoleFilter, clusterFilter, setClusterFilter, onNavigate }: {
  selected: string | null; setSelected: (gid: string | null) => void; roleFilter: Role | 'All'; setRoleFilter: (role: Role | 'All') => void; clusterFilter: string; setClusterFilter: (cluster: string) => void; onNavigate: (page: Page) => void
}) {
  const [query, setQuery] = useState('')
  const [searchError, setSearchError] = useState('')
  const found = nodes.find((node) => node.gid === selected)
  function searchGid(event: React.FormEvent) { event.preventDefault(); const match = nodes.find((node) => node.gid.toLowerCase() === query.trim().toLowerCase()); if (match) { setRoleFilter('All'); setClusterFilter('All'); setSelected(match.gid); setSearchError('') } else setSearchError(query.trim() ? 'No matching GID in this network' : 'Enter a GID to search') }
  return <div className="page-content network-page">
    <div className="page-header"><div><Kicker>NETWORK INTELLIGENCE / 01</Kicker><h1>Network explorer</h1><p>Follow the flow. Understand every connection.</p></div><div className="header-chip">{nodes.length ? <><span className="live-dot" /> {nodes.length} entities · {transfers.length} transfers</> : 'No analysis loaded'}</div></div>
    <div className="network-toolbar"><form className="search-box" onSubmit={searchGid}><Search size={18} /><input value={query} onChange={(e) => { setQuery(e.target.value); setSearchError('') }} placeholder="Search by GID" aria-label="Search by GID" disabled={!nodes.length} /><button type="submit" disabled={!nodes.length}>Find <ArrowRight size={15} /></button></form><label className="select-wrap"><Filter size={15} /><select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value as Role | 'All'); setSelected(null) }} aria-label="Filter by role" disabled={!nodes.length}><option value="All">All roles</option>{roles.map((role) => <option key={role}>{role}</option>)}</select><ChevronDown size={14} /></label><label className="select-wrap"><Layers3 size={15} /><select value={clusterFilter} onChange={(e) => { setClusterFilter(e.target.value); setSelected(null) }} aria-label="Filter by cluster" disabled={!nodes.length}><option>All</option>{clusterNames.map((name) => <option key={name}>{name}</option>)}</select><ChevronDown size={14} /></label></div>
    {searchError && <div className="form-error">{searchError}</div>}
    <div className={`network-workspace ${found ? 'with-details' : ''}`}><div className="network-canvas"><div className="canvas-heading"><span>TRANSACTION NETWORK</span>{nodes.length > 0 && <span>Scroll to zoom · Drag to pan · Select an entity</span>}</div>{nodes.length ? <><Graph selected={selected} onSelect={setSelected} roleFilter={roleFilter} clusterFilter={clusterFilter} /><div className="graph-legend">{roles.map((role) => <span key={role}><RoleDot role={role} />{role}</span>)}</div></> : <EmptyData title="No network data available">Entities and transfer paths will appear when an analysis is available.</EmptyData>}</div>{found && <DetailsPanel node={found} onClose={() => setSelected(null)} goToInvestigation={() => onNavigate('Investigation')} />}</div>
    {nodes.length > 0 && <div className="network-footnote"><Sparkles size={16} /> Select an entity to inspect its profile and connected transfers. Arrows show transfer direction.</div>}
  </div>
}

function PriorityPage({ onSelect, onNavigate }: { onSelect: (gid: string) => void; onNavigate: (page: Page) => void }) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<'score' | 'transactions'>('score')
  const [riskFilter, setRiskFilter] = useState('All')
  const rows = useMemo(() => nodes.filter((node) => (riskFilter === 'All' || node.risk === riskFilter) && `${node.gid} ${node.name}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => sort === 'score' ? b.score - a.score : b.transactions - a.transactions), [query, sort, riskFilter])
  const csv = () => { const content = ['GID,Entity,Role,Cluster,Risk,Score,Volume,Transactions', ...rows.map((node) => `${node.gid},${node.name},${node.role},${node.cluster},${node.risk},${node.score},${node.volume},${node.transactions}`)].join('\n'); const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([content], { type: 'text/csv' })); link.download = 'money-graph-priority.csv'; link.click(); URL.revokeObjectURL(link.href) }
  return <div className="page-content"><div className="page-header"><div><Kicker>ENTITY RISK / 02</Kicker><h1>Priority queue</h1><p>Focus on the entities that need attention first.</p></div><button className="button button-secondary" onClick={csv} disabled={!rows.length}><Download size={16} /> Export CSV</button></div>
    <div className="stat-row"><div className="stat-card"><span>Entities tracked</span><strong>{nodes.length || '—'}</strong><small>{nodes.length ? `Across ${clusters.length} clusters` : 'Awaiting analysis'}</small></div><div className="stat-card"><span>Critical risk</span><strong>{nodes.length ? nodes.filter((node) => node.risk === 'Critical').length : '—'}</strong><small>Highest attention required</small></div><div className="stat-card"><span>High risk</span><strong>{nodes.length ? nodes.filter((node) => node.risk === 'High').length : '—'}</strong><small>Review in priority order</small></div><div className="stat-card"><span>Network volume</span><strong>—</strong><small>Available with analysis</small></div></div>
    <div className="panel table-panel"><div className="panel-title"><div><h2>Ranked entities</h2><p>Ordered by risk score and network activity</p></div><MoreHorizontal size={19} /></div><div className="table-tools"><div className="search-field"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search entity or GID" aria-label="Search priority table" disabled={!nodes.length} /></div><label className="select-wrap"><SlidersHorizontal size={15} /><select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)} aria-label="Filter by risk" disabled={!nodes.length}><option>All</option><option>Critical</option><option>High</option><option>Medium</option><option>Low</option></select><ChevronDown size={14} /></label><label className="select-wrap"><span>Sort:</span><select value={sort} onChange={(e) => setSort(e.target.value as 'score' | 'transactions')} aria-label="Sort entities" disabled={!nodes.length}><option value="score">Risk score</option><option value="transactions">Transactions</option></select><ChevronDown size={14} /></label></div>
      <div className="table-scroll"><table><thead><tr><th>ENTITY / GID</th><th>ROLE</th><th>CLUSTER</th><th>RISK</th><th>RISK SCORE</th><th>VOLUME</th><th>TXNS</th><th></th></tr></thead><tbody>{rows.map((node) => <tr key={node.gid} onClick={() => { onSelect(node.gid); onNavigate('Network') }} tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') { onSelect(node.gid); onNavigate('Network') } }}><td><strong>{node.name}</strong><small>{node.gid}</small></td><td><span className="role-cell"><RoleDot role={node.role} />{node.role}</span></td><td>{node.cluster}</td><td><RiskBadge risk={node.risk} /></td><td><span className="score-cell"><strong>{node.score}</strong><span><i style={{ width: `${node.score}%` }} /></span></span></td><td className="mono">{node.volume}</td><td className="mono">{node.transactions}</td><td><ChevronRight size={17} /></td></tr>)}</tbody></table>{rows.length === 0 && <div className="empty-state">{nodes.length ? 'No entities match the current filters.' : 'Risk rankings will appear when analysis data is available.'}</div>}</div><div className="table-footer">{nodes.length ? `Showing ${rows.length} of ${nodes.length} entities` : 'No analysis loaded'} {nodes.length > 0 && <span>Click a row to inspect its network <ArrowRight size={14} /></span>}</div></div>
  </div>
}

function ClustersPage({ setClusterFilter, setSelected, onNavigate }: { setClusterFilter: (name: string) => void; setSelected: (gid: string | null) => void; onNavigate: (page: Page) => void }) {
  return <div className="page-content"><div className="page-header"><div><Kicker>CONNECTED COMMUNITIES / 03</Kicker><h1>Clusters</h1><p>Explore related entities as connected communities.</p></div><span className="header-chip"><Layers3 size={16} /> {clusters.length ? `${clusters.length} clusters identified` : 'No analysis loaded'}</span></div>
    <div className="cluster-intro"><div><span className="eyebrow">NETWORK STRUCTURE</span><h2>Patterns emerge<br />when connections align.</h2><p>Each cluster groups entities with shared transfer paths. Open one to explore the relationships in context.</p></div><div className="cluster-mini"><span className="cluster-orbit one" /><span className="cluster-orbit two" /><span className="cluster-orbit three" /><i className="mini-node a" /><i className="mini-node b" /><i className="mini-node c" /><i className="mini-node d" /><i className="mini-node e" /></div></div>
    {clusters.length ? <div className="cluster-cards">{clusters.map((cluster, index) => <button className="cluster-card" key={cluster.id} onClick={() => { setSelected(null); setClusterFilter(cluster.name); onNavigate('Network') }}><div className="cluster-card-top"><span className="cluster-index">{String(index + 1).padStart(2, '0')} / {cluster.id}</span><RiskBadge risk={cluster.risk} /></div><div className={`cluster-visual visual-${index % 3}`}><i /><i /><i /><i /><span /></div><h3>{cluster.name}</h3><p>{cluster.description}</p><div className="cluster-card-stats"><span><strong>{cluster.members}</strong> Entities</span><span><strong>{cluster.volume}</strong> Volume</span></div><span className="cluster-link">Explore cluster <ArrowUpRight size={17} /></span></button>)}</div> : <div className="panel cluster-empty"><EmptyData title="No clusters available">Connected communities will appear after the network has been analyzed.</EmptyData></div>}
    {clusters.length > 0 && <div className="cluster-note"><CircleHelp size={18} /><span>Cluster membership reflects the current network view and can change as new connections are identified.</span></div>}
  </div>
}

function InvestigationPage({ onSelect, onNavigate }: { onSelect: (gid: string) => void; onNavigate: (page: Page) => void }) {
  const [active, setActive] = useState('All cases')
  const visible = cases.filter((item) => active === 'All cases' || item.status === active)
  return <div className="page-content"><div className="page-header"><div><Kicker>CASE WORKSPACE / 04</Kicker><h1>Investigations</h1><p>Keep every lead connected to the evidence.</p></div><span className="header-chip">{cases.length ? `${cases.length} case files` : 'No case files loaded'}</span></div>
    <div className="investigation-summary"><div><span className="eyebrow">CASE WORKSPACE</span><h2>Follow the evidence.</h2><p>Review linked entities and trace the transfer paths behind each case.</p><button className="button button-primary" onClick={() => onNavigate('Network')}>View network <ArrowRight size={16} /></button></div><div className="summary-metrics"><span><strong>{cases.length || '—'}</strong>Case files</span><span><strong>{cases.length ? cases.reduce((total, item) => total + item.entities, 0) : '—'}</strong>Linked entities</span><span><strong>{cases.length ? cases.filter((item) => item.status === 'In review').length : '—'}</strong>In review</span></div></div>
    <div className="panel cases-panel"><div className="panel-title"><div><h2>Case files</h2><p>Investigations in this workspace</p></div></div>{cases.length > 0 && <div className="tab-list">{['All cases', 'In review', 'Open'].map((tab) => <button key={tab} className={active === tab ? 'active' : ''} onClick={() => setActive(tab)}>{tab}</button>)}</div>}<div className="case-list">{visible.length ? visible.map((item) => <button key={item.id} className="case-row" onClick={() => { onSelect(item.gid); onNavigate('Network') }}><span className="case-icon"><Fingerprint size={21} /></span><span className="case-main"><span className="mono">{item.id}</span><strong>{item.title}</strong><small>{item.entities} linked entities · {item.owner}</small></span><span className="case-meta"><RiskBadge risk={item.priority} /><small>{item.updated}</small></span><span className="case-status">{item.status}</span><ChevronRight size={19} /></button>) : <div className="empty-state">{cases.length ? 'No cases match this status.' : 'Case files will appear when investigation data is available.'}</div>}</div></div>
  </div>
}

export default function App() {
  const [page, setPage] = useState<Page>('Overview')
  const [selected, setSelected] = useState<string | null>(null)
  const [roleFilter, setRoleFilter] = useState<Role | 'All'>('All')
  const [clusterFilter, setClusterFilter] = useState('All')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [showWorkspace, setShowWorkspace] = useState(false)
  const [showProfile, setShowProfile] = useState(false)
  const [isLoading] = useState(false)
  function navigate(next: Page) { setPage(next); setMobileOpen(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }
  function inspect(gid: string) { setRoleFilter('All'); setClusterFilter('All'); setSelected(gid) }
  return <div className="app-shell">
    <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}><div className="sidebar-brand"><BrandMark /><strong>MONEY GRAPH</strong><span>AML INTELLIGENCE<br />PLATFORM</span></div><nav aria-label="Primary navigation">{pages.map(({ name, icon: Icon }) => <button key={name} className={`nav-link ${page === name ? 'active' : ''}`} onClick={() => navigate(name)}><Icon size={21} strokeWidth={1.65} /><span>{name}</span>{page === name && <i />}</button>)}</nav><div className="sidebar-bottom"><span>TRACE. EXPLAIN.<br />PRIORITIZE.</span><p>Financial network<br />intelligence</p></div></aside>
    {mobileOpen && <button className="mobile-scrim" aria-label="Close menu" onClick={() => setMobileOpen(false)} />}
    <div className="main-shell"><header className="topbar"><div className="top-left"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={22} /></button><div className="workspace-switch"><button onClick={() => setShowWorkspace(!showWorkspace)}>AML Investigation Workspace <ChevronDown size={16} /></button>{showWorkspace && <div className="popover workspace-popover"><span className="eyebrow">CURRENT WORKSPACE</span><strong>AML Investigation Workspace</strong><small>Money Graph intelligence platform</small></div>}</div></div><div className="top-actions"><button className="icon-button notifications" onClick={() => setShowNotifications(!showNotifications)} aria-label="Notifications"><Bell size={20} /></button>{showNotifications && <div className="popover notification-popover"><span className="eyebrow">NOTIFICATIONS</span><strong>No notifications loaded</strong><small>Updates will appear here when available.</small></div>}<span className="top-divider" /><button className="profile-button" onClick={() => setShowProfile(!showProfile)}><span className="avatar">M</span><span>Money Graph</span><ChevronDown size={16} /></button>{showProfile && <div className="popover profile-popover"><span className="eyebrow">WORKSPACE</span><strong>Money Graph</strong><small>Investigation workspace</small></div>}</div></header>
      <main><PageErrorBoundary>{isLoading ? <div className="loading-screen"><BrandMark small /><span>Preparing workspace...</span></div> : page === 'Overview' ? <Overview onNavigate={navigate} onSelect={inspect} /> : page === 'Network' ? <NetworkPage selected={selected} setSelected={setSelected} roleFilter={roleFilter} setRoleFilter={setRoleFilter} clusterFilter={clusterFilter} setClusterFilter={setClusterFilter} onNavigate={navigate} /> : page === 'Priority' ? <PriorityPage onSelect={inspect} onNavigate={navigate} /> : page === 'Clusters' ? <ClustersPage setClusterFilter={setClusterFilter} setSelected={setSelected} onNavigate={navigate} /> : <InvestigationPage onSelect={inspect} onNavigate={navigate} />}</PageErrorBoundary></main>
    </div>
  </div>
}
