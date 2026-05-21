import os
import json
import zipfile
import shutil
import tempfile
import requests
import subprocess
import uuid
import base64
from datetime import datetime, UTC

MODRINTH_PROJECT_ID = "nn3bsyaN"

MINECRAFT_DIR = os.path.expandvars(r"%APPDATA%\.minecraft")
PROFILES_PATH = os.path.join(MINECRAFT_DIR, "launcher_profiles.json")
ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.png")

JAVA_URL = "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.3%2B9/OpenJDK25U-jre_x64_windows_hotspot_25.0.3_9.zip"


def get_modpack_name(project_id):
    url = f"https://api.modrinth.com/v2/project/{project_id}"
    print("Fetching modpack metadata from Modrinth...")
    data = requests.get(url).json()
    title = data.get("title") or data.get("name") or project_id
    slug = data.get("slug") or title
    return title, slug


def get_game_dir(modpack_slug):
    return os.path.join(MINECRAFT_DIR, modpack_slug)


def get_mods_dir(game_dir):
    return os.path.join(game_dir, "mods")


def get_java_dir(game_dir):
    return os.path.join(game_dir, "runtime")


def get_java_extract_dir(java_dir):
    return os.path.join(java_dir, "jre")

# =========================
# JAVA DOWNLOAD
# =========================
def download_java(tmp_dir):
    print("Downloading bundled Java runtime...")

    zip_path = os.path.join(tmp_dir, "java.zip")
    response = requests.get(JAVA_URL)
    with open(zip_path, 'wb') as f:
        f.write(response.content)

    return zip_path


def extract_java(zip_path, java_extract_dir):
    print("Extracting Java runtime...")

    ensure_clean_dir(java_extract_dir)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(java_extract_dir)

    # Find java.exe
    for root, _, files in os.walk(java_extract_dir):
        if "java.exe" in files:
            return os.path.join(root, "java.exe")

    raise Exception("java.exe not found after extraction")

# =========================
# MODRINTH
# =========================
def get_latest_mrpack_url(project_id):
    url = f"https://api.modrinth.com/v2/project/{project_id}/version"

    print("Fetching modpack versions from Modrinth...")
    data = requests.get(url).json()

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
# Java is bundled with Minecraft Launcher
# =========================
def download_fabric_installer(tmp_dir):
    url = "https://meta.fabricmc.net/v2/versions/installer"
    data = requests.get(url).json()

    installer_url = data[0]["url"]

    path = os.path.join(tmp_dir, "fabric-installer.jar")
    response = requests.get(installer_url)
    with open(path, 'wb') as f:
        f.write(response.content)

    return path


def install_fabric(java, installer, mc_version, loader_version):
    print(f"Installing Fabric {loader_version} for MC {mc_version}")

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
    response = requests.get(url)
    with open(path, 'wb') as f:
        f.write(response.content)
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
def sync_mods(manifest, game_dir, mods_dir):
    print("Syncing mods...")

    ensure_clean_dir(mods_dir)  # 🔥 always reset mods folder

    for file in manifest["files"]:
        url = file["downloads"][0]
        path = file["path"]
        
        # Destination is profile path + file path (e.g., GAME_DIR/mods/filename.jar)
        dest = os.path.join(game_dir, path)
        dest_dir = os.path.dirname(dest)
        
        # Ensure destination directory exists
        os.makedirs(dest_dir, exist_ok=True)
        
        filename = os.path.basename(path)
        print("Downloading", filename)
        response = requests.get(url)
        with open(dest, 'wb') as f:
            f.write(response.content)


def apply_overrides(extracted, game_dir):
    print("Applying overrides...")

    for folder in ["overrides", "client-overrides"]:
        src = os.path.join(extracted, folder)

        if os.path.exists(src):
            shutil.copytree(src, game_dir, dirs_exist_ok=True)


# =========================
# PROFILE UPDATE (idempotent)
# =========================
def update_profile(version_id, modpack_name, game_dir):
    with open(PROFILES_PATH, encoding="utf-8") as f:
        data = json.load(f)

    profiles = data["profiles"]
    now = datetime.now(UTC).isoformat()

    key = None
    for k, v in profiles.items():
        if v.get("name") == modpack_name:
            key = k

    profile = {
        "created": now,
        "lastUsed": now,
        "lastVersionId": version_id,
        "name": modpack_name,
        "type": "custom",
        "gameDir": game_dir,
        "icon": "data:image/png;base64,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"
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

    modpack_name, modpack_slug = get_modpack_name(MODRINTH_PROJECT_ID)
    game_dir = get_game_dir(modpack_slug)
    mods_dir = get_mods_dir(game_dir)
    java_dir = get_java_dir(game_dir)
    java_extract_dir = get_java_extract_dir(java_dir)

    os.makedirs(game_dir, exist_ok=True)

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
        print("Modpack:", modpack_name, "(folder=", modpack_slug, ")")

        # --- Java ---
        # --- Bundled Java ---
        java_zip = download_java(tmp)
        java = extract_java(java_zip, java_extract_dir)

        print("Using Java:", java)

        # --- Fabric (install every run) ---
        installer = download_fabric_installer(tmp)
        install_fabric(java, installer, mc_version, loader_version)

        # --- MOD SYNC (FULL REPLACE) ---
        sync_mods(manifest, game_dir, mods_dir)

        # --- Overrides (overwrite-safe) ---
        apply_overrides(extracted, game_dir)

        # --- Profile update ---
        version_id = build_version_id(deps)
        update_profile(version_id, modpack_name, game_dir)

    print("Modpack is up to date!")


if __name__ == "__main__":
    main()