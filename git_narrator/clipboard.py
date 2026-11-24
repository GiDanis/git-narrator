"""Zero-dependency clipboard support via native utilities and safe OSC 52 TTY escape sequences."""

import base64
import os
import shutil
import subprocess
import sys


def _run_clipboard_cmd(cmd: list[str], data: bytes) -> bool:
    try:
        subprocess.run(
            cmd,
            input=data,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=2,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _write_osc52(text: str) -> bool:
    """Emit OSC 52 clipboard escape sequence strictly to a TTY (never corrupt piped stdout)."""
    raw_bytes = text.encode("utf-8")
    b64_payload = base64.b64encode(raw_bytes).decode("ascii")

    if os.environ.get("TMUX"):
        osc_seq = f"\033Ptmux;\033\033]52;c;{b64_payload}\a\033\\"
    else:
        osc_seq = f"\033]52;c;{b64_payload}\a"

    # Prefer direct TTY device so redirected stdout (> pr.md) stays clean
    try:
        with open("/dev/tty", "w", encoding="utf-8") as tty:
            tty.write(osc_seq)
            tty.flush()
            return True
    except OSError:
        pass

    if sys.stderr.isatty():
        try:
            sys.stderr.write(osc_seq)
            sys.stderr.flush()
            return True
        except OSError:
            pass

    if sys.stdout.isatty():
        try:
            sys.stdout.write(osc_seq)
            sys.stdout.flush()
            return True
        except OSError:
            pass

    return False


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard via native utilities or OSC 52 TTY fallback."""
    if not text:
        return False

    payload = text.encode("utf-8")

    # 1. macOS pbcopy
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        if _run_clipboard_cmd(["pbcopy"], payload):
            return True

    # 2. Wayland wl-copy
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy") and _run_clipboard_cmd(["wl-copy"], payload):
        return True

    # 3. X11 xclip / xsel
    if os.environ.get("DISPLAY"):
        if shutil.which("xclip") and _run_clipboard_cmd(["xclip", "-selection", "clipboard"], payload):
            return True
        if shutil.which("xsel") and _run_clipboard_cmd(["xsel", "--clipboard", "--input"], payload):
            return True

    # 4. Windows clip.exe
    if sys.platform == "win32" and shutil.which("clip"):
        if _run_clipboard_cmd(["clip"], payload):
            return True

    # 5. OSC 52 Terminal Escape Sequence (TTY only)
    return _write_osc52(text)
