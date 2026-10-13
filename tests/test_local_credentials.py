import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "app/skills/vision-chart-analyst/scripts/vision_chart_analyst.py"
spec = importlib.util.spec_from_file_location("vision_credentials", SCRIPT)
vision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vision)


def test_reads_explicit_local_configuration(monkeypatch, tmp_path):
    for name in vision.MODEL_API_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / ".env"
    config.write_text("VISION_API_KEY=local-fixture-value\n")
    monkeypatch.setenv("VISION_CONFIG_FILE", str(config))
    assert vision.model_api_key() == "local-fixture-value"
    monkeypatch.delenv("VISION_API_KEY")


def test_dedicated_key_and_process_environment_take_priority(monkeypatch, tmp_path):
    config = tmp_path / ".env"
    config.write_text("VISION_API_KEY=file-fixture-value\n")
    monkeypatch.setenv("VISION_CONFIG_FILE", str(config))
    monkeypatch.setenv("VISION_API_KEY", "process-fixture-value")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-fixture-value")
    assert vision.model_api_key() == "process-fixture-value"
