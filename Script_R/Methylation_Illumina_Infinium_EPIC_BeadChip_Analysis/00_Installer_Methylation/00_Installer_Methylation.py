
from __future__ import annotations
import csv, json, os, queue, re, shlex, shutil, subprocess, threading, traceback
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

COLORS = {
    "bg":"#F3F7FB","panel":"#FFFFFF","navy":"#17324D","blue":"#2B6CB0",
    "blue_hover":"#1F5A96","teal":"#157A75","green":"#2F855A",
    "orange":"#C05621","red":"#C53030","muted":"#5E6B78","border":"#CBD5E0",
    "log_bg":"#0F172A","log_fg":"#E2E8F0"
}

def windows_to_wsl(path_text):
    text = str(path_text).strip()
    if not text: return ""
    if text.startswith("/"): return text
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if m:
        return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\","/")
    return text.replace("\\","/")

def wsl_to_windows(path_text):
    text = str(path_text).strip()
    if not text or os.name != "nt": return text
    m = re.match(r"^/mnt/([A-Za-z])/(.*)$", text)
    if m:
        return f"{m.group(1).upper()}:\\" + m.group(2).replace("/","\\")
    return text

def find_windows_rscript():
    found = shutil.which("Rscript")
    if found: return found
    if os.name == "nt":
        candidates = []
        for base in [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))/"R",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))/"R"
        ]:
            if base.is_dir():
                candidates += list(base.glob("R-*/bin/Rscript.exe"))
                candidates += list(base.glob("R-*/bin/x64/Rscript.exe"))
        if candidates:
            return str(sorted(candidates, key=lambda p: str(p))[-1])
    return ""

def run_process(command, log, cwd=None, check=True):
    shell = isinstance(command, str)
    display = command if shell else subprocess.list2cmdline([str(x) for x in command])
    log("$ " + str(display))
    proc = subprocess.Popen(
        command, cwd=str(cwd) if cwd else None, shell=shell,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, universal_newlines=True, bufsize=1
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    rc = proc.wait()
    if check and rc != 0:
        raise RuntimeError(f"Command failed with exit code {rc}:\n{display}")
    return rc

def run_windows_r(rscript, script, args, log, check=True):
    rscript = str(rscript).strip() or find_windows_rscript()
    if not rscript:
        raise RuntimeError(
            "Windows Rscript.exe was not found. Browse to your existing Windows Rscript.exe."
        )
    return run_process([rscript, str(script)] + [str(x) for x in args], log, check=check)

def _wsl_prefix(distro=""):
    cmd = ["wsl.exe" if os.name == "nt" else "wsl"]
    if str(distro).strip(): cmd += ["-d", str(distro).strip()]
    return cmd

def run_wsl_command(command_text, log, distro="", activate=True, check=True):
    command_text = str(command_text)
    if activate:
        command_text = 'source "$HOME/.methylation_wsl_activate.sh" && ' + command_text
    return run_process(_wsl_prefix(distro)+["bash","-lc",command_text], log, check=check)

def run_wsl_script(script_path, args, log, distro="", activate=True, check=True):
    script_wsl = windows_to_wsl(str(Path(script_path).resolve()))
    qargs = []
    for value in args:
        text = str(value)
        if re.match(r"^[A-Za-z]:[\\/]", text):
            text = windows_to_wsl(text)
        qargs.append(shlex.quote(text))
    command = "bash " + shlex.quote(script_wsl)
    if qargs: command += " " + " ".join(qargs)
    return run_wsl_command(command, log, distro=distro, activate=activate, check=check)

def convert_tsv_paths(input_tsv, output_tsv, columns, direction="wsl_to_windows"):
    src, dst = Path(input_tsv), Path(output_tsv)
    with src.open("r",encoding="utf-8-sig",newline="") as h:
        reader = csv.DictReader(h,delimiter="\t")
        rows, fields = list(reader), list(reader.fieldnames or [])
    converter = wsl_to_windows if direction=="wsl_to_windows" else windows_to_wsl
    for row in rows:
        for col in columns:
            if row.get(col): row[col] = converter(row[col])
    dst.parent.mkdir(parents=True,exist_ok=True)
    with dst.open("w",encoding="utf-8",newline="") as h:
        w = csv.DictWriter(h,fieldnames=fields,delimiter="\t")
        w.writeheader(); w.writerows(rows)
    return dst

class StepGUI:
    def __init__(self,title,subtitle,description,fields,runner,output_field=None,window_size="1180x860"):
        self.title,self.subtitle,self.description = title,subtitle,description
        self.fields,self.runner,self.output_field = fields,runner,output_field
        self.root = tk.Tk(); self.root.title(title); self.root.geometry(window_size)
        self.root.minsize(940,680); self.root.configure(bg=COLORS["bg"])
        self.vars={}; self.messages=queue.Queue(); self.worker=None
        self.status=tk.StringVar(value="Ready")
        self._styles(); self._build(); self.root.after(100,self._poll)

    def _styles(self):
        s=ttk.Style(self.root)
        try: s.theme_use("clam")
        except Exception: pass
        s.configure("Main.TFrame",background=COLORS["bg"])
        s.configure("Panel.TFrame",background=COLORS["panel"])
        s.configure("Header.TLabel",background=COLORS["navy"],foreground="white",
                    font=("Segoe UI",18,"bold"),padding=(12,10))
        s.configure("SubHeader.TLabel",background=COLORS["navy"],foreground="#D8E7F5",
                    font=("Segoe UI",10),padding=(12,0,12,10))
        s.configure("Panel.TLabelframe",background=COLORS["panel"])
        s.configure("Panel.TLabelframe.Label",background=COLORS["panel"],foreground=COLORS["navy"],
                    font=("Segoe UI",10,"bold"))
        s.configure("Panel.TLabel",background=COLORS["panel"],foreground="#243447")
        s.configure("Muted.TLabel",background=COLORS["panel"],foreground=COLORS["muted"])
        for name,color in [("Primary",COLORS["blue"]),("Backup",COLORS["teal"]),
                           ("Restore",COLORS["green"]),("Open",COLORS["orange"])]:
            s.configure(f"{name}.TButton",background=color,foreground="white",
                        font=("Segoe UI",10,"bold" if name=="Primary" else "normal"),padding=(10,7))

    def _var(self,spec):
        k,d=spec.get("kind","text"),spec.get("default","")
        if k=="bool": return tk.BooleanVar(value=bool(d))
        if k=="int": return tk.IntVar(value=int(d))
        if k=="float": return tk.DoubleVar(value=float(d))
        return tk.StringVar(value=str(d))

    def _build(self):
        outer=ttk.Frame(self.root,style="Main.TFrame"); outer.pack(fill="both",expand=True)
        head=ttk.Frame(outer,style="Panel.TFrame"); head.pack(fill="x")
        ttk.Label(head,text=self.title,style="Header.TLabel").pack(fill="x")
        ttk.Label(head,text=self.subtitle,style="SubHeader.TLabel").pack(fill="x")
        body=ttk.Frame(outer,padding=10,style="Main.TFrame"); body.pack(fill="both",expand=True)
        exp=ttk.LabelFrame(body,text="What this step does",padding=10,style="Panel.TLabelframe")
        exp.pack(fill="x",pady=(0,8))
        ttk.Label(exp,text=self.description,wraplength=1090,justify="left",style="Panel.TLabel").pack(anchor="w")

        formbox=ttk.LabelFrame(body,text="Inputs and parameters",padding=8,style="Panel.TLabelframe")
        formbox.pack(fill="x",pady=5)
        canvas=tk.Canvas(formbox,height=300,bg=COLORS["panel"],highlightthickness=0)
        sb=ttk.Scrollbar(formbox,orient="vertical",command=canvas.yview)
        inner=ttk.Frame(canvas,style="Panel.TFrame")
        inner.bind("<Configure>",lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0),window=inner,anchor="nw")
        canvas.configure(yscrollcommand=sb.set); canvas.pack(side="left",fill="x",expand=True); sb.pack(side="right",fill="y")

        for row,spec in enumerate(self.fields):
            var=self._var(spec); self.vars[spec["name"]]=var
            ttk.Label(inner,text=spec["label"],style="Panel.TLabel").grid(row=row,column=0,sticky="w",padx=(4,10),pady=5)
            kind=spec.get("kind","text")
            if kind=="bool":
                ttk.Checkbutton(inner,variable=var,text=spec.get("check_text","")).grid(row=row,column=1,sticky="w",pady=5)
            elif kind=="choice":
                ttk.Combobox(inner,textvariable=var,values=spec.get("choices",[]),state="readonly",width=28).grid(row=row,column=1,sticky="w",pady=5)
            elif kind in ("int","float"):
                ttk.Entry(inner,textvariable=var,width=18).grid(row=row,column=1,sticky="w",pady=5)
            else:
                ttk.Entry(inner,textvariable=var,width=74).grid(row=row,column=1,sticky="ew",pady=5)
                if kind=="file":
                    ttk.Button(inner,text="Browse...",command=lambda s=spec,v=var:self._browse_file(s,v)).grid(row=row,column=2,padx=6,pady=5)
                elif kind=="dir":
                    ttk.Button(inner,text="Browse...",command=lambda v=var:self._browse_dir(v)).grid(row=row,column=2,padx=6,pady=5)
            if spec.get("help"):
                ttk.Label(inner,text=spec["help"],wraplength=390,justify="left",style="Muted.TLabel").grid(row=row,column=3,sticky="w",padx=8,pady=5)
        inner.columnconfigure(1,weight=1)

        buttons=ttk.Frame(body,style="Main.TFrame"); buttons.pack(fill="x",pady=7)
        self.run_button=ttk.Button(buttons,text="RUN THIS STEP",style="Primary.TButton",command=self._run); self.run_button.pack(side="left",padx=3)
        ttk.Button(buttons,text="Backup Settings",style="Backup.TButton",command=self._backup).pack(side="left",padx=3)
        ttk.Button(buttons,text="Restore Settings",style="Restore.TButton",command=self._restore).pack(side="left",padx=3)
        if self.output_field:
            ttk.Button(buttons,text="Open Output Folder",style="Open.TButton",command=self._open_output).pack(side="left",padx=3)
        ttk.Button(buttons,text="Clear Log",command=lambda:self.log_widget.delete("1.0","end")).pack(side="left",padx=3)

        logbox=ttk.LabelFrame(body,text="Run log",padding=5,style="Panel.TLabelframe"); logbox.pack(fill="both",expand=True,pady=5)
        self.log_widget=tk.Text(logbox,wrap="none",font=("Consolas",10),bg=COLORS["log_bg"],fg=COLORS["log_fg"],insertbackground="white",relief="flat")
        sy=ttk.Scrollbar(logbox,orient="vertical",command=self.log_widget.yview)
        sx=ttk.Scrollbar(logbox,orient="horizontal",command=self.log_widget.xview)
        self.log_widget.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.log_widget.pack(side="left",fill="both",expand=True); sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x")
        bottom=ttk.Frame(body,style="Main.TFrame"); bottom.pack(fill="x",pady=(5,0))
        ttk.Label(bottom,textvariable=self.status).pack(side="left")
        self.progress=ttk.Progressbar(bottom,mode="indeterminate",length=270); self.progress.pack(side="right")

    def _browse_file(self,spec,var):
        v=filedialog.askopenfilename(filetypes=spec.get("filetypes",[("All files","*.*")]))
        if v: var.set(v)
    def _browse_dir(self,var):
        v=filedialog.askdirectory(initialdir=var.get() or None)
        if v: var.set(v)
    def values(self): return {k:v.get() for k,v in self.vars.items()}
    def log(self,text): self.messages.put(("log",str(text)))
    def _run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy","This step is already running."); return
        self.status.set("Running..."); self.progress.start(10); self.run_button.configure(state="disabled")
        vals=self.values()
        def work():
            try: self.messages.put(("done",self.runner(vals,self.log)))
            except Exception: self.messages.put(("error",traceback.format_exc()))
        self.worker=threading.Thread(target=work,daemon=True); self.worker.start()
    def _poll(self):
        try:
            while True:
                kind,payload=self.messages.get_nowait()
                if kind=="log":
                    self.log_widget.insert("end",payload+"\n"); self.log_widget.see("end")
                elif kind=="done":
                    self.progress.stop(); self.run_button.configure(state="normal"); self.status.set("Complete")
                    messagebox.showinfo(self.title,str(payload or "Step completed successfully."))
                elif kind=="error":
                    self.progress.stop(); self.run_button.configure(state="normal"); self.status.set("Error")
                    self.log_widget.insert("end",payload+"\n"); self.log_widget.see("end")
                    messagebox.showerror(self.title+" — Error",payload)
        except queue.Empty: pass
        self.root.after(100,self._poll)
    def _backup(self):
        p=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("JSON settings","*.json"),("All files","*.*")],initialfile="Step_Settings_Backup.json")
        if p:
            Path(p).write_text(json.dumps({"step":self.title,"settings":self.values()},indent=2),encoding="utf-8")
            messagebox.showinfo("Backup Settings",f"Settings saved to:\n{p}")
    def _restore(self):
        p=filedialog.askopenfilename(filetypes=[("JSON settings","*.json"),("All files","*.*")])
        if not p: return
        try:
            data=json.loads(Path(p).read_text(encoding="utf-8")); settings=data.get("settings",data)
            for k,v in settings.items():
                if k in self.vars: self.vars[k].set(v)
            messagebox.showinfo("Restore Settings",f"Settings restored from:\n{p}")
        except Exception as e: messagebox.showerror("Restore Settings",str(e))
    def _open_output(self):
        text=str(self.vars[self.output_field].get()).strip()
        if not text: return
        p=Path(text); p.mkdir(parents=True,exist_ok=True)
        if os.name=="nt": os.startfile(str(p))
        else: subprocess.Popen(["xdg-open",str(p)])
    def run(self): self.root.mainloop()

# -----------------------------------------------------------------------------
# EMBEDDED WORKER SUPPORT
# -----------------------------------------------------------------------------
def run_embedded_windows_r(rscript, r_code, args, log, check=True):
    """
    Execute R code embedded inside this Python file using the user's Windows R.
    A temporary .R file is created only for execution and removed immediately.
    """
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".R", prefix="methylation_step_",
            delete=False, encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(r_code)
            temp_path = handle.name
        return run_windows_r(rscript, temp_path, args, log, check=check)
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

def run_embedded_wsl_script(shell_code, args, log, distro="", activate=True, check=True):
    """
    Execute Bash code embedded inside this Python file in WSL1.
    A temporary .sh file is created only for execution and removed immediately.
    """
    import tempfile
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", prefix="methylation_step_",
            delete=False, encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(shell_code)
            temp_path = handle.name
        return run_wsl_script(
            temp_path, args, log, distro=distro, activate=activate, check=check
        )
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

# -----------------------------------------------------------------------------
# INSTALLER-SPECIFIC CODE
# -----------------------------------------------------------------------------

import importlib.util
import sys


EMBEDDED_INSTALL_WSL_SH = '#!/usr/bin/env bash\nset -euo pipefail\nENV_NAME="${1:-methylation}"\nMINIFORGE_DIR="${2:-$HOME/miniforge3}"\nACTIVATE_FILE="$HOME/.methylation_wsl_activate.sh"\nMINIFORGE_DIR="${MINIFORGE_DIR/#\\$HOME/$HOME}"\nMINIFORGE_DIR="${MINIFORGE_DIR/#\\~/$HOME}"\n\nfind_conda() {\n  if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE}" ]]; then echo "${CONDA_EXE}"\n  elif command -v conda >/dev/null 2>&1; then command -v conda\n  elif [[ -x "${MINIFORGE_DIR}/bin/conda" ]]; then echo "${MINIFORGE_DIR}/bin/conda"\n  fi\n}\nCONDA_EXE_PATH="$(find_conda || true)"\nif [[ -z "${CONDA_EXE_PATH}" ]]; then\n  case "$(uname -m)" in x86_64|amd64) A=x86_64;; aarch64|arm64) A=aarch64;; *) echo "Unsupported architecture"; exit 3;; esac\n  F="/tmp/Miniforge3-Linux-${A}.sh"\n  U="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${A}.sh"\n  if command -v curl >/dev/null 2>&1; then curl -fL --retry 3 -o "$F" "$U"\n  elif command -v wget >/dev/null 2>&1; then wget -O "$F" "$U"\n  else echo "ERROR: curl or wget is required"; exit 4; fi\n  bash "$F" -b -p "$MINIFORGE_DIR"; rm -f "$F"; CONDA_EXE_PATH="${MINIFORGE_DIR}/bin/conda"\nfi\nCONDA_BASE="$("$CONDA_EXE_PATH" info --base)"\nPKGS=(fastqc trim-galore bismark bowtie2 samtools multiqc sra-tools pigz perl)\nif ! "$CONDA_EXE_PATH" env list | awk \'{print $1}\' | grep -Fxq "$ENV_NAME"; then\n  "$CONDA_EXE_PATH" create -y -n "$ENV_NAME" -c conda-forge -c bioconda "${PKGS[@]}"\nelse\n  "$CONDA_EXE_PATH" install -y -n "$ENV_NAME" -c conda-forge -c bioconda "${PKGS[@]}"\nfi\ncat > "$ACTIVATE_FILE" <<EOF\n#!/usr/bin/env bash\nsource "${CONDA_BASE}/etc/profile.d/conda.sh"\nconda activate "${ENV_NAME}"\nEOF\nchmod +x "$ACTIVATE_FILE"\necho "Verifying tools with conda run; R is deliberately NOT installed in WSL."\nFAIL=0\nfor x in fastqc trim_galore bismark bowtie2 samtools multiqc prefetch fastq-dump fasterq-dump; do\n  if "$CONDA_EXE_PATH" run -n "$ENV_NAME" bash -lc "command -v $x" >/dev/null 2>&1; then echo "[PASS] $x"\n  else echo "[FAIL] $x"; FAIL=$((FAIL+1)); fi\ndone\n[[ "$FAIL" -eq 0 ]] || exit 10\necho "Activation helper: $ACTIVATE_FILE"\n'
EMBEDDED_INSTALL_WINDOWS_R = '#!/usr/bin/env Rscript\noptions(repos=c(CRAN="https://cloud.r-project.org"))\noptions(timeout=max(1800,getOption("timeout")))\nif (!requireNamespace("BiocManager",quietly=TRUE)) install.packages("BiocManager")\npackages <- c(\n "minfi","limma","methylKit","DMRcate","GenomicRanges","IRanges",\n "IlluminaHumanMethylationEPICmanifest","IlluminaHumanMethylationEPICanno.ilm10b4.hg19",\n "IlluminaHumanMethylationEPICv2manifest","IlluminaHumanMethylationEPICv2anno.20a1.hg38",\n "minfiDataEPIC"\n)\ncat("Windows R:",R.version.string,"\\n"); print(.libPaths())\nfailed <- character()\nfor (pkg in packages) {\n if (!requireNamespace(pkg,quietly=TRUE)) {\n  tryCatch(BiocManager::install(pkg,ask=FALSE,update=FALSE,dependencies=TRUE),\n           error=function(e) cat("INSTALL ERROR:",conditionMessage(e),"\\n"))\n }\n if (requireNamespace(pkg,quietly=TRUE)) cat("[PASS]",pkg,as.character(packageVersion(pkg)),"\\n")\n else {cat("[FAIL]",pkg,"\\n"); failed<-c(failed,pkg)}\n}\nif (length(failed)) quit(status=10)\n'
EMBEDDED_VERIFY_WINDOWS_R = '#!/usr/bin/env Rscript\npackages<-c("BiocManager","minfi","limma","methylKit","DMRcate","GenomicRanges","IRanges",\n"IlluminaHumanMethylationEPICmanifest","IlluminaHumanMethylationEPICanno.ilm10b4.hg19",\n"IlluminaHumanMethylationEPICv2manifest","IlluminaHumanMethylationEPICv2anno.20a1.hg38")\nfailed<-character(); cat("R:",R.version.string,"\\n"); print(.libPaths())\nfor(pkg in packages){ok<-requireNamespace(pkg,quietly=TRUE);ver<-if(ok)as.character(packageVersion(pkg))else"-";\ncat(sprintf("%-60s %-6s %s\\n",pkg,if(ok)"PASS"else"FAIL",ver));if(!ok)failed<-c(failed,pkg)}\nif(length(failed))quit(status=10)\n'

def runner(v, log):
    rscript = str(v["rscript"]).strip() or find_windows_rscript()
    if not rscript:
        raise RuntimeError("Windows Rscript.exe was not found.")

    log("=== Architecture ===")
    log("Windows Python: GUI + Python analyses")
    log("Windows R: existing user installation")
    log("WSL1: Linux methylation/sequencing tools only")
    log("R will NOT be installed in WSL/Conda.")

    missing = [
        x for x in ["numpy", "pandas", "scipy", "matplotlib"]
        if importlib.util.find_spec(x) is None
    ]
    if missing and v["install_python"]:
        run_process(
            [sys.executable, "-m", "pip", "install", "--upgrade"] + missing,
            log
        )
    elif missing:
        log("WARNING: missing Windows Python packages: " + ", ".join(missing))
    else:
        log("[PASS] numpy / pandas / scipy / matplotlib")

    try:
        import tkinter
        log("[PASS] tkinter")
    except Exception as exc:
        raise RuntimeError(f"tkinter missing: {exc}")

    if v["install_wsl"]:
        log("\n=== WSL1 tools ===")
        run_embedded_wsl_script(
            EMBEDDED_INSTALL_WSL_SH,
            [v["conda_env"], v["miniforge_dir"]],
            log,
            distro=v["wsl_distro"],
            activate=False
        )

    if v["install_r"]:
        log("\n=== Windows R/Bioconductor packages ===")
        run_embedded_windows_r(
            rscript, EMBEDDED_INSTALL_WINDOWS_R, [], log
        )

    log("\n=== Verify Windows R/Bioconductor packages ===")
    run_embedded_windows_r(
        rscript, EMBEDDED_VERIFY_WINDOWS_R, [], log
    )

    if v["verify_wsl"]:
        log("\n=== Verify WSL1 tools ===")
        command = (
            'source "$HOME/.methylation_wsl_activate.sh" && '
            'for x in fastqc trim_galore bismark bowtie2 samtools multiqc '
            'prefetch fastq-dump fasterq-dump; do '
            'if command -v "$x" >/dev/null 2>&1; then '
            'echo "[PASS] $x -> $(command -v "$x")"; '
            'else echo "[FAIL] $x"; exit 10; fi; done'
        )
        run_wsl_command(
            command, log, distro=v["wsl_distro"], activate=False
        )

    return (
        "Installation/verification complete.\n\n"
        "Windows R was reused; no R was installed in WSL/Conda.\n"
        f"Windows Rscript:\n{rscript}"
    )


fields=[
{"name":"rscript","label":"Windows Rscript.exe","kind":"file","default":find_windows_rscript(),"filetypes":[("Rscript.exe","Rscript.exe"),("Executables","*.exe"),("All files","*.*")],"help":"Your existing Windows R; no second R is installed."},
{"name":"wsl_distro","label":"WSL distribution (blank = default)","kind":"text","default":""},
{"name":"conda_env","label":"WSL Conda environment","kind":"text","default":"methylation","help":"Linux tools only."},
{"name":"miniforge_dir","label":"Miniforge folder inside WSL","kind":"text","default":"$HOME/miniforge3"},
{"name":"install_python","label":"Windows Python","kind":"bool","default":True,"check_text":"Install missing numpy/pandas/scipy/matplotlib"},
{"name":"install_wsl","label":"WSL1 tools","kind":"bool","default":True,"check_text":"Install/repair FastQC, Trim Galore, Bismark, Bowtie2, samtools, MultiQC, SRA Toolkit"},
{"name":"install_r","label":"Windows R libraries","kind":"bool","default":True,"check_text":"Install/repair minfi, limma, methylKit, DMRcate and EPIC annotations"},
{"name":"verify_wsl","label":"Verification","kind":"bool","default":True,"check_text":"Verify all WSL commands"}
]
if __name__=="__main__":
 StepGUI("00_Installer_Methylation","Windows Python + Windows R + WSL1 Linux tools",
 "Colored installer with per-window Backup/Restore. It reuses Windows R and never installs R into Conda/WSL. WSL installation uses conda run and therefore does not require conda init.",
 fields,runner).run()
