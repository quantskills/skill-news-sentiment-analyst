"""
PandaAI 认证模块 — 从环境变量加载凭证，优雅降级。

设计原则:
- 凭证只从环境变量读取，不写任何配置文件
- PandaAI 为可选增强功能，未配置时不影响核心新闻采集
- 提供清晰的错误信息，引导用户完成配置

用法:
    from auth import init_pandaai, PANDA_AVAILABLE

    init_pandaai()                    # 尝试加载 PandaAI
    if PANDA_AVAILABLE:
        import panda_data
        panda_data.get_stock_daily(...)
    else:
        print("PandaAI 未配置，跳过增强验证")
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

PANDA_AVAILABLE = False
_panda_module = None

_SETUP_HINT = """
╔══════════════════════════════════════════════════════════════╗
║  PandaAI 数据服务未配置（这是可选功能，不影响新闻采集）       ║
║                                                            ║
║  如需启用回测验证 / 资金流向 / 内部人信号检查:                ║
║                                                            ║
║  1. cd {skill_dir}                                        ║
║  2. cp .env.example .env                                  ║
║  3. 编辑 .env 填入 PandaAI 凭证                            ║
║  4. export PANDA_DATA_TOKEN="your-token"                  ║
║                                                            ║
║  获取凭证: https://www.pandaai.online/data-service         ║
╚══════════════════════════════════════════════════════════════╝
"""

_SETUP_HINT_SHORT = (
    "PandaAI 未配置。如需启用增强验证: "
    "cp .env.example .env 并填入凭证，然后 export PANDA_DATA_TOKEN='xxx'。"
    "详见 https://www.pandaai.online/data-service"
)


def _find_skill_dir() -> str:
    """定位 skill 根目录（包含 .env.example 的目录）"""
    # 从当前文件向上找
    candidates = [
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        os.path.expanduser("~/.claude/skills/news-sentiment-analyst"),
        os.path.join(os.getcwd(), ".claude/skills/news-sentiment-analyst"),
    ]
    for d in candidates:
        if os.path.isfile(os.path.join(d, ".env.example")):
            return d
    return candidates[0]


def _load_env_file() -> None:
    """加载 .env 文件中的环境变量（如果存在且未设置）"""
    skill_dir = _find_skill_dir()
    env_path = os.path.join(skill_dir, ".env")

    if not os.path.isfile(env_path):
        return

    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


def init_pandaai(verbose: bool = True) -> bool:
    """
    初始化 PandaAI SDK。

    加载顺序:
    1. 从 .env 文件加载凭证（不覆盖已存在的环境变量）
    2. 尝试 import panda_data
    3. 尝试 set_token / 账号密码登录
    4. 标记 PANDA_AVAILABLE

    Returns:
        bool: PandaAI 是否可用
    """
    global PANDA_AVAILABLE, _panda_module

    if PANDA_AVAILABLE:
        return True

    # Step 1: 加载 .env
    _load_env_file()

    # Step 2: 检查凭证
    token = os.environ.get("PANDA_DATA_TOKEN", "").strip()
    username = os.environ.get("PANDA_DATA_USERNAME", "").strip()
    password = os.environ.get("PANDA_DATA_PASSWORD", "").strip()

    if not token and not (username and password):
        if verbose:
            hint = _SETUP_HINT.format(skill_dir=_find_skill_dir())
            logger.info(hint)
        return False

    # Step 3: 尝试 import
    try:
        import panda_data as pd_mod
        _panda_module = pd_mod
    except ImportError:
        logger.warning(
            "panda_data SDK 未安装。运行: pip install panda_data"
        )
        return False

    # Step 4: 认证
    try:
        if token:
            # API Token 方式
            if hasattr(_panda_module, "set_token"):
                _panda_module.set_token(token)
                logger.info("PandaAI 已通过 token 连接")
            elif hasattr(_panda_module, "set_api_key"):
                _panda_module.set_api_key(token)
                logger.info("PandaAI 已通过 API key 连接")
            else:
                os.environ["PANDA_DATA_TOKEN"] = token
                logger.info("PandaAI token 已设置到环境变量")
        elif username and password:
            # 账号密码方式
            if hasattr(_panda_module, "login"):
                _panda_module.login(username, password)
                logger.info(f"PandaAI 已通过账号 {username} 登录")
            else:
                logger.warning(
                    "panda_data SDK 不支持 login()，请使用 PANDA_DATA_TOKEN"
                )
                return False
        else:
            return False

        PANDA_AVAILABLE = True
        return True

    except Exception as e:
        logger.warning(f"PandaAI 初始化失败: {e}")
        return False


def get_panda() -> "module | None":
    """返回已认证的 panda_data 模块，或 None"""
    global PANDA_AVAILABLE, _panda_module
    if not PANDA_AVAILABLE:
        init_pandaai(verbose=False)
    return _panda_module if PANDA_AVAILABLE else None


def is_panda_available() -> bool:
    """PandaAI 是否已连接"""
    global PANDA_AVAILABLE
    if not PANDA_AVAILABLE:
        init_pandaai(verbose=False)
    return PANDA_AVAILABLE


def require_panda():
    """
    要求 PandaAI 可用，否则抛出友好错误。

    用于必须使用 PandaAI 的功能（如回测）。
    """
    if not init_pandaai(verbose=True):
        raise RuntimeError(_SETUP_HINT_SHORT)
