import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import { PageLoading } from '@/components/ui/PageLoading'

// 页面懒加载
const Login = lazy(() => import('@/pages/Login'))
const ProjectList = lazy(() => import('@/pages/ProjectList'))
const ProjectDetail = lazy(() => import('@/pages/ProjectDetail'))
const WorldSetting = lazy(() => import('@/pages/WorldSetting'))
const WorldRules = lazy(() => import('@/pages/WorldRules'))
const Outline = lazy(() => import('@/pages/Outline'))
const Characters = lazy(() => import('@/pages/Characters'))
const Relationships = lazy(() => import('@/pages/Relationships'))
const Organizations = lazy(() => import('@/pages/Organizations'))
const Chapters = lazy(() => import('@/pages/Chapters'))
const ChapterReader = lazy(() => import('@/pages/ChapterReader'))
const ChapterAnalysis = lazy(() => import('@/pages/ChapterAnalysis'))
const WritingStyles = lazy(() => import('@/pages/WritingStyles'))
const Memories = lazy(() => import('@/pages/Memories'))
const Settings = lazy(() => import('@/pages/Settings'))
const MCPPlugins = lazy(() => import('@/pages/MCPPlugins'))
const UserManagement = lazy(() => import('@/pages/UserManagement'))
const BookDissect = lazy(() => import('@/pages/BookDissect'))
const ReferencePackLibrary = lazy(() => import('@/pages/ReferencePackLibrary'))
const ReferencePackDetail = lazy(() => import('@/pages/ReferencePackDetail'))
const ProjectReferencePacks = lazy(() => import('@/pages/ProjectReferencePacks'))
const PlotBridges = lazy(() => import('@/pages/PlotBridges'))

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          {/* 公开页面 - 无布局 */}
          <Route path="/login" element={<Login />} />

          {/* 受保护页面 - 带布局 */}
          <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
            <Route path="/" element={<ProjectList />} />
            <Route path="/projects" element={<ProjectList />} />
            <Route path="/book-dissect" element={<BookDissect />} />
            <Route path="/reference-packs" element={<ReferencePackLibrary />} />
            <Route path="/reference-packs/:packId" element={<ReferencePackDetail />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/mcp-plugins" element={<MCPPlugins />} />
            <Route path="/user-management" element={<UserManagement />} />
          </Route>

          {/* 项目详情 - 带项目子布局 */}
          <Route path="/project/:projectId" element={<ProtectedRoute><ProjectDetail /></ProtectedRoute>}>
            <Route index element={<Navigate to="world-setting" replace />} />
            <Route path="world-setting" element={<WorldSetting />} />
            <Route path="world-rules" element={<WorldRules />} />
            <Route path="outline/*" element={<Outline />} />
            <Route path="characters" element={<Characters />} />
            <Route path="relationships" element={<Relationships />} />
            <Route path="organizations" element={<Organizations />} />
            <Route path="chapters" element={<Chapters />} />
            <Route path="chapter-analysis" element={<ChapterAnalysis />} />
            <Route path="writing-styles" element={<WritingStyles />} />
            <Route path="memories" element={<Memories />} />
            <Route path="reference-packs" element={<ProjectReferencePacks />} />
            <Route path="plot-bridges" element={<PlotBridges />} />
          </Route>

          {/* 独立页面 */}
          <Route path="/chapters/:chapterId/reader" element={<ProtectedRoute><ChapterReader /></ProtectedRoute>} />
          <Route path="/create/inspiration" element={<ProtectedRoute><Navigate to="/projects?panel=inspiration" replace /></ProtectedRoute>} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
