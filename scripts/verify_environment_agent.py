from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from learning_ext.environment_agent.service import audited_exploration
from learning_ext.practice.environment import inspect_environment

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true")
parser.add_argument("--task", default="学习 Python 工程基础。检查 Python 3.10+、Git 与 VS Code 的本机条件；不安装任何东西。")
args = parser.parse_args()
report = audited_exploration(args.task) if args.live else inspect_environment(args.task)
path = ROOT / "output/runtime/environment-acceptance.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({key: report.get(key) for key in ("engine", "complete", "stop_reason", "items")}, ensure_ascii=False, indent=2))
