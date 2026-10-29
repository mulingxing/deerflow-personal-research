"""PPT conversion boundaries without calling a language model or browser."""

from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ppt import service
from src.ppt.graph import ppt_generator_node as generator_module
from src.prompts.template import get_prompt_template
from src.server.chat_request import GeneratePPTRequest


def test_markdown_removes_images_and_model_theme_by_default():
    source = """---
marp: true
theme: gaia
---
# 测试
![网页图片](https://example.com/photo.png)
![本地文件](file:///C:/private/notes.png)
![内网图片](http://127.0.0.1/private.png)
<!-- theme: uncover -->
<!-- backgroundImage: https://example.com/background.png -->
<style>section { background-image: url(https://example.com/style.png); }</style>
"""

    result = service._prepare_markdown(source)

    assert "marp: true" in result
    assert "theme:" not in result
    assert "https://example.com/photo.png" not in result
    assert "网页图片" in result
    assert "file:///" not in result
    assert "127.0.0.1" not in result
    assert "background.png" not in result
    assert "style.png" not in result
    assert "本地文件" in result


def test_remote_images_require_explicit_opt_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MARP_ALLOW_REMOTE_IMAGES", "true")
    result = service._prepare_markdown(
        "![公开](https://example.com/image.png) ![本地](file:///C:/private.png)"
    )

    assert "https://example.com/image.png" in result
    assert "file:///" not in result


def test_reference_images_and_html_media_cannot_load_resources():
    source = """---
marp: true
theme: gaia
backgroundImage: https://example.com/yaml.png
---
![图表][chart]
![速记图]
[chart]: https://example.com/chart.png
[速记图]: https://example.com/shortcut.png
<picture><source srcset="https://example.com/picture.png"><img src="https://example.com/photo.png"></picture>
<video poster="https://example.com/poster.png"><source src="https://example.com/video.mp4"></video>
<source srcset="https://example.com/standalone.png">
"""

    result = service._prepare_markdown(source)

    assert result.startswith("---\nmarp: true\n---")
    assert "theme:" not in result
    assert "backgroundImage:" not in result
    assert "![" not in result
    assert "<picture" not in result
    assert "<video" not in result
    assert "<source" not in result
    assert "poster.png" not in result
    assert "picture.png" not in result
    assert "chart.png" not in result
    assert "shortcut.png" not in result
    assert "图表" in result


def test_reference_images_remain_disabled_after_remote_opt_in(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MARP_ALLOW_REMOTE_IMAGES", "true")
    result = service._prepare_markdown(
        "![图表][chart]\n\n[chart]: https://example.com/chart.png"
    )

    assert "![" not in result
    assert "图表" in result
    assert "chart.png" not in result


def test_image_references_match_case_and_spacing_without_removing_text_links():
    result = service._prepare_markdown(
        "![引用图][Chart   One]\n"
        "[chart one]: https://example.com/image.png\n"
        "[普通链接][read]\n"
        "[read]: https://example.com/article"
    )

    assert "image.png" not in result
    assert "引用图" in result
    assert "[read]: https://example.com/article" in result


def test_leading_slide_separator_does_not_remove_the_title_slide():
    result = service._prepare_markdown(
        "---\n# 第一页标题\n目标: 讲清楚项目\n---\n# 第二页标题"
    )

    assert result.startswith("---\nmarp: true\n---\n\n# 第一页标题")
    assert "# 第一页标题" in result
    assert "目标: 讲清楚项目" in result
    assert "# 第二页标题" in result


def test_dense_quote_and_table_are_paginated_without_losing_rows():
    # 第 4 页类型：引文、三行表格和补充说明挤在同一页。
    source = """## 三、三个步骤的原文表述

资料中“三步复习法”小节原文：

> 第一步，用自己的话复述本周概念；第二步，从笔记中找出一条支持该概念的证据；第三步，写下仍然不理解的问题，留到下一次讨论。

| 步骤 | 原文表述 | 结构完整性评估 |
| --- | --- | --- |
| 第一步 | 用自己的话复述本周概念 | 动作（复述）＋方式（用自己的话）＋对象（本周概念），表述完整 |
| 第二步 | 从笔记中找出一条支持该概念的证据 | 来源（笔记）＋数量（一条）＋对象（支持该概念的证据），表述完整 |
| 第三步 | 写下仍然不理解的问题，留到下一次讨论 | 动作（写下）＋对象（仍不理解的问题）＋后续处置（留到下一次讨论），表述完整 |

- 三步为连续一句叙述，未单独设置小标题。"""

    pages = service._paginate_slide(source)

    assert len(pages) >= 3
    assert pages[0].startswith("## 三、三个步骤的原文表述")
    assert "| 步骤 | 原文表述 | 结构完整性评估 |" not in pages[0]
    for step in ("第一步", "第二步", "第三步"):
        assert sum(f"| {step} |" in page for page in pages) == 1
    for page in pages:
        if "| 第" in page:
            assert "| 步骤 | 原文表述 | 结构完整性评估 |" in page
    assert "- 三步为连续一句叙述，未单独设置小标题。" in pages[-1]


def test_dense_subsections_move_to_continuation_slides_with_context():
    # 第 8 页类型：方法、局限性和引用义务连续排版。
    source = """## 调查说明

### 方法论与数据处理

- 限定范围检索：不联网、不引入外部来源
- 逐字摘录原文，不作改写
- 按“动作＋对象（＋方式或处置）”结构逐项评估表述完整性

### 局限性讨论

- 定位精度受限：无页码，出处仅精确至小节级
- 文本厚度有限：一句话概括，方法来源、理论依据、示例与判定标准均缺失
- 性质限定：虚构文本内的一致性结论，不具备作为真实学习方法依据的效力

### 引用义务

依“资料使用约定”：回答关于本学习小组的问题应优先引用本资料；资料无答案时应明确说明没有找到，不得以常识补全。"""

    pages = service._paginate_slide(source)

    assert len(pages) >= 2
    assert all(page.startswith("## 调查说明") for page in pages)
    assert "### 引用义务" not in pages[0]
    for page in pages:
        if "- 性质限定" in page:
            assert "### 局限性讨论" in page
        if "依“资料使用约定”" in page:
            assert "### 引用义务" in page


def test_large_table_does_not_leave_a_title_only_slide():
    source = """## 对照表

| 项目 | 说明 | 备注 |
| --- | --- | --- |
| 甲 | 很长的说明文字用于测试表格分页 | 很长的备注文字用于测试表格分页 |
| 乙 | 很长的说明文字用于测试表格分页 | 很长的备注文字用于测试表格分页 |
| 丙 | 很长的说明文字用于测试表格分页 | 很长的备注文字用于测试表格分页 |
| 丁 | 很长的说明文字用于测试表格分页 | 很长的备注文字用于测试表格分页 |
| 戊 | 很长的说明文字用于测试表格分页 | 很长的备注文字用于测试表格分页 |"""

    pages = service._paginate_slide(source)

    assert len(pages) >= 2
    assert all("| 项目 | 说明 | 备注 |" in page for page in pages)
    assert all(page != "## 对照表" for page in pages)
    for item in "甲乙丙丁戊":
        assert sum(f"| {item} |" in page for page in pages) == 1


def test_slide_separator_inside_fenced_code_is_not_paginated():
    slides = service._split_source_slides(
        "# 示例\n\n```markdown\n---\n## 文本\n```\n\n---\n\n## 下一页"
    )

    assert len(slides) == 2
    assert "```markdown\n---\n## 文本\n```" in slides[0]


def test_chinese_ppt_prompt_explicitly_requests_chinese():
    prompt = get_prompt_template("ppt/ppt_composer", locale="zh-CN")

    assert "始终使用中文输出" in prompt
    assert "{{ locale }}" not in prompt


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/secret.txt",
        "../assets/image.png",
        "http://localhost/private.png",
        "https://192.168.1.3/private.png",
        "https://[broken",
    ],
)
def test_local_image_urls_are_rejected(url: str):
    assert not service._is_public_image_url(url)


def test_unlisted_theme_is_rejected_before_running_cli():
    with pytest.raises(ValueError, match="Unsupported presentation theme"):
        service.render_marp_pptx("# Slide", "../../private.css")


def test_request_accepts_only_known_themes():
    assert GeneratePPTRequest(content="Study notes", theme="paper").theme == "paper"
    with pytest.raises(ValidationError):
        GeneratePPTRequest(content="Study notes", theme="../private.css")


def test_cli_failure_removes_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    original_temporary_directory = service.tempfile.TemporaryDirectory

    def temporary_directory(*args, **kwargs):
        return original_temporary_directory(*args, dir=tmp_path, **kwargs)

    def failed_conversion(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "marp", stderr="bad input")

    monkeypatch.setattr(service.tempfile, "TemporaryDirectory", temporary_directory)
    monkeypatch.setattr(
        service, "_resolve_node_and_cli", lambda: (Path("node"), Path("marp.js"))
    )
    monkeypatch.setattr(service, "_browser_options", list)
    monkeypatch.setattr(service.subprocess, "run", failed_conversion)

    with pytest.raises(RuntimeError, match="bad input"):
        service.render_marp_pptx("# Slide", "default")

    assert list(tmp_path.iterdir()) == []


def test_layout_overflow_retries_before_generating_pptx(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    inspected = iter([[2], []])

    def fake_marp(command: list[str], _workdir: Path) -> None:
        output = Path(command[-1])
        calls.append(output.suffix)
        if output.suffix == ".pptx":
            with zipfile.ZipFile(output, "w") as deck:
                deck.writestr("ppt/presentation.xml", "<presentation/>")

    monkeypatch.setattr(
        service, "_resolve_node_and_cli", lambda: (Path("node"), Path("marp.js"))
    )
    monkeypatch.setattr(service, "_browser_options", list)
    monkeypatch.setattr(service, "_run_marp", fake_marp)
    monkeypatch.setattr(
        service, "_inspect_slide_layout", lambda *_args: next(inspected)
    )

    result = service.render_marp_pptx("## 测试\n\n- 一\n- 二", "paper")

    assert calls == [".html", ".html", ".pptx"]
    with zipfile.ZipFile(io.BytesIO(result)) as deck:
        assert "ppt/presentation.xml" in deck.namelist()


def test_unbreakable_overflow_is_rejected_instead_of_exported(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []
    monkeypatch.setattr(
        service, "_resolve_node_and_cli", lambda: (Path("node"), Path("marp.js"))
    )
    monkeypatch.setattr(service, "_browser_options", list)
    monkeypatch.setattr(
        service,
        "_run_marp",
        lambda command, _workdir: calls.append(Path(command[-1]).suffix),
    )
    monkeypatch.setattr(service, "_inspect_slide_layout", lambda *_args: [1])

    with pytest.raises(service.PPTLayoutOverflowError, match="第 1 页内容超出画布"):
        service.render_marp_pptx("## 过长\n\n" + "长段落" * 500, "paper")

    assert calls == [".html", ".html"]


def test_generator_passes_selected_theme(monkeypatch: pytest.MonkeyPatch):
    captured = []

    def fake_renderer(content: str, theme: str) -> bytes:
        captured.append((content, theme))
        return b"pptx"

    monkeypatch.setattr(generator_module, "render_marp_pptx", fake_renderer)

    result = generator_module.ppt_generator_node(
        {"ppt_content": "# Slide", "theme": "paper"}
    )

    assert captured == [("# Slide", "paper")]
    assert result == {"ppt_bytes": b"pptx"}
