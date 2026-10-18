/** 项目自定义提示词（GET/PUT/DELETE /projects/{id}/prompts）：只开放写作指导，输出格式与作品资料由系统自动拼接 */
export interface ProjectPromptVariable {
  name: string;
  label: string;
}

export interface ProjectPromptItem {
  key: string;
  group: string;
  title: string;
  description: string;
  variables: ProjectPromptVariable[];
  default_content: string;
  /** 当前生效的内容：改过就是作者的版本，否则等于 default_content */
  content: string;
  customized: boolean;
  /** 改过之后系统默认又变了（升级，或项目换了类型 / 视角） */
  default_changed: boolean;
  updated_at: string | null;
}

export interface ProjectPromptGroup {
  id: string;
  title: string;
  description: string;
}

export interface ProjectPromptList {
  groups: ProjectPromptGroup[];
  items: ProjectPromptItem[];
}

export interface ProjectPromptResetAll {
  reset: number;
  items: ProjectPromptItem[];
}
