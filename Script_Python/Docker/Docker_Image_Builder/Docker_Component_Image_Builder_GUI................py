import tkinter as tk
from pathlib import Path
from tkinter import ttk

from project_state import ProjectState
from tab1_project_state import ProjectStateTab
from tab2_base import BaseTab
from tab3_components import ComponentsTab
from tab4_compile_sources import SourcesTab
from tab5_runtime_libraries import RuntimeTab
from tab6_build_image import BuildTab
from tab7_verify_export import ValidationTab


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
            padding=(14, 8),
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
        self.base_tab = BaseTab(self.notebook, self)
        self.components_tab = ComponentsTab(self.notebook, self)
        self.sources_tab = SourcesTab(self.notebook, self)
        self.runtime_tab = RuntimeTab(self.notebook, self)
        self.build_tab = BuildTab(self.notebook, self)
        self.validation_tab = ValidationTab(self.notebook, self)

        self.notebook.add(self.project_tab, text="1. Project / Base")
        self.notebook.add(self.base_tab, text="2. Base Inventory")
        self.notebook.add(self.components_tab, text="3. Add Components")
        self.notebook.add(self.sources_tab, text="4. Compile Sources")
        self.notebook.add(self.runtime_tab, text="5. Runtime Libraries")
        self.notebook.add(self.build_tab, text="6. Build Docker Image")
        self.notebook.add(self.validation_tab, text="7. Verify / Export")

        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.state.subscribe(self._state_changed)

    def _state_changed(self, state, key):
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
            except Exception:
                pass


if __name__ == "__main__":
    DockerImageBuilderApp().mainloop()
