from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from learning_ext.agent.everything_runtime import BUNDLE, PAYLOAD_HASHES, bundle_status

SOURCES = {
    "Everything-1.4.1.1032.x64.zip": "698df475ec44e638f66f1b6a32d28fea613cec78d3b6310e6abe53431eeb940c",
    "Everything-SDK.zip": "f5716d9513cce6b462b5170a0a2e7e081e191d9bcac6774f5decc061497df443",
    "ES-1.1.0.38.x64.zip": "5e0c70cbf4f694080c34aa7c6c745e606c16fe76a4b5423b93ebf9dc34274c99",
    "ES-1.1.0.38.src.zip": "2e36d1177633218821cbf1ce6430ba88e6fc5192cc81a1c254d16e72df63a8ee",
    "License.txt": "c13d19adcbfd5d07e9512de9df99956a3423399ed1fadc5fd33186697ad8df2f",
}


def bundle(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, digest in SOURCES.items():
        path = cache / name
        if not path.exists():
            with opener.open("https://www.voidtools.com/" + name, timeout=30) as response:
                content = response.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Official download hash mismatch: " + name)
            path.write_bytes(content)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Cached download hash mismatch: " + name)
    with zipfile.ZipFile(cache / "Everything-1.4.1.1032.x64.zip") as portable, zipfile.ZipFile(cache / "Everything-SDK.zip") as sdk, zipfile.ZipFile(cache / "ES-1.1.0.38.x64.zip") as cli, zipfile.ZipFile(cache / "ES-1.1.0.38.src.zip") as cli_source:
        sdk_source = sdk.read("src/Everything.c").decode().replace("\r", "")
        sdk_license = "\n".join(line.removeprefix("//").strip() for line in sdk_source.split("// Notes:", 1)[0].splitlines()).strip() + "\n"
        files = {
            "Everything.exe": portable.read("everything.exe"), "Everything.lng": portable.read("Everything.lng"),
            "Everything64.dll": sdk.read("dll/Everything64.dll"), "es.exe": cli.read("es.exe"),
            "LICENSE-Everything.txt": (cache / "License.txt").read_bytes(),
            "LICENSE-SDK.txt": sdk_license.encode(), "LICENSE-ES.txt": cli_source.read("ES-1.1.0.38/LICENSE"),
            "sdk/Everything.h": sdk.read("include/Everything.h"),
            "sdk/Everything.c": sdk.read("src/Everything.c"),
            "sdk/everything_ipc.h": sdk.read("ipc/everything_ipc.h"),
        }
    for name, digest in PAYLOAD_HASHES.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise ValueError("Extracted payload hash mismatch: " + name)
    BUNDLE.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = BUNDLE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != content:
            target.write_bytes(content)
    manifest = {
        "schema": 1, "everything_version": "1.4.1.1032", "es_version": "1.1.0.38",
        "architecture": "x64", "bundled_at": datetime.now(timezone.utc).isoformat(),
        "sources": [{"url": "https://www.voidtools.com/" + name, "sha256": digest} for name, digest in SOURCES.items()],
        "files": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    (BUNDLE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (BUNDLE / "README.txt").write_text(
        "Official Everything 1.4.1.1032 x64 portable, Everything SDK and ES 1.1.0.38.\n"
        "Sources: https://www.voidtools.com/downloads/\n"
        "Everything is freeware; its full application source is not open source.\n"
        "Preserve all LICENSE files and manifest.json when redistributing.\n"
        "The application starts an isolated, folder-scoped instance on demand, without installing a service.\n",
        encoding="utf-8",
    )
    return bundle_status()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--cache", type=Path, default=ROOT / "output/runtime/everything-download")
    args = parser.parse_args()
    result = bundle_status() if args.verify else bundle(args.cache)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)
