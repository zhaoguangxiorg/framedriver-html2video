# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""字体家族名 → 字体文件路径的只读解析，及多 face（.ttc）检测。

- resolve_font_file()：按平台解析字体文件路径。
  - Windows：枚举注册表 Fonts 键（HKLM/HKCU），显示名去掉尾部
    (TrueType)/(OpenType) 后缀后做精确或集合字体前缀匹配；
  - Linux：调用 fc-match，仅接受家族名精确匹配，绝不返回模糊匹配路径；
  - 其他平台或未命中：返回 None。
- is_multi_face()：按扩展名判断字体文件是否为多 face 的 .ttc 集合。

全程只读，仅用 Python 标准库，不安装、不修改系统。
"""
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Windows 字体默认目录
_WINDOWS_FONTS_DIR = r"C:\Windows\Fonts"

# 注册表字体显示名尾部常见后缀
_DISPLAY_NAME_SUFFIXES = (" (TrueType)", " (OpenType)")


def _strip_display_name_suffix(display_name: str) -> str:
    """去掉注册表字体显示名尾部的 (TrueType)/(OpenType) 后缀。"""
    for suffix in _DISPLAY_NAME_SUFFIXES:
        if display_name.endswith(suffix):
            return display_name[: -len(suffix)]
    return display_name


def _match_display_name(base_name: str, font_name: str) -> bool:
    """注册表显示名（去后缀后）与目标字体名的匹配规则。"""
    if base_name == font_name:
        return True
    # 集合字体注册名，如 "Microsoft YaHei & Microsoft YaHei UI"
    if base_name.startswith(font_name) and base_name[len(font_name):].lstrip().startswith("&"):
        return True
    return False


def _resolve_windows(font_name: str) -> Optional[str]:
    """Windows：枚举注册表 Fonts 键解析字体文件路径。"""
    try:
        import winreg  # 仅 Windows 平台存在
    except ImportError:
        return None

    registry_keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    for hive, subkey in registry_keys:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                index = 0
                while True:
                    try:
                        display_name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break  # 该键枚举完毕
                    index += 1

                    base_name = _strip_display_name_suffix(str(display_name))
                    if not _match_display_name(base_name, font_name):
                        continue

                    if not value:
                        continue
                    font_path = str(value)
                    if ":" not in font_path and not font_path.startswith("\\"):
                        font_path = os.path.join(_WINDOWS_FONTS_DIR, font_path)
                    return os.path.normpath(font_path)
        except OSError:
            continue  # 该键不可用（无权限等），尝试下一个
    return None


def _resolve_linux(font_name: str) -> Optional[str]:
    """Linux：fc-match 精确匹配家族名，绝不返回模糊匹配的字体路径。"""
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family}|%{file}", font_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    stdout = result.stdout.strip()
    if "|" not in stdout:
        return None

    family_part, file_part = stdout.split("|", 1)
    # %{family} 可能含逗号分隔的多个家族名，取第一个与目标精确比较
    first_family = family_part.split(",")[0].strip()
    if first_family != font_name:
        return None

    font_path = file_part.strip()
    return font_path or None


def resolve_font_file(font_name: str) -> Optional[str]:
    """按平台解析字体家族名对应的字体文件路径；未命中返回 None。"""
    if not font_name or not font_name.strip():
        return None

    # platform.system() 极少返回空串，用 sys.platform 兜底（如 "win32"/"linux"）
    system = platform.system() or sys.platform
    if system in ("Windows", "win32"):
        return _resolve_windows(font_name)
    if system in ("Linux", "linux"):
        return _resolve_linux(font_name)
    return None


def is_multi_face(font_file: str) -> bool:
    """判断字体文件是否为多 face：.ttc（TrueType Collection）返回 True。"""
    return Path(font_file).suffix.lower() == ".ttc"


def resolve_subtitle_font(
    font_name: str = "",
    font_file: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """按优先级解析字幕字体来源，返回 (字体文件路径, 错误文案)。

    优先级：font_file（subtitle_font_file 直接指定）> font_name（字体名解析）。
    - font_file 非空：仅支持单 face 文件（.ttf/.otf）；文件不存在或为
      .ttc/.otc 多 face 集合 → 返回 (None, 错误文案)。
    - font_name 非空：走 resolve_font_file 名字解析；解析不到 → 返回错误文案。
    - 均未配置 → (None, None)（无字幕需求）。

    只读，不安装不修改。
    """
    if font_file:
        path = Path(font_file)
        if not path.exists():
            return (None, f"字幕字体文件不存在：{font_file}")
        if path.suffix.lower() in (".ttc", ".otc"):
            return (None, "subtitle_font_file 仅支持单 face 字体文件（.ttf/.otf），不支持 .ttc/.otc 多 face 集合")
        return (str(path.resolve()), None)

    if font_name:
        resolved = resolve_font_file(font_name)
        if resolved is None:
            return (None, f"未能在系统中找到字体 \"{font_name}\"")
        return (resolved, None)

    return (None, None)
