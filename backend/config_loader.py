"""外部配置文件加载器 - 用于打包后的 exe"""
import os
import sys
import configparser
from pathlib import Path


def get_exe_dir():
    """获取 exe 所在目录（打包后）或脚本所在目录（开发时）"""
    if getattr(sys, 'frozen', False):
        # 打包后的 exe
        return Path(sys.executable).parent
    else:
        # 开发环境
        return Path(__file__).parent.parent


def get_config_path():
    """获取配置文件路径"""
    exe_dir = get_exe_dir()
    return exe_dir / "config.ini"


def create_default_config():
    """创建默认配置文件"""
    config = configparser.ConfigParser()
    
    config['database'] = {
        'url': 'sqlite+aiosqlite:///./data/mumuai.db',
    }
    
    config['app'] = {
        'host': '0.0.0.0',
        'port': '8000',
        'debug': 'false',
    }
    
    config['ai'] = {
        'openai_api_key': '',
        'openai_base_url': '',
        'anthropic_api_key': '',
        'anthropic_base_url': '',
        'gemini_api_key': '',
        'gemini_base_url': '',
    }
    
    config['auth'] = {
        'local_auth_enabled': 'true',
        'local_auth_username': 'admin',
        'local_auth_password': 'admin123',
    }
    
    config_path = get_config_path()
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write("# WenlanAI 配置文件\n")
        f.write("# 修改后需要重启应用才能生效\n\n")
        config.write(f)
    
    print(f"[OK] 已创建默认配置文件: {config_path}")
    return config


def load_config():
    """加载配置文件"""
    config_path = get_config_path()
    
    if not config_path.exists():
        print(f"[WARN] 配置文件不存在，创建默认配置: {config_path}")
        return create_default_config()

    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    print(f"[OK] 已加载配置文件: {config_path}")
    return config


def apply_config_to_env(config):
    """将配置文件的内容应用到环境变量"""
    # 数据库配置
    if config.has_option('database', 'url'):
        os.environ['DATABASE_URL'] = config.get('database', 'url')
    
    # AI 配置
    if config.has_option('ai', 'openai_api_key'):
        os.environ['OPENAI_API_KEY'] = config.get('ai', 'openai_api_key')
    if config.has_option('ai', 'openai_base_url'):
        os.environ['OPENAI_BASE_URL'] = config.get('ai', 'openai_base_url')
    if config.has_option('ai', 'anthropic_api_key'):
        os.environ['ANTHROPIC_API_KEY'] = config.get('ai', 'anthropic_api_key')
    if config.has_option('ai', 'anthropic_base_url'):
        os.environ['ANTHROPIC_BASE_URL'] = config.get('ai', 'anthropic_base_url')
    if config.has_option('ai', 'gemini_api_key'):
        os.environ['GEMINI_API_KEY'] = config.get('ai', 'gemini_api_key')
    if config.has_option('ai', 'gemini_base_url'):
        os.environ['GEMINI_BASE_URL'] = config.get('ai', 'gemini_base_url')
    
    # 认证配置
    if config.has_option('auth', 'local_auth_enabled'):
        os.environ['LOCAL_AUTH_ENABLED'] = config.get('auth', 'local_auth_enabled')
    if config.has_option('auth', 'local_auth_username'):
        os.environ['LOCAL_AUTH_USERNAME'] = config.get('auth', 'local_auth_username')
    if config.has_option('auth', 'local_auth_password'):
        os.environ['LOCAL_AUTH_PASSWORD'] = config.get('auth', 'local_auth_password')


def init_config():
    """初始化配置（在应用启动前调用）"""
    config = load_config()
    apply_config_to_env(config)
    return config

