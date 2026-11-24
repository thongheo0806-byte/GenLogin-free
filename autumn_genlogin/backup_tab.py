"""BackupTabMixin: UI callbacks owned by this independent controller."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from .profile_backup import export_encrypted_profile, restore_encrypted_profile


class BackupTabMixin:
    def backup_profile(self):
        pid = self.selected_id()
        if not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Encrypted profile backup",
                                   "Close this browser profile before backing up its session.",
                                   parent=self.root)
            return
        if not messagebox.askyesno("Sensitive browser-data backup",
                                   "The encrypted backup contains browser cookies, sessions and local storage.\n"
                                   "It intentionally excludes OS vault passwords and installed extension packages.\n\n"
                                   "Keep the passphrase private. Lost passphrases cannot be recovered. Continue?",
                                   parent=self.root):
            return
        target = filedialog.asksaveasfilename(title="Save encrypted profile backup",
                        defaultextension=".aglb", filetypes=[("Autumn encrypted backup","*.aglb")])
        if not target:
            return
        secret = simpledialog.askstring("Encrypt profile",
                        "Enter a strong passphrase (12+ characters):", show="*",parent=self.root)
        if secret is None:
            return
        check = simpledialog.askstring("Confirm passphrase",
                        "Re-enter the backup passphrase:", show="*",parent=self.root)
        if secret != check:
            messagebox.showerror("Encrypted backup","Passphrases do not match.",parent=self.root)
            return
        self._run_ui_task(
            lambda:export_encrypted_profile(self.store,pid,Path(target),secret),
            lambda count:self.notice(f"Encrypted profile backup saved ({count} files)"),
            title="Encrypted backup",
        )

    def restore_profile(self):
        source = filedialog.askopenfilename(title="Restore encrypted profile backup",
                        filetypes=[("Autumn encrypted backup","*.aglb")])
        if not source:
            return
        if not messagebox.askyesno("Restore sensitive profile data",
                                   "Restore browser data as a NEW local profile?\n"
                                   "Existing profiles will not be overwritten.\n"
                                   "Proxy passwords and extension packages are NOT restored.",
                                   parent=self.root):
            return
        secret = simpledialog.askstring("Decrypt profile",
                        "Enter the backup passphrase:", show="*",parent=self.root)
        if secret is None:
            return
        def done(profile):
            self.refresh()
            self.notice("Restored encrypted profile: "+profile.name)
            messagebox.showinfo("Profile restored",
                "Restored a NEW profile. Reconfigure proxy passwords and "
                "review browser compatibility before launching it.",
                parent=self.root)
        self._run_ui_task(
            lambda:restore_encrypted_profile(self.store,Path(source),secret),
            done,title="Restore backup",
        )

    def export_profiles(self):
        path=filedialog.asksaveasfilename(
            defaultextension=".json",filetypes=[("JSON","*.json")],
            initialfile="autumn-profiles.json")
        if path:
            self._run_ui_task(
                lambda:self.store.export_metadata(Path(path)),
                lambda count:self.notice(
                    f"Exported {count} metadata records (no passwords/cookies)"),
                title="Export metadata",
            )

    def import_profiles(self):
        path=filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if path:
            def done(count):
                self.refresh()
                self.notice(
                    f"Imported {count} profiles (fresh IDs and empty sessions)")
            self._run_ui_task(
                lambda:self.store.import_metadata(Path(path)),
                done,title="Import metadata",
            )

