import os
import json
import hashlib
import time
from pathlib import Path
from flask import Flask, jsonify, send_file, request, Response


app = Flask(__name__)

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PACKAGES_DIR = BASE_DIR / "packages"
MANIFEST_PATH = BASE_DIR / "manifest.json"
LOGS_DIR = BASE_DIR / "logs"

PACKAGES_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


def compute_sha256(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_manifest(version: str, build_number: int, filename: str,
                   release_notes: str = "", is_mandatory: bool = False,
                   min_launcher: str = "1.0.0") -> dict:
    package_path = PACKAGES_DIR / filename
    if not package_path.exists():
        raise FileNotFoundError(f"Package not found: {package_path}")

    return {
        "version": version,
        "build_number": build_number,
        "release_date": time.strftime("%Y-%m-%d"),
        "download_url": f"/releases/{filename}",
        "checksum_sha256": compute_sha256(package_path),
        "file_size_bytes": package_path.stat().st_size,
        "min_launcher_version": min_launcher,
        "release_notes": release_notes,
        "is_mandatory": is_mandatory,
        "delta_patches": []
    }


@app.route("/api/v1/manifest.json", methods=["GET"])
def get_manifest():
    if not MANIFEST_PATH.exists():
        return jsonify({"error": "No manifest available"}), 404
    with open(MANIFEST_PATH, "r") as f:
        manifest = json.load(f)
    return jsonify(manifest)


@app.route("/releases/<filename>", methods=["GET"])
def download_package(filename):
    file_path = PACKAGES_DIR / filename
    if not file_path.exists():
        return jsonify({"error": "Package not found"}), 404

    range_header = request.headers.get("Range", None)
    if range_header:
        byte_start, byte_end = 0, None
        try:
            byte_range = range_header.replace("bytes=", "").split("-")
            byte_start = int(byte_range[0])
            if byte_range[1]:
                byte_end = int(byte_range[1])
        except (ValueError, IndexError):
            pass

        file_size = file_path.stat().st_size
        byte_end = byte_end or file_size - 1

        with open(file_path, "rb") as f:
            f.seek(byte_start)
            data = f.read(byte_end - byte_start + 1)

        resp = Response(data, 206, mimetype="application/octet-stream")
        resp.headers["Content-Range"] = f"bytes {byte_start}-{byte_end}/{file_size}"
        resp.headers["Content-Length"] = str(len(data))
        resp.headers["Accept-Ranges"] = "bytes"
        return resp

    return send_file(
        file_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename
    )


@app.route("/api/v1/telemetry", methods=["POST"])
def receive_telemetry():
    data = request.get_json(silent=True) or {}
    log_entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ip": request.remote_addr,
        "data": data
    }
    log_file = LOGS_DIR / f"telemetry_{time.strftime('%Y%m%d')}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")
    return jsonify({"status": "ok"}), 200


@app.route("/api/v1/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest_exists": MANIFEST_PATH.exists()
    })


@app.route("/api/v1/admin/regenerate-manifest", methods=["POST"])
def regenerate_manifest():
    data = request.get_json(silent=True) or {}
    version = data.get("version", "1.0.0")
    build_number = data.get("build_number", 100)
    filename = data.get("filename", "SPEED-Z-v1.0.0.zip")
    release_notes = data.get("release_notes", "")
    is_mandatory = data.get("is_mandatory", False)

    try:
        manifest = build_manifest(version, build_number, filename,
                                   release_notes, is_mandatory)
        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
        return jsonify({"status": "ok", "manifest": manifest})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
