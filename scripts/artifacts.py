"""Publish checksum-locked upstream static libraries without maintaining a source fork."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import tomllib
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/k2-fsa/sherpa-onnx"
REPOSITORY = "https://github.com/chogng/ash-sherpa-onnx"
LIBRARIES = (
    "sherpa-onnx-c-api", "sherpa-onnx-core", "kaldi-decoder-core",
    "sherpa-onnx-kaldifst-core", "sherpa-onnx-fstfar", "sherpa-onnx-fst",
    "kaldi-native-fbank-core", "kissfft-float", "piper_phonemize", "espeak-ng",
    "ucd", "onnxruntime", "ssentencepiece_core",
)
TARGETS = {
    "aarch64-apple-darwin", "x86_64-apple-darwin",
    "aarch64-unknown-linux-gnu", "x86_64-unknown-linux-gnu",
    "aarch64-pc-windows-msvc", "x86_64-pc-windows-msvc",
}
BINDING_DOC = '''//! Upstream Sherpa ONNX C API bindings.
//!
//! Enable `static` and set `SHERPA_ONNX_LIB_DIR` to the prepared, checksum-verified
//! library directory. This package has no downloader or C++ compiler dependencies.
//! Library acquisition and verification belong to the consuming build entrypoint.

'''


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def lock() -> dict:
    document = json.loads((ROOT / "inputs.lock.json").read_text(encoding="utf-8"))
    if (document["schemaVersion"] != 1 or document["runtime"] != "sherpa-onnx"
        or document["source"]["repository"] != UPSTREAM
        or document["source"]["release"] != "v" + document["version"]
        or not re.fullmatch(r"[0-9a-f]{40}", document["source"]["commit"])
        or not re.fullmatch(r"\d+\.\d+\.\d+-ash\.[1-9]\d*", document["bundleVersion"])
        or document["artifacts"].keys() != TARGETS):
        raise ValueError("Invalid source lock")
    return document


def download(url: str, destination: Path, size: int | None, checksum: str) -> None:
    if destination.is_file() and digest(destination) == checksum:
        if size is None or destination.stat().st_size == size:
            return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            with urlopen(Request(url, headers={"User-Agent": "ash-sherpa-onnx"}), timeout=180) as source:
                shutil.copyfileobj(source, output)
            output.close()
            if (size is not None and temporary.stat().st_size != size) or digest(temporary) != checksum:
                raise ValueError(f"Downloaded resource checksum mismatch: {url}")
            temporary.replace(destination)
        finally:
            output.close()
            temporary.unlink(missing_ok=True)


def bindings(document: dict, update: bool) -> None:
    entry = document["bindings"]
    version = document["version"]
    archive = ROOT / ".build" / f"sherpa-onnx-sys-{version}.crate"
    download(f"https://static.crates.io/crates/sherpa-onnx-sys/sherpa-onnx-sys-{version}.crate",
             archive, None, entry["sha256"])
    with tarfile.open(archive, "r:gz") as contents:
        for name, checksum in entry["files"].items():
            if not re.fullmatch(r"src/[a-z_]+\.rs", name):
                raise ValueError(f"Invalid binding path: {name}")
            source = contents.extractfile(f"sherpa-onnx-sys-{version}/{name}")
            data = source.read()
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError(f"Upstream binding checksum mismatch: {name}")
            if name == "src/lib.rs":
                # Only replace the upstream downloader documentation; the FFI ABI is unchanged.
                data = BINDING_DOC.encode() + data[data.index(b"#![allow"):]
            destination = ROOT / name
            if update:
                destination.write_bytes(data)
            elif destination.read_bytes() != data:
                raise ValueError(f"Binding differs from locked upstream source: {name}")


def verify() -> None:
    document = lock()
    manifest = tomllib.loads((ROOT / "Cargo.toml").read_text())
    if manifest["package"]["version"] != document["version"]:
        raise ValueError("Binding and runtime versions differ")
    if "dependencies" in manifest or "build-dependencies" in manifest:
        raise ValueError("The FFI package must not acquire download/build dependencies")
    build_script = (ROOT / "build.rs").read_text()
    for name in LIBRARIES:
        if f'"{name}"' not in build_script:
            raise ValueError(f"Missing Rust link input: {name}")
    for target, artifact in document["artifacts"].items():
        if (Path(artifact["name"]).name != artifact["name"]
            or not artifact["name"].endswith(".tar.bz2")
            or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
            or type(artifact["size"]) is not int or artifact["size"] <= 0):
            raise ValueError(f"Invalid artifact for {target}")
    bindings(document, update=False)
    print("Source lock, FFI provenance and link inputs agree")


def stage(target: str) -> None:
    document = lock()
    artifact = document["artifacts"][target]
    filename = artifact["name"]
    archive = ROOT / ".build" / filename
    download(f"{UPSTREAM}/releases/download/v{document['version']}/{filename}",
             archive, artifact["size"], artifact["sha256"])
    destination = ROOT / ".build" / target / "lib"
    destination.mkdir(parents=True, exist_ok=True)
    names = {f"{name}.lib" if "windows" in target else f"lib{name}.a" for name in LIBRARIES}
    prefix = filename.removesuffix(".tar.bz2") + "/lib/"
    found = set()
    with tarfile.open(archive, "r|bz2") as contents:
        for member in contents:
            if member.name not in {prefix + name for name in names}:
                continue
            name = member.name.removeprefix(prefix)
            if not member.isfile() or name in found:
                raise ValueError(f"Invalid library member: {member.name}")
            with contents.extractfile(member) as source, (destination / name).open("wb") as output:
                shutil.copyfileobj(source, output)
            found.add(name)
    if found != names:
        raise ValueError(f"Missing libraries for {target}: {names - found}")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    shutil.copyfile(archive, dist / filename)
    if os.environ.get("GITHUB_ENV"):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
            output.write(f"SHERPA_ONNX_LIB_DIR={destination}\n")
    print(f"SHERPA_ONNX_LIB_DIR={destination}")


def aggregate() -> None:
    document = lock()
    dist = ROOT / "dist"
    for artifact in document["artifacts"].values():
        archive = dist / artifact["name"]
        if archive.stat().st_size != artifact["size"] or digest(archive) != artifact["sha256"]:
            raise ValueError(f"Release artifact mismatch: {archive}")
    runtime = {key: value for key, value in document.items() if key != "bindings"}
    runtime["distribution"] = {"repository": REPOSITORY, "release": "v" + document["bundleVersion"]}
    (dist / "runtime-lock.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ROOT / "LICENSE", dist / "LICENSE")
    shutil.copyfile(ROOT / "NOTICE", dist / "NOTICE")
    (dist / "SHA256SUMS").write_text("".join(f"{digest(path)}  {path.name}\n" for path in sorted(dist.iterdir())
                                                if path.is_file() and path.name != "SHA256SUMS"), encoding="utf-8")


def upstream() -> None:
    request = Request("https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/latest",
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "ash-sherpa-onnx"})
    with urlopen(request, timeout=60) as response:
        latest = json.load(response)
    pinned = "v" + lock()["version"]
    print(f"Pinned: {pinned}; latest upstream: {latest['tag_name']}\n{latest['html_url']}")
    if latest["tag_name"] != pinned:
        raise SystemExit("Upstream changed. Review ABI, bindings, archives, licenses and platform builds before updating.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify", "import-bindings", "stage", "aggregate", "upstream"])
    parser.add_argument("--target", choices=sorted(TARGETS))
    args = parser.parse_args()
    if args.command == "stage":
        if not args.target:
            parser.error("stage requires --target")
        stage(args.target)
    elif args.command == "import-bindings":
        bindings(lock(), update=True)
    else:
        {"verify": verify, "aggregate": aggregate, "upstream": upstream}[args.command]()
