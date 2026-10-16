/** 设置页「记忆检索」：向量模型状态（GET /api/settings/embedding） */

export interface EmbeddingModelItem {
  id: string;
  label: string;
  size_label: string;
  description: string;
  language: string;
  recommended: boolean;
  /** 预设模型可在线下载；false = 手动放进 embedding 目录的本地模型 */
  preset: boolean;
  installed: boolean;
  active: boolean;
}

export interface EmbeddingStatus {
  /** 有向量模型在用（false = 召回只按人物 / 关键词匹配） */
  available: boolean;
  active_model: string | null;
  dimension: number | null;
  /** 一次最多读的 token 数 */
  max_tokens: number | null;
  selected_model: string | null;
  /** 环境变量 / .env 的 EMBEDDING_MODEL：指定了就以它为准，设置页只读 */
  env_model: string | null;
  env_locked: boolean;
  /** 管理员才能下载 / 切换（全站共用一份模型） */
  can_manage: boolean;
  downloading: boolean;
  download_job_id: string | null;
  embedding_dir: string;
  models: EmbeddingModelItem[];
}

export interface EmbeddingDownloadResult {
  model: string;
  activated: boolean;
  rebuild_job_id?: string | null;
}
