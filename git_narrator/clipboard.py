"""Zero-dependency clipboard support via terminal OSC 52 escape sequences,
with automatic fallback to system clipboard utilities (pbcopy, wl-copy, xclip).
"""

import base64
import os
import shutil
import subprocess
import sys


def copy_to_clipboard(text: str) -> bool:
    """Copies text to the system clipboard.
    
    Tries native system tools if available, then emits terminal OSC 52 escape
    sequence which works seamlessly across SSH, tmux, and modern terminal emulators.
    """
    if not text:
        return False

    # Attempt 1: macOS pbcopy
    if sys.platform == "darwin" and shutil.which("pbcopy"):
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=2)
            return True
        except Exception:
            pass

    # Attempt 2: Wayland wl-copy
    if shutil.which("wl-copy") and os.environ.get("WAYLAND_DISPLAY"):
        try:
            subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True, timeout=2)
            return True
        except Exception:
            pass

    # Attempt 3: X11 xclip
    if shutil.which("xclip") and os.environ.get("DISPLAY"):
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=True,
                timeout=2,
            )
            return True
        except Exception:
            pass

    # Attempt 4: OSC 52 Terminal Escape Sequence (Universal & Zero-Dependency)
    # Works in iTerm2, Kitty, Alacritty, WezTerm, Windows Terminal, tmux, GNOME Terminal
    try:
        raw_bytes = text.encode("utf-8")
        b64_payload = base64.b64encode(raw_bytes).decode("ascii")

        # In tmux, wrap sequence in DCS passthrough: \033Ptmux;\033 ... \033\\
        if os.environ.get("TMUX"):
            osc_seq = f"\033Ptmux;\033\033]52;c;{b64_payload}\a\033\\"
        else:
            osc_seq = f"\033]52;c;{b64_payload}\a"

        sys.stdout.write(osc_seq)
        sys.stdout.flush()
        return True
    except Exception:
        return False
