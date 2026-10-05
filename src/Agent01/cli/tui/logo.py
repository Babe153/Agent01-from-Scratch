from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

from rich.text import Text

from Agent01.core.paths import find_project_root


FALLBACK_LOGO = [
    "  <      >  ",
    "   /\\__/\\   ",
    "  |  ||  |  ",
    "  |______|  ",
    "   ||  ||   ",
]


def default_logo_path() -> Path:
    """返回项目根目录下用户自己的 logo.png 路径。
    这里只计算路径，不读取图片；render_logo 未指定 path 时会使用它。
    """
    return find_project_root() / "logo.png"


def render_logo(path: Path | None = None, *, max_width: int = 36, max_rows: int = 12) -> Text:
    """对外提供 Logo 渲染入口，返回可放入 Textual Static 的 Rich Text。
    优先读取指定图片，否则使用默认路径；读取或处理失败时返回字符 Logo，
    使界面仍能启动。max_width/max_rows 控制图片转换后的字符尺寸。
    """
    logo_path = path or default_logo_path()
    try:
        return _render_png_logo(str(logo_path), max_width=max_width, max_rows=max_rows)
    except Exception:
        return _render_fallback_logo()


@lru_cache(maxsize=16)
def _render_png_logo(path: str, *, max_width: int, max_rows: int) -> Text:
    """将图片转换成带前景色和背景色的终端文字。
    读取 RGBA 图片，裁掉多余空白，再按字符宽度和两倍字符行数等比缩小。
    每两个竖直相邻像素合为一个字符，配合颜色表现上下两半；奇数高度补一行。
    lru_cache 缓存最多 16 组参数的结果，相同路径和尺寸不会每次重新读图，
    因此修改原图片后，同一进程中的缓存不会自动失效。
    """
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    image = _crop_visible(image)
    image.thumbnail((max_width, max_rows * 2), Image.Resampling.NEAREST)
    width, height = image.size
    if height % 2:
        image = _pad_bottom(image)
        width, height = image.size

    pixels = image.load()
    text = Text()
    for y in range(0, height, 2):
        for x in range(width):
            upper = pixels[x, y]
            lower = pixels[x, y + 1]
            text.append(_pixel_char(upper, lower), style=_pixel_style(upper, lower))
        if y + 2 < height:
            text.append("\n")
    return text


def _crop_visible(image: "Image.Image") -> "Image.Image":
    """扫描图片，寻找不透明且不是近白色的像素所占的边界。
    在边界四周保留最多 8 像素空白，裁剪后返回新图片；没有可见像素则原样返回。
    边界使用 min/max 限制在图片范围内，避免裁剪越界。
    """
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a > 16 and (r < 245 or g < 245 or b < 245):
                xs.append(x)
                ys.append(y)
    if not xs or not ys:
        return rgba
    padding = 8
    left = max(0, min(xs) - padding)
    top = max(0, min(ys) - padding)
    right = min(width, max(xs) + padding + 1)
    bottom = min(height, max(ys) + padding + 1)
    return rgba.crop((left, top, right, bottom))


def _pad_bottom(image: "Image.Image") -> "Image.Image":
    """为奇数高度图片在底部补一行透明像素。
    创建同宽、增高一行的 RGBA 画布，将原图粘贴到左上角，
    使后续读取 y 与 y+1 两行像素时不会越界。
    """
    from PIL import Image

    width, height = image.size
    padded = Image.new("RGBA", (width, height + 1), (255, 255, 255, 0))
    padded.paste(image, (0, 0))
    return padded


def _pixel_char(upper: tuple[int, int, int, int], lower: tuple[int, int, int, int]) -> str:
    """根据上下两个像素是否可见，选择对应的半块字符。
    上半可见用 ▀，仅下半可见用 ▄，都不可见用空格。
    两者都可见时仍用 ▀，下半颜色由字符背景色表示。
    """
    upper_visible = _visible(upper)
    lower_visible = _visible(lower)
    if upper_visible and lower_visible:
        return "▀"
    if upper_visible:
        return "▀"
    if lower_visible:
        return "▄"
    return " "


def _pixel_style(upper: tuple[int, int, int, int], lower: tuple[int, int, int, int]) -> str:
    """为半块字符生成 Rich 颜色样式。
    上下均可见时，上像素作为前景色、下像素作为背景色；
    只一半可见时只设置对应前景色，都不可见则不附加样式。
    """
    upper_visible = _visible(upper)
    lower_visible = _visible(lower)
    if upper_visible and lower_visible:
        return f"rgb({_rgb(upper)}) on rgb({_rgb(lower)})"
    if upper_visible:
        return f"rgb({_rgb(upper)})"
    if lower_visible:
        return f"rgb({_rgb(lower)})"
    return ""


def _visible(pixel: tuple[int, int, int, int]) -> bool:
    """判断 RGBA 像素是否应当显示。
    透明度须大于 16，而且 RGB 至少一个通道小于 245；
    这会把透明和接近白色的像素当作背景忽略，并不只是判断透明度。
    """
    r, g, b, a = pixel
    return a > 16 and (r < 245 or g < 245 or b < 245)


def _rgb(pixel: tuple[int, int, int, int]) -> str:
    """取出 RGBA 的前三个通道并拼成逗号分隔字符串。
    例如 (255,120,42,255) 变成 255,120,42，供 Rich 的 rgb(...) 样式使用。
    """
    return ",".join(str(channel) for channel in pixel[:3])


def _render_fallback_logo(lines: Iterable[str] = FALLBACK_LOGO) -> Text:
    """图片无法渲染时，把备用字符画拼成橙色的 Rich Text。
    enumerate 同时提供行号和内容，用于在行间添加换行。
    换行判断使用默认 FALLBACK_LOGO 的长度，此实现主要服务默认备用图案。
    """
    text = Text()
    for index, line in enumerate(lines):
        text.append(line, style="bold rgb(255,120,42)")
        if index < len(FALLBACK_LOGO) - 1:
            text.append("\n")
    return text
