# Author: AI Agent (guided by zhaoguangxi)
# Modified: 2026-08-11

import os
from pathlib import Path
from typing import Tuple

from video_pipeline.config import VideoConfig, parse_resolution

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(__file__).parent.parent / ".playwright-browsers")


def html_to_image(
    html_file_path: str,
    output_path: str,
    config: VideoConfig,
    animation_timeout_ms: int = 5000,
) -> Tuple[str, int, int]:
    """
    将 HTML 文件渲染为图片。

    Args:
        html_file_path: HTML 文件路径
        output_path: 输出图片路径
        config: 视频配置对象
        animation_timeout_ms: 等待 CSS 动画完成的最大超时时间（毫秒），
                              动画完成则立即截图，超时则按当前状态截图

    Returns:
        (image_path, width, height) 元组

    Raises:
        FileNotFoundError: HTML 文件不存在时
        RuntimeError: 浏览器启动或页面加载失败时
    """
    from playwright.sync_api import sync_playwright, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

    html_path = Path(html_file_path).resolve()
    if not html_path.exists():
        raise FileNotFoundError(f"HTML file not found: {html_file_path}")

    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = parse_resolution(config.resolution)

    # 注入 JS：监听所有有限动画的 animationend 事件，完成后设置 window.__animationsDone = true
    _animation_wait_script = """
    (function () {
        var pending = 0;
        var els = document.querySelectorAll('*');
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            var cs = getComputedStyle(el);
            var names = cs.animationName;
            var iter = cs.animationIterationCount;
            if (!names || names === 'none') continue;
            // 排除无限循环动画（永远不会触发 animationend）
            if (iter === 'infinite') continue;
            // 一个元素可能有多个动画，按逗号分割
            var nameList = names.split(',').map(function (s) { return s.trim(); });
            for (var j = 0; j < nameList.length; j++) {
                if (nameList[j] && nameList[j] !== 'none') pending++;
            }
            (function (target, count) {
                target.addEventListener('animationend', function (e) {
                    if (e.target === target) {
                        pending -= count;
                        if (pending <= 0) window.__animationsDone = true;
                    }
                });
            })(el, nameList.length);
        }
        // 没有有限动画，立即标记完成
        if (pending <= 0) window.__animationsDone = true;
    })();
    """

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=config.device_scale_factor,
                )
                page = context.new_page()
                page.goto(html_path.as_uri(), wait_until="networkidle")

                # 注入 JS，开始监听 animationend
                page.evaluate(_animation_wait_script)

                # 等待所有动画完成（最多 animation_timeout_ms），超时不报错直接截图
                try:
                    page.wait_for_function(
                        "() => window.__animationsDone === true",
                        timeout=animation_timeout_ms,
                    )
                except PlaywrightTimeoutError:
                    pass  # 超时：按当前状态截图

                page.screenshot(path=str(output_path), full_page=False)
                context.close()
            finally:
                browser.close()
    except PlaywrightError as e:
        raise RuntimeError(f"Playwright error: {e}") from e

    return (str(output_path), width, height)
