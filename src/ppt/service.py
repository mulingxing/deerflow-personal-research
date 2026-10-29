"""Render a Markdown slide deck with a selected, trusted Marp theme."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import zipfile
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
THEME_DIRECTORY = Path(__file__).resolve().parent / "themes"
BUILTIN_THEMES = {"default", "gaia", "uncover"}
CUSTOM_THEMES = {
    "gaia": THEME_DIRECTORY / "gaia.css",
    "midnight": THEME_DIRECTORY / "midnight.css",
    "paper": THEME_DIRECTORY / "paper.css",
}
PPT_THEMES = frozenset(BUILTIN_THEMES | CUSTOM_THEMES.keys())
MARP_TIMEOUT_SECONDS = 180
MAX_SLIDE_MARKDOWN_CHARS = 200_000
LAYOUT_CHECK_SCRIPT = Path(__file__).resolve().parent / "fit_check.cjs"
# 中文注释：按保守的文字高度估算分页，给标题、表格和主题留出空间。
MAX_SLIDE_HEIGHT_UNITS = 10.5
RETRY_SLIDE_HEIGHT_UNITS = 7.0
SLIDE_TEXT_WIDTH_UNITS = 58
IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
IMAGE_REFERENCE_PATTERN = re.compile(r"!\[([^\]]*)\][ \t]*\[([^\]]*)\]")
IMAGE_SHORTCUT_PATTERN = re.compile(r"!\[([^\]]*)\](?![ \t]*[\[(])")
REFERENCE_DEFINITION_PATTERN = re.compile(r"^[ \t]{0,3}\[([^\]]+)\]:")
MEDIA_BLOCK_PATTERN = re.compile(
    r"<(?P<tag>style|script|picture|video|audio|iframe|object|svg)\b[^>]*>"
    r".*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
MEDIA_TAG_PATTERN = re.compile(
    r"</?(?:img|source|track|embed|link|picture|video|audio|iframe|object|"
    r"svg|style|script|base)\b[^>]*>",
    re.IGNORECASE | re.DOTALL,
)
SLIDE_SEPARATOR_PATTERN = re.compile(r"^[ \t]*---[ \t]*$")
HEADING_PATTERN = re.compile(r"^[ \t]*(#{1,6})[ \t]+")
LIST_ITEM_PATTERN = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
TABLE_DIVIDER_PATTERN = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*$"
)


class PPTLayoutOverflowError(ValueError):
    """The generated content cannot fit in a slide even after re-pagination."""


def _resolve_node_and_cli() -> tuple[Path, Path]:
    """Use the project's pinned CLI instead of depending on a global command."""
    node_candidates = [
        os.getenv("MARP_NODE_PATH"),
        str(PROJECT_ROOT / ".tools" / "node" / "node.exe"),
        str(PROJECT_ROOT / ".tools" / "node" / "bin" / "node"),
        shutil.which("node"),
    ]
    node = next(
        (
            Path(candidate)
            for candidate in node_candidates
            if candidate and Path(candidate).is_file()
        ),
        None,
    )
    cli = Path(
        os.getenv("MARP_CLI_PATH")
        or PROJECT_ROOT
        / "web"
        / "node_modules"
        / "@marp-team"
        / "marp-cli"
        / "marp-cli.js"
    )

    if node is None:
        raise RuntimeError("Node.js is unavailable; set MARP_NODE_PATH")
    if not cli.is_file():
        raise RuntimeError("Marp CLI is unavailable; install the web dependencies")
    return node, cli


def _browser_options() -> list[str]:
    """Prefer the installed Edge browser on Windows; let Marp auto-detect elsewhere."""
    configured = os.getenv("MARP_BROWSER_PATH")
    if configured:
        browser = Path(configured)
        if not browser.is_file():
            raise RuntimeError("MARP_BROWSER_PATH does not point to a browser")
        return ["--browser-path", str(browser)]

    if os.name == "nt":
        for path in (
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        ):
            if path.is_file():
                return ["--browser", "edge", "--browser-path", str(path)]
    for browser_name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "microsoft-edge-stable",
    ):
        detected = shutil.which(browser_name)
        if detected:
            return ["--browser-path", detected]
    for path in (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ):
        if path.is_file():
            return ["--browser-path", str(path)]
    return []


def _is_public_image_url(raw_url: str) -> bool:
    """Reject file URLs and direct requests to the local network."""
    try:
        parsed = urlsplit(raw_url.strip("<>"))
        host = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    host = host.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return False
    try:
        return ip_address(host).is_global
    except ValueError:
        return True


def _normalize_reference_label(label: str) -> str:
    """Match Markdown reference labels regardless of case or repeated spaces."""
    return re.sub(r"\s+", " ", label.strip()).casefold()


def _split_source_slides(markdown: str) -> list[str]:
    """Split Marp slides without mistaking a code-fence line for a separator."""
    slides: list[str] = []
    lines: list[str] = []
    fence: tuple[str, int] | None = None
    for line in markdown.splitlines():
        marker = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1]:
                fence = None
        if fence is None and SLIDE_SEPARATOR_PATTERN.fullmatch(line):
            if lines and "\n".join(lines).strip():
                slides.append("\n".join(lines).strip())
            lines = []
        else:
            lines.append(line)
    if lines and "\n".join(lines).strip():
        slides.append("\n".join(lines).strip())
    return slides


def _is_table_start(lines: list[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and "|" in lines[index]
        and bool(TABLE_DIVIDER_PATTERN.fullmatch(lines[index + 1]))
    )


def _slide_blocks(slide: str) -> list[tuple[str, str]]:
    """Keep headings, list items and whole tables as separate pagination units."""
    lines = slide.splitlines()
    blocks: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if _is_table_start(lines, index):
            end = index + 2
            while end < len(lines) and lines[end].strip() and "|" in lines[end]:
                end += 1
            blocks.append(("table", "\n".join(lines[index:end])))
            index = end
            continue
        if HEADING_PATTERN.match(line):
            blocks.append(("heading", line))
            index += 1
            continue
        if LIST_ITEM_PATTERN.match(line):
            end = index + 1
            while (
                end < len(lines)
                and lines[end].strip()
                and (
                    lines[end].startswith((" ", "\t"))
                    and not LIST_ITEM_PATTERN.match(lines[end])
                )
            ):
                end += 1
            blocks.append(("list", "\n".join(lines[index:end])))
            index = end
            continue
        if line.lstrip().startswith(">"):
            end = index + 1
            while end < len(lines) and lines[end].lstrip().startswith(">"):
                end += 1
            blocks.append(("quote", "\n".join(lines[index:end])))
            index = end
            continue
        fence = re.match(r"^[ \t]*(`{3,}|~{3,})", line)
        if fence:
            end = index + 1
            closing = re.compile(
                rf"^[ \t]*{re.escape(fence.group(1)[0])}{{{len(fence.group(1))},}}[ \t]*$"
            )
            while end < len(lines) and not closing.match(lines[end]):
                end += 1
            blocks.append(("code", "\n".join(lines[index : min(end + 1, len(lines))])))
            index = min(end + 1, len(lines))
            continue
        end = index + 1
        while (
            end < len(lines)
            and lines[end].strip()
            and not (
                HEADING_PATTERN.match(lines[end])
                or LIST_ITEM_PATTERN.match(lines[end])
                or lines[end].lstrip().startswith(">")
                or _is_table_start(lines, end)
            )
        ):
            end += 1
        blocks.append(("paragraph", "\n".join(lines[index:end])))
        index = end
    return blocks


def _text_width(text: str) -> int:
    """Approximate the width of Chinese and Latin text in the Marp theme."""
    text = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?:\*\*|__|`)", "", text)
    return sum(
        2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text
    )


def _line_count(text: str, width: int = SLIDE_TEXT_WIDTH_UNITS) -> int:
    return max(
        1,
        sum(
            max(1, (_text_width(line) + width - 1) // width)
            for line in text.splitlines()
        ),
    )


def _block_height(kind: str, content: str) -> float:
    if kind == "heading":
        level = len(HEADING_PATTERN.match(content).group(1))  # type: ignore[union-attr]
        return (2.1 if level <= 2 else 1.7) * _line_count(content)
    if kind == "list":
        return 0.2 + 1.35 * _line_count(content)
    if kind == "quote":
        return 0.5 + 1.35 * _line_count(content, 54)
    if kind == "code":
        return 0.5 + 1.2 * max(1, len(content.splitlines()) - 2)
    return 0.35 + 1.35 * _line_count(content)


def _table_parts(content: str) -> tuple[list[str], list[str]]:
    lines = content.splitlines()
    return lines[:2], lines[2:]


def _table_row_height(row: str, column_widths: list[int]) -> float:
    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    visual_lines = max(
        (
            max(1, (_text_width(cell) + width - 1) // width)
            for cell, width in zip(cells, column_widths)
        ),
        default=1,
    )
    return 0.4 + 1.25 * visual_lines


def _table_column_widths(lines: list[str]) -> list[int]:
    cells = [
        [cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines
    ]
    count = max(map(len, cells), default=1)
    weights = [
        max(
            6,
            max(
                (_text_width(row[index]) for row in cells if len(row) > index),
                default=0,
            ),
        )
        for index in range(count)
    ]
    total = sum(weights)
    return [max(6, int(SLIDE_TEXT_WIDTH_UNITS * weight / total)) for weight in weights]


def _paginate_slide(
    slide: str, max_height_units: float = MAX_SLIDE_HEIGHT_UNITS
) -> list[str]:
    blocks = _slide_blocks(slide)
    if not blocks:
        return []

    # 中文注释：续页重复主标题，让拆开的内容仍能看出属于哪个主题。
    main_heading = (
        blocks[0][1]
        if blocks[0][0] == "heading" and blocks[0][1].lstrip().startswith("## ")
        else None
    )
    pages: list[list[str]] = [[]]
    height = 0.0
    active_subheading: str | None = None

    def has_body() -> bool:
        return any(not HEADING_PATTERN.match(part) for part in pages[-1])

    def new_page(repeat_subheading: bool = False) -> None:
        nonlocal height
        titles = [main_heading] if main_heading else []
        if repeat_subheading and active_subheading:
            titles.append(active_subheading)
        pages.append(titles)
        height = _block_height("heading", main_heading) if main_heading else 0.0
        if repeat_subheading and active_subheading:
            height += _block_height("heading", active_subheading)

    for index, (kind, content) in enumerate(blocks):
        # 主标题已经随当前页或续页出现，无需重复插入。
        if (
            kind == "heading"
            and content == main_heading
            and index != 0
            and pages[-1]
            and pages[-1][0] == content
        ):
            continue
        if kind == "heading" and content.lstrip().startswith("### "):
            group_height = _block_height(kind, content)
            for next_kind, next_content in blocks[index + 1 :]:
                if next_kind == "heading":
                    break
                if next_kind == "table":
                    header, rows = _table_parts(next_content)
                    widths = _table_column_widths([header[0], *rows])
                    group_height += _table_row_height(header[0], widths)
                    group_height += sum(_table_row_height(row, widths) for row in rows)
                else:
                    group_height += _block_height(next_kind, next_content)
            if has_body() and height + group_height > max_height_units:
                new_page()
            active_subheading = content
        if kind == "table":
            header, rows = _table_parts(content)
            widths = _table_column_widths([header[0], *rows])
            header_height = _table_row_height(header[0], widths)
            if not rows:
                if has_body() and height + header_height > max_height_units:
                    new_page(repeat_subheading=True)
                pages[-1].append(content)
                height += header_height
                continue
            row_heights = [_table_row_height(row, widths) for row in rows]
            if (
                has_body()
                and height + header_height + sum(row_heights) > max_height_units
            ):
                new_page(repeat_subheading=True)
            current_rows: list[str] = []
            for row, row_height in zip(rows, row_heights):
                if current_rows and height + row_height > max_height_units:
                    pages[-1].append("\n".join([*header, *current_rows]))
                    new_page(repeat_subheading=True)
                    current_rows = []
                if not current_rows:
                    height += header_height
                current_rows.append(row)
                height += row_height
            if current_rows:
                pages[-1].append("\n".join([*header, *current_rows]))
            continue

        block_height = _block_height(kind, content)
        if has_body() and height + block_height > max_height_units:
            new_page(repeat_subheading=kind != "heading")
        pages[-1].append(content)
        height += block_height

    return ["\n\n".join(page) for page in pages if page]


def _paginate_markdown(
    markdown: str, max_height_units: float = MAX_SLIDE_HEIGHT_UNITS
) -> str:
    slides = [
        page
        for slide in _split_source_slides(markdown)
        for page in _paginate_slide(slide, max_height_units)
    ]
    return "\n\n---\n\n".join(slides)


def _prepare_markdown(
    content: str, max_height_units: float = MAX_SLIDE_HEIGHT_UNITS
) -> str:
    """Ensure AI Markdown is treated as Marp slides, including fenced output."""
    markdown = content.strip()
    if not markdown:
        raise ValueError("Presentation content cannot be empty")
    if len(markdown) > MAX_SLIDE_MARKDOWN_CHARS:
        raise ValueError("Presentation Markdown is too long")

    fenced = re.fullmatch(
        r"```(?:markdown|md)?\s*\n(.*?)\n```", markdown, re.DOTALL | re.IGNORECASE
    )
    if fenced:
        markdown = fenced.group(1).strip()

    # 中文注释：去掉可触发浏览器加载资源的原始 HTML 与 Marp 指令。
    markdown = MEDIA_BLOCK_PATTERN.sub("", markdown)
    markdown = MEDIA_TAG_PATTERN.sub("", markdown)
    markdown = re.sub(r"(?s)<!--.*?-->", "", markdown)
    # 中文注释：默认移除所有图片 URL，避免浏览器转换时访问用户资料中的未知地址。
    allow_remote_images = (
        os.getenv("MARP_ALLOW_REMOTE_IMAGES", "false").lower() == "true"
    )
    markdown = IMAGE_PATTERN.sub(
        lambda match: (
            match.group(0)
            if allow_remote_images and _is_public_image_url(match.group(2).split()[0])
            else match.group(1)
        ),
        markdown,
    )
    # 引用式图片可经定义行间接加载；图片标记和对应定义都不传给浏览器。
    image_labels = {
        _normalize_reference_label(match.group(2) or match.group(1))
        for match in IMAGE_REFERENCE_PATTERN.finditer(markdown)
    }
    image_labels.update(
        _normalize_reference_label(match.group(1))
        for match in IMAGE_SHORTCUT_PATTERN.finditer(markdown)
    )
    markdown = IMAGE_REFERENCE_PATTERN.sub(lambda match: match.group(1), markdown)
    markdown = IMAGE_SHORTCUT_PATTERN.sub(lambda match: match.group(1), markdown)
    safe_lines = []
    for line in markdown.splitlines():
        definition = REFERENCE_DEFINITION_PATTERN.match(line)
        if (
            definition
            and _normalize_reference_label(definition.group(1)) in image_labels
        ):
            continue
        safe_lines.append(line)
    markdown = "\n".join(safe_lines)

    frontmatter = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", markdown, re.DOTALL)
    metadata_body = frontmatter.group(1) if frontmatter else ""
    metadata_key = re.search(r"(?m)^[ \t]*[A-Za-z_][\w-]*[ \t]*:", metadata_body)
    slide_heading = re.search(r"(?m)^[ \t]*#{1,6}[ \t]+", metadata_body)
    marp_directive = re.search(
        r"(?im)^[ \t]*(?:marp|theme|size|paginate|header|footer|style|"
        r"backgroundImage|backgroundColor|color|transition|math)[ \t]*:",
        metadata_body,
    )
    if frontmatter and (marp_directive or (metadata_key and not slide_heading)):
        # 只保留服务端自建的 frontmatter，避免模型覆盖主题或指定背景图片。
        markdown = markdown[frontmatter.end() :].lstrip()
    else:
        # 开头的分隔线是首张幻灯片的标记，避免它在服务端 frontmatter 后生成空白页。
        markdown = re.sub(r"\A---[ \t]*\n", "", markdown, count=1)

    return f"---\nmarp: true\n---\n\n{_paginate_markdown(markdown, max_height_units)}\n"


def _run_marp(command: list[str], workdir: Path) -> None:
    """Run the trusted CLI with a bounded execution time."""
    try:
        subprocess.run(
            command,
            cwd=workdir,
            check=True,
            capture_output=True,
            text=True,
            timeout=MARP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("PPT conversion timed out") from exc
    except subprocess.CalledProcessError as exc:
        reason = (exc.stderr or exc.stdout or "Marp CLI exited with an error").strip()
        raise RuntimeError(f"PPT conversion failed: {reason[-500:]}") from exc


def _inspect_slide_layout(
    node: Path, cli: Path, html: Path, browser_options: list[str], workdir: Path
) -> list[int]:
    """Use the same browser as Marp to detect content beyond the slide canvas."""
    browser_path = ""
    if "--browser-path" in browser_options:
        browser_path = browser_options[browser_options.index("--browser-path") + 1]
    command = [
        str(node),
        str(LAYOUT_CHECK_SCRIPT),
        str(cli),
        str(html),
        browser_path,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        inspection = json.loads(result.stdout)
        if not isinstance(inspection, dict) or not isinstance(
            inspection.get("overflow_slides"), list
        ):
            raise TypeError("Layout checker returned an invalid result")
        return [int(index) for index in inspection["overflow_slides"]]
    except (
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError("PPT layout inspection failed") from exc


def render_marp_pptx(content: str, theme: str = "default") -> bytes:
    """Convert slide Markdown into PPTX bytes and remove every temporary file."""
    if theme not in PPT_THEMES:
        raise ValueError(f"Unsupported presentation theme: {theme}")

    node, cli = _resolve_node_and_cli()
    theme_option = str(CUSTOM_THEMES[theme]) if theme in CUSTOM_THEMES else theme
    with tempfile.TemporaryDirectory(prefix="deerflow-ppt-") as directory:
        workdir = Path(directory)
        source = workdir / "slides.md"
        html = workdir / "slides.html"
        output = workdir / "slides.pptx"

        base_command = [
            str(node),
            str(cli),
            str(source),
            "--no-config-file",
            "--no-html",
            "--no-allow-local-files",
            "--theme",
            theme_option,
        ]
        browser_options = _browser_options()
        # 中文注释：用同一主题先渲染 HTML 并测量实际文字边界，避免交付被裁切的 PPT。
        overflow_slides: list[int] = []
        for height_budget in (MAX_SLIDE_HEIGHT_UNITS, RETRY_SLIDE_HEIGHT_UNITS):
            source.write_text(
                _prepare_markdown(content, max_height_units=height_budget),
                encoding="utf-8",
            )
            _run_marp([*base_command, "-o", str(html)], workdir)
            overflow_slides = _inspect_slide_layout(
                node, cli, html, browser_options, workdir
            )
            if not overflow_slides:
                break
        if overflow_slides:
            pages = ", ".join(str(index) for index in overflow_slides[:8])
            raise PPTLayoutOverflowError(
                f"PPT 第 {pages} 页内容超出画布，请缩短长段落或表格后重试"
            )

        command = [
            *base_command,
            "--browser-timeout",
            "60",
            *browser_options,
            "-o",
            str(output),
        ]
        _run_marp(command, workdir)

        if not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError("Marp CLI did not create a PPTX file")
        # 中文注释：扩展名正确还不够，确认生成的是可打开的 PPTX 压缩包。
        with zipfile.ZipFile(output) as presentation:
            if "ppt/presentation.xml" not in presentation.namelist():
                raise RuntimeError("Marp CLI created an invalid PPTX file")
        return output.read_bytes()
