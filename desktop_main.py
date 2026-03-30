from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile


def _prepare_runtime_environment() -> None:
    if not getattr(sys, "frozen", False):
        base_prefix = Path(sys.base_prefix)
        dll_dir = base_prefix / "DLLs"
        path_parts = [str(base_prefix), str(dll_dir), os.environ.get("PATH", "")]
        os.environ["PATH"] = os.pathsep.join(part for part in path_parts if part)

        tcl_root = base_prefix / "tcl"
        tcl_library = tcl_root / "tcl8.6"
        tk_library = tcl_root / "tk8.6"
        if tcl_library.exists():
            os.environ.setdefault("TCL_LIBRARY", str(tcl_library))
        if tk_library.exists():
            os.environ.setdefault("TK_LIBRARY", str(tk_library))

    mpl_config_dir = Path(tempfile.gettempdir()) / "cpk_reporter_mpl"
    mpl_config_dir.mkdir(exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))


_prepare_runtime_environment()

from cpk_ui import run_app


if __name__ == "__main__":
    run_app()
