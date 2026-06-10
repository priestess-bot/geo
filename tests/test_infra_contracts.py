from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - local CI image currently provides PyYAML.
    yaml = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(yaml is None, "PyYAML is required for compose/config contract checks")
class InfraContractsTest(unittest.TestCase):
    def _compose_config(self, *profiles: str) -> dict[str, object]:
        command = ["docker", "compose", "-f", "infra/docker-compose.yml"]
        for profile in profiles:
            command.extend(["--profile", profile])
        command.append("config")
        result = subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return yaml.safe_load(result.stdout)

    def test_litellm_profile_wires_proxy_and_judge_worker(self) -> None:
        config = self._compose_config("llm-gateway")
        services = config["services"]
        litellm = services["litellm"]
        worker = services["collector-worker-litellm"]

        self.assertEqual(litellm["image"], "docker.litellm.ai/berriai/litellm:main-latest")
        self.assertIn("--config", litellm["command"])
        self.assertIn("/app/config.yaml", litellm["command"])
        self.assertIn("--port", litellm["command"])
        self.assertIn("4000", litellm["command"])
        self.assertEqual(litellm["environment"]["LITELLM_MASTER_KEY"], "sk-geno-local")
        self.assertIn("4000", {str(port["published"]) for port in litellm["ports"]})
        self.assertTrue(
            any(volume["target"] == "/app/config.yaml" and volume["read_only"] for volume in litellm["volumes"])
        )

        self.assertEqual(worker["environment"]["LITELLM_BASE_URL"], "http://litellm:4000")
        self.assertEqual(worker["environment"]["LITELLM_API_KEY"], "sk-geno-local")
        self.assertIn("--judge-gateway", worker["command"])
        self.assertIn("litellm", worker["command"])
        self.assertIn("--judge-model", worker["command"])
        self.assertIn("geno-gpt-4.1-mini", worker["command"])
        self.assertIn("litellm", worker["depends_on"])

    def test_litellm_config_uses_env_secrets_and_geno_model_aliases(self) -> None:
        config = yaml.safe_load((ROOT / "infra/litellm_config.yaml").read_text(encoding="utf-8"))
        model_list = {item["model_name"]: item["litellm_params"] for item in config["model_list"]}

        self.assertEqual(model_list["geno-gpt-4.1-mini"]["model"], "openai/gpt-4.1-mini")
        self.assertEqual(model_list["geno-gpt-4.1-mini"]["api_key"], "os.environ/OPENAI_API_KEY")
        self.assertEqual(model_list["geno-text-embedding-3-small"]["model"], "openai/text-embedding-3-small")
        self.assertEqual(model_list["geno-text-embedding-3-small"]["api_key"], "os.environ/OPENAI_API_KEY")
        self.assertEqual(config["general_settings"]["master_key"], "os.environ/LITELLM_MASTER_KEY")


if __name__ == "__main__":
    unittest.main()
