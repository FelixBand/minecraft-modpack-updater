import os
import json
import zipfile
import shutil
import tempfile
import urllib.request
import subprocess
import uuid
from datetime import datetime, UTC

MODPACK_NAME = "Felix's QOL Modpack"
MODRINTH_PROJECT_ID = "nn3bsyaN"

MINECRAFT_DIR = os.path.expandvars(r"%APPDATA%\.minecraft")
PROFILES_PATH = os.path.join(MINECRAFT_DIR, "launcher_profiles.json")
GAME_DIR = os.path.join(MINECRAFT_DIR, MODPACK_NAME)

MODS_DIR = os.path.join(GAME_DIR, "mods")


# =========================
# MODRINTH
# =========================
def get_latest_mrpack_url(project_id):
    url = f"https://api.modrinth.com/v2/project/{project_id}/version"

    print("Fetching modpack versions from Modrinth...")
    data = json.loads(urllib.request.urlopen(url).read())

    if not data:
        raise Exception("No versions found")

    for version in sorted(
        data,
        key=lambda v: v.get("date_published", ""),
        reverse=True
    ):
        for file in version.get("files", []):
            if file.get("filename", "").endswith(".mrpack"):
                return file["url"]

    raise Exception("No .mrpack found")


# =========================
# UTIL
# =========================
def run(cmd):
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)


def ensure_clean_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


# =========================
# JAVA
# =========================
def find_java():
    try:
        subprocess.run(["java", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return "java"
    except:
        return None


def download_java(tmp_dir):
    print("Downloading Java...")
    url = "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jre/hotspot/normal/eclipse"

    path = os.path.join(tmp_dir, "java.zip")
    urllib.request.urlretrieve(url, path)

    extract_dir = os.path.join(tmp_dir, "java")
    shutil.unpack_archive(path, extract_dir)

    for root, _, files in os.walk(extract_dir):
        if "java.exe" in files:
            return os.path.join(root, "java.exe")

    raise Exception("Java install failed")


# =========================
# FABRIC
# =========================
def download_fabric_installer(tmp_dir):
    url = "https://meta.fabricmc.net/v2/versions/installer"
    data = json.loads(urllib.request.urlopen(url).read())

    installer_url = data[0]["url"]

    path = os.path.join(tmp_dir, "fabric-installer.jar")
    urllib.request.urlretrieve(installer_url, path)

    return path


def install_fabric(java, installer, mc_version, loader_version):
    print(f"Ensuring Fabric {loader_version} for MC {mc_version}")

    run([
        java,
        "-jar",
        installer,
        "client",
        "-mcversion", mc_version,
        "-loader", loader_version,
        "-dir", MINECRAFT_DIR,
        "-noprofile"
    ])


# =========================
# MODPACK DOWNLOAD
# =========================
def download_mrpack(tmp_dir, url):
    path = os.path.join(tmp_dir, "modpack.mrpack")
    urllib.request.urlretrieve(url, path)
    return path


def extract_mrpack(path, tmp_dir):
    out = os.path.join(tmp_dir, "extracted")
    zipfile.ZipFile(path).extractall(out)
    return out


def read_manifest(extracted):
    with open(os.path.join(extracted, "modrinth.index.json"), encoding="utf-8") as f:
        return json.load(f)


# =========================
# MOD SYNC (IMPORTANT PART)
# =========================
def sync_mods(manifest):
    print("Syncing mods...")

    ensure_clean_dir(MODS_DIR)  # 🔥 always reset mods folder

    for file in manifest["files"]:
        url = file["downloads"][0]
        filename = os.path.basename(file["path"])
        dest = os.path.join(MODS_DIR, filename)

        print("Downloading", filename)
        urllib.request.urlretrieve(url, dest)


def apply_overrides(extracted):
    print("Applying overrides...")

    for folder in ["overrides", "client-overrides"]:
        src = os.path.join(extracted, folder)

        if os.path.exists(src):
            shutil.copytree(src, GAME_DIR, dirs_exist_ok=True)


# =========================
# PROFILE UPDATE (idempotent)
# =========================
def update_profile(version_id):
    with open(PROFILES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    profiles = data["profiles"]
    now = datetime.now(UTC).isoformat()

    key = None
    for k, v in profiles.items():
        if v.get("name") == MODPACK_NAME:
            key = k

    profile = {
        "created": now,
        "lastUsed": now,
        "lastVersionId": version_id,
        "name": MODPACK_NAME,
        "type": "custom",
        "gameDir": GAME_DIR,
        "icon": "Furnace"
    }

    if key:
        profiles[key] = profile
    else:
        profiles[uuid.uuid4().hex] = profile

    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def build_version_id(deps):
    return f"fabric-loader-{deps['fabric-loader']}-{deps['minecraft']}"


# =========================
# MAIN (UPDATER MODE)
# =========================
def main():
    subprocess.run(
        ["taskkill", "/F", "/IM", "MinecraftLauncher.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    os.makedirs(GAME_DIR, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:

        # --- Always fetch latest modpack ---
        mrpack_url = get_latest_mrpack_url(MODRINTH_PROJECT_ID)
        mrpack_file = download_mrpack(tmp, mrpack_url)
        extracted = extract_mrpack(mrpack_file, tmp)

        manifest = read_manifest(extracted)
        deps = manifest["dependencies"]

        mc_version = deps["minecraft"]
        loader_version = deps["fabric-loader"]

        print("Target MC:", mc_version, "| Fabric:", loader_version)

        # --- Java ---
        java = find_java()
        if not java:
            java = download_java(tmp)

        # --- Fabric (auto-updates if needed) ---
        installer = download_fabric_installer(tmp)
        install_fabric(java, installer, mc_version, loader_version)

        # --- MOD SYNC (FULL REPLACE) ---
        sync_mods(manifest)

        # --- Overrides (overwrite-safe) ---
        apply_overrides(extracted)

        # --- Profile update ---
        version_id = build_version_id(deps)
        update_profile(version_id)

    print("Modpack is up to date!")


if __name__ == "__main__":
    main()