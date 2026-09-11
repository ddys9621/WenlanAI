"""世界规则服务 - 为生成流程提供世界观规则支持"""
import hashlib
import uuid
from typing import List, Optional, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.world_rule import WorldRule
from app.models.project import Project
from app.logger import get_logger
from app.services.ai_service import ai_service
from app.services.embedding_runtime import get_chroma_client, get_embedding_model
from app.services.generation_trace import trace_reference

logger = get_logger(__name__)


class WorldRuleService:
    """世界规则服务类 - 支持向量检索"""

    _instance = None
    _initialized = False

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """接入共享的 ChromaDB 客户端与 Embedding 模型（见 embedding_runtime，与 MemoryService 同一份）"""
        if self._initialized:
            return

        try:
            self.client = get_chroma_client()
            self.embedding_model = get_embedding_model()
            if self.embedding_model is None:
                raise RuntimeError("Embedding 模型不可用")

            self._initialized = True

        except Exception as e:
            logger.error(f"❌ WorldRuleService 初始化失败: {str(e)}")
            # 降级：不使用向量检索
            self.client = None
            self.embedding_model = None
            self._initialized = True

    def _get_collection_name(self, project_id: str) -> str:
        """生成项目专属的 collection 名称"""
        project_hash = hashlib.sha256(project_id.encode()).hexdigest()[:8]
        return f"world_rules_p_{project_hash}"

    def _get_or_create_collection(self, project_id: str):
        """获取或创建项目的世界规则 collection"""
        if not self.client:
            return None

        collection_name = self._get_collection_name(project_id)
        try:
            return self.client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "project_id": project_id,
                    "type": "world_rules"
                }
            )
        except Exception as e:
            logger.error(f"❌ 获取 world_rules collection 失败: {str(e)}")
            return None

    @staticmethod
    async def get_rules_by_project(
        db: AsyncSession,
        project_id: str,
        category: Optional[str] = None
    ) -> List[WorldRule]:
        """
        获取指定项目的世界规则列表
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            category: 可选的分类过滤（cultivation_realm/equipment_template）
            
        Returns:
            世界规则列表，按 order_index 排序
        """
        conditions = [WorldRule.project_id == project_id]
        if category:
            conditions.append(WorldRule.category == category)
        
        result = await db.execute(
            select(WorldRule)
            .where(and_(*conditions))
            .order_by(WorldRule.order_index.asc(), WorldRule.created_at.asc())
        )
        return result.scalars().all()

    @staticmethod
    async def generate_rules_summary_text(
        db: AsyncSession,
        project_id: str,
        category: Optional[str] = None
    ) -> str:
        """
        生成世界规则摘要文本（用于 prompt 中段）
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            category: 可选的分类过滤
            
        Returns:
            格式化的规则摘要文本
        """
        rules = await WorldRuleService.get_rules_by_project(db, project_id, category)
        
        if not rules:
            return ""
        
        # 按分类分组
        rules_by_category: Dict[str, List[WorldRule]] = {}
        for rule in rules:
            if rule.category not in rules_by_category:
                rules_by_category[rule.category] = []
            rules_by_category[rule.category].append(rule)
        
        parts = []

        # 能力/地位体系
        if "cultivation_realm" in rules_by_category:
            realm_lines = ["### 能力/地位体系"]
            for rule in rules_by_category["cultivation_realm"]:
                realm_lines.append(f"- **{rule.name}**（{rule.key}）：{rule.summary or '暂无描述'}")
            parts.append("\n".join(realm_lines))

        # 资源/载体系统
        if "equipment_template" in rules_by_category:
            equip_lines = ["### 资源/载体系统"]
            for rule in rules_by_category["equipment_template"]:
                equip_lines.append(f"- **{rule.name}**（{rule.key}）：{rule.summary or '暂无描述'}")
            parts.append("\n".join(equip_lines))

        # 地图/地点系统
        if "map_location" in rules_by_category:
            map_lines = ["### 地图/地点系统"]
            for rule in rules_by_category["map_location"]:
                map_lines.append(f"- **{rule.name}**（{rule.key}）：{rule.summary or '暂无描述'}")
            parts.append("\n".join(map_lines))

        if not parts:
            return ""

        return "## 世界规则明细\n\n" + "\n\n".join(parts)

    @staticmethod
    def format_rule_for_prompt(rule: WorldRule) -> str:
        """
        将单条规则格式化为适合 prompt 的文本

        Args:
            rule: 世界规则对象

        Returns:
            格式化的规则文本
        """
        text = f"**{rule.name}**（{rule.key}）"
        if rule.summary:
            text += f"：{rule.summary}"
        if rule.details:
            text += f"\n详细设定：{rule.details}"
        return text

    async def upsert_rule_to_vector_db(
        self,
        rule: WorldRule
    ) -> bool:
        """
        将世界规则添加或更新到向量数据库

        Args:
            rule: 世界规则对象

        Returns:
            是否成功
        """
        if not self.client or not self.embedding_model:
            logger.warning("⚠️ 向量数据库未初始化，跳过规则向量化")
            return False

        try:
            collection = self._get_or_create_collection(rule.project_id)
            if not collection:
                return False

            # 构建完整的文本描述（用于向量化）
            text_parts = [
                f"分类：{rule.category}",
                f"名称：{rule.name}",
                f"标识：{rule.key}"
            ]
            if rule.summary:
                text_parts.append(f"简介：{rule.summary}")
            if rule.details:
                text_parts.append(f"详细设定：{rule.details}")

            full_text = "\n".join(text_parts)

            # 生成 embedding
            embedding = self.embedding_model.encode(full_text).tolist()

            # 添加到 ChromaDB
            collection.upsert(
                ids=[rule.id],
                embeddings=[embedding],
                documents=[full_text],
                metadatas=[{
                    "rule_id": rule.id,
                    "project_id": rule.project_id,
                    "category": rule.category,
                    "key": rule.key,
                    "name": rule.name,
                    "order_index": rule.order_index
                }]
            )

            logger.info(f"✅ 规则已向量化: {rule.name} ({rule.key})")
            return True

        except Exception as e:
            logger.error(f"❌ 规则向量化失败: {str(e)}")
            return False

    async def delete_rule_from_vector_db(
        self,
        project_id: str,
        rule_id: str
    ) -> bool:
        """
        从向量数据库中删除规则

        Args:
            project_id: 项目ID
            rule_id: 规则ID

        Returns:
            是否成功
        """
        if not self.client:
            return False

        try:
            collection = self._get_or_create_collection(project_id)
            if not collection:
                return False

            collection.delete(ids=[rule_id])
            logger.info(f"✅ 规则已从向量库删除: {rule_id}")
            return True

        except Exception as e:
            logger.error(f"❌ 删除规则向量失败: {str(e)}")
            return False

    async def search_relevant_rules(
        self,
        db: AsyncSession,
        project_id: str,
        query: str,
        limit: int = 5,
        category: Optional[str] = None
    ) -> List[WorldRule]:
        """
        根据查询文本语义检索最相关的世界规则

        Args:
            db: 数据库会话
            project_id: 项目ID
            query: 查询文本（例如：当前章节大纲、剧情描述）
            limit: 返回数量，默认 5
            category: 可选的分类过滤

        Returns:
            相关的世界规则列表
        """
        if not self.client or not self.embedding_model:
            logger.warning("⚠️ 向量检索不可用，降级为返回所有规则")
            return await self.get_rules_by_project(db, project_id, category)

        try:
            collection = self._get_or_create_collection(project_id)
            if not collection:
                return await self.get_rules_by_project(db, project_id, category)

            # 生成查询 embedding
            query_embedding = self.embedding_model.encode(query).tolist()

            # 构建过滤条件
            where_filter = None
            if category:
                where_filter = {"category": category}

            # 向量检索
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_filter
            )

            if not results or not results['ids'] or not results['ids'][0]:
                logger.info(f"📭 未找到相关规则，返回默认规则")
                return await self.get_rules_by_project(db, project_id, category)

            # 获取规则 ID 列表
            rule_ids = results['ids'][0]

            # 从数据库查询完整的规则对象
            stmt = select(WorldRule).where(
                and_(
                    WorldRule.project_id == project_id,
                    WorldRule.id.in_(rule_ids)
                )
            ).order_by(WorldRule.order_index)

            result = await db.execute(stmt)
            rules = result.scalars().all()

            logger.info(f"🔍 向量检索到 {len(rules)} 条相关规则")
            return list(rules)

        except Exception as e:
            logger.error(f"❌ 向量检索失败: {str(e)}，降级为返回所有规则")
            return await self.get_rules_by_project(db, project_id, category)

    async def generate_rules_summary_with_search(
        self,
        db: AsyncSession,
        project_id: str,
        query: str,
        limit: int = 5
    ) -> str:
        """
        基于语义检索生成世界规则摘要（智能版）

        Args:
            db: 数据库会话
            project_id: 项目ID
            query: 查询文本（当前剧情描述）
            limit: 检索数量

        Returns:
            格式化的规则摘要文本
        """
        # 使用向量检索获取最相关的规则
        rules = await self.search_relevant_rules(db, project_id, query, limit)

        if not rules:
            return ""

        # 按分类分组
        categories = {}
        for rule in rules:
            if rule.category not in categories:
                categories[rule.category] = []
            categories[rule.category].append(rule)

        # 格式化输出
        parts = ["## 🌟 相关世界规则（智能检索）\n"]

        category_names = {
            "cultivation_realm": "能力/地位体系",
            "equipment_template": "资源/载体系统",
            "map_location": "地图/地点系统"
        }

        for category, category_rules in categories.items():
            category_name = category_names.get(category, category)
            parts.append(f"### {category_name}")

            for idx, rule in enumerate(category_rules, 1):
                parts.append(f"{idx}. {WorldRuleService.format_rule_for_prompt(rule)}")

            parts.append("")  # 空行分隔

        trace_reference(
            "world_rules",
            "世界规则（语义检索）",
            [{"title": rule.name, "detail": category_names.get(rule.category, rule.category)} for rule in rules],
            query=query[:80],
        )
        return "\n".join(parts)

    async def generate_initial_rules_for_project(
        self,
        db: AsyncSession,
        project: Project,
        user_ai_service = None
    ) -> List[WorldRule]:
        """
        为项目自动生成初始世界规则（仅在规则为空时执行）

        Args:
            db: 数据库会话
            project: 项目对象

        Returns:
            生成的世界规则列表
        """
        # 1. 检查是否已有规则
        existing_count = await db.execute(
            select(func.count(WorldRule.id)).where(WorldRule.project_id == project.id)
        )
        count = existing_count.scalar()

        if count > 0:
            logger.info(f"📋 项目 {project.id} 已有 {count} 条世界规则，跳过自动生成")
            # 返回现有规则
            result = await db.execute(
                select(WorldRule).where(WorldRule.project_id == project.id).order_by(WorldRule.order_index)
            )
            return list(result.scalars().all())

        logger.info(f"🎨 项目 {project.id} 无世界规则，开始自动生成...")

        # 2. 获取角色和组织信息（用于生成上下文）
        from app.models.character import Character

        characters_result = await db.execute(
            select(Character).where(
                Character.project_id == project.id,
                Character.is_organization == False
            ).limit(5)
        )
        characters = characters_result.scalars().all()

        organizations_result = await db.execute(
            select(Character).where(
                Character.project_id == project.id,
                Character.is_organization == True
            ).limit(3)
        )
        organizations = organizations_result.scalars().all()

        # 3. 构建生成 prompt
        prompt = self._build_initial_rules_prompt(project, characters, organizations)

        # 4. 调用大模型生成规则（流式 + 重试 + LLM 二次修复；max_tokens 取用户设置）
        try:
            # 使用用户配置的 AIService (如果提供) 或全局默认 AIService
            active_ai_service = user_ai_service if user_ai_service is not None else ai_service

            max_retries = 3
            last_error = None
            response_text = ""  # 保留到循环外，供二次修复兜底使用
            rules_data = None

            from app.utils.json_cleaner import clean_and_parse_json, repair_json_with_llm

            for attempt in range(max_retries):
                try:
                    logger.info(
                        f"🔵 开始第 {attempt + 1}/{max_retries} 次世界规则生成调用（流式）"
                    )

                    # 低 temperature 提高 JSON 结构合规性
                    response_text = ""
                    async for chunk in active_ai_service.generate_text_stream(
                        prompt=prompt,
                        provider=None,  # 使用用户配置的默认provider
                        model=None,     # 使用用户配置的默认model
                        temperature=0.3,
                    ):
                        response_text += chunk

                    # 5. 使用统一的 JSON 清理工具解析返回结果
                    rules_data = clean_and_parse_json(
                        response_text,
                        expected_type='object',
                        log_prefix=f"[世界规则生成-第{attempt + 1}次]",
                    )
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"⚠️ 第 {attempt + 1}/{max_retries} 次世界规则生成失败: {e}"
                    )

            # 6. 本地重试全部失败 → LLM 二次格式修复兜底（对齐 wizard_stream 主世界观流程）
            if rules_data is None and response_text:
                try:
                    logger.info("[世界规则生成] 进入 LLM 二次格式修复兜底")
                    rules_data = await repair_json_with_llm(
                        response_text,
                        user_ai_service=active_ai_service,
                        expected_type='object',
                        provider=None,
                        model=None,
                        schema_hint="cultivation_realm, equipment_template, map_location",
                        log_prefix="[世界规则生成]",
                    )
                    logger.info("[世界规则生成] LLM 二次格式修复成功")
                except Exception as repair_err:
                    logger.error(
                        f"[世界规则生成] LLM 二次格式修复仍失败: {repair_err}"
                    )

            if rules_data is None:
                # 所有重试 + 二次修复均失败，抛出最后一次错误
                raise last_error or Exception("世界规则生成多次重试仍失败")

            # 6. 批量创建规则
            created_rules = []

            # 处理境界体系
            for rule_data in rules_data.get("cultivation_realm", []):
                rule = WorldRule(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    category="cultivation_realm",
                    key=rule_data["key"],
                    name=rule_data["name"],
                    order_index=rule_data.get("order_index", 0),
                    summary=rule_data.get("summary", ""),
                    details=rule_data.get("details", "")
                )
                db.add(rule)
                created_rules.append(rule)

            # 处理装备系统
            for rule_data in rules_data.get("equipment_template", []):
                rule = WorldRule(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    category="equipment_template",
                    key=rule_data["key"],
                    name=rule_data["name"],
                    order_index=rule_data.get("order_index", 0),
                    summary=rule_data.get("summary", ""),
                    details=rule_data.get("details", "")
                )
                db.add(rule)
                created_rules.append(rule)

            # 处理地图/地点系统
            for rule_data in rules_data.get("map_location", []):
                rule = WorldRule(
                    id=str(uuid.uuid4()),
                    project_id=project.id,
                    category="map_location",
                    key=rule_data["key"],
                    name=rule_data["name"],
                    order_index=rule_data.get("order_index", 0),
                    summary=rule_data.get("summary", ""),
                    details=rule_data.get("details", "")
                )
                db.add(rule)
                created_rules.append(rule)

            # 注意: 不在这里commit，让调用者控制事务
            # 调用者会在整个向导流程结束后统一commit

            # 7. 向量化所有规则 (延迟到commit后执行，这里先跳过)
            # 向量化需要在规则持久化后进行，由调用者在commit后手动调用
            # for rule in created_rules:
            #     try:
            #         await self.upsert_rule_to_vector_db(rule)
            #     except Exception as e:
            #         logger.warning(f"⚠️ 规则向量化失败: {rule.name} - {str(e)}")

            logger.info(f"✅ 成功为项目 {project.id} 生成 {len(created_rules)} 条世界规则 (待commit)")
            return created_rules

        except Exception as e:
            logger.error(f"❌ 自动生成世界规则失败: {str(e)}")
            # 不在这里rollback，让调用者决定事务处理
            # 只返回空列表，表示生成失败但不影响外层事务
            return []

    def _build_initial_rules_prompt(
        self,
        project: Project,
        characters: List,
        organizations: List
    ) -> str:
        """构建初始规则生成的 prompt - 根据题材自适应"""

        # 角色信息
        char_info = ""
        if characters:
            char_list = []
            for char in characters[:5]:
                char_list.append(f"- {char.name}（{char.role_type or '角色'}）：{char.personality or '待定'}")
            char_info = "\n".join(char_list)

        # 组织信息
        org_info = ""
        if organizations:
            org_list = []
            for org in organizations[:3]:
                org_list.append(f"- {org.name}（{org.organization_type or '组织'}）")
            org_info = "\n".join(org_list)

        # 【新增】题材判断 - 决定使用哪套规则描述
        genre = (project.genre or "").lower()

        # 玄幻/仙侠/奇幻类关键词
        FANTASY_KEYWORDS = ["玄幻", "仙侠", "修真", "异世界", "西幻", "魔法", "奇幻", "武侠", "仙", "修仙"]
        # 现代/现实类关键词
        MODERN_KEYWORDS = ["现代", "都市", "现实", "职场", "言情", "校园", "青春", "悬疑", "推理", "科幻"]

        is_fantasy = any(k in genre for k in FANTASY_KEYWORDS)
        is_modern = any(k in genre for k in MODERN_KEYWORDS) and not is_fantasy

        # 根据题材选择不同的任务描述
        if is_fantasy:
            # 玄幻/仙侠题材 - 使用修炼境界 + 装备系统
            task_description = self._get_fantasy_task_description()
            examples = self._get_fantasy_examples()
        elif is_modern:
            # 现代/现实题材 - 使用地位层级 + 资源系统
            task_description = self._get_modern_task_description()
            examples = self._get_modern_examples()
        else:
            # 通用题材 - 使用中性描述
            task_description = self._get_generic_task_description()
            examples = self._get_generic_examples()

        # 构建完整 prompt
        prompt = f"""你是一位资深的小说世界观设计师。请为以下小说项目设计一套完整的世界规则体系。

## 项目信息

**作品名称**：{project.title}
**题材类型**：{project.genre or '通用'}
**核心主题**：{project.theme or '未设定'}
**世界时代**：{project.world_time_period or '未设定'}
**世界地域**：{project.world_location or '未设定'}
**世界氛围**：{project.world_atmosphere or '未设定'}

**世界规则概述**：
{project.world_rules or '未设定'}

**主要角色**：
{char_info or '暂无'}

**重要组织/势力**：
{org_info or '暂无'}

---

{task_description}

---

## 输出格式（严格 JSON）

{examples}

**注意**：
- key 必须是小写字母+下划线，方便代码使用
- order_index 从 1 开始递增
- summary 控制在 1-2 句话
- details 可以详细一些，包含具体数值、典型特征、在剧情中的作用等

请直接输出 JSON，不要有其他解释文字。"""

        return prompt

    def _get_fantasy_task_description(self) -> str:
        """玄幻/仙侠题材的任务描述"""
        return """## 任务要求

请根据上述信息，设计：

1. **能力&境界体系**（cultivation_realm）：
   - 适合该题材的修炼/力量等级系统
   - 建议 5-9 个等级，从低到高递进
   - 每个境界包含：名称、简介、详细设定（寿元、战力范围、突破条件、典型特征等）
   - 要能体现"实力差距"和"成长路径"

2. **装备&资源系统**（equipment_template）：
   - 适合该世界观的装备/道具/资源分类
   - 建议 3-6 个类别（如：法器、丹药、功法、灵石等）
   - 每个类别包含：名称、简介、详细设定（品质划分、获取方式、作用、稀有度等）
   - 要能驱动剧情冲突（争夺、交易、炼制等）

3. **地图&地点系统**（map_location）：
   - 故事中的重要地点和区域
   - 建议 3-8 个地点（如：宗门、秘境、城池、险地等）
   - 每个地点包含：名称、简介、详细设定（地理位置、势力归属、危险等级、特殊资源、与其他地点的关系等）
   - 要能为剧情提供空间框架和地理约束"""

    def _get_modern_task_description(self) -> str:
        """现代/现实题材的任务描述"""
        return """## 任务要求

请根据上述信息，设计：

1. **地位&实力层级体系**（cultivation_realm）：
   - 适合现代题材的社会地位/职业等级/权力层级系统
   - 建议 5-9 个等级，从低到高递进
   - 例如：学生→班干部→学生会→校领导 / 实习生→员工→主管→经理→总监→高管
   - 每个层级包含：名称、简介、详细设定（典型权力、资源掌控、行为边界、常见冲突等）
   - **禁止**：不要设计修仙、斗气、魔法等超自然修炼体系（除非题材明确是都市异能）

2. **资源&规则系统**（equipment_template）：
   - 适合现代世界观的核心资源/关键道具分类
   - 建议 3-6 个类别（如：金钱/资本、信息/情报、人脉/关系、技术/专利、舆论/流量等）
   - 每个类别包含：名称、简介、详细设定（获取难度、持有者类型、在故事中的作用、典型冲突方式等）
   - 要能驱动现实向剧情（竞争、交易、博弈、制约等）

3. **地图&地点系统**（map_location）：
   - 故事中的重要地点和场所
   - 建议 3-8 个地点（如：公司总部、学校、住宅区、商业中心、关键场所等）
   - 每个地点包含：名称、简介、详细设定（地理位置、功能用途、常驻人群、安全等级、与其他地点的关系等）
   - 要能为现代剧情提供空间框架（通勤距离、社交圈层、冲突场景等）"""

    def _get_generic_task_description(self) -> str:
        """通用题材的任务描述"""
        return """## 任务要求

请根据上述信息，设计：

1. **能力&地位体系**（cultivation_realm）：
   - 适合该题材的实力/地位/等级系统
   - 建议 5-9 个等级，从低到高递进
   - 每个等级包含：名称、简介、详细设定（典型能力、权力范围、限制条件、常见特征等）
   - 要能体现"层级差异"和"成长/晋升路径"

2. **资源&载体系统**（equipment_template）：
   - 适合该世界观的核心资源/关键道具分类
   - 建议 3-6 个类别
   - 每个类别包含：名称、简介、详细设定（获取方式、作用、稀有度、在剧情中的价值等）
   - 要能驱动剧情冲突和角色动机

3. **地图&地点系统**（map_location）：
   - 故事中的重要地点和区域
   - 建议 3-8 个地点
   - 每个地点包含：名称、简介、详细设定（地理位置、功能特点、重要性、与其他地点的关系等）
   - 要能为剧情提供空间框架"""

    def _get_fantasy_examples(self) -> str:
        """玄幻题材的 JSON 示例"""
        return """```json
{
  "cultivation_realm": [
    {
      "key": "qi_refining",
      "name": "炼气期",
      "order_index": 1,
      "summary": "修炼入门阶段，初步感应天地灵气",
      "details": "寿元：100-150年。战力：可对抗数名凡人。修炼特点：需筑基丹辅助突破。典型代表：外门弟子。"
    },
    {
      "key": "foundation_establishment",
      "name": "筑基期",
      "order_index": 2,
      "summary": "筑基成功，灵力凝实，可御器飞行",
      "details": "寿元：200-300年。战力：可毁灭小型建筑。修炼特点：需天材地宝辅助。典型代表：内门弟子、小宗门长老。"
    }
  ],
  "equipment_template": [
    {
      "key": "magic_weapon",
      "name": "法器",
      "order_index": 1,
      "summary": "修士使用的灵力武器",
      "details": "品质划分：下品/中品/上品/极品。获取方式：炼制、宗门奖励、击杀夺取。作用：增强战力、辅助修炼。稀有度：上品以上极为罕见。"
    },
    {
      "key": "elixir",
      "name": "丹药",
      "order_index": 2,
      "summary": "辅助修炼和疗伤的灵丹",
      "details": "品质划分：一品到九品。获取方式：炼丹、宗门兑换、拍卖行购买。作用：加速修炼、突破瓶颈、疗伤解毒。稀有度：高品丹药需要炼丹大师。"
    }
  ],
  "map_location": [
    {
      "key": "sect_mountain",
      "name": "天元宗山门",
      "order_index": 1,
      "summary": "主角所在宗门，位于灵脉之上",
      "details": "地理位置：东域中心，昆仑山脉支脉。势力归属：天元宗（正道大宗）。危险等级：外门安全，禁地危险。特殊资源：灵脉、藏经阁、炼丹房。与其他地点关系：距离天元城100里，距离魔域3000里。"
    },
    {
      "key": "forbidden_forest",
      "name": "迷雾森林",
      "order_index": 2,
      "summary": "危险秘境，盛产天材地宝",
      "details": "地理位置：宗门后山，常年迷雾笼罩。势力归属：无主之地，妖兽盘踞。危险等级：极高（筑基以下必死）。特殊资源：千年灵药、妖兽内丹。剧情作用：试炼场所、寻宝冒险。"
    }
  ]
}
```"""

    def _get_modern_examples(self) -> str:
        """现代题材的 JSON 示例"""
        return """```json
{
  "cultivation_realm": [
    {
      "key": "intern",
      "name": "实习生",
      "order_index": 1,
      "summary": "职场新人，处于学习和试用阶段",
      "details": "典型权力：无决策权，只能执行任务。资源掌控：基本工资，无项目资源。行为边界：需要导师指导，不能独立对外。常见冲突：转正竞争、导师压榨。"
    },
    {
      "key": "manager",
      "name": "部门经理",
      "order_index": 3,
      "summary": "中层管理者，掌握一定资源和决策权",
      "details": "典型权力：部门预算审批、人员招聘建议权。资源掌控：部门预算、团队人力。行为边界：需向总监汇报，跨部门协作需审批。常见冲突：部门利益争夺、晋升竞争。"
    }
  ],
  "equipment_template": [
    {
      "key": "capital",
      "name": "资本/资金",
      "order_index": 1,
      "summary": "现代社会最核心的资源",
      "details": "获取难度：融资、贷款、投资回报。持有者类型：企业家、投资人、高管。在故事中的作用：启动项目、收购公司、贿赂关键人物。典型冲突：融资竞争、资金链断裂。"
    },
    {
      "key": "information",
      "name": "信息/情报",
      "order_index": 2,
      "summary": "关键商业情报或机密信息",
      "details": "获取难度：商业间谍、内部人士、黑客攻击。持有者类型：记者、侦探、竞争对手。在故事中的作用：揭露丑闻、抢占先机、要挟谈判。典型冲突：信息泄露、反间谍。"
    }
  ],
  "map_location": [
    {
      "key": "company_hq",
      "name": "星辰科技总部",
      "order_index": 1,
      "summary": "主角工作的科技公司总部大楼",
      "details": "地理位置：市中心CBD核心区，地铁2号线直达。功能用途：办公、会议、研发中心。常驻人群：3000+员工，高管层在顶楼。安全等级：门禁森严，核心区域需权限卡。剧情作用：日常工作场景、办公室政治、重要会议。"
    },
    {
      "key": "luxury_apartment",
      "name": "江景豪宅区",
      "order_index": 2,
      "summary": "高端住宅区，上流社会聚集地",
      "details": "地理位置：滨江路，距离公司总部20分钟车程。功能用途：居住、社交、私密会面。常驻人群：企业家、高管、名流。安全等级：私人保安，访客需登记。剧情作用：展现阶层差距、社交场合、秘密交易。与其他地点关系：与公司总部形成'工作-生活'对比。"
    }
  ]
}
```"""

    def _get_generic_examples(self) -> str:
        """通用题材的 JSON 示例"""
        return """```json
{
  "cultivation_realm": [
    {
      "key": "level_1",
      "name": "初级",
      "order_index": 1,
      "summary": "起始阶段，能力有限",
      "details": "典型能力：基础技能。权力范围：个人行动。限制条件：需要指导和资源支持。常见特征：成长空间大，容易受挫。"
    },
    {
      "key": "level_2",
      "name": "中级",
      "order_index": 2,
      "summary": "进阶阶段，具备一定实力",
      "details": "典型能力：独立完成任务。权力范围：小范围影响力。限制条件：仍需上级批准重大决策。常见特征：开始承担责任。"
    }
  ],
  "equipment_template": [
    {
      "key": "resource_1",
      "name": "核心资源A",
      "order_index": 1,
      "summary": "世界中的关键资源",
      "details": "获取方式：任务奖励、交易、争夺。作用：提升能力、解锁权限。稀有度：中等。在剧情中的价值：推动角色成长和冲突。"
    }
  ],
  "map_location": [
    {
      "key": "main_city",
      "name": "中心城市",
      "order_index": 1,
      "summary": "故事主要发生地",
      "details": "地理位置：世界中心区域。功能特点：政治、经济、文化中心。重要性：大部分角色活动范围。与其他地点关系：连接各个区域的枢纽。"
    }
  ]
}
```"""


# 创建全局实例
world_rule_service = WorldRuleService()

