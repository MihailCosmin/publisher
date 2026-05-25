import os
from os import system, remove, rename
from os.path import join, isdir, isfile, dirname, basename, exists
from shutil import copy2
from re import sub
from glob import glob

CURRENT_DIR = dirname(__file__)
REPO_ROOT = dirname(dirname(CURRENT_DIR))
GO_BUILDLIB = join(REPO_ROOT, "go", "sphelper", "buildlib", "buildlib.go")


def ensure_makensis_on_path():
    import shutil
    from os import environ
    from os.path import join, exists

    if shutil.which("makensis"):
        return  # already available

    candidates = []

    # Known env hints
    for var in ("NSISDIR", "ChocolateyInstall", "ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        v = environ.get(var)
        if not v:
            continue
        if var == "NSISDIR":
            candidates.append(join(v, "makensis.exe"))
        elif var == "ChocolateyInstall":
            candidates.append(join(v, "bin", "makensis.exe"))
        elif var in ("ProgramFiles", "ProgramFiles(x86)"):
            candidates.append(join(v, "NSIS", "makensis.exe"))
        elif var == "LocalAppData":
            candidates.append(join(v, "Programs", "NSIS", "makensis.exe"))

    # Also try typical absolute paths
    candidates += [
        r"C:\Program Files\NSIS\makensis.exe",
        r"C:\Program Files (x86)\NSIS\makensis.exe",
        r"C:\tools\NSIS\makensis.exe",
    ]

    for exe in candidates:
        if exists(exe):
            nsis_dir = dirname(exe)
            os.environ["PATH"] = nsis_dir + os.pathsep + os.environ.get("PATH", "")
            return

    # Last resort: clear, actionable error
    raise SystemExit(
        "NSIS (makensis) not found. Install it (e.g., `choco install nsis -y` or `winget install NSIS.NSIS`) "
        "and re-run, or add makensis.exe to PATH."
    )

# call it right before dist
ensure_makensis_on_path()

def to_posix(p: str) -> str:
    return p.replace('\\', '/')

def mingw_bin_dir(cc_path_posix: str) -> str:
    return dirname(cc_path_posix.replace('/', '\\'))

def first_existing(paths):
    for p in paths:
        if p and exists(p):
            return p
    return None

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def try_make_import_lib(mingw_bin_win: str, dll_path_win: str, out_lib_win: str) -> bool:
    gendef = join(mingw_bin_win, "gendef.exe")
    dlltool = join(mingw_bin_win, "dlltool.exe")
    if not (exists(gendef) and exists(dlltool) and exists(dll_path_win)):
        return False
    dll_dir = dirname(dll_path_win)
    dll_name = basename(dll_path_win)
    def_path = join(dll_dir, os.path.splitext(dll_name)[0] + ".def")
    r1 = system(f'"{gendef}" "{dll_path_win}"')
    r2 = system(f'"{dlltool}" -d "{def_path}" -l "{out_lib_win}"') if r1 == 0 else 1
    try:
        if exists(def_path):
            os.remove(def_path)
    except Exception:
        pass
    return r1 == 0 and r2 == 0 and exists(out_lib_win)

# ---- Paths ----
MINGW = r"C:\mingw64\bin\x86_64-w64-mingw32-gcc.exe"
LUA_HEADERS = r"C:\Users\munte\Develop\IT\Speedata\lua-5.4.2_Win64_dll17_lib\include"

# ---- Normalize paths ----
MINGW_POSIX = to_posix(MINGW)
LUA_HEADERS_POSIX = to_posix(LUA_HEADERS)
LUAGLUE_C_POSIX = to_posix(join(REPO_ROOT, "c", "luaglue.c"))

# ---- Tooling env (cgo + MinGW) ----
os.environ['CC'] = MINGW_POSIX
os.environ['CXX'] = MINGW_POSIX.replace('gcc.exe', 'g++.exe')
os.environ['PATH'] = mingw_bin_dir(MINGW_POSIX) + os.pathsep + os.environ.get('PATH', '')
os.environ['CGO_ENABLED'] = '1'
os.environ['CGO_CFLAGS'] = f"-I{LUA_HEADERS_POSIX}"

# ---- Detect Lua import lib (lua53/lua54) ----
headers_win = LUA_HEADERS_POSIX.replace('/', '\\')
headers_parent = dirname(headers_win)
candidate_lib_dirs = [
    join(headers_parent, "lib"),
    headers_parent,
    join(headers_parent, "libs"),
    join(headers_parent, "bin"),
]

lib_dir_win = None
lib_name = None  # lua53 or lua54

for d in candidate_lib_dirs:
    if not exists(d):
        continue
    if first_existing(glob(join(d, "liblua53.dll.a"))) or first_existing(glob(join(d, "liblua53.a"))) or first_existing(glob(join(d, "lua53.lib"))):
        lib_dir_win, lib_name = d, "lua53"; break
    if first_existing(glob(join(d, "liblua54.dll.a"))) or first_existing(glob(join(d, "liblua54.a"))) or first_existing(glob(join(d, "lua54.lib"))):
        lib_dir_win, lib_name = d, "lua54"; break

if not lib_dir_win or not lib_name:
    dll53 = dll54 = None
    for d in candidate_lib_dirs:
        if not exists(d): continue
        if not dll53: dll53 = first_existing(glob(join(d, "lua53.dll")))
        if not dll54: dll54 = first_existing(glob(join(d, "lua54.dll")))
    if dll53:
        lib_dir_win, lib_name = dirname(dll53), "lua53"
        out_lib = join(lib_dir_win, "liblua53.dll.a")
        if not exists(out_lib):
            try_make_import_lib(mingw_bin_dir(MINGW_POSIX), dll53, out_lib)
    elif dll54:
        lib_dir_win, lib_name = dirname(dll54), "lua54"
        out_lib = join(lib_dir_win, "liblua54.dll.a")
        if not exists(out_lib):
            try_make_import_lib(mingw_bin_dir(MINGW_POSIX), dll54, out_lib)

# ---- Local sdluatex binaries (pre-extracted) ----
SDLUATEX_WIN_DIR = r"C:\Users\munte\Develop\IT\Speedata\luatex_122-win-mac-linux\win"
if not exists(SDLUATEX_WIN_DIR):
    raise SystemExit(f"ERROR: sdluatex Windows binaries not found at {SDLUATEX_WIN_DIR}")

LUATEX_BIN_ROOT = join(REPO_ROOT, "luatex")
LUATEX_WIN_AMD64_DEFAULT = join(LUATEX_BIN_ROOT, "windows", "amd64", "default")
ensure_dir(LUATEX_WIN_AMD64_DEFAULT)

for fname in os.listdir(SDLUATEX_WIN_DIR):
    src = join(SDLUATEX_WIN_DIR, fname)
    dst = join(LUATEX_WIN_AMD64_DEFAULT, fname)
    if not exists(dst):
        copy2(src, dst)
        print(f"  Copied: {fname}")

# Link against lua53w64 from the downloaded sdluatex zip (both libsplib.dll and luaglue.dll)
# Static-link MinGW runtimes so libgcc_s_seh-1.dll / libwinpthread-1.dll are not required on the target machine.
os.environ['CGO_LDFLAGS'] = f"-llua53w64 -L{to_posix(LUATEX_WIN_AMD64_DEFAULT)} -static-libgcc -static-libstdc++ -Wl,-Bstatic,-lwinpthread,-Bdynamic"

# Expose for sphelper
os.environ['LUATEX_BIN'] = to_posix(LUATEX_BIN_ROOT)

# ---- Patch BuildCLib Windows command only (no other buildlib.go changes) ----
backup_path = join(REPO_ROOT, "go", "sphelper", "buildlib", "buildlib.go_old")
copy2(GO_BUILDLIB, backup_path)

with open(GO_BUILDLIB, "r", encoding="utf-8") as f:
    CONTENT = f.read()

TARGET_REGEX = 'case "windows":(.|\\n)*?cmd(.|\\n)*?luaglue.c(.|\\n)*?}'

WIN_TARGET = f'''case "windows":
        cmd = exec.Command(
            "{MINGW_POSIX}",
            "-shared",
            "-o",
            filepath.Join(dylibbuild, "luaglue.dll"),
            "{LUAGLUE_C_POSIX}",
            "-I{LUA_HEADERS_POSIX}",
            "-L{to_posix(LUATEX_WIN_AMD64_DEFAULT)}",
            "-llua53w64",
            "-llibsplib",
            "-L"+dylibbuild,
            "-static-libgcc",
            "-static-libstdc++",
            "-Wl,-Bstatic,-lwinpthread,-Bdynamic")
    }}'''

with open(GO_BUILDLIB, "w", encoding="utf-8") as f:
    f.write(sub(TARGET_REGEX, lambda _: WIN_TARGET, CONTENT))

# ---- Run build pipeline ----
INSTALL_DIR = to_posix(dirname(REPO_ROOT))
SPHELPER = to_posix(join(dirname(REPO_ROOT), "bin", "sphelper"))
rc1 = system("rake build")
rc2 = system("rake buildlib")
rc3 = system(f'"{SPHELPER}" dist windows/amd64')

# ---- Post-dist fixups ----
dist_bin = join(dirname(REPO_ROOT), "build", "speedata-publisher", "bin")
if rc3 == 0 and exists(dist_bin):
    # lua53.dll is just lua53w64.dll renamed — copy it so dependents that load "lua53.dll" find it
    lua53w64 = join(dist_bin, "lua53w64.dll")
    lua53 = join(dist_bin, "lua53.dll")
    if exists(lua53w64) and not exists(lua53):
        copy2(lua53w64, lua53)
        print("Copied lua53w64.dll -> lua53.dll")
    # luatex.exe is not the sdluatex binary and is not needed at runtime
    luatex_exe = join(dist_bin, "luatex.exe")
    if exists(luatex_exe):
        remove(luatex_exe)
        print("Removed luatex.exe from dist bin/")

# ---- Restore buildlib.go regardless ----
if isfile(backup_path):
    try:
        remove(GO_BUILDLIB)
        rename(backup_path, GO_BUILDLIB)
    except Exception:
        pass

# Exit with first failing code
exit_code = 0
for rc in (rc1, rc2, rc3):
    if rc != 0 and exit_code == 0:
        exit_code = rc
raise SystemExit(exit_code)
