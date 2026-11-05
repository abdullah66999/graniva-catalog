"""Keep the private FacetLine worker workspace in a private Supabase bucket."""

import argparse
import os
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

BUCKET = "facetline-private"
OBJECT = "worker/workspace.zip"
MAX_ARCHIVE = 240 * 1024 * 1024
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "logs", "reports", "proofs"}
SKIP_FILES = {".env", ".drafts.lock", ".state.lock", "state.json"}


def credentials(root):
    values = dict(os.environ)
    env_path = root / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            if separator and name.strip() not in values:
                values[name.strip()] = value.strip().strip("'\"")
    url = values.get("SUPABASE_URL", "").strip().rstrip("/")
    key = values.get("SUPABASE_SECRET_KEY", "").strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".supabase.co") or parsed.path or parsed.username or not key.startswith("sb_secret_"):
        raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY must be configured locally or as environment secrets")
    return url, key


def storage_request(method, root, data=None):
    url, key = credentials(root)
    request = Request(f"{url}/storage/v1/object/{BUCKET}/{OBJECT}", data=data, method=method,
        headers={"apikey": key, "Authorization": "Bearer " + key,
            "Content-Type": "application/zip", "x-upsert": "true"})
    try:
        with build_opener().open(request, timeout=180) as response:
            return response.read(MAX_ARCHIVE + 1)
    except HTTPError as error:
        error.close()
        raise ValueError(f"Supabase Storage returned HTTP {error.code}") from None
    except (URLError, TimeoutError):
        raise ValueError("Could not reach Supabase Storage") from None


def paths(root):
    root = root.resolve()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (current_path / d).is_symlink())
        for name in sorted(files):
            path = current_path / name
            relative = path.relative_to(root)
            if name in SKIP_FILES or name == ".env" or name.startswith(".env.") or path.is_symlink():
                continue
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            yield path, relative


def make_archive(root, target):
    references = list((root / "autopilot" / "references").glob("*.png"))
    if len(references) != 5:
        raise ValueError("The private worker workspace must contain all five visual references")
    total = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, relative in paths(root):
            total += path.stat().st_size
            if total > MAX_ARCHIVE:
                raise ValueError("Worker workspace exceeds the 240 MiB upload limit")
            archive.write(path, relative.as_posix())
    if Path(target).stat().st_size > MAX_ARCHIVE:
        Path(target).unlink(missing_ok=True)
        raise ValueError("Compressed worker workspace exceeds the 240 MiB upload limit")


def upload(root):
    with tempfile.TemporaryDirectory(prefix="facetline-cloud-", dir=root.parent) as temp:
        bundle = Path(temp) / "workspace.zip"
        make_archive(root, bundle)
        storage_request("POST", root, bundle.read_bytes())
        print(f"Private worker workspace uploaded ({bundle.stat().st_size / 1024 / 1024:.1f} MiB compressed).")


def download(root):
    data = storage_request("GET", root)
    if not data or len(data) > MAX_ARCHIVE:
        raise ValueError("Private worker archive is empty or exceeds the allowed size")
    root.mkdir(parents=True, exist_ok=True)
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > 20000 or sum(item.file_size for item in members) > 800 * 1024 * 1024:
            raise ValueError("Private worker archive exceeds extraction limits")
        for item in members:
            name = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if name.is_absolute() or ".." in name.parts or stat.S_ISLNK(mode):
                raise ValueError("Unsafe path in private worker archive")
            target = (root / Path(*name.parts)).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError("Archive path escapes worker workspace")
        archive.extractall(root)
    if len(list((root / "autopilot" / "references").glob("*.png"))) != 5:
        raise ValueError("Downloaded worker workspace is missing one or more visual references")
    print("Private worker workspace downloaded and checked.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "download", "upload"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    if args.command in {"setup", "upload"}:
        upload(args.root.resolve())
    else:
        download(args.root.resolve())


if __name__ == "__main__":
    main()
