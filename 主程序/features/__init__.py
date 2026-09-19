# -*- coding: utf-8 -*-
"""功能模块自动发现 —— 加功能只需新建文件，不需要修改注册表。

每个 .py 文件的 Feature 子类会自动注册到 REGISTRY
"""
import pkgutil
import importlib
from pathlib import Path

# 先导入 REGISTRY
from app.feature import REGISTRY

# 自动导入 features/ 下所有 .py 模块并注册 Feature 子类
pkg_dir = Path(__file__).parent
for (_, module_name, _) in pkgutil.iter_modules([str(pkg_dir)]):
    # 跳过 __init__ 自己和旧的非 Feature 模块
    if module_name == "__init__":
        continue
    # 跳过尚未迁移到 Feature 的旧模块（仍是 def 执行() 函数式）
    if module_name in ("heal", "daily", "dungeon"):
        continue

    try:
        mod = importlib.import_module(f"features.{module_name}")
        # 查找模块中的 Feature 子类并注册
        from app.feature import Feature
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type) and
                issubclass(attr, Feature) and
                attr is not Feature and
                attr not in REGISTRY):
                REGISTRY.append(attr)
                print(f"[功能注册] {attr.NAME} ({module_name})")
    except Exception as e:
        print(f"[功能加载] 跳过 {module_name}: {e}")

# 导出 REGISTRY 供外部使用
__all__ = ["REGISTRY"]
