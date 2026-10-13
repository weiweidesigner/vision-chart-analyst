#!/usr/bin/env python3
"""Read a chart screenshot with a multimodal model and return visual insights."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
MODEL_API_KEY_ENV_NAMES = ("VISION_API_KEY", "DEEPSEEK_API_KEY", "ARK_API_KEY", "VOLCANO_API_KEY", "VOLCENGINE_API_KEY")


def model_api_key() -> str:
    local_config = os.getenv("VISION_CONFIG_FILE", "").strip()
    if local_config:
        load_dotenv(Path(local_config).expanduser(), override=False)
    for env_name in MODEL_API_KEY_ENV_NAMES:
        value = os.getenv(env_name)
        if value:
            return value
    return ""


def parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def plain_text_excerpt(text: str, limit: int = 360) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def language_rule(language: str) -> str:
    return {
        "en": "Write natural English only.",
        "ja": "Write natural Japanese only.",
        "ko": "Write natural Korean only.",
        "th": "Write natural Thai only.",
        "zh-Hant": "Write Traditional Chinese only. Do not use Simplified Chinese.",
        "zh-CN": "Write Simplified Chinese only.",
        "es": "Write natural Spanish only.",
        "fr": "Write natural French only.",
        "de": "Write natural German only.",
        "pt": "Write natural Portuguese only.",
    }.get(language, "Write in the same language as the user question.")


def read_context(args: argparse.Namespace) -> str:
    chunks: list[str] = []
    if args.context_file:
        path = Path(args.context_file).expanduser()
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    if args.context_text:
        chunks.append(str(args.context_text))
    return "\n\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def model_client() -> OpenAI:
    api_key = model_api_key()
    if not api_key:
        raise RuntimeError("未配置 VISION_API_KEY（或兼容模型密钥），无法执行图像理解。")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("VISION_BASE_URL", os.getenv("VOLCANO_VISION_BASE_URL", os.getenv("VOLCANO_BASE_URL", DEFAULT_BASE_URL))),
        timeout=float(os.getenv("VISION_TIMEOUT_SECONDS", os.getenv("VOLCANO_VISION_TIMEOUT_SECONDS", "60"))),
    )


def render_html_to_image(path: Path, render_dir: Path) -> Path:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
    except ImportError as exc:
        raise RuntimeError("缺少 Playwright，无法将 HTML 渲染为图片。") from exc

    render_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}".encode("utf-8")).hexdigest()[:12]
    output = render_dir / f"{path.stem}-{fingerprint}.png"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        page.goto(path.as_uri(), wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except PlaywrightTimeoutError:
            pass
        # Business components can be transparent in the product UI. Vision input
        # still needs a deterministic light canvas so dark text never gets
        # composited onto a dark/transparent decoder background.
        page.add_style_tag(content="html, body { background: #ffffff !important; }")
        try:
            page.wait_for_function(
                """
                () => {
                  const visual = document.querySelector('canvas, svg, #chart, #wrap, .chart-container, .component-root, main');
                  if (!visual) return false;
                  const rect = visual.getBoundingClientRect();
                  return rect.width >= 120 && rect.height >= 60;
                }
                """,
                timeout=20000,
            )
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(700)
        target = None
        for selector in (
            "#wrap",
            "[data-timeline-container='true']",
            ".component-root",
            ".chart-container",
            ".yahoo-card",
            "main",
        ):
            locator = page.locator(selector).first
            try:
                if locator.count() and locator.bounding_box():
                    target = locator
                    break
            except Exception:
                continue
        if target is None:
            page.screenshot(path=str(output), full_page=True, animations="disabled")
        else:
            target.screenshot(path=str(output), animations="disabled")
        browser.close()
    if not output.is_file():
        raise RuntimeError(f"HTML 渲染截图失败：{path}")
    return output


def chart_completion(client: OpenAI, prompt: str, image_path: Path, *, retry: bool = False) -> tuple[str, str]:
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                image_content(str(image_path)),
            ],
        }
    ]
    kwargs: dict[str, Any] = {
        "model": os.getenv("VISION_MODEL_NAME", os.getenv("VOLCANO_VISION_MODEL", os.getenv("ARK_VISION_MODEL", DEFAULT_MODEL))),
        "messages": messages,
        "temperature": 0.0 if retry else 0.2,
        "max_tokens": 6000 if retry else 4000,
    }
    if not retry:
        kwargs["response_format"] = {"type": "json_object"}
    completion = client.chat.completions.create(**kwargs)
    choice = completion.choices[0]
    raw = choice.message.content or ""
    finish_reason = str(getattr(choice, "finish_reason", "") or "")
    return raw, finish_reason


def materialize_visual_input(path: str, render_dir: Path) -> Path:
    source = Path(path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise RuntimeError(f"输入文件不存在：{source}")
    if source.suffix.lower() == ".html":
        return render_html_to_image(source, render_dir)
    return source


def image_content(path: str) -> dict[str, Any]:
    image_path = Path(path).expanduser().resolve()
    if not image_path.exists():
        raise RuntimeError(f"图像文件不存在：{image_path}")
    image_base64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    suffix = image_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{image_base64}",
            "detail": os.getenv("VISION_IMAGE_DETAIL", "original"),
        },
    }


def analyze_chart(args: argparse.Namespace) -> dict[str, Any]:
    if not args.image:
        raise RuntimeError("chart 模式必须提供 --image。")
    render_dir = Path(args.render_dir).expanduser().resolve()
    image_path = materialize_visual_input(args.image, render_dir)

    context = read_context(args)
    analysis_focus = (
        "For technical-analysis charts (including kline), assess price structure, moving-average position, "
        "momentum indicators, volume confirmation, visible support/resistance, and the conditions that would "
        "confirm or invalidate the current pattern. Keep every statement consistent with visible numeric labels.\n"
        "For capital-flow charts (including trade_flow, volume_profile, and order flow), explain the dominant "
        "flow direction, which order-size groups contribute most, intraday turning points, and divergence or "
        "confirmation between flow and price. Rank order-size contribution by each row's net flow (inflow minus "
        "outflow), never by its gross inflow or gross outflow bar alone. When the row values are legible, calculate "
        "the four net contributions and include them in latestVisibleValues so the ranking can be checked. Order-size "
        "buckets do not identify institutions, main funds, or retail traders. Do not report sample counts, do not "
        "spell out arithmetic formulas, and do not turn field names into analysis.\n"
    )
    prompt = (
        "You are a senior financial analyst who looks at charts to spot investment-relevant signals.\n"
        f"{language_rule(args.language)}\n"
        "Your job is to read the chart visually, not just restate the raw payload.\n"
        "Focus on: the latest visible period, direction changes, inflection points, divergence between series, "
        "outliers, volume/turnover/liquidity confirmation, and what an investor should pay attention to next.\n"
        "For time-series charts, explicitly identify the rightmost visible x-axis label or rightmost plotted point as latestVisiblePeriod. "
        "Include latestVisibleValues only when an explicit value label or tooltip is attached to the rightmost plotted point. "
        "Never copy a y-axis tick as a latest value and never estimate a latest value from the axis scale; otherwise leave the array empty "
        "and omit that numeric latest value from the summary. "
        "Use historical performance only as reference context for the latest visible state.\n"
        "Also validate whether the rendered business component visibly contains usable business data. "
        "Set hasUsableData=false only when the component is blank, explicitly says no data/unavailable/error, "
        "or contains only titles, axes, legends, placeholders, loading states, or empty table/chart scaffolding. "
        "Do not mark it empty merely because a value is difficult to read. Set dataStatus to ok, empty, or error.\n"
        "Do not mention screenshots, images, models, OCR, HTML, or system steps.\n"
        "Do not give absolute buy/sell instructions.\n"
        f"{analysis_focus}"
        "Return JSON only in the shape {\"summary\":\"...\",\"hasUsableData\":true,\"dataStatus\":\"ok\","
        "\"latestVisiblePeriod\":\"...\",\"latestVisibleValues\":[{\"series\":\"...\",\"value\":\"...\"}]}.\n"
        "The summary must be 2-4 sentences, written for humans, grounded in what is visible in the chart.\n\n"
        f"User question: {args.question}\n"
        f"Module: {args.module_label} ({args.script})\n"
        f"Code: {args.code}\n"
        f"Structured context:\n{context[:12000]}"
    )
    client = model_client()
    raw, finish_reason = chart_completion(client, prompt, image_path)
    parsed = parse_json_object(raw)
    summary = str((parsed or {}).get("summary") or "").strip()
    if not summary:
        retry_prompt = (
            f"{language_rule(args.language)}\n"
            "直接阅读图表并回答用户问题。不要描述执行过程、数据抓取、渲染、截图、模型或工具。"
            "资金流图必须判断净流入或净流出、主要订单档位、盘中转折，以及资金与股价是否同向；"
            "订单档位贡献必须按每档流入减流出的净额排序，不能按流入或流出总额排序；可读时把各档净额写入 latestVisibleValues。"
            "订单档位不等于机构、主力或散户，不得推断交易者身份。"
            "技术图必须判断趋势、量价或指标确认和关键条件。只使用图中可见证据，不编造原因。"
            "右端最新数值只有在数据点有明确标签或 tooltip 时才可写；不能把纵轴刻度当作最新值，也不能估算。"
            "返回一个 JSON 对象，summary 必须是非空的 2-4 句用户结论；同时返回 "
            "hasUsableData、dataStatus、latestVisiblePeriod、latestVisibleValues。\n"
            f"用户问题：{args.question}\n模块：{args.module_label}（{args.script}）\n代码：{args.code}"
        )
        raw, retry_finish_reason = chart_completion(client, retry_prompt, image_path, retry=True)
        parsed = parse_json_object(raw)
        summary = str((parsed or {}).get("summary") or "").strip()
        finish_reason = retry_finish_reason or finish_reason
    if not summary:
        raise RuntimeError(f"多模态模型未返回可用的图表结论（finish_reason={finish_reason or 'unknown'}）。")
    raw_has_usable_data = (parsed or {}).get("hasUsableData")
    has_usable_data = raw_has_usable_data if isinstance(raw_has_usable_data, bool) else None
    data_status = str((parsed or {}).get("dataStatus") or "").strip().lower()
    if data_status not in {"ok", "empty", "error"}:
        data_status = "ok" if summary else ""
    latest_period = str((parsed or {}).get("latestVisiblePeriod") or "").strip()
    latest_values = (parsed or {}).get("latestVisibleValues")
    if not isinstance(latest_values, list):
        latest_values = []
    normalized_values = []
    for item in latest_values[:8]:
        if isinstance(item, dict):
            series = str(item.get("series") or item.get("label") or "").strip()
            value = str(item.get("value") or "").strip()
            if series or value:
                normalized_values.append({"series": series, "value": value})
    return {
        "script": args.script,
        "summary": summary,
        "hasUsableData": has_usable_data,
        "dataStatus": data_status,
        "latestVisiblePeriod": latest_period,
        "latestVisibleValues": normalized_values,
        "renderedImage": str(image_path),
    }


def analyze_uploaded(args: argparse.Namespace) -> dict[str, Any]:
    images = args.images or ([args.image] if args.image else [])
    if not images:
        raise RuntimeError("uploaded 模式必须提供至少一个 --image。")
    prompt = (
        "你是多模态信息识别工具。请结合用户问句读取上传图片，抽取后续分析可直接使用的信息。\n"
        "要求：只描述图片中真实可见或可识别的内容；不要编造，不要评价图片质量。\n"
        "如果图片包含图表，必须优先识别图表标题/名称、图表类型、坐标轴、图例/系列名称、时间/分类和值；"
        "图表标题必须来自图片中可见文本，不能根据数据自行改写或生成；如果看不清标题，chartTitle 返回空字符串并在 details 说明。\n"
        "如果用户要求重绘，chartTitle、chartType、seriesNames 和 extractedData 是后续选择图表组件的依据，必须尽量准确。\n"
        "如果图片包含表格，也要保留表头、行列含义和单元格数值。\n"
        "返回 JSON，格式为 "
        "{\"summary\":\"...\",\"chartTitle\":\"\",\"chartType\":\"\",\"xAxis\":\"\",\"yAxis\":\"\","
        "\"seriesNames\":[\"...\"],\"legend\":[\"...\"],\"details\":[\"...\"],\"extractedData\":[...]}。\n\n"
        f"用户问句：{args.question}"
    )
    render_dir = Path(args.render_dir).expanduser().resolve()
    rendered_images = [materialize_visual_input(image, render_dir) for image in images[:6]]
    client = model_client()

    def complete(request_prompt: str, *, retry: bool) -> tuple[str, str, str]:
        content: list[dict[str, Any]] = [{"type": "text", "text": request_prompt}]
        for image in rendered_images:
            content.append(image_content(str(image)))
        kwargs: dict[str, Any] = {
            "model": os.getenv("VISION_MODEL_NAME", os.getenv("VOLCANO_VISION_MODEL", os.getenv("ARK_VISION_MODEL", DEFAULT_MODEL))),
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0 if retry else 0.1,
            "max_tokens": 6000 if retry else 4000,
        }
        if not retry:
            kwargs["response_format"] = {"type": "json_object"}
        completion = client.chat.completions.create(**kwargs)
        choice = completion.choices[0]
        message = choice.message
        return (
            str(message.content or ""),
            str(getattr(choice, "finish_reason", "") or ""),
            str(getattr(message, "refusal", "") or ""),
        )

    def payload_from_raw(raw: str) -> dict[str, Any]:
        parsed = parse_json_object(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"summary": plain_text_excerpt(raw, limit=1800)}

    raw, finish_reason, refusal = complete(prompt, retry=False)
    parsed = payload_from_raw(raw)
    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        retry_prompt = (
            "请直接读取上传图片并返回 JSON，不要描述执行过程。"
            "summary 必须是非空的 2-4 句结论；若包含图表，同时尽量返回 chartTitle、chartType、"
            "xAxis、yAxis、seriesNames、legend、details 和 extractedData。"
            "只写图片中真实可见的信息，不得编造。\n\n"
            f"用户问句：{args.question}"
        )
        raw, retry_finish_reason, retry_refusal = complete(retry_prompt, retry=True)
        parsed = payload_from_raw(raw)
        summary = str(parsed.get("summary") or "").strip()
        finish_reason = retry_finish_reason or finish_reason
        refusal = retry_refusal or refusal
    if not summary:
        refusal_note = f"，refusal={plain_text_excerpt(refusal, 160)}" if refusal else ""
        raise RuntimeError(
            f"多模态模型未返回可用的图片结论（finish_reason={finish_reason or 'unknown'}{refusal_note}）。"
        )

    parsed["summary"] = summary
    for key, default_value in (
        ("chartTitle", ""),
        ("chartType", ""),
        ("xAxis", ""),
        ("yAxis", ""),
        ("seriesNames", []),
        ("legend", []),
        ("details", []),
        ("extractedData", []),
    ):
        parsed.setdefault(key, default_value)
    parsed["renderedImages"] = [str(path) for path in rendered_images]
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Multimodal chart visual insight analyzer.")
    parser.add_argument("--mode", choices=("chart", "uploaded"), default="chart")
    parser.add_argument("--question", required=True)
    parser.add_argument("--image")
    parser.add_argument("--images", action="append", default=[])
    parser.add_argument("--module-label", default="")
    parser.add_argument("--script", default="uploaded_image_vision")
    parser.add_argument("--code", default="")
    parser.add_argument("--context-file")
    parser.add_argument("--context-text")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--output")
    parser.add_argument("--render-dir", default=os.getenv("VISION_RENDER_DIR", "/tmp/aime-chart-vision"))
    args = parser.parse_args()

    result = analyze_uploaded(args) if args.mode == "uploaded" else analyze_chart(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
