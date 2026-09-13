import { withProjectHeader } from './activeProject';

export interface SSEMessage {
  type:
    | 'progress' | 'chunk' | 'result' | 'error' | 'done' | 'start' | 'content' | 'meta'
    | 'thinking' | 'partial' | 'bridges'
    | 'stage' | 'tool_call' | 'reference' | 'llm';
  message?: string;
  progress?: number;
  word_count?: number;
  status?: 'processing' | 'success' | 'error' | 'warning';
  content?: string;
  data?: unknown;
  error?: string;
  code?: number;
  /** meta 等扩展事件携带的附加字段（如 used_packs / used_dimensions / strength） */
  [key: string]: unknown;
}

export interface SSEClientOptions<TResult = unknown> {
  onProgress?: (message: string, progress: number, status: string, wordCount?: number) => void;
  onChunk?: (content: string) => void;
  onResult?: (data: TResult) => void;
  onError?: (error: string, code?: number) => void;
  onComplete?: () => void;
  onConnectionError?: (error: Event) => void;
  /** type=meta 事件（如一键仿写的 used_packs/used_dimensions/strength） */
  onMeta?: (meta: Record<string, unknown>) => void;
  /** 业务自定义事件（thinking / partial / bridges / stage / tool_call / reference / llm / start 及未知类型），原样回调 */
  onEvent?: (message: SSEMessage) => void;
  /** 每条消息的原始回调（含 progress / content / result / done / error），先于分类回调触发；通用任务 store 用它做事件归约 */
  onMessage?: (message: SSEMessage) => void;
  signal?: AbortSignal;
}

/** 后端存在 {error} 与 {message} 两种错误字段风格，统一取值 */
function extractErrorText(message: SSEMessage): string {
  return message.error || message.message || '未知错误';
}

/** 非 2xx：优先取 FastAPI 的 {detail}，否则退回 "HTTP error! status: N"（连接层重连逻辑按该前缀识别） */
async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body?.detail === 'string' && body.detail.trim()) return body.detail;
  } catch {
    /* 非 JSON 响应体 */
  }
  return `HTTP error! status: ${response.status}`;
}

type ResolveSSE = (value: unknown) => void;
type RejectSSE = (reason?: unknown) => void;

class SSEPostClient<TResult = unknown, TRequest = unknown> {
  private url: string;
  private data: TRequest;
  private options: SSEClientOptions<TResult>;
  private abortController: AbortController | null = null;
  private accumulatedContent = '';
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  private isAborted = false;
  private resultData: TResult | undefined;
  /** 已收到 done / error 事件，Promise 已经落定 */
  private settled = false;

  constructor(url: string, data: TRequest, options: SSEClientOptions<TResult> = {}) {
    this.url = url;
    this.data = data;
    this.options = options;
  }

  connect(): Promise<unknown> {
    return new Promise((resolve, reject) => {
      void this.connectStream(resolve, reject);
    });
  }

  private async connectStream(resolve: ResolveSSE, reject: RejectSSE): Promise<void> {
    const externalSignal = this.options.signal;
    const abortHandler = () => this.abort();

    try {
      this.abortController = new AbortController();
      this.isAborted = false;

      if (externalSignal?.aborted) {
        this.abort();
        reject(new DOMException('Request aborted', 'AbortError'));
        return;
      }

      externalSignal?.addEventListener('abort', abortHandler, { once: true });

      const response = await fetch(this.url, {
        method: 'POST',
        // 项目内带 X-Project-Id：后端按项目 AI 偏好覆盖模型 / 参数
        headers: withProjectHeader({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(this.data),
        signal: this.abortController.signal,
      });

      if (!response.ok) {
        throw new Error(await readErrorDetail(response));
      }

      this.reader = response.body?.getReader() || null;
      const decoder = new TextDecoder();

      if (!this.reader) {
        throw new Error('无法获取响应流');
      }

      let buffer = '';

      while (!this.isAborted) {
        const { done, value } = await this.reader.read();

        if (done) {
          // 流被对端/代理关闭却没收到 done/error 事件：不能让 Promise 永远挂起
          if (!this.settled && !this.isAborted) {
            const message = '连接在生成完成前中断';
            this.options.onError?.(message);
            reject(new Error(message));
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() === '' || line.startsWith(':')) {
            continue;
          }

          try {
            const dataMatch = line.match(/^data: (.+)$/m);
            if (dataMatch) {
              const message = JSON.parse(dataMatch[1]) as SSEMessage;
              this.handleMessage(message, resolve, reject);
            }
          } catch (error) {
            console.error('解析SSE消息失败:', error, line);
          }
        }
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') {
        console.log('Request aborted');
        reject(error);
      } else {
        const message = error instanceof Error ? error.message : 'Request failed';
        console.error('SSE POST request failed:', error);
        if (!this.settled) this.options.onError?.(message);
        reject(error);
      }
    } finally {
      externalSignal?.removeEventListener('abort', abortHandler);
      await this.closeReader();
    }
  }

  private async closeReader(): Promise<void> {
    if (this.reader) {
      try {
        await this.reader.cancel();
      } catch (error) {
        console.debug('关闭 reader 时出错:', error);
      }
      this.reader = null;
    }
  }

  private handleMessage(message: SSEMessage, resolve: ResolveSSE, reject: RejectSSE) {
    this.options.onMessage?.(message);
    switch (message.type) {
      case 'progress':
        if (this.options.onProgress && message.progress !== undefined) {
          this.options.onProgress(
            message.message || '',
            message.progress,
            message.status || 'processing',
            message.word_count
          );
        }
        break;

      case 'chunk':
      case 'content':
        if (message.content) {
          this.accumulatedContent += message.content;
          this.options.onChunk?.(message.content);
        }
        break;

      case 'result':
        if (message.data !== undefined) {
          this.resultData = message.data as TResult;
          this.options.onResult?.(this.resultData);
        }
        break;

      case 'error': {
        const errText = extractErrorText(message);
        this.settled = true;
        this.options.onError?.(errText, message.code);
        reject(new Error(errText));
        break;
      }

      case 'done':
        this.settled = true;
        this.options.onComplete?.();
        if (this.resultData !== undefined) {
          resolve(this.resultData);
        } else if (this.accumulatedContent) {
          resolve({ content: this.accumulatedContent });
        } else {
          resolve(true);
        }
        break;

      case 'meta':
        this.options.onMeta?.(message as Record<string, unknown>);
        break;

      case 'thinking':
      case 'partial':
      case 'bridges':
      case 'start':
      case 'stage':
      case 'tool_call':
      case 'reference':
      case 'llm':
        this.options.onEvent?.(message);
        break;

      default:
        console.debug(`[SSE] 收到未处理的消息类型: ${message.type}`, message);
        this.options.onEvent?.(message);
        break;
    }
  }

  abort() {
    this.isAborted = true;
    if (this.abortController) {
      this.abortController.abort();
    }
    if (this.reader) {
      this.reader.cancel().catch((error) => {
        console.debug('取消 reader 失败:', error);
      });
      this.reader = null;
    }
  }
}

export async function ssePost<TResult = unknown, TRequest = unknown>(
  url: string,
  data: TRequest,
  options: SSEClientOptions<TResult> = {}
): Promise<TResult> {
  const client = new SSEPostClient<TResult, TRequest>(url, data, options);
  try {
    return await client.connect() as TResult;
  } finally {
    client.abort();
  }
}
