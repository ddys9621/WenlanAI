import { authApi } from '../services/api';
import { toast } from 'sonner';

/**
 * 会话管理工具
 * 负责监控会话状态、自动刷新和过期处理
 */
class SessionManager {
  // 用 ReturnType 而不是 number：src 下的 vitest 用例会把 @types/node 带进同一 tsc 程序，浏览器 / node 两套 setTimeout 签名都兼容
  private checkInterval: ReturnType<typeof setInterval> | null = null;
  private activityTimeout: ReturnType<typeof setTimeout> | null = null;
  private lastActivityTime: number = Date.now();
  
  // 配置参数
  private readonly CHECK_INTERVAL = 60 * 1000; // 每分钟检查一次
  private readonly REFRESH_THRESHOLD = 30 * 60 * 1000; // 剩余30分钟时刷新
  private readonly ACTIVITY_TIMEOUT = 30 * 60 * 1000; // 30分钟无活动则不自动刷新
  private readonly WARNING_THRESHOLD = 5 * 60 * 1000; // 剩余5分钟时警告
  
  private warningShown = false;

  /**
   * 启动会话监控
   */
  start() {
    if (this.checkInterval) {
      return;
    }

    // 先检查是否有有效的会话
    const expireAt = this.getSessionExpireTime();
    
    if (!expireAt) {
      this.stop();
      return;
    }
    
    const now = Date.now();
    const remaining = expireAt - now;
    const remainingMinutes = Math.floor(remaining / 60000);
    
    // 如果会话已过期，不启动监控
    if (remaining <= 0) {
      return;
    }
    
    this.lastActivityTime = now;
    this.warningShown = false;
    console.log(`✅ [会话] 启动监控，剩余 ${remainingMinutes} 分钟`);
    
    // 立即检查一次
    this.checkSession();
    
    // 定期检查会话状态
    this.checkInterval = setInterval(() => {
      this.checkSession();
    }, this.CHECK_INTERVAL);
    
    // 监听用户活动
    this.setupActivityListeners();
  }

  /**
   * 停止会话监控
   */
  stop() {
    console.log('[SessionManager] 停止会话监控');
    
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
    }
    
    if (this.activityTimeout) {
      clearTimeout(this.activityTimeout);
      this.activityTimeout = null;
    }
    
    this.removeActivityListeners();
    this.warningShown = false;
  }

  /**
   * 检查会话状态
   */
  private async checkSession() {
    try {
      const expireAt = this.getSessionExpireTime();
      
      if (!expireAt) {
        this.stop();
        return;
      }
      
      const now = Date.now();
      const remaining = expireAt - now;
      const remainingMinutes = Math.floor(remaining / 60000);
      
      // 会话已过期
      if (remaining <= 0) {
        console.log('⏰ [会话] 已过期，退出登录');
        this.handleSessionExpired();
        return;
      }
      
      // 显示即将过期警告
      if (remaining <= this.WARNING_THRESHOLD && !this.warningShown) {
        this.warningShown = true;
        toast.warning(`您的登录状态将在 ${remainingMinutes} 分钟后过期，请注意保存数据`, {
          duration: 10000,
        });
      }
      
      // 需要刷新会话
      if (remaining <= this.REFRESH_THRESHOLD) {
        const timeSinceLastActivity = now - this.lastActivityTime;
        
        // 检查用户是否活跃（30分钟内有活动）
        if (timeSinceLastActivity < this.ACTIVITY_TIMEOUT) {
          await this.refreshSession();
        }
      }
    } catch {
      // 静默处理错误
    }
  }

  /**
   * 刷新会话
   */
  private async refreshSession() {
    try {
      const result = await authApi.refreshSession();
      this.warningShown = false; // 重置警告状态
      
      console.log(`🔄 [会话] 自动续期成功，延长 ${result.remaining_minutes} 分钟`);
      
      toast.success('登录状态已自动延长', {
        duration: 2000,
      });
    } catch {
      // 刷新失败可能是会话已过期
      this.handleSessionExpired();
    }
  }

  /**
   * 处理会话过期
   */
  private async handleSessionExpired() {
    this.stop();
    
    const currentPath = window.location.pathname;
    // 如果已经在登录页，不显示错误提示
    if (currentPath === '/login') {
      return;
    }
    
    // 调用登出接口清除服务器端的 Cookie
    try {
      await authApi.logout();
    } catch {
      // 即使登出失败也继续跳转
    }
    
    toast.error('登录已过期，请重新登录', {
      duration: 3000,
    });
    
    // 延迟跳转，让用户看到提示
    setTimeout(() => {
      window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`;
    }, 1000);
  }

  /**
   * 获取会话过期时间（毫秒时间戳）
   */
  private getSessionExpireTime(): number | null {
    const cookies = document.cookie.split(';');
    
    for (const cookie of cookies) {
      const [name, value] = cookie.trim().split('=');
      
      if (name === 'session_expire_at') {
        const timestamp = parseInt(value, 10);
        return timestamp * 1000; // 转换为毫秒
      }
    }
    
    return null;
  }

  /**
   * 设置用户活动监听器
   */
  private setupActivityListeners() {
    const events = ['mousedown', 'keydown', 'scroll', 'touchstart'];
    
    events.forEach(event => {
      document.addEventListener(event, this.handleUserActivity, { passive: true });
    });
  }

  /**
   * 移除用户活动监听器
   */
  private removeActivityListeners() {
    const events = ['mousedown', 'keydown', 'scroll', 'touchstart'];
    
    events.forEach(event => {
      document.removeEventListener(event, this.handleUserActivity);
    });
  }

  /**
   * 处理用户活动
   */
  private handleUserActivity = () => {
    this.lastActivityTime = Date.now();
    
    // 重置活动超时
    if (this.activityTimeout) {
      clearTimeout(this.activityTimeout);
    }
    
    this.activityTimeout = setTimeout(() => {
      // 用户已超过30分钟无活动
    }, this.ACTIVITY_TIMEOUT);
  };

  /**
   * 手动刷新会话（供外部调用）
   */
  async manualRefresh(): Promise<boolean> {
    try {
      await this.refreshSession();
      return true;
    } catch {
      return false;
    }
  }
}

// 导出单例
export const sessionManager = new SessionManager();
