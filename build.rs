use std::env;
use std::path::PathBuf;

const LIBRARIES: &[&str] = &[
    "sherpa-onnx-c-api",
    "sherpa-onnx-core",
    "kaldi-decoder-core",
    "sherpa-onnx-kaldifst-core",
    "sherpa-onnx-fstfar",
    "sherpa-onnx-fst",
    "kaldi-native-fbank-core",
    "kissfft-float",
    "piper_phonemize",
    "espeak-ng",
    "ucd",
    "onnxruntime",
    "ssentencepiece_core",
];

fn main() {
    println!("cargo:rerun-if-env-changed=SHERPA_ONNX_LIB_DIR");
    println!("cargo:rerun-if-env-changed=DOCS_RS");
    if env::var_os("DOCS_RS").is_some() {
        return;
    }
    assert!(
        env::var_os("CARGO_FEATURE_STATIC").is_some()
            && env::var_os("CARGO_FEATURE_SHARED").is_none(),
        "ash-sherpa-onnx supports the static feature only"
    );
    let target = env::var("TARGET").expect("Cargo target");
    assert!(
        matches!(
            target.as_str(),
            "x86_64-pc-windows-msvc"
                | "aarch64-pc-windows-msvc"
                | "x86_64-apple-darwin"
                | "aarch64-apple-darwin"
                | "x86_64-unknown-linux-gnu"
                | "aarch64-unknown-linux-gnu"
        ),
        "No Sherpa ONNX static bundle is available for {target}"
    );
    let directory = PathBuf::from(env::var_os("SHERPA_ONNX_LIB_DIR").expect(
        "Prepare the locked Sherpa ONNX bundle and set SHERPA_ONNX_LIB_DIR before invoking Cargo",
    ));
    let directory = directory
        .canonicalize()
        .expect("Sherpa ONNX library directory");
    for library in LIBRARIES {
        let filename = if target.contains("windows") {
            format!("{library}.lib")
        } else {
            format!("lib{library}.a")
        };
        let file = directory.join(filename);
        assert!(file.is_file(), "Missing static library: {}", file.display());
        println!("cargo:rerun-if-changed={}", file.display());
        println!("cargo:rustc-link-lib=static={library}");
    }
    println!("cargo:rustc-link-search=native={}", directory.display());
    // Match the system dependencies of upstream's static C API archives.
    if target.ends_with("linux-gnu") {
        for library in ["stdc++", "m", "pthread", "dl"] {
            println!("cargo:rustc-link-lib=dylib={library}");
        }
    } else if target.ends_with("apple-darwin") {
        println!("cargo:rustc-link-lib=dylib=c++");
        println!("cargo:rustc-link-lib=framework=Foundation");
    }
}
