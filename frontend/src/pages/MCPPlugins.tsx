import { useEffect, useState, useCallback } from 'react'
import { Plus, Pencil, Trash2, Power, TestTube, Loader2, Plug, Wrench, ChevronDown, ChevronUp, Store } from 'lucide-react'
import { toast } from 'sonner'
import { mcpPluginApi } from '@/services/api'
import { Modal } from '@/components/ui/Modal'
import { MCPMarketplace } from '@/components/mcp/MCPMarketplace'
import { cn } from '@/lib/utils'
import type { MCPPlugin, MCPPluginCreate, MCPPluginUpdate, MCPTool } from '@/types'

type ModalMode = 'simple' | 'full' | 'edit'
type PageTab = 'mine' | 'market'

export default function MCPPlugins() {
  const [tab, setTab] = useState<PageTab>('mine')
  const [plugins, setPlugins] = useState<MCPPlugin[]>([])
  const [loading, setLoading] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)

  // 弹窗状态
  const [showModal, setShowModal] = useState(false)
  const [modalMode, setModalMode] = useState<ModalMode>('simple')
  const [configJson, setConfigJson] = useState('')
  const [editingPlugin, setEditingPlugin] = useState<MCPPlugin | null>(null)

  // 完整创建 / 编辑表单
  const [form, setForm] = useState({
    plugin_name: '',
    display_name: '',
    description: '',
    server_type: 'stdio' as 'http' | 'stdio',
    server_url: '',
    command: '',
    args: '',
    env: '',
    headers: '',
    enabled: true,
  })

  // 展开详情
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // 工具列表
  const [toolsMap, setToolsMap] = useState<Record<string, MCPTool[]>>({})
  const [loadingToolsId, setLoadingToolsId] = useState<string | null>(null)

  const fetchPlugins = useCallback(async () => {
    try {
      setLoading(true)
      const data = await mcpPluginApi.getPlugins()
      setPlugins(data)
    } catch { /* api 层已 toast */ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchPlugins() }, [fetchPlugins])

  // ---- 操作 ----

  const handleToggle = async (plugin: MCPPlugin) => {
    try {
      const updated = await mcpPluginApi.togglePlugin(plugin.id, !plugin.enabled)
      setPlugins(prev => prev.map(p => p.id === updated.id ? updated : p))
      toast.success(`${updated.enabled ? '已启用' : '已禁用'} ${updated.display_name}`)
    } catch { /* api 层已 toast */ }
  }

  const handleTest = async (plugin: MCPPlugin) => {
    try {
      setTestingId(plugin.id)
      const result = await mcpPluginApi.testPlugin(plugin.id)
      if (result.success) {
        toast.success(`连接成功，发现 ${result.tools_count || 0} 个工具`)
      } else {
        toast.error(result.message || '连接失败')
      }
    } catch { /* api 层已 toast */ } finally { setTestingId(null) }
  }

  const handleDelete = async (plugin: MCPPlugin) => {
    if (!confirm(`确定删除「${plugin.display_name}」？`)) return
    try {
      await mcpPluginApi.deletePlugin(plugin.id)
      setPlugins(prev => prev.filter(p => p.id !== plugin.id))
      toast.success('插件已删除')
    } catch { /* api 层已 toast */ }
  }

  // Simple 创建
  const handleCreateSimple = async () => {
    if (!configJson.trim()) { toast.error('请输入配置 JSON'); return }
    try {
      const created = await mcpPluginApi.createPluginSimple({ config_json: configJson, enabled: true })
      setPlugins(prev => [...prev, created])
      toast.success('插件已创建')
      closeModal()
    } catch { /* api 层已 toast */ }
  }

  // 完整创建
  const handleCreateFull = async () => {
    if (!form.plugin_name.trim()) { toast.error('请填写插件名称'); return }
    try {
      const data: MCPPluginCreate = {
        plugin_name: form.plugin_name,
        display_name: form.display_name || undefined,
        description: form.description || undefined,
        plugin_type: form.server_type,
        enabled: form.enabled,
      }
      if (form.server_type === 'http') {
        data.server_url = form.server_url || undefined
        if (form.headers.trim()) {
          try { data.headers = JSON.parse(form.headers) } catch { toast.error('Headers JSON 格式错误'); return }
        }
      } else {
        data.command = form.command || undefined
        if (form.args.trim()) data.args = form.args.split('\n').map(s => s.trim()).filter(Boolean)
        if (form.env.trim()) {
          try { data.env = JSON.parse(form.env) } catch { toast.error('环境变量 JSON 格式错误'); return }
        }
      }
      const created = await mcpPluginApi.createPlugin(data)
      setPlugins(prev => [...prev, created])
      toast.success('插件已创建')
      closeModal()
    } catch { /* api 层已 toast */ }
  }

  // 编辑
  const openEdit = (plugin: MCPPlugin) => {
    setEditingPlugin(plugin)
    setForm({
      plugin_name: plugin.plugin_name,
      display_name: plugin.display_name,
      description: plugin.description || '',
      server_type: plugin.plugin_type,
      server_url: plugin.server_url || '',
      command: plugin.command || '',
      args: (plugin.args || []).join('\n'),
      env: plugin.env ? JSON.stringify(plugin.env, null, 2) : '',
      headers: plugin.headers ? JSON.stringify(plugin.headers, null, 2) : '',
      enabled: plugin.enabled,
    })
    setModalMode('edit')
    setShowModal(true)
  }

  const handleUpdate = async () => {
    if (!editingPlugin) return
    try {
      const data: MCPPluginUpdate = {
        display_name: form.display_name || undefined,
        description: form.description || undefined,
        enabled: form.enabled,
      }
      if (editingPlugin.plugin_type === 'http') {
        data.server_url = form.server_url || undefined
        if (form.headers.trim()) {
          try { data.headers = JSON.parse(form.headers) } catch { toast.error('Headers JSON 格式错误'); return }
        }
      } else {
        data.command = form.command || undefined
        if (form.args.trim()) data.args = form.args.split('\n').map(s => s.trim()).filter(Boolean)
        if (form.env.trim()) {
          try { data.env = JSON.parse(form.env) } catch { toast.error('环境变量 JSON 格式错误'); return }
        }
      }
      const updated = await mcpPluginApi.updatePlugin(editingPlugin.id, data)
      setPlugins(prev => prev.map(p => p.id === updated.id ? updated : p))
      toast.success('插件已更新')
      closeModal()
    } catch { /* api 层已 toast */ }
  }

  // 查看工具列表
  const handleViewTools = async (plugin: MCPPlugin) => {
    if (toolsMap[plugin.id]) {
      // 已加载过，切换显示
      setToolsMap(prev => { const n = { ...prev }; delete n[plugin.id]; return n })
      return
    }
    try {
      setLoadingToolsId(plugin.id)
      const res = await mcpPluginApi.getPluginTools(plugin.id)
      setToolsMap(prev => ({ ...prev, [plugin.id]: res.tools }))
    } catch { /* api 层已 toast */ } finally { setLoadingToolsId(null) }
  }

  // 弹窗辅助
  const closeModal = () => {
    setShowModal(false)
    setModalMode('simple')
    setConfigJson('')
    setEditingPlugin(null)
    setForm({ plugin_name: '', display_name: '', description: '', server_type: 'stdio', server_url: '', command: '', args: '', env: '', headers: '', enabled: true })
  }

  const openCreate = (mode: 'simple' | 'full') => {
    setModalMode(mode)
    setShowModal(true)
  }

  const statusColor = (status: MCPPlugin['status']) => {
    switch (status) {
      case 'active': return 'bg-green-100 text-green-700'
      case 'error': return 'bg-red-100 text-red-700'
      default: return 'bg-gray-100 text-gray-600'
    }
  }

  const inputCls = 'w-full border border-surface-border rounded-btn px-3 py-2 text-sm focus:border-brand focus:ring-2 focus:ring-brand/20 outline-none transition-colors'

  // 商城安装成功后，把新插件并入「我的插件」列表（同名则替换）
  const handleInstalled = useCallback((plugin: MCPPlugin) => {
    setPlugins(prev => prev.some(p => p.id === plugin.id) ? prev.map(p => p.id === plugin.id ? plugin : p) : [...prev, plugin])
  }, [])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <h1 className="lj-page-title">MCP 插件管理</h1>
          <div className="flex gap-2" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'mine'} onClick={() => setTab('mine')} className={cn('hh-chip', tab === 'mine' && 'hh-chip--active')}>
              <Plug className="w-3.5 h-3.5" />我的插件 <span className="tabular-nums opacity-70">{plugins.length}</span>
            </button>
            <button type="button" role="tab" aria-selected={tab === 'market'} onClick={() => setTab('market')} className={cn('hh-chip', tab === 'market' && 'hh-chip--active')}>
              <Store className="w-3.5 h-3.5" />MCP 商城
            </button>
          </div>
        </div>
        {tab === 'mine' && (
          <div className="flex gap-2">
            <button onClick={() => openCreate('simple')} className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors inline-flex items-center gap-1.5">
              <Plus className="w-4 h-4" />
              快速添加
            </button>
            <button onClick={() => openCreate('full')} className="border border-surface-border text-content-secondary hover:bg-surface-hover rounded-btn px-4 py-2 text-sm inline-flex items-center gap-1.5">
              <Plus className="w-4 h-4" />
              完整创建
            </button>
          </div>
        )}
      </div>

      {tab === 'market' ? (
        <MCPMarketplace onInstalled={handleInstalled} />
      ) : loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-content-secondary" /></div>
      ) : plugins.length === 0 ? (
        <div className="text-center py-12 text-content-secondary text-sm space-y-3">
          <Plug className="w-8 h-8 mx-auto opacity-40" />
          <p>暂无插件</p>
          <button type="button" onClick={() => setTab('market')} className="border border-surface-border text-content-secondary hover:bg-surface-hover rounded-btn px-4 py-2 text-sm inline-flex items-center gap-1.5">
            <Store className="w-4 h-4" />
            去 MCP 商城一键安装
          </button>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {plugins.map(p => (
            <div key={p.id} className="bg-white border border-surface-border rounded-card p-4 space-y-3">
              {/* 头部：点击展开详情 */}
              <div className="flex items-start justify-between gap-2 cursor-pointer" onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <h3 className="text-sm font-semibold text-content truncate">{p.display_name}</h3>
                    {expandedId === p.id ? <ChevronUp className="w-3.5 h-3.5 text-content-secondary shrink-0" /> : <ChevronDown className="w-3.5 h-3.5 text-content-secondary shrink-0" />}
                  </div>
                  <p className="text-xs text-content-secondary">{p.transport === 'sse' ? 'SSE' : p.plugin_type.toUpperCase()} · {p.category}</p>
                </div>
                <span className={`text-xs px-1.5 py-0.5 rounded shrink-0 ${statusColor(p.status)}`}>
                  {p.status === 'active' ? '正常' : p.status === 'error' ? '异常' : '未激活'}
                </span>
              </div>

              {p.description && <p className="text-xs text-content-secondary line-clamp-2">{p.description}</p>}
              {p.last_error && <p className="text-xs text-red-500 line-clamp-1">{p.last_error}</p>}

              {/* 展开详情 */}
              {expandedId === p.id && (
                <div className="text-xs space-y-1.5 bg-surface-hover/30 rounded-btn p-3 border border-surface-border">
                  <div><span className="text-content-secondary">名称：</span><span className="text-content">{p.plugin_name}</span></div>
                  {p.plugin_type === 'http' && p.server_url && (
                    <div><span className="text-content-secondary">URL：</span><span className="text-content break-all">{p.server_url}</span></div>
                  )}
                  {p.plugin_type === 'stdio' && p.command && (
                    <div><span className="text-content-secondary">命令：</span><span className="text-content font-mono">{p.command} {(p.args || []).join(' ')}</span></div>
                  )}
                  {p.last_test_at && (
                    <div><span className="text-content-secondary">上次测试：</span><span className="text-content">{new Date(p.last_test_at).toLocaleString('zh-CN')}</span></div>
                  )}
                  <div><span className="text-content-secondary">创建时间：</span><span className="text-content">{new Date(p.created_at).toLocaleString('zh-CN')}</span></div>
                </div>
              )}

              {/* 工具列表 */}
              {toolsMap[p.id] && (
                <div className="text-xs space-y-1 bg-blue-50/50 rounded-btn p-3 border border-blue-100">
                  <div className="font-medium text-content mb-1">工具列表 ({toolsMap[p.id].length})</div>
                  {toolsMap[p.id].length === 0 ? (
                    <p className="text-content-secondary">暂无工具</p>
                  ) : (
                    <div className="space-y-1 max-h-40 overflow-y-auto">
                      {toolsMap[p.id].map(tool => (
                        <div key={tool.name} className="flex items-start gap-1.5">
                          <Wrench className="w-3 h-3 text-blue-500 mt-0.5 shrink-0" />
                          <div>
                            <span className="font-medium text-content">{tool.name}</span>
                            {tool.description && <p className="text-content-secondary">{tool.description}</p>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* 操作栏 */}
              <div className="flex items-center justify-between pt-1 border-t border-surface-border">
                <div className="flex gap-1">
                  <button
                    onClick={() => handleToggle(p)}
                    className={`p-1.5 rounded transition-colors ${p.enabled ? 'text-green-600 hover:bg-green-50' : 'text-content-secondary hover:bg-surface-hover'}`}
                    title={p.enabled ? '禁用' : '启用'}
                  >
                    <Power className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => handleTest(p)}
                    disabled={testingId === p.id}
                    className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors disabled:opacity-50"
                    title="测试连接"
                  >
                    {testingId === p.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <TestTube className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={() => handleViewTools(p)}
                    disabled={loadingToolsId === p.id}
                    className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors disabled:opacity-50"
                    title="查看工具"
                  >
                    {loadingToolsId === p.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wrench className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={() => openEdit(p)}
                    className="p-1.5 rounded hover:bg-surface-hover text-content-secondary transition-colors"
                    title="编辑"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                </div>
                <button onClick={() => handleDelete(p)} className="p-1.5 rounded hover:bg-red-50 text-content-secondary hover:text-red-500 transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 弹窗 */}
      {showModal && (
        <Modal
          title={modalMode === 'edit' ? '编辑插件' : modalMode === 'full' ? '创建 MCP 插件' : '快速添加 MCP 插件'}
          onClose={closeModal}
          size="xl"
          footer={modalMode === 'simple' ? (
            <>
              <button onClick={closeModal} className="border border-surface-border text-content-secondary hover:bg-surface-hover rounded-btn px-4 py-2 text-sm">取消</button>
              <button onClick={handleCreateSimple} className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors">创建</button>
            </>
          ) : (
            <>
              <button onClick={closeModal} className="border border-surface-border text-content-secondary hover:bg-surface-hover rounded-btn px-4 py-2 text-sm">取消</button>
              <button
                onClick={modalMode === 'edit' ? handleUpdate : handleCreateFull}
                className="bg-brand hover:bg-brand-600 text-white rounded-btn px-4 py-2 text-sm font-medium transition-colors"
              >
                {modalMode === 'edit' ? '保存' : '创建'}
              </button>
            </>
          )}
        >
          {modalMode === 'simple' ? (
            <div className="space-y-4">
              <p className="text-xs text-content-secondary">粘贴标准 MCP 配置 JSON（如 Claude Desktop 格式）</p>
              <textarea
                value={configJson}
                onChange={e => setConfigJson(e.target.value)}
                rows={10}
                placeholder='{"mcpServers":{"name":{"command":"...","args":[...]}}}'
                className={`${inputCls} resize-none font-mono`}
              />
            </div>
          ) : (
            /* 完整创建 / 编辑 共用表单 */
            <div className="space-y-4">
              {modalMode === 'full' && (
                <div>
                  <label className="block text-sm text-content-secondary mb-1">插件名称 *</label>
                  <input value={form.plugin_name} onChange={e => setForm(f => ({ ...f, plugin_name: e.target.value }))} placeholder="my-plugin" className={inputCls} />
                </div>
              )}
              <div>
                <label className="block text-sm text-content-secondary mb-1">显示名称</label>
                <input value={form.display_name} onChange={e => setForm(f => ({ ...f, display_name: e.target.value }))} placeholder="我的插件" className={inputCls} />
              </div>
              <div>
                <label className="block text-sm text-content-secondary mb-1">描述</label>
                <input value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="插件功能描述" className={inputCls} />
              </div>

              {modalMode === 'full' && (
                <div>
                  <label className="block text-sm text-content-secondary mb-1">类型</label>
                  <select value={form.server_type} onChange={e => setForm(f => ({ ...f, server_type: e.target.value as 'http' | 'stdio' }))} className={inputCls}>
                    <option value="stdio">Stdio</option>
                    <option value="http">HTTP</option>
                  </select>
                </div>
              )}

              {/* 根据类型显示不同字段 */}
              {(modalMode === 'edit' ? editingPlugin?.plugin_type : form.server_type) === 'http' ? (
                <>
                  <div>
                    <label className="block text-sm text-content-secondary mb-1">服务器 URL</label>
                    <input value={form.server_url} onChange={e => setForm(f => ({ ...f, server_url: e.target.value }))} placeholder="http://localhost:3000/mcp" className={inputCls} />
                  </div>
                  <div>
                    <label className="block text-sm text-content-secondary mb-1">Headers (JSON)</label>
                    <textarea value={form.headers} onChange={e => setForm(f => ({ ...f, headers: e.target.value }))} rows={3} placeholder='{"Authorization": "Bearer ..."}' className={`${inputCls} resize-none font-mono`} />
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-sm text-content-secondary mb-1">命令</label>
                    <input value={form.command} onChange={e => setForm(f => ({ ...f, command: e.target.value }))} placeholder="npx" className={inputCls} />
                  </div>
                  <div>
                    <label className="block text-sm text-content-secondary mb-1">参数（每行一个）</label>
                    <textarea value={form.args} onChange={e => setForm(f => ({ ...f, args: e.target.value }))} rows={3} placeholder={"-y\n@modelcontextprotocol/server-xxx"} className={`${inputCls} resize-none font-mono`} />
                  </div>
                  <div>
                    <label className="block text-sm text-content-secondary mb-1">环境变量 (JSON)</label>
                    <textarea value={form.env} onChange={e => setForm(f => ({ ...f, env: e.target.value }))} rows={3} placeholder='{"API_KEY": "..."}' className={`${inputCls} resize-none font-mono`} />
                  </div>
                </>
              )}

              <label className="flex items-center gap-2 text-sm text-content-secondary cursor-pointer">
                <input type="checkbox" checked={form.enabled} onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))} className="rounded" />
                启用插件
              </label>
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}
