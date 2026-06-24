"""
PandaAI 认证模块 — 手机号+密码登录，凭证只从环境变量读取。

设计原则:
- 只有一种登录方式: panda_data.init_token(username="86手机号", password="密码")
- 凭证来源: 环境变量 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD
- 也支持从 .env 文件加载（.env 已 gitignore）
- PandaAI 为可选增强，未配置时不影响核心新闻采集

用法:
    from auth import init_pandaai, PANDA_AVAILABLE

    if init_pandaai():
        import panda_data
        panda_data.get_stock_daily(...)
"""

import logging
import os

logger = logging.getLogger(__name__)

PANDA_AVAILABLE = False

_SETUP_MSG = """\
╔══════════════════════════════════════════════════════════════╗
║  PandaAI 数据服务未配置（可选增强，不影响新闻采集）          ║
║                                                            ║
║  配置步骤:                                                  ║
║  1. cd {skill_dir}                                        ║
║  2. cp .env.example .env                                  ║
║  3. 编辑 .env 填入手机号和密码                              ║
║     PANDA_DATA_USERNAME=86你的手机号                       ║
║     PANDA_DATA_PASSWORD=你的密码                           ║
║                                                            ║
║  注册/订阅: https://www.pandaai.online/data-service        ║
║  Elite(¥153/月) 含融资融券+北向+龙虎榜+财务数据            ║
╚══════════════════════════════════════════════════════════════╝"""

_SETUP_MSG_SHORT = (
    "PandaAI 未配置。cp .env.example .env 并填入手机号密码即可。"
    "详见 https://www.pandaai.online/data-service"
)


def _find_skill_dir() -> str:
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
    """从 .env 文件加载环境变量（不覆盖已设置的值）"""
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

    1. 从 .env 文件加载凭证
    2. 读取 PANDA_DATA_USERNAME + PANDA_DATA_PASSWORD
    3. 调用 panda_data.init_token(username, password)
    """
    global PANDA_AVAILABLE

    if PANDA_AVAILABLE:
        return True

    _load_env_file()

    username = os.environ.get("PANDA_DATA_USERNAME", "").strip()
    password = os.environ.get("PANDA_DATA_PASSWORD", "").strip()

    if not username or not password:
        if verbose:
            logger.info(_SETUP_MSG.format(skill_dir=_find_skill_dir()))
        return False

    try:
        import panda_data
    except ImportError:
        logger.warning("panda_data 未安装。运行: pip install panda_data")
        return False

    try:
        panda_data.init_token(username=username, password=password)
        PANDA_AVAILABLE = True
        logger.info("PandaAI 已连接")
        return True
    except Exception as e:
        logger.warning(f"PandaAI 登录失败: {e}")
        return False


def is_panda_available() -> bool:
    if not PANDA_AVAILABLE:
        init_pandaai(verbose=False)
    return PANDA_AVAILABLE


def require_panda():
    """要求 PandaAI 可用，否则抛出带配置指引的异常"""
    if not init_pandaai(verbose=True):
        raise RuntimeError(_SETUP_MSG_SHORT)
