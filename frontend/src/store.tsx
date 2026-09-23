import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  deleteAnalysis,
  fetchAnalysis,
  fetchClusters,
  fetchGraph,
  fetchSummary,
  fetchTopNodes,
  setActiveAnalysisId,
  type AnalysisResponse,
  type ApiCluster,
  type ApiGraphResponse,
  type ApiSummary,
  type ApiTopNode,
} from './api'

interface GraphDataState {
  analysisId: string | null
  analysis: AnalysisResponse | null
  summary: ApiSummary | null
  graph: ApiGraphResponse | null
  clusters: ApiCluster[]
  topNodes: ApiTopNode[]
  loading: boolean
  graphLoading: boolean
  error: string | null
  reload: () => void
  activateAnalysis: (analysis: AnalysisResponse) => void
  resetAnalysis: () => Promise<void>
  openCluster: (clusterId: number) => Promise<void>
  searchNode: (gid: string) => Promise<boolean>
  resetGraph: () => Promise<void>
}

const DataContext = createContext<GraphDataState | null>(null)

export function DataProvider({ children }: { children: ReactNode }) {
  const [analysisId, setAnalysisId] = useState<string | null>(
    () => sessionStorage.getItem('moneygraph.analysisId'),
  )
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null)
  const [summary, setSummary] = useState<ApiSummary | null>(null)
  const [graph, setGraph] = useState<ApiGraphResponse | null>(null)
  const [clusters, setClusters] = useState<ApiCluster[]>([])
  const [topNodes, setTopNodes] = useState<ApiTopNode[]>([])
  const [loading, setLoading] = useState(Boolean(analysisId))
  const [graphLoading, setGraphLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    if (!analysisId) {
      setActiveAnalysisId(null)
      setAnalysis(null)
      setSummary(null)
      setGraph(null)
      setClusters([])
      setTopNodes([])
      setError(null)
      setLoading(false)
      return
    }
    setActiveAnalysisId(analysisId)
    setLoading(true)
    setError(null)
    Promise.all([
      fetchAnalysis(analysisId),
      fetchSummary(),
      fetchGraph({ view: 'auto', limit: 4000 }),
      fetchClusters(),
      fetchTopNodes(),
    ])
      .then(([metadata, apiSummary, apiGraph, apiClusters, apiTop]) => {
        if (cancelled) return
        setAnalysis(metadata)
        setSummary(apiSummary)
        setGraph(apiGraph)
        setClusters(apiClusters)
        setTopNodes(apiTop)
        setLoading(false)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Не удалось загрузить данные с backend.')
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [analysisId, reloadKey])

  const reload = useCallback(() => setReloadKey((k) => k + 1), [])
  const activateAnalysis = useCallback((value: AnalysisResponse) => {
    sessionStorage.setItem('moneygraph.analysisId', value.analysis_id)
    setActiveAnalysisId(value.analysis_id)
    setAnalysis(value)
    setAnalysisId(value.analysis_id)
    setReloadKey((k) => k + 1)
  }, [])
  const resetAnalysis = useCallback(async () => {
    if (analysisId) await deleteAnalysis(analysisId)
    sessionStorage.removeItem('moneygraph.analysisId')
    setActiveAnalysisId(null)
    setAnalysisId(null)
  }, [analysisId])

  const replaceGraph = useCallback(async (request: () => Promise<ApiGraphResponse>) => {
    setGraphLoading(true)
    try {
      setGraph(await request())
      setError(null)
    } finally {
      setGraphLoading(false)
    }
  }, [])
  const openCluster = useCallback(
    async (clusterId: number) => replaceGraph(
      () => fetchGraph({ clusterId, view: 'full', limit: 4000 }),
    ),
    [replaceGraph],
  )
  const searchNode = useCallback(async (gid: string) => {
    try {
      await replaceGraph(async () => {
        const response = await fetchGraph({ gid, depth: 1, view: 'full', limit: 4000 })
        if (!response.nodes.some((node) => node.id === gid)) throw new Error('not-found')
        return response
      })
      return true
    } catch {
      return false
    }
  }, [replaceGraph])
  const resetGraph = useCallback(
    async () => replaceGraph(() => fetchGraph({ view: 'auto', limit: 4000 })),
    [replaceGraph],
  )

  const value = useMemo<GraphDataState>(
    () => ({
      analysisId, analysis, summary, graph, clusters, topNodes, loading,
      graphLoading, error, reload, activateAnalysis, resetAnalysis,
      openCluster, searchNode, resetGraph,
    }),
    [
      analysisId, analysis, summary, graph, clusters, topNodes, loading,
      graphLoading, error, reload, activateAnalysis, resetAnalysis,
      openCluster, searchNode, resetGraph,
    ],
  )

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export function useGraphData(): GraphDataState {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error('useGraphData() must be used within <DataProvider>')
  return ctx
}
