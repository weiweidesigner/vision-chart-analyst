# Vision Chart Analyst

读取图表 HTML 或图片，通过配置的视觉模型生成结构化解读。HTML 输入先使用 Playwright 截图；不取市场数据、不渲染新图表。

## 安装

建议 Python 3.11+：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## 本地密钥配置

复制 `.env.example` 到本地 `.env` 并填写 `VISION_API_KEY`。真实密钥只存储在本地；`.env` 和其他 `.env.*` 文件被 Git 忽略，仅提交空示例。也可直接通过进程环境提供 `VISION_API_KEY`。

```bash
cp .env.example .env
chmod 600 .env
# 编辑本地 .env 后运行：
VISION_CONFIG_FILE="$PWD/.env" python app/skills/vision-chart-analyst/scripts/vision_chart_analyst.py --mode chart --image /path/to/chart.png --question '解读最新趋势' --language zh-CN --output outputs/analysis.json
```

`VISION_CONFIG_FILE` 显式指定本地配置文件；已有进程环境优先于文件。保留 `DEEPSEEK_API_KEY`、`ARK_API_KEY` 等兼容入口，但专用 `VISION_API_KEY` 优先。其他变量包括 `VISION_BASE_URL`、`VISION_MODEL_NAME`、`VISION_TIMEOUT_SECONDS`、`VISION_RENDER_DIR`。模型与服务是否支持视觉输入需由调用方配置确认。

完整参数及输出格式见 `app/skills/vision-chart-analyst/SKILL.md`。发送给模型的内容包括输入图像、用户问题和提供的上下文。

## 验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试使用模拟响应，无需真实凭据或模型请求。
