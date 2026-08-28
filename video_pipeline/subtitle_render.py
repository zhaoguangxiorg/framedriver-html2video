# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

"""SRT 字幕解析 + ffmpeg drawtext 字幕滤镜构建。

背景：本项目字幕渲染从 ffmpeg `subtitles` 滤镜（libass，按字体名匹配、
存在静默回退）切换为 `drawtext` 滤镜（fontfile= 文件加载，无回退、
失败即报错）——把"实际使用的字幕字体 = 用户配置的字体"变成确定性事实。

职责：
- parse_srt()：解析 TTS 生成的 SRT 文件为 (start_sec, end_sec, text) 列表；
- build_subtitle_filters()：将每句字幕构建为一个 drawtext 滤镜，用逗号
  连接成 filter_chain，供 image_audio_to_video 等模块注入 -vf；同时返回
  warnings（如 .ttc 多 face、无有效字幕等提示）。

本模块仅做纯字符串构建，不执行 ffmpeg。
"""
import re
import unicodedata
from pathlib import Path

from video_pipeline.font_resolver import is_multi_face
from video_pipeline.config import VideoConfig, parse_resolution

# drawtext 直接支持的颜色名；其他值（如 0xRRGGBB）按原样透传
_DRAWTEXT_NAMED_COLORS = {
    "white", "black", "red", "green", "blue", "yellow", "cyan", "magenta",
}

# SRT 时间码行正则：HH:MM:SS,mmm --> HH:MM:SS,mmm（小时允许 1~2 位，容忍空白）
_SRT_TIMECODE_RE = re.compile(
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2}),(?P<sms>\d{3})"
    r"\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2}),(?P<ems>\d{3})"
)

# 字幕字体为 .ttc 多 face 集合时的提示文案（照常渲染 face 0，风险透明化）
_SRT_FONT_FACE_WARNING = (
    "字幕字体为多 face 集合（.ttc 文件），当前使用该文件的第一个 face 渲染字幕。"
    "若字体包含多个字面（如日文/简体/繁体），实际字形可能与预期不同。"
    "建议改用单 face 字体文件（.ttf/.otf，如思源黑体官方单语言版）。"
)

# SRT 文件无有效字幕内容时的提示文案
_SRT_EMPTY_WARNING = "SRT 文件无有效字幕内容，未渲染字幕"

# 字幕折行参数：水平边距（每侧像素）与安全系数。
# 宽度估算无法像素级精确（半角字符宽度因字体而异），安全系数让估算偏紧，
# 宁可早折行也不让长行溢出裁字。
_SUBTITLE_H_MARGIN = 40
_SUBTITLE_WIDTH_SAFETY = 0.92

# 字号/垂直边距的基准高度（像素）：配置值按"视频高 1080"定义，
# 实际渲染时按视频高度等比缩放，保证不同宽高比下字幕相对画面大小一致。
_FONT_SIZE_REFERENCE_HEIGHT = 1080


def _timecode_to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    """SRT 时间码（HH/MM/SS/毫秒字符串）转秒数。"""
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def parse_srt(srt_path: str) -> list[tuple[float, float, str]]:
    """读取并解析 SRT 字幕文件。

    Args:
        srt_path: SRT 文件路径（utf-8 编码）

    Returns:
        (start_sec, end_sec, text) 列表；多行文本用换行拼接为一个 text。
        格式异常的块会被跳过；文件不存在或解码失败时返回空列表，不抛异常。
    """
    try:
        content = Path(srt_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    cues: list[tuple[float, float, str]] = []
    # 按空行分隔字幕块（兼容 \r\n 换行）
    for block in re.split(r"\r?\n[ \t]*\r?\n", content):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # 首行为序号（纯数字）时跳过，容忍缺失序号的块
        start_index = 1 if lines[0].strip().isdigit() else 0
        # 在块内查找时间码行
        timecode_index = -1
        for i in range(start_index, len(lines)):
            if _SRT_TIMECODE_RE.search(lines[i]):
                timecode_index = i
                break
        if timecode_index < 0:
            continue  # 无时间码行，视为格式异常块，跳过
        # 时间码行之后的文本行（多行用换行拼接）
        text = "\n".join(lines[timecode_index + 1:]).strip()
        if not text:
            continue

        match = _SRT_TIMECODE_RE.search(lines[timecode_index])
        start_sec = _timecode_to_seconds(
            match.group("sh"), match.group("sm"), match.group("ss"), match.group("sms"),
        )
        end_sec = _timecode_to_seconds(
            match.group("eh"), match.group("em"), match.group("es"), match.group("ems"),
        )
        cues.append((start_sec, end_sec, text))

    return cues


def _escape_drawtext_text(text: str) -> str:
    """转义 drawtext text='...' 参数内的文本（filter 图文本层级）。

    顺序敏感（必须按此顺序）：
    1. 先转义反斜杠，避免后续插入的转义符被二次转义；
    2. 换行符（真实 \\n 0x0A）**原样保留**：drawtext 只按真实换行符分行渲染。
       不能转成字面 \\n（反斜杠+n）——实测 drawtext 会把 \\n 当普通文本显示，
       filter 图解析（av_get_token）也不会把 \\n 还原成换行；
    3. 最后转义 filter 图特殊字符 `'` `:` `,`（这些是还原语义，单层转义即可）。
       真实换行位于 text='...' 引号内，ffmpeg 参数解析会原样保留。
    """
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
    )


def _escape_filter_value(value: str) -> str:
    """转义 filter 图参数值内的特殊字符（fontfile / enable 等参数值用）。

    冒号是滤镜参数分隔符、逗号是滤镜分隔符，需转义为 \\: 与 \\,；
    先转义反斜杠，避免已有转义符被二次处理。
    """
    return value.replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,")


def _color_to_drawtext(color: str) -> str:
    """颜色名 → drawtext 颜色参数（fontcolor / bordercolor）。

    white/black/red/green/blue/yellow/cyan/magenta 直接返回原名称；
    其他值（如 0xRRGGBB）原样透传。
    """
    if color.lower() in _DRAWTEXT_NAMED_COLORS:
        return color.lower()
    return color


def _y_expression(position: str, margin: int) -> str:
    """字幕位置 → drawtext y 表达式。

    bottom → h-text_h-{margin}；top → {margin}；middle → (h-text_h)/2。
    """
    pos = (position or "bottom").lower()
    if pos == "top":
        return str(margin)
    if pos == "middle":
        return "(h-text_h)/2"
    return f"h-text_h-{margin}"


def _char_width(ch: str, fontsize: int) -> int:
    """估算单个字符的渲染宽度（像素）。

    全角字符（中文/日文假名/韩文/全角标点及数字字母）= fontsize；
    半角字符（英文/数字/ASCII 标点）= fontsize//2。
    用 east_asian_width 判断全角/半角，覆盖标准中西文宽度差异。
    """
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return fontsize
    return max(fontsize // 2, 1)


def _wrap_text(text: str, max_width_px: int, fontsize: int) -> str:
    """按估算宽度把长句拆成多行（drawtext 不支持自动换行）。

    规则：
    - 原文本内的换行视为强制断行点，逐段折行后仍用 \\n 连接（保留多行语义）；
    - 段内按空格切分为 token，英文单词/数字整词不拆开；
    - 逐 token 累加宽度，超宽时整词下移到下一行；
    - 单个 token 本身超宽（超长单词/URL）时按字符硬切兜底；
    - 全角/半角宽度由 _char_width 区分，中英文行容量自动不同。

    Returns:
        用 "\\n" 连接的多行文本；单行不超宽时原样返回。
    """
    return "\n".join(
        _wrap_segment(seg, max_width_px, fontsize) for seg in text.split("\n")
    )


def _wrap_segment(text: str, max_width_px: int, fontsize: int) -> str:
    """对不含换行的单段文本做宽度折行（_wrap_text 的内部实现）。"""
    lines: list[str] = []
    current = ""
    current_w = 0

    for token in re.split(r"(\s+)", text):
        if not token:
            continue
        token_w = sum(_char_width(ch, fontsize) for ch in token)
        if token.isspace():
            # 行首空格跳过；行中空格计入宽度（保持词间距离）
            if current:
                current += token
                current_w += token_w
            continue
        if current and current_w + token_w > max_width_px:
            # 整词超宽：当前行收尾，词移到下一行
            lines.append(current.rstrip())
            current = ""
            current_w = 0
        if token_w > max_width_px and not current:
            # 单个 token 超宽（超长单词）：按字符硬切
            piece = ""
            piece_w = 0
            for ch in token:
                ch_w = _char_width(ch, fontsize)
                if piece and piece_w + ch_w > max_width_px:
                    lines.append(piece)
                    piece = ""
                    piece_w = 0
                piece += ch
                piece_w += ch_w
            current = piece
            current_w = piece_w
        else:
            current += token
            current_w += token_w

    if current:
        lines.append(current.rstrip())
    return "\n".join(lines)


def build_subtitle_filters(
    srt_path: str,
    config: VideoConfig,
    font_file: str,
) -> tuple[str, list[str]]:
    """构建 drawtext 字幕滤镜链。

    为 SRT 中的每一句生成一个 drawtext 滤镜（fontfile= 文件加载），
    用逗号连接为 filter_chain，供上层注入 -vf；同时返回 warnings
    （.ttc 多 face 提示、无有效字幕提示等）。

    Args:
        srt_path: SRT 字幕文件路径
        config: 视频配置（字幕字号/颜色/描边/位置/边距等）
        font_file: 字幕字体文件路径（video_pipeline.font_resolver.resolve_subtitle_font 解析结果）

    Returns:
        (filter_chain, warnings)；SRT 无有效字幕时 filter_chain 为空串。
    """
    warnings: list[str] = []

    # .ttc 多 face：照常渲染 face 0，但给出显式提示
    if is_multi_face(font_file):
        warnings.append(_SRT_FONT_FACE_WARNING)

    cues = parse_srt(srt_path)
    if not cues:
        warnings.append(_SRT_EMPTY_WARNING)
        return ("", warnings)

    # fontfile 路径统一为正斜杠（Windows 盘符冒号等由 _escape_filter_value 转义）
    fontfile_value = _escape_filter_value(Path(font_file).as_posix())

    # 字号/垂直边距为"基准高度 1080"下的绝对值，按实际视频高度等比缩放，
    # 保证不同宽高比下字幕相对画面大小一致（16:9 与 9:16 观感统一）
    video_width, video_height = parse_resolution(config.resolution)
    font_scale = video_height / _FONT_SIZE_REFERENCE_HEIGHT
    fontsize = max(int(config.subtitle_font_size * font_scale), 1)
    subtitle_margin = max(int(config.subtitle_margin * font_scale), 0)
    # 折行可用宽度：与渲染同源（视频宽度），
    # 每侧留水平边距并打安全系数——估算偏紧，宁可早折行也不裁字
    max_subtitle_width = int((video_width - 2 * _SUBTITLE_H_MARGIN) * _SUBTITLE_WIDTH_SAFETY)
    fontcolor = _color_to_drawtext(config.subtitle_color)
    bordercolor = _color_to_drawtext(config.subtitle_outline_color)
    borderw = config.subtitle_outline_width
    y_expr = _y_expression(config.subtitle_position, subtitle_margin)

    filters: list[str] = []
    for start_sec, end_sec, text in cues:
        # 长句按宽度估算折行（drawtext 不支持自动换行），中英文宽度区分、整词保护
        text = _wrap_text(text, max_subtitle_width, fontsize)
        # enable 表达式内逗号为函数参数分隔符，在 filter 图文本层级转义为 \,
        enable_value = _escape_filter_value(
            f"between(t,{start_sec:.3f},{end_sec:.3f})"
        )
        drawtext = (
            f"drawtext=fontfile='{fontfile_value}':expansion=none:"
            f"text='{_escape_drawtext_text(text)}':"
            f"fontsize={fontsize}:fontcolor={fontcolor}:"
            f"borderw={borderw}:bordercolor={bordercolor}:"
            f"x=(w-text_w)/2:y={y_expr}:"
            f"enable='{enable_value}'"
        )
        filters.append(drawtext)

    return (",".join(filters), warnings)
