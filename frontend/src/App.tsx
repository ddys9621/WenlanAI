import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AppLayout } from '@/components/layout/AppLayout'
import { AdminRoute, ProtectedRoute } from '@/components/ProtectedRoute'
import { PageLoading } from '@/components/ui/PageLoading'

// 页面懒加载
const Login = lazy(() => import('@/pages/Login'))
const ProjectList = lazy(() => import('@/pages/ProjectList'))
const ProjectDetail = lazy(() => import('@/pages/ProjectDetail'))
const WorldSetting = lazy(() => import('@/pages/WorldSetting'))
const WorldRules = lazy(() => import('@/pages/WorldRules'))
const SettingEntries = lazy(() => import('@/pages/SettingEntries'))
const Outline = lazy(() => import('@/pages/Outline'))
const Characters = lazy(() => import('@/pages/Characters'))
const Relationships = lazy(() => import('@/pages/Relationships'))
const Organizations = lazy(() => import('@/pages/Organizations'))
const ChapterAnalysis = lazy(() => import('@/pages/ChapterAnalysis'))
const WritingStyles = lazy(() => import('@/pages/WritingStyles'))
const ProjectPrompts = lazy(() => import('@/pages/ProjectPrompts'))
const Memories = lazy(() => import('@/pages/Memories'))
const Settings = lazy(() => import('@/pages/Settings'))
const MCPPlugins = lazy(() => import('@/pages/MCPPlugins'))
const UserManagement = lazy(() => import('@/pages/UserManagement'))
const BookDissect = lazy(() => import('@/pages/BookDissect'))
const KnowledgeLibrary = lazy(() => import('@/pages/KnowledgeLibrary'))
const KnowledgeSource = lazy(() => import('@/pages/KnowledgeSource'))
const ProjectKnowledge = lazy(() => import('@/pages/ProjectKnowledge'))
const WorldMap = lazy(() => import('@/pages/WorldMap'))

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
            {/* 参考库已并入知识库，老链接重定向 */}
            <Route path="/reference-packs/*" element={<Navigate to="/knowledge" replace />} />
            <Route path="/knowledge" element={<KnowledgeLibrary />} />
            <Route path="/knowledge/:sourceId" element={<KnowledgeSource />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/mcp-plugins" element={<MCPPlugins />} />
            <Route path="/user-management" element={<AdminRoute><UserManagement /></AdminRoute>} />
          </Route>

          {/* 项目详情 - 带项目子布局 */}
          <Route path="/project/:projectId" element={<ProtectedRoute><ProjectDetail /></ProtectedRoute>}>
            <Route index element={<Navigate to="world-setting" replace />} />
            <Route path="world-setting" element={<WorldSetting />} />
            <Route path="world-rules" element={<WorldRules />} />
            <Route path="setting-entries" element={<SettingEntries />} />
            <Route path="world-map" element={<WorldMap />} />
            <Route path="outline/*" element={<Outline />} />
            <Route path="characters" element={<Characters />} />
            <Route path="relationships" element={<Relationships />} />
            <Route path="organizations" element={<Organizations />} />
            {/* 旧「章节管理」/chapters 已并入剧情分析，老链接重定向 */}
            <Route path="chapters" element={<Navigate to="../chapter-analysis" replace />} />
            <Route path="chapter-analysis" element={<ChapterAnalysis />} />
            <Route path="writing-styles" element={<WritingStyles />} />
            <Route path="prompts" element={<ProjectPrompts />} />
            <Route path="memories" element={<Memories />} />
            <Route path="knowledge" element={<ProjectKnowledge />} />
            <Route path="reference-packs" element={<Navigate to="../knowledge" replace />} />
          </Route>

          {/* 独立页面 */}
          <Route path="/create/inspiration" element={<ProtectedRoute><Navigate to="/projects?panel=inspiration" replace /></ProtectedRoute>} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
