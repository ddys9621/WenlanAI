"""向量记忆服务 - 基于ChromaDB实现长期记忆和语义检索"""
import hashlib
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.logger import get_logger
from app.services.embedding_runtime import EMBEDDING_PATH, collection_suffix, get_chroma_client, get_embedding_model

logger = get_logger(__name__)


def collection_name_for(user_id: str, project_id: str) -> str:
    """u_{user_hash}_p_{project_hash}[_e{模型指纹}]：SHA256 压缩到 63 字符内；自定义向量模型另起集合（维度不同不能混存）。"""
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()[:8]
    project_hash = hashlib.sha256(project_id.encode()).hexdigest()[:8]
    return f"u_{user_hash}_p_{project_hash}{collection_suffix()}"


class MemoryService:
    """向量记忆管理服务 - 实现语义检索和长期记忆"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """接入共享的 ChromaDB 客户端与 Embedding 模型（见 embedding_runtime）"""
        if self._initialized:
            return
            
        try:
            self.client = get_chroma_client()
            self.embedding_model = get_embedding_model()
            if self.embedding_model is None:
                raise RuntimeError("无法加载任何Embedding模型")
            
            self._initialized = True
            logger.info("✅ MemoryService初始化成功")
            
        except Exception as e:
            # 降级而非崩溃：缺模型/向量库故障时应用仍可启动，
            # 仅向量记忆相关功能不可用（各公共方法有 try/except 空值兜底）
            logger.error(f"❌ MemoryService初始化失败: {str(e)}")
            logger.error("⚠️ 应用将以「无向量记忆」模式运行：语义检索/伏笔追踪/记忆增强上下文不可用")
            logger.error(f"💡 修复方式：把 embedding 模型放入 {EMBEDDING_PATH} 后重启（桌面版启动器会尝试自动下载）")
            self.client = None
            self.embedding_model = None
            self._initialized = True
    
    def get_collection(self, user_id: str, project_id: str):
        """
        获取或创建项目的记忆集合
        
        每个用户的每个项目有独立的collection,实现数据隔离
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
        
        Returns:
            ChromaDB Collection对象
        """
        # ChromaDB collection命名规则：
        # 1. 3-63字符（最重要！）
        # 2. 开头和结尾必须是字母或数字
        # 3. 只能包含字母、数字、下划线或短横线
        # 4. 不能包含连续的点(..)
        # 5. 不能是有效的IPv4地址
        
        # 降级守卫：初始化失败（缺模型等）时给出清晰错误，
        # 调用方各方法的 try/except 会将其转为空结果
        if self.client is None or self.embedding_model is None:
            raise RuntimeError(
                "向量记忆服务不可用（embedding 模型未加载），相关功能已降级"
            )

        # 使用SHA256哈希压缩ID长度，确保不超过63字符
        # 格式: u_{user_hash}_p_{project_hash} (约30字符)
        collection_name = collection_name_for(user_id, project_id)
        
        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "user_id": user_id,
                    "project_id": project_id,
                    "created_at": datetime.now().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"❌ 获取collection失败: {str(e)}")
            raise

    async def batch_add_memories(
        self,
        user_id: str,
        project_id: str,
        memories: List[Dict[str, Any]]
    ) -> int:
        """
        批量添加记忆(性能更好)
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            memories: 记忆列表,每个包含id、content、type、metadata
        
        Returns:
            成功添加的数量
        """
        if not memories:
            return 0
            
        try:
            collection = self.get_collection(user_id, project_id)
            
            ids = []
            documents = []
            metadatas = []
            embeddings = []
            
            # 批量准备数据
            for mem in memories:
                ids.append(mem['id'])
                documents.append(mem['content'])
                
                # 生成embedding
                embedding = self.embedding_model.encode(mem['content']).tolist()
                embeddings.append(embedding)
                
                # 准备元数据
                metadata = mem.get('metadata', {})
                chroma_metadata = {
                    "memory_type": mem['type'],
                    "chapter_id": str(metadata.get("chapter_id", "")),
                    "chapter_number": int(metadata.get("chapter_number", 0)),
                    "importance": float(metadata.get("importance_score", 0.5)),
                    "tags": json.dumps(metadata.get("tags", []), ensure_ascii=False),
                    "title": str(metadata.get("title", ""))[:200],
                    "is_foreshadow": int(metadata.get("is_foreshadow", 0)),
                    "created_at": datetime.now().isoformat()
                }
                metadatas.append(chroma_metadata)
            
            # upsert 而不是 add：Chroma 的 add 遇到已存在 id 会静默忽略，重新分析的章节会一直留着旧内容
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            
            logger.info(f"✅ 批量添加记忆成功: {len(memories)}条")
            return len(memories)
            
        except Exception as e:
            logger.error(f"❌ 批量添加记忆失败: {str(e)}")
            return 0
    
    async def search_memories(
        self,
        user_id: str,
        project_id: str,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10,
        min_importance: float = 0.0,
        chapter_range: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        """
        语义搜索相关记忆
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            query: 查询文本(会被转换为向量进行相似度搜索)
            memory_types: 过滤特定类型的记忆
            limit: 返回结果数量
            min_importance: 最低重要性阈值
            chapter_range: 章节范围 (start, end)
        
        Returns:
            相关记忆列表,按相似度排序
        """
        try:
            collection = self.get_collection(user_id, project_id)
            
            # 生成查询向量
            query_embedding = self.embedding_model.encode(query).tolist()
            
            # 构建过滤条件 - ChromaDB要求使用$and组合多个条件
            where_filter = None
            conditions = []
            
            if memory_types:
                conditions.append({"memory_type": {"$in": memory_types}})
            if min_importance > 0:
                conditions.append({"importance": {"$gte": min_importance}})
            if chapter_range:
                conditions.append({"chapter_number": {"$gte": chapter_range[0]}})
                conditions.append({"chapter_number": {"$lte": chapter_range[1]}})
            
            # 根据条件数量选择合适的格式
            if len(conditions) == 0:
                where_filter = None
            elif len(conditions) == 1:
                where_filter = conditions[0]
            else:
                where_filter = {"$and": conditions}
            
            # 执行向量相似度搜索
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_filter
            )
            
            # 格式化结果
            memories = []
            if results['ids'] and results['ids'][0]:
                for i in range(len(results['ids'][0])):
                    memories.append({
                        "id": results['ids'][0][i],
                        "content": results['documents'][0][i],
                        "metadata": results['metadatas'][0][i],
                        "similarity": 1 - results['distances'][0][i] if 'distances' in results else 1.0,
                        "distance": results['distances'][0][i] if 'distances' in results else 0.0
                    })
            
            logger.info(f"🔍 语义搜索完成: 查询='{query[:30]}...', 找到{len(memories)}条记忆")
            return memories
            
        except Exception as e:
            logger.error(f"❌ 搜索记忆失败: {str(e)}")
            return []
    
    async def get_recent_memories(
        self,
        user_id: str,
        project_id: str,
        current_chapter: int,
        recent_count: int = 3,
        min_importance: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        获取最近几章的重要记忆(用于保持连贯性)
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            current_chapter: 当前章节号
            recent_count: 获取最近几章
            min_importance: 最低重要性阈值
        
        Returns:
            最近章节的记忆列表,按重要性排序
        """
        try:
            collection = self.get_collection(user_id, project_id)
            
            # 计算章节范围
            start_chapter = max(1, current_chapter - recent_count)
            
            # 获取最近章节的记忆
            results = collection.get(
                where={
                    "$and": [
                        {"chapter_number": {"$gte": start_chapter}},
                        {"chapter_number": {"$lt": current_chapter}},
                        {"importance": {"$gte": min_importance}}
                    ]
                },
                limit=100  # 先获取足够多的记忆
            )
            
            memories = []
            if results['ids']:
                for i in range(len(results['ids'])):
                    memories.append({
                        "id": results['ids'][i],
                        "content": results['documents'][i],
                        "metadata": results['metadatas'][i]
                    })
            
            # 按重要性和章节号排序
            memories.sort(
                key=lambda x: (float(x['metadata'].get('importance', 0)), 
                              int(x['metadata'].get('chapter_number', 0))),
                reverse=True
            )
            
            # 返回最重要的前N条
            top_memories = memories[:20]
            logger.info(f"📚 获取最近记忆: 章节{start_chapter}-{current_chapter-1}, 找到{len(top_memories)}条")
            return top_memories
            
        except Exception as e:
            logger.error(f"❌ 获取最近记忆失败: {str(e)}")
            return []
    
    async def find_unresolved_foreshadows(
        self,
        user_id: str,
        project_id: str,
        current_chapter: int
    ) -> List[Dict[str, Any]]:
        """
        查找未完结的伏笔
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            current_chapter: 当前章节号
        
        Returns:
            未完结伏笔列表
        """
        try:
            collection = self.get_collection(user_id, project_id)
            
            # 查找伏笔状态为1(已埋下但未回收)的记忆
            results = collection.get(
                where={
                    "$and": [
                        {"is_foreshadow": 1},
                        {"chapter_number": {"$lt": current_chapter}}
                    ]
                },
                limit=50
            )
            
            foreshadows = []
            if results['ids']:
                for i in range(len(results['ids'])):
                    foreshadows.append({
                        "id": results['ids'][i],
                        "content": results['documents'][i],
                        "metadata": results['metadatas'][i]
                    })
            
            # 按重要性排序
            foreshadows.sort(
                key=lambda x: float(x['metadata'].get('importance', 0)),
                reverse=True
            )
            
            logger.info(f"🎣 找到未完结伏笔: {len(foreshadows)}个")
            return foreshadows
            
        except Exception as e:
            logger.error(f"❌ 查找伏笔失败: {str(e)}")
            return []
    
    # 角色相关记忆只查本章出场的前几个人：几十个名字拼成一个查询，嵌入模型 128 token 一截断就成了噪音
    CHARACTER_QUERY_LIMIT = 4

    async def get_important_plot_points(
        self,
        user_id: str,
        project_id: str,
        before_chapter: int,
        limit: int = 5,
        min_importance: float = 0.8,
    ) -> List[Dict[str, Any]]:
        """本章之前最重要的情节点：按重要性降序、同分取更近的章（不靠语义检索，长篇里的"锚点事件"）。"""
        try:
            collection = self.get_collection(user_id, project_id)
            results = collection.get(
                where={
                    "$and": [
                        {"memory_type": {"$in": ["plot_point", "hook"]}},
                        {"importance": {"$gte": min_importance}},
                        {"chapter_number": {"$lte": before_chapter - 1}},
                    ]
                },
                limit=500,
            )
            items = [
                {"id": results["ids"][i], "content": results["documents"][i], "metadata": results["metadatas"][i]}
                for i in range(len(results.get("ids") or []))
            ]
            items.sort(
                key=lambda m: (
                    float(m["metadata"].get("importance", 0) or 0),
                    int(m["metadata"].get("chapter_number", 0) or 0),
                ),
                reverse=True,
            )
            return items[:limit]
        except Exception as e:
            logger.error(f"❌ 获取重要情节点失败: {str(e)}")
            return []

    async def build_context_for_generation(
        self,
        user_id: str,
        project_id: str,
        current_chapter: int,
        chapter_outline: str,
        character_names: List[str] = None,
        query_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        为章节生成构建向量记忆上下文（所有检索都限定在本章之前，重写中间章节时不会把"未来"漏进来）

        - relevant_memories：按本章查询语句做语义检索（不含章节摘要——摘要已由前情脉络 / 相关旧事覆盖）
        - character_states：本章出场的前几个角色各自的近事
        - plot_points：本章之前最重要的情节点（按重要性 + 时间）
        - recent_context / foreshadows：保留键位但置空——近期剧情已由最近章节摘要与全文覆盖，
          未回收伏笔以 DB 承诺表为唯一真相（向量库里的伏笔回收后不会更新状态）

        Args:
            user_id: 用户ID
            project_id: 项目ID
            current_chapter: 当前章节号
            chapter_outline: 本章大纲（未给 query_text 时用作检索语句）
            character_names: 本章涉及的角色名（按重要性排序，只取前 CHARACTER_QUERY_LIMIT 个）
            query_text: 精简检索语句（标题 + 关键事件 + 出场人物），优先于整段章纲
        """
        logger.info(f"🧠 开始构建章节{current_chapter}的向量记忆上下文...")
        chapter_range = (0, max(current_chapter - 1, 0))
        query = (query_text or chapter_outline or "").strip()[:300]

        relevant: List[Dict[str, Any]] = []
        if query:
            relevant = await self.search_memories(
                user_id=user_id,
                project_id=project_id,
                query=query,
                memory_types=["plot_point", "hook", "character_event", "foreshadow"],
                limit=8,
                min_importance=0.4,
                chapter_range=chapter_range,
            )

        character_memories: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        for name in [n for n in (character_names or []) if n][: self.CHARACTER_QUERY_LIMIT]:
            for mem in await self.search_memories(
                user_id=user_id,
                project_id=project_id,
                query=f"{name} 状态 处境",
                memory_types=["character_event"],
                limit=3,
                chapter_range=chapter_range,
            ):
                if mem["id"] not in seen_ids:
                    seen_ids.add(mem["id"])
                    character_memories.append(mem)

        plot_points = await self.get_important_plot_points(user_id, project_id, before_chapter=current_chapter)

        context = {
            "recent_context": "",
            "relevant_memories": self._format_memories(relevant, "语义相关记忆") if relevant else "",
            "character_states": self._format_memories(character_memories[:8], "角色近事") if character_memories else "",
            "foreshadows": "",
            "plot_points": self._format_memories(plot_points, "关键情节锚点") if plot_points else "",
            "stats": {
                "relevant_count": len(relevant),
                "character_count": len(character_memories),
                "plot_point_count": len(plot_points),
            }
        }

        logger.info(
            f"✅ 向量记忆上下文完成: 相关{len(relevant)}条, 角色近事{len(character_memories)}条, 锚点{len(plot_points)}条"
        )
        return context
    def _format_memories(self, memories: List[Dict], section_title: str = "记忆") -> str:
        """
        格式化记忆列表为文本
        
        Args:
            memories: 记忆列表
            section_title: 章节标题
        
        Returns:
            格式化后的文本
        """
        if not memories:
            return f"【{section_title}】\n暂无相关记忆\n"
        
        lines = [f"【{section_title}】"]
        for i, mem in enumerate(memories, 1):
            meta = mem.get('metadata', {})
            chapter_num = meta.get('chapter_number', '?')
            mem_type = meta.get('memory_type', '未知')
            importance = float(meta.get('importance', 0.5))
            title = meta.get('title', '')
            content = mem['content']
            
            # 格式: [序号] 第X章-类型(重要性) 标题: 内容
            line = f"{i}. [第{chapter_num}章-{mem_type}★{importance:.1f}]"
            if title:
                line += f" {title}: {content[:100]}"
            else:
                line += f" {content[:150]}"
            lines.append(line)
        
        return "\n".join(lines) + "\n"
    
    async def delete_chapter_memories(
        self,
        user_id: str,
        project_id: str,
        chapter_id: str
    ) -> bool:
        """
        删除指定章节的所有记忆
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
            chapter_id: 章节ID
        
        Returns:
            是否删除成功
        """
        try:
            collection = self.get_collection(user_id, project_id)
            
            # 查找该章节的所有记忆
            results = collection.get(
                where={"chapter_id": chapter_id}
            )
            
            if results['ids']:
                # 删除这些记忆
                collection.delete(ids=results['ids'])
                logger.info(f"🗑️ 已删除章节{chapter_id[:8]}的{len(results['ids'])}条记忆")
                return True
            else:
                logger.info(f"ℹ️ 章节{chapter_id[:8]}没有记忆需要删除")
                return True
                
        except Exception as e:
            logger.error(f"❌ 删除章节记忆失败: {str(e)}")
            return False
    
    async def delete_project_memories(
        self,
        user_id: str,
        project_id: str
    ) -> bool:
        """
        删除指定项目的所有记忆(包括向量数据库)
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
        
        Returns:
            是否删除成功
        """
        try:
            # 生成collection名称
            collection_name = collection_name_for(user_id, project_id)
            
            # 删除整个collection(这会清理所有向量数据)
            try:
                self.client.delete_collection(name=collection_name)
                logger.info(f"🗑️ 已删除项目{project_id[:8]}的向量数据库collection: {collection_name}")
                return True
            except Exception as e:
                # 如果collection不存在,也算成功
                if "does not exist" in str(e).lower():
                    logger.info(f"ℹ️ 项目{project_id[:8]}的collection不存在,无需删除")
                    return True
                else:
                    raise
                
        except Exception as e:
            logger.error(f"❌ 删除项目记忆失败: {str(e)}")
            return False

    async def get_memory_stats(
        self,
        user_id: str,
        project_id: str
    ) -> Dict[str, Any]:
        """
        获取记忆统计信息
        
        Args:
            user_id: 用户ID
            project_id: 项目ID
        
        Returns:
            统计信息字典
        """
        try:
            collection = self.get_collection(user_id, project_id)
            
            # 获取所有记忆
            all_memories = collection.get()
            
            if not all_memories['ids']:
                return {
                    "total_count": 0,
                    "by_type": {},
                    "by_chapter": {},
                    "foreshadow_count": 0
                }
            
            # 统计各类型数量
            type_counts = {}
            chapter_counts = {}
            foreshadow_count = 0
            
            for meta in all_memories['metadatas']:
                mem_type = meta.get('memory_type', 'unknown')
                chapter_num = meta.get('chapter_number', 0)
                is_foreshadow = meta.get('is_foreshadow', 0)
                
                type_counts[mem_type] = type_counts.get(mem_type, 0) + 1
                chapter_counts[str(chapter_num)] = chapter_counts.get(str(chapter_num), 0) + 1
                
                if is_foreshadow == 1:
                    foreshadow_count += 1
            
            stats = {
                "total_count": len(all_memories['ids']),
                "by_type": type_counts,
                "by_chapter": chapter_counts,
                "foreshadow_count": foreshadow_count,
                "foreshadow_resolved": sum(1 for m in all_memories['metadatas'] if m.get('is_foreshadow') == 2)
            }
            
            logger.info(f"📊 记忆统计: 总计{stats['total_count']}条, 伏笔{foreshadow_count}个")
            return stats
            
        except Exception as e:
            logger.error(f"❌ 获取统计信息失败: {str(e)}")
            return {"error": str(e)}


# 创建全局实例
memory_service = MemoryService()
            