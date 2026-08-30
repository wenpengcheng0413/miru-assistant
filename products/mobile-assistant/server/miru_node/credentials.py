"""Windows CurrentUser DPAPI storage for the independent Home Node token."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _require_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Home Node DPAPI credentials require Windows")


def _crypt(data: bytes, *, protect: bool) -> bytes:
    _require_windows()
    buffer = ctypes.create_string_buffer(data)
    source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = _DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(source), "Miru Home Node", None, None, None,
            flags, ctypes.byref(output),
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None,
            flags, ctypes.byref(output),
        )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def protect_token(token: str, path: str | Path) -> None:
    value = token.strip()
    if len(value) < 32:
        raise ValueError("Home Node token is too short")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _crypt(value.encode("utf-8"), protect=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(encrypted)
    os.replace(temporary, target)


def load_token(path: str | Path) -> str:
    encrypted = Path(path).read_bytes()
    value = _crypt(encrypted, protect=False).decode("utf-8").strip()
    if len(value) < 32:
        raise ValueError("Home Node credential is invalid")
    return value
