from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "skills"
    / "vision-chart-analyst"
    / "scripts"
    / "vision_chart_analyst.py"
)
SPEC = importlib.util.spec_from_file_location("vision_chart_analyst", SCRIPT)
assert SPEC and SPEC.loader
vision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vision)


class FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=next(self.responses), refusal=None),
                )
            ]
        )


class AnalyzeUploadedTests(unittest.TestCase):
    def args(self, image: Path, render_dir: Path):
        return SimpleNamespace(
            images=[str(image)],
            image=None,
            question="分析一下",
            render_dir=str(render_dir),
        )

    def test_retries_empty_response_and_returns_valid_summary(self):
        completions = FakeCompletions([
            "",
            '{"summary":"图中价格近期回落。","chartType":"K线图"}',
        ])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "chart.png"
            image.write_bytes(b"png")
            with patch.object(vision, "model_client", return_value=client):
                result = vision.analyze_uploaded(self.args(image, root / "rendered"))

        self.assertEqual(result["summary"], "图中价格近期回落。")
        self.assertEqual(result["chartType"], "K线图")
        self.assertEqual(len(completions.calls), 2)
        self.assertIn("response_format", completions.calls[0])
        self.assertNotIn("response_format", completions.calls[1])

    def test_raises_after_two_empty_responses(self):
        completions = FakeCompletions(["", ""])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "chart.png"
            image.write_bytes(b"png")
            with patch.object(vision, "model_client", return_value=client):
                with self.assertRaisesRegex(RuntimeError, "未返回可用的图片结论"):
                    vision.analyze_uploaded(self.args(image, root / "rendered"))

        self.assertEqual(len(completions.calls), 2)


if __name__ == "__main__":
    unittest.main()
