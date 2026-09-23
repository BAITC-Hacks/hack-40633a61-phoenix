// Единая точка загрузки живых данных с backend + React Context, чтобы
// компоненты App.tsx (Overview/NetworkPage/PriorityPage/ClustersPage/
// InvestigationPage/Graph) могли читать nodes/transfers/clusters/cases так
// же, как раньше читали статические массивы из data.ts — минимальная правка
// самого App.tsx, вся загрузка/трансформация вынесена сюда.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  ApiError,
  fetchClusters,
  fetchGraph,
  fetchSummary,
  fetchTopNodes,
  toCaseFiles,
  toClusters,
  toGraphNodes,
  toSummary,
  toTransfers,
  setActiveAnalysisId,
} from './api'
import type { CaseFile, Cluster, GraphNode, Summary, Transfer } from './data'

interface GraphDataState {
  nodes: GraphNode[]
  transfers: Transfer[]
  clusters: Cluster[]
  cases: CaseFile[]
  summary: Summary | null
  loading: boolean
  error: string | null
  reload: () => void
  analysisId: string | null
  selectAnalysis: (analysisId: string | null) => void
}

const DataContext = createContext<GraphDataState | null>(null)

export function DataProvider({ children }: { children: ReactNode }) {
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [transfers, setTransfers] = useState<Transfer[]>([])
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [cases, setCases] = useState<CaseFile[]>([])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [analysisId, setAnalysisId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    // Keep the interactive canvas readable; summary/cluster/top endpoints
    // still represent the complete analysis.
    Promise.all([fetchSummary(), fetchGraph({ limit: 600 }), fetchClusters(), fetchTopNodes()])
      .then(([apiSummary, graph, apiClusters, apiTop]) => {
        if (cancelled) return
        setNodes(toGraphNodes(graph.nodes))
        setTransfers(toTransfers(graph.edges))
        setClusters(toClusters(apiClusters))
        setCases(toCaseFiles(apiTop, graph.nodes, apiSummary.generated_at))
        setSummary(toSummary(apiSummary))
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 503) {
          // out/*.csv ещё не сгенерированы (./run.sh не запускался) —
          // понятное сообщение вместо падения страницы.
          setError('Аналитика ещё не сгенерирована на backend: запустите ./run.sh, затем обновите страницу.')
        } else {
          setError(err instanceof Error ? err.message : 'Не удалось загрузить данные с backend.')
        }
        setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])
  const selectAnalysis = useCallback((value: string | null) => {
    setActiveAnalysisId(value)
    setAnalysisId(value)
    setReloadKey((k) => k + 1)
  }, [])

  const value = useMemo<GraphDataState>(
    () => ({ nodes, transfers, clusters, cases, summary, loading, error, reload, analysisId, selectAnalysis }),
    [nodes, transfers, clusters, cases, summary, loading, error, reload, analysisId, selectAnalysis],
  )

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export function useGraphData(): GraphDataState {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error('useGraphData() must be used within <DataProvider>')
  return ctx
}
