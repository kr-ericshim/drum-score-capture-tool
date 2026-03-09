from __future__ import annotations

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata


hiddenimports: list[str] = []
datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []


def _extend_hiddenimports(package: str) -> None:
    try:
        hiddenimports.extend(collect_submodules(package))
    except Exception:
        return


def _extend_datas(package: str) -> None:
    try:
        datas.extend(collect_data_files(package))
    except Exception:
        pass
    try:
        datas.extend(copy_metadata(package))
    except Exception:
        pass


def _extend_binaries(package: str) -> None:
    try:
        binaries.extend(collect_dynamic_libs(package))
    except Exception:
        return


for package_name in ("yt_dlp", "websockets", "requests", "urllib3", "mutagen", "curl_cffi"):
    _extend_hiddenimports(package_name)

for package_name in ("yt_dlp", "certifi"):
    _extend_datas(package_name)

for package_name in ("curl_cffi",):
    _extend_binaries(package_name)
