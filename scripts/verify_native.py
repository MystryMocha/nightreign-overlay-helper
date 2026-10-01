"""校验 native/ 下预编译二进制的 SHA256，防止被悄悄替换。

清单文件 native/SHA256SUMS 每行格式与 sha256sum 一致：``<hex>  <文件名>``。
更换 DLL 时先运行 ``python scripts/verify_native.py --update`` 重新生成清单，
并在 native/README.md 里记录新版本的来源，这样替换二进制必然会在 PR diff 里留下可见痕迹。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

NATIVE_DIR = Path(__file__).resolve().parent.parent / "native"
MANIFEST_NAME = "SHA256SUMS"
BINARY_SUFFIXES = (".dll", ".exe", ".so", ".dylib")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_binaries(native_dir: Path) -> list[Path]:
    return sorted(p for p in native_dir.iterdir() if p.is_file() and p.suffix.lower() in BINARY_SUFFIXES)


def read_manifest(manifest: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for lineno, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"{manifest.name}:{lineno}: malformed line: {raw!r}")
        entries[parts[1].lstrip("*").strip()] = parts[0].lower()
    return entries


def write_manifest(native_dir: Path) -> None:
    lines = [f"{sha256_of(p)}  {p.name}" for p in list_binaries(native_dir)]
    (native_dir / MANIFEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def verify(native_dir: Path) -> list[str]:
    """返回问题列表，空列表表示校验通过"""
    manifest = native_dir / MANIFEST_NAME
    if not manifest.is_file():
        return [f"{MANIFEST_NAME} not found in {native_dir}"]

    try:
        expected = read_manifest(manifest)
    except ValueError as e:
        return [str(e)]

    problems: list[str] = []
    actual = {p.name: p for p in list_binaries(native_dir)}
    for name, digest in expected.items():
        path = native_dir / name
        if not path.is_file():
            problems.append(f"{name}: listed in {MANIFEST_NAME} but missing")
        elif sha256_of(path) != digest:
            problems.append(f"{name}: SHA256 mismatch (expected {digest}, got {sha256_of(path)})")
    for name in actual:
        if name not in expected:
            problems.append(f"{name}: not listed in {MANIFEST_NAME}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=NATIVE_DIR, help="native 目录（默认仓库内的 native/）")
    parser.add_argument("--update", action="store_true", help="按当前文件重新生成 SHA256SUMS")
    args = parser.parse_args(argv)

    if args.update:
        write_manifest(args.dir)
        print(f"Updated {args.dir / MANIFEST_NAME}")
        return 0

    problems = verify(args.dir)
    for p in problems:
        print(f"ERROR: {p}", file=sys.stderr)
    if problems:
        return 1
    print("native binaries verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
