import os
from pathlib import Path


class SystemUtils:
    @staticmethod
    def is_container():
        """
        检测是否运行在容器环境中（Docker 或 Podman）
        """
        # 检查 Docker 环境标识文件
        if Path("/.dockerenv").exists():
            return True

        # 检查 Podman 环境变量
        if os.getenv("container") == "podman":
            return True

        return False
