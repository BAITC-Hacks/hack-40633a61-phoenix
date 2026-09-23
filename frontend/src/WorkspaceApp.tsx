import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import cytoscape, { type Core } from 'cytoscape'
import {
  Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, Bot, Database,
  FileUp, Fingerprint, Focus, Languages, Layers3, Menu, Network,
  RotateCcw, Search, ShieldAlert, Sparkles, X,
} from 'lucide-react'
import {
  ApiError,
  askAi,
  fetchAiStatus,
  fetchNodeDetail,
  uploadAnalysis,
  type ApiGraphResponse,
  type ApiNodeDetail,
} from './api'
import { formatKzt, riskColors, roleLabelsByLanguage, type RiskLevel } from './data'
import { useI18n } from './i18n'
import { useGraphData } from './store'

type Page = 'overview' | 'priority' | 'clusters' | 'assistant'

function Brand() {
  const { t } = useI18n()
  return <div className="workspace-brand">
    <svg viewBox="0 0 42 42" aria-hidden="true">
      <path d="M21 3 37 12v18L21 39 5 30V12L21 3Z" />
      <path d="m5 12 16 10 16-10M21 3v19m0 0v17" />
      <circle cx="21" cy="22" r="4" />
    </svg>
    <span><strong>MONEY GRAPH</strong><small>{t('platform')}</small></span>
  </div>
}

function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  const { t } = useI18n()
  return <span className={`risk-chip risk-${level}`}>
    <i />{t(level)}{score === undefined ? '' : ` · ${score.toFixed(1)}`}
  </span>
}

function UploadPanel() {
  const { t } = useI18n()
  const { analysis, analysisId, activateAnalysis, resetAnalysis } = useGraphData()
  const [files, setFiles] = useState<Partial<Record<'nodes' | 'edges' | 'transactions', File>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [inputKey, setInputKey] = useState(0)

  const submit = async () => {
    if (!files.nodes || !files.edges || !files.transactions) return
    setBusy(true)
    setError('')
    try {
      const result = await uploadAnalysis({
        nodes: files.nodes,
        edges: files.edges,
        transactions: files.transactions,
      })
      activateAnalysis(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('uploadError'))
    } finally {
      setBusy(false)
    }
  }
  const reset = async () => {
    setBusy(true)
    setError('')
    try {
      await resetAnalysis()
      setFiles({})
      setInputKey((value) => value + 1)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('deleteError'))
    } finally {
      setBusy(false)
    }
  }

  if (analysisId && analysis) {
    return <section className="dataset-status panel">
      <div><span className="status-dot" /><strong>{t('activeDataset')}</strong></div>
      <div className="dataset-files">
        {analysis.files.map((file) => <span key={file.kind}><Database size={14} />{file.name}</span>)}
      </div>
      <time>{t('analyzedAt')}: {new Date(analysis.analyzed_at).toLocaleString()}</time>
      <button className="icon-button danger" onClick={reset} disabled={busy} title={t('resetAnalysis')} aria-label={t('resetAnalysis')}><X size={19} /></button>
      {error && <div className="inline-error"><ShieldAlert size={16} />{error}</div>}
    </section>
  }

  return <section className="upload-compact panel">
    <div className="upload-copy"><FileUp size={24} /><div><h2>{t('uploadTitle')}</h2><p>{t('uploadHint')}</p></div></div>
    <div className="upload-fields">
      {(['nodes', 'edges', 'transactions'] as const).map((kind) => <label key={`${kind}-${inputKey}`}>
        <span>{t(kind)}</span>
        <strong>{files[kind]?.name ?? t('choose')}</strong>
        <input
          type="file"
          accept=".parquet"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) setFiles((current) => ({ ...current, [kind]: file }))
            setError('')
          }}
        />
      </label>)}
      <button
        className="button button-primary analyze-button"
        disabled={busy || !files.nodes || !files.edges || !files.transactions}
        onClick={submit}
      >
        {busy ? t('analyzing') : t('analyze')} <ArrowRight size={16} />
      </button>
    </div>
    {error && <div className="inline-error"><ShieldAlert size={16} /><span><strong>{t('uploadError')}:</strong> {error}</span></div>}
  </section>
}

function TransactionGraph({
  data,
  selected,
  onSelect,
  onCluster,
  fitSignal,
}: {
  data: ApiGraphResponse
  selected: string | null
  onSelect: (gid: string) => void
  onCluster: (clusterId: number) => void
  fitSignal: number
}) {
  const container = useRef<HTMLDivElement>(null)
  const core = useRef<Core | null>(null)
  const handlers = useRef({ onSelect, onCluster })
  handlers.current = { onSelect, onCluster }

  useEffect(() => {
    if (!container.current) return
    const volumes = data.edges.map((edge) => edge.sum_kzt)
    const maxVolume = Math.max(...volumes, 1)
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...data.nodes.map((node) => ({
          data: {
            ...node,
            color: riskColors[node.risk_level],
            size: Math.min(70, 22 + Math.sqrt(node.member_count) * 3 + node.risk_score * 0.18),
            display: node.label || node.id,
          },
        })),
        ...data.edges.map((edge) => ({
          data: {
            ...edge,
            color: riskColors[edge.risk_level],
            width: 1.2 + 7 * Math.sqrt(edge.sum_kzt / maxVolume),
          },
        })),
      ],
      layout: {
        name: 'cose',
        animate: false,
        fit: true,
        padding: 54,
        idealEdgeLength: data.aggregated ? 150 : 92,
        nodeRepulsion: data.aggregated ? 180000 : 90000,
        gravity: 0.35,
        numIter: 700,
      },
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            width: 'data(size)',
            height: 'data(size)',
            label: 'data(display)',
            color: '#cfdbde',
            'font-size': 10,
            'font-family': 'DM Sans, sans-serif',
            'text-valign': 'bottom',
            'text-margin-y': 8,
            'text-outline-color': '#111a1f',
            'text-outline-width': 2,
            'border-color': '#263a40',
            'border-width': 3,
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'node[kind = "cluster"]',
          style: { 'border-width': 6, 'border-color': '#dbe7e8', 'font-size': 12 },
        },
        {
          selector: 'edge',
          style: {
            width: 'data(width)',
            'line-color': 'data(color)',
            'target-arrow-color': 'data(color)',
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.8,
            'curve-style': 'bezier',
            opacity: 0.62,
            'overlay-opacity': 0,
          },
        },
        { selector: '.faded', style: { opacity: 0.1 } },
        { selector: '.connected', style: { opacity: 1, 'z-index': 10 } },
        { selector: '.selected', style: { 'border-color': '#ffffff', 'border-width': 5, opacity: 1 } },
      ],
      minZoom: 0.15,
      maxZoom: 3,
      wheelSensitivity: 0.25,
    })
    cy.on('tap', 'node', (event) => {
      const node = event.target
      if (node.data('kind') === 'cluster') handlers.current.onCluster(Number(node.data('cluster_id')))
      else handlers.current.onSelect(node.id())
    })
    cy.on('tap', (event) => {
      if (event.target === cy) handlers.current.onSelect('')
    })
    core.current = cy
    return () => { cy.destroy(); core.current = null }
  }, [data])

  useEffect(() => {
    const cy = core.current
    if (!cy) return
    cy.elements().removeClass('faded connected selected')
    if (!selected) return
    const node = cy.$id(selected)
    if (!node.length) return
    cy.elements().addClass('faded')
    node.closedNeighborhood().removeClass('faded').addClass('connected')
    node.addClass('selected')
    cy.animate({ fit: { eles: node.closedNeighborhood(), padding: 90 }, duration: 350 })
  }, [selected, data])

  useEffect(() => {
    core.current?.animate({ fit: { eles: core.current.elements(), padding: 54 }, duration: 350 })
  }, [fitSignal])

  return <div className="graph-stage">
    <div className="graph-grid" />
    <div className="cytoscape workspace-canvas" ref={container} />
  </div>
}

function NodeCard({ gid, onClose }: { gid: string | null; onClose: () => void }) {
  const { language, t } = useI18n()
  const [node, setNode] = useState<ApiNodeDetail | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setNode(null)
    setError('')
    if (!gid) return
    let cancelled = false
    fetchNodeDetail(gid)
      .then((value) => { if (!cancelled) setNode(value) })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : t('loadError')) })
    return () => { cancelled = true }
  }, [gid, t])

  if (!gid) return <aside className="node-card panel node-card-empty"><Fingerprint size={31} /><h3>{t('nodeDetails')}</h3><p>{t('selectNode')}</p></aside>
  if (error) return <aside className="node-card panel node-card-empty"><ShieldAlert size={27} /><p>{error}</p><button className="icon-button" onClick={onClose}><X size={18} /></button></aside>
  if (!node) return <aside className="node-card panel node-card-empty"><span className="loader" /></aside>

  const role = roleLabelsByLanguage[node.role]?.[language] ?? node.role
  return <aside className="node-card panel">
    <div className="node-card-head">
      <span className="node-avatar"><Fingerprint size={23} /></span>
      <div><small>{t('nodeDetails')}</small><h2>{node.gid}</h2><span>{role}</span></div>
      <button className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button>
    </div>
    <RiskBadge level={node.risk_level} score={node.risk_score} />
    <div className="risk-meter"><i style={{ width: `${node.risk_score}%`, background: riskColors[node.risk_level] }} /></div>
    <div className="node-metrics">
      <div><span>{t('cluster')}</span><strong>#{node.cluster_id}</strong></div>
      <div><span>{t('incoming')}</span><strong>{node.in_tx ?? 0}</strong></div>
      <div><span>{t('outgoing')}</span><strong>{node.out_tx ?? 0}</strong></div>
      <div><span>{t('incomingAmount')}</span><strong>{formatKzt(node.in_kzt)}</strong></div>
      <div><span>{t('outgoingAmount')}</span><strong>{formatKzt(node.out_kzt)}</strong></div>
    </div>
    {Object.keys(node.attributes).length > 0 && <section className="card-section"><h3>{t('entityAttributes')}</h3><dl>{Object.entries(node.attributes).slice(0, 8).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl></section>}
    <section className="card-section"><h3>{t('factors')}</h3><p>{node.risk_explanation}</p></section>
    <section className="card-section"><h3>{t('connections')}</h3><div className="connection-list">{node.neighbors.slice(0, 6).map((item) => <div key={`${item.direction}-${item.gid}`}><span>{item.direction === 'in' ? <ArrowDownLeft size={15} /> : <ArrowUpRight size={15} />}</span><code>{item.gid}</code><strong>{formatKzt(item.sum_kzt)}</strong></div>)}</div></section>
    <section className="card-section"><h3>{t('recentTransactions')}</h3><div className="transaction-list">{node.transactions.slice(0, 8).map((tx) => <article key={tx.tx_id}><div><code>{tx.tx_id}</code><RiskBadge level={tx.risk_level} /></div><strong>{formatKzt(tx.sum_kzt)}</strong><span>{tx.source} → {tx.target}</span><time>{new Date(tx.date).toLocaleString()}</time></article>)}</div></section>
  </aside>
}

function GraphWorkspace({ selected, setSelected }: { selected: string | null; setSelected: (gid: string | null) => void }) {
  const { t } = useI18n()
  const { graph, graphLoading, openCluster, searchNode, resetGraph } = useGraphData()
  const [query, setQuery] = useState('')
  const [searchError, setSearchError] = useState('')
  const [fitSignal, setFitSignal] = useState(0)
  if (!graph) return null
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const value = query.trim()
    if (!value) return
    const found = graph.nodes.some((node) => node.id === value && node.kind === 'entity')
    if (found) {
      setSelected(value)
      setSearchError('')
      return
    }
    if (await searchNode(value)) {
      setSelected(value)
      setSearchError('')
    } else setSearchError(t('noMatch'))
  }
  return <section className={`graph-workspace ${selected ? 'with-node' : ''}`}>
    <div className="graph-panel panel">
      <div className="graph-toolbar">
        <div><h2>{t('graphTitle')}</h2><p>{graph.aggregated ? `${t('clusterOverview')} · ${t('openCluster')}` : t('graphHint')}</p></div>
        <form onSubmit={submit}><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('searchPlaceholder')} /><button>{t('search')}</button></form>
        <button className="toolbar-button" onClick={() => setFitSignal((value) => value + 1)}><Focus size={16} />{t('fit')}</button>
        <button className="toolbar-button" onClick={async () => { setSelected(null); await resetGraph() }}><RotateCcw size={16} />{t('resetView')}</button>
      </div>
      {searchError && <div className="search-error">{searchError}</div>}
      <div className="graph-meta"><span>{graph.nodes.length} {t('entities')}</span><span>{graph.edges.length} {t('transfers')}</span>{graphLoading && <span className="loader small" />}</div>
      <TransactionGraph data={graph} selected={selected} onSelect={(gid) => setSelected(gid || null)} onCluster={async (id) => { setSelected(null); await openCluster(id) }} fitSignal={fitSignal} />
      <div className="graph-legend">
        <strong>{t('riskLegend')}</strong>
        {(['low', 'medium', 'high', 'critical'] as RiskLevel[]).map((level) => <span key={level}><i style={{ background: riskColors[level] }} />{t(level)}</span>)}
        <em>{t('edgeLegend')}</em>
      </div>
    </div>
    <NodeCard gid={selected} onClose={() => setSelected(null)} />
  </section>
}

function OverviewPage({ selected, setSelected }: { selected: string | null; setSelected: (gid: string | null) => void }) {
  const { t } = useI18n()
  const { analysisId, summary, error, loading, reload } = useGraphData()
  return <div className="workspace-page">
    <UploadPanel />
    {!analysisId ? <div className="workspace-empty panel"><Network size={42} /><h1>{t('emptyTitle')}</h1><p>{t('emptyText')}</p></div>
      : loading ? <div className="workspace-empty panel"><span className="loader" /><p>{t('analyzing')}</p></div>
        : error ? <div className="workspace-empty panel"><ShieldAlert size={37} /><h2>{t('loadError')}</h2><p>{error}</p><button className="button button-primary" onClick={reload}>{t('retry')}</button></div>
          : <>
            {summary && <div className="summary-strip">
              <span><strong>{summary.n_nodes}</strong>{t('entities')}</span>
              <span><strong>{summary.n_edges}</strong>{t('transfers')}</span>
              <span><strong>{summary.n_clusters}</strong>{t('clusters')}</span>
              <p><Sparkles size={15} />{t('heuristicNotice')}</p>
            </div>}
            <GraphWorkspace selected={selected} setSelected={setSelected} />
          </>}
  </div>
}

function PriorityPage({ inspect }: { inspect: (gid: string) => void }) {
  const { language, t } = useI18n()
  const { analysisId, topNodes } = useGraphData()
  return <div className="workspace-page content-page">
    <header><span>AML / 01</span><h1>{t('rankedEntities')}</h1></header>
    {!analysisId ? <div className="workspace-empty panel"><Database size={34} /><p>{t('noAnalysis')}</p></div> : <div className="risk-list panel">
      {topNodes.slice().sort((a, b) => b.risk_score - a.risk_score).map((node) => <button key={node.gid} onClick={() => inspect(node.gid)}>
        <span className="rank">#{node.rank}</span><span><strong>{node.gid}</strong><small>{roleLabelsByLanguage[node.role]?.[language] ?? node.role}</small></span>
        <RiskBadge level={node.risk_level} score={node.risk_score} /><p>{node.why}</p><ArrowRight size={17} />
      </button>)}
    </div>}
  </div>
}

function ClustersPage({ open }: { open: (clusterId: number) => void }) {
  const { t } = useI18n()
  const { analysisId, clusters } = useGraphData()
  return <div className="workspace-page content-page">
    <header><span>AML / 02</span><h1>{t('clusterHypotheses')}</h1></header>
    {!analysisId ? <div className="workspace-empty panel"><Layers3 size={34} /><p>{t('noAnalysis')}</p></div> : <div className="cluster-grid">
      {clusters.slice().sort((a, b) => b.risk_score - a.risk_score).map((cluster) => <button className="cluster-risk-card panel" key={cluster.cluster_id} onClick={() => open(cluster.cluster_id)}>
        <div><strong>{t('cluster')} #{cluster.cluster_id}</strong><RiskBadge level={cluster.risk_level} score={cluster.risk_score} /></div>
        <p>{cluster.risk_explanation}</p><small>{cluster.hypothesis}</small>
        <footer><span>{t('members')}: <b>{cluster.n_nodes}</b></span><span>{t('internalVolume')}: <b>{formatKzt(cluster.sum_kzt_internal)}</b></span></footer>
      </button>)}
    </div>}
  </div>
}

function AssistantPage({ selected }: { selected: string | null }) {
  const { language, t } = useI18n()
  const { analysisId, graph } = useGraphData()
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [citations, setCitations] = useState<string[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setConfigured(null)
    setError('')
    if (!analysisId) return
    fetchAiStatus().then((status) => setConfigured(status.configured)).catch((err) => setError(err instanceof Error ? err.message : t('loadError')))
  }, [analysisId, t])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(''); setAnswer(''); setCitations([])
    try {
      const clusterId = selected
        ? graph?.nodes.find((node) => node.id === selected)?.cluster_id
        : null
      const response = await askAi(question, language, selected, clusterId)
      setAnswer(response.answer)
      setCitations(response.citations.map((item) => item.gid))
    } catch (err) {
      setError(err instanceof ApiError && err.status === 503 ? t('aiNoKey') : err instanceof Error ? err.message : t('loadError'))
    } finally { setBusy(false) }
  }
  return <div className="workspace-page content-page"><header><span>AML / AI</span><h1>{t('askTitle')}</h1><p>{t('askHint')}</p></header>
    {!analysisId ? <div className="workspace-empty panel"><Bot size={37} /><p>{t('aiNoAnalysis')}</p></div> : <div className="assistant-workspace panel">
      <div className={`ai-status ${configured ? 'ready' : ''}`}>{configured === null ? t('aiChecking') : configured ? t('aiReady') : t('aiNoKey')}</div>
      <form onSubmit={submit}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={t('askPlaceholder')} maxLength={2000} disabled={!configured || busy} /><button className="button button-primary" disabled={!configured || busy || !question.trim()}>{busy ? t('analyzing') : t('ask')} <Bot size={16} /></button></form>
      {error && <div className="inline-error"><ShieldAlert size={16} />{error}</div>}
      {answer && <article className="ai-answer"><p>{answer}</p>{citations.length > 0 && <div><strong>{t('sources')}:</strong>{citations.map((gid) => <code key={gid}>{gid}</code>)}</div>}</article>}
    </div>}
  </div>
}

export default function WorkspaceApp() {
  const { language, setLanguage, t } = useI18n()
  const { analysisId, searchNode, openCluster } = useGraphData()
  const [page, setPage] = useState<Page>('overview')
  const [selected, setSelected] = useState<string | null>(null)
  const [mobile, setMobile] = useState(false)
  useEffect(() => { setSelected(null) }, [analysisId])
  const pages = useMemo(() => [
    { id: 'overview' as const, icon: Network, label: t('overview') },
    { id: 'priority' as const, icon: Activity, label: t('priority') },
    { id: 'clusters' as const, icon: Layers3, label: t('clusters') },
    { id: 'assistant' as const, icon: Bot, label: t('assistant') },
  ], [t])
  const navigate = (next: Page) => { setPage(next); setMobile(false) }
  const inspect = async (gid: string) => {
    await searchNode(gid)
    setSelected(gid)
    navigate('overview')
  }
  const cluster = async (id: number) => {
    await openCluster(id)
    setSelected(null)
    navigate('overview')
  }
  return <div className="app-shell workspace-shell">
    <aside className={`sidebar workspace-sidebar ${mobile ? 'sidebar-open' : ''}`}>
      <Brand />
      <nav>{pages.map(({ id, icon: Icon, label }) => <button key={id} className={page === id ? 'active' : ''} onClick={() => navigate(id)}><Icon size={19} /><span>{label}</span></button>)}</nav>
      <div className="sidebar-disclaimer"><ShieldAlert size={17} />{t('heuristicNotice')}</div>
    </aside>
    {mobile && <button className="mobile-scrim" onClick={() => setMobile(false)} aria-label="close" />}
    <div className="main-shell">
      <header className="topbar workspace-topbar">
        <button className="icon-button mobile-menu" onClick={() => setMobile(true)}><Menu size={20} /></button>
        <div><strong>{t('workspace')}</strong><small>{t('platform')}</small></div>
        <label className="language-switch"><Languages size={16} /><span>{t('language')}</span><select value={language} onChange={(event) => setLanguage(event.target.value as 'ru' | 'kk')}><option value="ru">{t('ru')}</option><option value="kk">{t('kk')}</option></select></label>
      </header>
      <main>
        {page === 'overview' ? <OverviewPage selected={selected} setSelected={setSelected} />
          : page === 'priority' ? <PriorityPage inspect={inspect} />
            : page === 'clusters' ? <ClustersPage open={cluster} />
              : <AssistantPage selected={selected} />}
      </main>
    </div>
  </div>
}
