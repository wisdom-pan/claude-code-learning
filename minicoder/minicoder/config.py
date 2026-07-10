"""配置加载 —— 环境变量 + 项目根 .env 文件。

配置两个 provider 各自的 key/base_url,加上模型与轮数覆盖。
没有引入 python-dotenv,自己解析 .env,保持零额外依赖、可读。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# provider -> 默认模型
_DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
}
_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def _load_dotenv(path: Path) -> None:
    """把 .env 里的键值读进 os.environ(不覆盖已存在的真实环境变量)。"""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    provider: str
    model: str
    api_key: str
    base_url: str | None
    max_rounds: int

    @classmethod
    def load(cls, dotenv_path: str | Path | None = None) -> Config:
        # 先加载 .env(默认当前工作目录),真实环境变量优先
        _load_dotenv(Path(dotenv_path) if dotenv_path else Path.cwd() / ".env")

        provider = os.environ.get("MINICODER_PROVIDER", "openai").strip().lower()
        if provider not in _DEFAULT_MODELS:
            raise ValueError(
                f"未知 provider: {provider!r},支持 {list(_DEFAULT_MODELS)}"
            )

        model = os.environ.get("MINICODER_MODEL", "").strip() or _DEFAULT_MODELS[provider]

        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or _DEFAULT_OPENAI_BASE_URL
        else:  # anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
            base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or "https://api.anthropic.com"

        try:
            max_rounds = int(os.environ.get("MINICODER_MAX_ROUNDS", "50"))
        except ValueError:
            max_rounds = 50

        return cls(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_rounds=max_rounds,
        )

    def require_api_key(self) -> None:
        """在真正发起请求前调用;缺 key 时给出清晰指引。"""
        if not self.api_key:
            var = "OPENAI_API_KEY" if self.provider == "openai" else "ANTHROPIC_API_KEY"
            raise RuntimeError(
                f"缺少 {var}。请设置环境变量或在 .env 中填写(参考 .env.example)。"
            )
