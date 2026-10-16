# Ash Sherpa ONNX artifacts

Independent distribution repository for checksum-pinned Sherpa ONNX static libraries.
This repository is not a fork of the Sherpa ONNX source tree. The safe Rust API comes
directly from the upstream `sherpa-onnx` crate on crates.io.

## Contents

- `inputs.lock.json`: upstream release archive names, sizes and SHA-256; published
  `sherpa-onnx-sys` crate checksum and FFI source checksums.
- `src/`: the upstream FFI declarations, imported from the checksum-locked published
  crate. Only the module documentation for library preparation is replaced.
- `build.rs`: static linking only; no network, archive, compiler or build dependencies.
- Releases: six upstream static library archives copied byte for byte, a consumer
  `runtime-lock.json`, license notices and `SHA256SUMS`. No model weights.

Windows x64/ARM64 uses MSVC and static CRT (`/MT`). macOS x64/ARM64 and Linux GNU
x64/ARM64 use the upstream CPU archives. **musl is unsupported**: glibc archives
must never be relabeled as musl. Add a target only after producing suitable ONNX
Runtime and Sherpa libraries and completing a target consumer build.

## Consume

Pin the upstream wrapper to `=1.13.8`, disable defaults, enable `static`. Patch only
`sherpa-onnx-sys` to an exact commit of this repository. Download the selected
release archive using the published lock, verify its size and SHA-256, extract the
13 static libraries and set `SHERPA_ONNX_LIB_DIR` before invoking Cargo. Ash owns
that preparation in its build entrypoint. Cargo never downloads C++ libraries.

The patch remains necessary while upstream's sys crate unconditionally depends on
HTTP/archive build packages (including yanked ZIP 2.x). When upstream supports
external libraries without these dependencies, migrate back to its sys crate too.

## Maintain

1. The weekly/manual upstream workflow reports new stable releases through a failed
   CI run. Updates are reviewed and pinned; consumers never follow `latest`.
2. Update runtime/Cargo versions, upstream release identity, archive hashes/sizes,
   published sys crate checksum and FFI file inventory in `inputs.lock.json`.
3. Run `python scripts/artifacts.py import-bindings`; review FFI changes and upstream
   link dependencies, platform requirements and third-party license notices.
4. Run `python scripts/artifacts.py verify` and `rustfmt --check --edition 2021 build.rs`.
   Imported upstream declarations retain their original formatting.
5. Dispatch the release workflow with `publish=true`. Every supported target stages
   the exact upstream archive and builds an existing upstream Rust example against
   the thin sys crate. Publication waits for every target to pass.
6. Advance `bundleVersion` for packaging revisions even when the upstream version
   stays unchanged. Releases are immutable; update Ash's Git pin and resource lock
   together, then compile the actual Ash consumer before removing old dependencies.

The first release is `v1.13.8-ash.1`. Local staging:

```sh
python scripts/artifacts.py stage --target x86_64-pc-windows-msvc
```

Models are managed by Ash separately, with their own download/cache lifecycle.
