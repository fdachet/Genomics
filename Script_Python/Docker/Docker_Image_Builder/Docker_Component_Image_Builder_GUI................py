import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox, ttk

from project_state import ProjectState
from tab1_project_state import ProjectStateTab
from tab1_builder_base import BuilderBaseTab
from tab2_base import BaseTab
from tab3_components import ComponentsTab
from tab4_compile_sources import SourcesTab
from tab5_runtime_libraries import RuntimeTab
from tab6_build_image import BuildTab
from tab7_verify_export import ValidationTab
from tab8_package_finder import PackageFinderTab
from tab9_container import ContainerTab
from tab10_recognized_elements import RecognizedElementsTab
from recognized_elements import select_database


class DockerImageBuilderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Component-Based Docker Image Builder")
        self.geometry("1500x900")
        self.minsize(1200, 760)
        self.configure(bg="#D5D8DC")

        self.state = ProjectState({
            "project_dir": str(Path.cwd()),
        })

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            "TNotebook",
            background="#D5D8DC",
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            font=("Segoe UI", 10, "bold"),
            padding=(7, 8),
            background="#D6DBDF",
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#FFFFFF")],
            foreground=[("selected", "#17202A")],
        )

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.project_tab = ProjectStateTab(self.notebook, self)
        self.builder_tab = BuilderBaseTab(self.notebook, self)
        self.base_tab = BaseTab(self.notebook, self)
        self.components_tab = ComponentsTab(self.notebook, self)
        self.sources_tab = SourcesTab(self.notebook, self)
        self.runtime_tab = RuntimeTab(self.notebook, self)
        self.build_tab = BuildTab(self.notebook, self)
        self.validation_tab = ValidationTab(self.notebook, self)
        self.package_finder_tab = PackageFinderTab(self.notebook, self)
        self.container_tab = ContainerTab(self.notebook, self)
        self.recognized_tab = RecognizedElementsTab(self.notebook, self)

        self.notebook.add(self.project_tab, text="0. Runtime Base")
        self.notebook.add(self.builder_tab, text="1. Builder Base")
        self.notebook.add(self.base_tab, text="2. Inventory")
        self.notebook.add(self.components_tab, text="3. Components")
        self.notebook.add(self.sources_tab, text="4. Compile")
        self.notebook.add(self.runtime_tab, text="5. Dependencies")
        self.notebook.add(self.build_tab, text="6. Build Image")
        self.notebook.add(self.validation_tab, text="7. Verify / Export")
        self.notebook.add(self.package_finder_tab, text="8. Packages")
        self.notebook.add(self.container_tab, text="9. Container")
        self.notebook.add(self.recognized_tab, text="10. Recognized")

        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.state.subscribe(self._state_changed)
        self._exit_after_build = False
        self.protocol('WM_DELETE_WINDOW', self._request_close)

    def _request_close(self):
        if self._exit_after_build or self.build_tab._busy:
            messagebox.showinfo(
                'Docker image build in progress',
                'The Docker image is still being assembled or exported. The program must remain open until this operation finishes.',
                parent=self,
            )
            return
        answer = messagebox.askyesnocancel(
            'Build and save before quitting?',
            'Assemble the complete Docker image and save it to a .tar archive before quitting?\n\n'
            'Yes — Build the complete image and save the TAR, then quit only after success.\n'
            'No — Quit without building or saving a new TAR.\n'
            'Cancel — Return to the application.',
            parent=self,
        )
        if answer is None:
            return
        if answer is False:
            self.destroy()
            return
        self._exit_after_build = True
        try:
            self.notebook.select(self.build_tab)
            self.build_tab.build()
        except Exception as exc:
            self._exit_after_build = False
            traceback.print_exc()
            messagebox.showerror('Build before exit', str(exc), parent=self)
            return
        if not self.build_tab._busy:
            self._exit_after_build = False

    def _build_finished_for_exit(self, success):
        if not self._exit_after_build:
            return
        self._exit_after_build = False
        if success:
            self.after_idle(self.destroy)

    def _state_changed(self, state, key):
        try:
            select_database(state.get('recognized_elements_database'))
        except ValueError:
            pass
        try:
            self.after_idle(self.project_tab.refresh_from_project_state)
        except Exception:
            pass

    def _tab_changed(self, event=None):
        try:
            selected = self.notebook.nametowidget(self.notebook.select())
        except Exception:
            return

        refresh = getattr(selected, "refresh_from_project_state", None)
        if callable(refresh):
            try:
                refresh()
                auto_check = getattr(selected, 'auto_check', None)
                if callable(auto_check):
                    auto_check()
            except Exception as exc:
                traceback.print_exc()
                messagebox.showerror('Tab refresh error',
                                     f'{selected.__class__.__name__} could not refresh:\n{type(exc).__name__}: {exc}\n\n'
                                     'See the Python console for the complete traceback.', parent=self)


if __name__ == "__main__":
    DockerImageBuilderApp().mainloop()
