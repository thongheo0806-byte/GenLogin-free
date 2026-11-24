"""ExtensionTabMixin: UI callbacks owned by this independent controller."""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox, ttk


class ExtensionTabMixin:
    def _build_extensions_tab(self, extensions_tab):
        # Extensions are never downloaded automatically and never executed on install.
        extension_header = ttk.Frame(extensions_tab)
        extension_header.pack(fill="x", pady=(0, 12))
        ttk.Label(extension_header, text="Locally installed Manifest V3 extensions", style="Heading.TLabel").pack(side="left")
        for title, cmd in (("Add folder", self.install_extension_folder), ("Add ZIP", self.install_extension_zip),
                           ("Update ZIP", self.update_extension_zip), ("Rollback update", self.rollback_extension_update),
                           ("Attach to selected profile", self.attach_extension), ("Detach", self.detach_extension),
                           ("Remove", self.remove_extension)):
            ttk.Button(extension_header, text=title, command=cmd).pack(side="right", padx=(7, 0))
        ttk.Label(extensions_tab, text="Only Playwright Chromium supports sideloaded extensions. Select a profile in Profiles first. Review permissions before enabling.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.extension_tree = ttk.Treeview(extensions_tab, columns=("name", "version", "permissions", "attached"), show="headings")
        for column, width in (("name", 280), ("version", 110), ("permissions", 470), ("attached", 120)):
            self.extension_tree.heading(column, text=column.title())
            self.extension_tree.column(column, width=width, stretch=column in ("name", "permissions"))
        self.extension_tree.pack(fill="both", expand=True)
        self.extension_tree.bind("<Double-1>", lambda *_: self.extension_details())
        ttk.Button(extensions_tab, text="View permissions", command=self.extension_details).pack(anchor="e", pady=(10, 0))
        self.refresh_extensions()

    def refresh_extensions(self):
        if not hasattr(self, "extension_tree"):
            return
        self.extension_tree.delete(*self.extension_tree.get_children())
        profile_id = self.selected_id(False)
        attached = set(self.extensions.attached_ids(profile_id)) if profile_id else set()
        for item in self.extensions.list():
            permissions = ", ".join([*item.permissions, *item.host_permissions])
            self.extension_tree.insert("", "end", iid=item.id,
                                       values=(item.name, item.version, permissions[:150], "Yes" if item.id in attached else "No"))

    def selected_extension(self):
        selection = self.extension_tree.selection()
        if not selection:
            messagebox.showinfo("Extensions", "Select an extension first", parent=self.root)
            return None
        return next((e for e in self.extensions.list() if e.id == selection[0]), None)

    def install_extension_folder(self):
        source = filedialog.askdirectory(title="Choose an unpacked Manifest V3 extension")
        if source:
            self._install_extension(Path(source), archive=False)

    def install_extension_zip(self):
        source = filedialog.askopenfilename(title="Choose a Manifest V3 extension archive", filetypes=[("ZIP", "*.zip")])
        if source:
            self._install_extension(Path(source), archive=True)

    def _install_extension(self, path: Path, archive: bool):
        if not messagebox.askyesno("Untrusted extension warning",
                                   "Browser extensions can read and modify web pages, including private data.\n"
                                   "Only install extensions that you trust and have reviewed. Continue?", parent=self.root):
            return
        try:
            record = self.extensions.install_zip(path) if archive else self.extensions.install_folder(path)
            self.refresh_extensions()
            self.notice(f"Imported {record.name}, not enabled on any profile")
            messagebox.showinfo("Extension imported (not enabled)",
                                f"Name: {record.name}\nVersion: {record.version}\n"
                                f"Permissions: {', '.join(record.permissions) or '(none)'}\n"
                                f"Hosts: {', '.join(record.host_permissions) or '(none)'}\n\n"
                                "Use Attach to allow this extension in a selected Chromium profile.", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Install extension", str(exc), parent=self.root)

    def update_extension_zip(self):
        old = self.selected_extension()
        if not old:
            return
        path = filedialog.askopenfilename(title="Choose a reviewed newer MV3 extension package",
                            filetypes=[("ZIP archive","*.zip")])
        if not path:
            return
        candidate = None
        try:
            candidate = self.extensions.prepare_update(old.id,Path(path),archive=True)
            additional_api = sorted(set(candidate.permissions) - set(old.permissions))
            additional_host = sorted(set(candidate.host_permissions) - set(old.host_permissions))
            if not messagebox.askyesno("Review extension update permissions",
                                       f"Update {old.name} from {old.version} to {candidate.version}?\n"
                                       "Review source trust: same extension name is NOT a developer signature.\n\n"
                                       f"NEW API permissions: {', '.join(additional_api) or '(none)'}\n"
                                       f"NEW host access: {', '.join(additional_host) or '(none)'}\n\n"
                                       "Affected profiles must all be stopped. "
                                       "The old package is retained for rollback.",
                                       parent=self.root):
                self.extensions.remove(candidate.id)
                return
            update = self.extensions.apply_update(old.id,candidate.id)
            self.refresh_extensions()
            self.notice(f"Updated {old.name} on {len(update.profile_ids)} stopped profiles")
            messagebox.showinfo("Extension updated",
                                f"New version imported: {candidate.version}\n"
                                "Restart affected profiles to load the new package.\n"
                                "Keep the old package if rollback may be necessary.",
                                parent=self.root)
        except Exception as exc:
            if candidate:
                try:
                    self.extensions.remove(candidate.id)
                except (ValueError, KeyError, OSError):
                    pass
            messagebox.showerror("Update extension",str(exc),parent=self.root)

    def rollback_extension_update(self):
        record = self.selected_extension()
        if not record:
            return
        updates = [u for u in self.extensions.list_upgrades()
                   if u.new_id == record.id and u.status == "applied"]
        if not updates:
            return messagebox.showinfo("Rollback",
                        "Select a newer extension package with an active update record.",
                        parent=self.root)
        latest = updates[0]
        previous = next((p for p in self.extensions.list() if p.id == latest.old_id), None)
        if previous is None:
            return messagebox.showerror("Rollback","Previous extension version is missing.",parent=self.root)
        if not messagebox.askyesno("Rollback extension",
                                   f"Restore {record.name} from {record.version} to {previous.version} "
                                   f"on {len(latest.profile_ids)} affected profiles?\n\n"
                                   "All affected browsers must be stopped. Current website actions "
                                   "cannot be undone. Restart profiles after rollback.",
                                   parent=self.root):
            return
        try:
            self.extensions.rollback_update(latest.id)
            self.refresh_extensions()
            self.notice(f"Rolled back {record.name} to {previous.version}")
        except Exception as exc:
            messagebox.showerror("Rollback extension",str(exc),parent=self.root)

    def extension_details(self):
        record = self.selected_extension()
        if record:
            messagebox.showinfo("Extension permissions",
                                f"{record.name} (v{record.version})\n\n"
                                f"API permissions: {', '.join(record.permissions) or '(none)'}\n"
                                f"Host permissions: {', '.join(record.host_permissions) or '(none)'}\n\n"
                                "Imported extension source is not audited or automatically updated.", parent=self.root)

    def attach_extension(self):
        record, pid = self.selected_extension(), self.selected_id()
        if not record or not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Profile running", "Stop this profile before modifying extensions")
            return
        if not messagebox.askyesno("Grant extension access",
                                   f"Enable {record.name} for this browser profile?\n\n"
                                   f"API permissions: {', '.join(record.permissions) or '(none)'}\n"
                                   f"Host permissions: {', '.join(record.host_permissions) or '(none)'}\n\n"
                                   "Extensions can observe page content.", parent=self.root):
            return
        try:
            self.extensions.attach(pid, record.id)
            self.refresh_extensions()
            self.notice(f"Attached extension {record.name}; restart the profile to load")
        except Exception as exc:
            messagebox.showerror("Attach extension", str(exc), parent=self.root)

    def detach_extension(self):
        record, pid = self.selected_extension(), self.selected_id()
        if not record or not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Profile running", "Stop the profile before detaching extensions")
            return
        self.extensions.detach(pid, record.id)
        self.refresh_extensions()
        self.notice(f"Detached {record.name}")

    def remove_extension(self):
        record = self.selected_extension()
        if not record:
            return
        if any(self.manager.active(p.id) and record.id in self.extensions.attached_ids(p.id) for p in self.store.all()):
            messagebox.showwarning("Extension active", "Stop attached browser profiles first")
            return
        if messagebox.askyesno("Remove extension", f"Delete local files for {record.name}?", parent=self.root):
            try:
                self.extensions.remove(record.id)
                self.refresh_extensions()
                self.notice(f"Removed {record.name}")
            except Exception as exc:
                messagebox.showerror("Remove extension", str(exc), parent=self.root)

