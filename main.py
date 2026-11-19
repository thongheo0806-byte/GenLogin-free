"""AutumnGenLogin desktop entry point and CI-friendly packaged self-test."""
from __future__ import annotations

import sys
import json


def self_check() -> int:
    try:
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from autumn_genlogin.models import Profile
        from autumn_genlogin.storage import Store
        import playwright.sync_api  # noqa: F401
        import keyring  # noqa: F401

        with TemporaryDirectory() as d:
            store = Store(Path(d))
            p = store.save(Profile(name="Self-check", start_url="https://example.com"))
            if store.get(p.id).name != "Self-check":
                return 2
            store.delete(p.id)
        print("AutumnGenLogin self-check OK")
        return 0
    except Exception as exc:
        print(f"AutumnGenLogin self-check FAILED: {exc}", file=sys.stderr)
        return 1


def doctor() -> int:
    from autumn_genlogin.storage import Store
    from autumn_genlogin.diagnostics import audit_store
    report = audit_store(Store(initialize=False))
    if "--doctor-json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report["checks"]:
            print(f"{item['status'].upper():4} {item['name']}: {item['detail']}")
        print("Summary:", report["summary"])
    return 1 if report["summary"]["failed"] else 0


def run_hub() -> int:
    """Self-hosted metadata sync server, loopback-only unless TLS proxy is used."""
    from pathlib import Path
    from autumn_genlogin.storage import data_home
    from autumn_genlogin.team_sync import TeamHub, HubHTTPServer
    import os
    port = int(os.environ.get("AUTUMN_HUB_PORT", "8899"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid sync hub port")
    hub = TeamHub(data_home() / "team-hub.sqlite3")
    server = HubHTTPServer(("127.0.0.1", port), hub)
    print(f"Autumn sync hub listening at http://127.0.0.1:{port}; TLS required for remote access",flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main() -> int:
    if "--hub" in sys.argv:
        return run_hub()
    if "--doctor" in sys.argv or "--doctor-json" in sys.argv:
        return doctor()
    if "--self-check" in sys.argv:
        return self_check()
    import tkinter as tk
    from autumn_genlogin.ui import App
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    try:
        App(root)
    except Exception as exc:
        # A damaged/newer SQLite catalog must not silently crash pythonw.exe.
        # The doctor path deliberately uses Store(initialize=False) and still works.
        message = (
            "AutumnGenLogin could not open its local profile catalog.\n\n"
            f"{type(exc).__name__}: {str(exc)[:240]}\n\n"
            "Your browser data has NOT been deleted.\n"
            "Open a terminal in the application folder and run:\n"
            "  START-WINDOWS.cmd --doctor\n"
            "Back up the data directory before attempting repairs."
        )
        print(message, file=sys.stderr)
        try:
            from tkinter import messagebox
            messagebox.showerror("AutumnGenLogin startup failed", message, parent=root)
        finally:
            root.destroy()
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
