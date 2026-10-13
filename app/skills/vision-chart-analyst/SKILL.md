---
name: vision-chart-analyst
description: Multimodal chart understanding skill. Accept chart HTML directly or image files, render HTML to a screenshot when needed, and read visible chart trends, inflection points, outliers, divergences, and investor-relevant signals.
---

# Vision Chart Analyst

Use `scripts/vision_chart_analyst.py` to read chart HTML directly, a rendered chart screenshot, or user-uploaded images. HTML input is opened in headless Chromium, allowed to finish rendering, captured at the chart component's real height, and then sent to the vision model.

This skill does not generate charts and does not fetch financial data. It consumes:

- the user question,
- a chart HTML file or screenshot,
- the chart module name/script/code,
- optional structured payload context.

## Script

- `vision_chart_analyst.py`: renders HTML when required, calls the configured multimodal model, and writes a JSON summary.

## Modes

- `--mode chart`: read one chart HTML/image and produce `{script, summary, renderedImage}`.
- `--mode uploaded`: read one or more HTML/image inputs and extract reusable visual/table/chart information.

## Common Arguments

- `--question`: original user request.
- `--image`: HTML/PNG/JPEG/GIF/WebP path for chart mode or a single uploaded input.
- `--images`: repeatable HTML/image paths for uploaded mode.
- `--module-label`: chart/component display label.
- `--script`: source chart script filename.
- `--code`: ticker or route code.
- `--context-file`: optional text file containing structured payload context.
- `--context-text`: optional inline context.
- `--language`: response language code such as `zh-CN`, `en`, `zh-Hant`, `ja`, `ko`, `es`, `fr`, `de`, `pt`, or `th`.
- `--output`: optional JSON output path.
- `--render-dir`: directory used for screenshots generated from HTML inputs.

## Output

Chart mode:

```json
{
  "script": "trade_flow.py",
  "summary": "...",
  "latestVisiblePeriod": "rightmost visible x-axis date/period, if readable",
  "latestVisibleValues": [
    {"series": "series name", "value": "visible/latest value if readable"}
  ],
  "renderedImage": "/absolute/path/to/rendered.png"
}
```

Uploaded mode:

```json
{
  "summary": "...",
  "chartTitle": "",
  "chartType": "",
  "xAxis": "",
  "yAxis": "",
  "seriesNames": [],
  "legend": [],
  "details": [],
  "extractedData": [],
  "renderedImages": ["/absolute/path/to/rendered.png"]
}
```

## Routing Notes

Use chart mode after a visual chart artifact exists. It should focus on what is visible in the chart: latest period, trend direction, turning points, outliers, series divergence, volume/liquidity confirmation, and the next point an investor should watch.

Technical-analysis charts should be interpreted visually for price structure, moving-average position, momentum indicators, volume confirmation, support/resistance, and pattern confirmation/invalidation. Capital-flow charts should be interpreted for dominant flow direction, order-size contribution, intraday turning points, and confirmation or divergence between flow and price. Do not generate prose from renderer metadata, sample counts, field lists, or arithmetic templates; in particular, omit sample-count narration and net-flow formulas from user-facing analysis.

For time-series charts, the rightmost visible x-axis label or rightmost plotted point is the latest visible period. Extract it explicitly into `latestVisiblePeriod`. If the value labels or axis scale allow a reasonable read, also populate `latestVisibleValues`. Historical performance is only a reference for explaining how the latest visible state was reached.

Use uploaded mode before routing when the user attaches images and the system needs to identify visible chart/table/content facts for downstream chart generation or analysis.

Do not mention screenshots, images, OCR, models, HTML, or system steps in the summary.

## Local Credentials

Use `VISION_API_KEY` from the process environment, or set `VISION_CONFIG_FILE` to an ignored local `.env` file. Existing process values are preserved. Never write actual credentials into scripts, prompts, tests, or repository configuration.
