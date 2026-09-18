#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$PROJECT_DIR"

MICROMAMBA_BIN="${HOME}/.local/bin/micromamba"
MAMBA_ROOT_PREFIX="${HOME}/micromamba"
export MAMBA_ROOT_PREFIX

echo
echo "============================================================"
echo " ctDNA tumor-genome pipeline - verified WSL1 installer"
echo "============================================================"
echo

for f in \
    environment_core.yml \
    environment_manta.yml \
    environment_gatk.yml \
    environment_vep.yml \
    environment_gridss.yml \
    environment_delly.yml \
    environment_svaba.yml \
    requirements_backend.txt; do
    [[ -f "$PROJECT_DIR/$f" ]] || {
        echo "ERROR: missing required installer file: $f"
        exit 1
    }
done

# ---------------------------------------------------------------------------
# Base Linux commands needed before Micromamba exists.
# ---------------------------------------------------------------------------
missing_base=()
for cmd in tar bzip2; do
    command -v "$cmd" >/dev/null 2>&1 || missing_base+=("$cmd")
done
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
    missing_base+=("curl")
fi

if (( ${#missing_base[@]} > 0 )); then
    echo "Missing base WSL packages: ${missing_base[*]}"
    if command -v apt-get >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
        echo "Installing base WSL packages with apt..."
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl bzip2 tar
    else
        echo "ERROR: install curl (or wget), tar, bzip2, and CA certificates, then rerun."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Install Micromamba.
# ---------------------------------------------------------------------------
if [[ ! -x "$MICROMAMBA_BIN" ]]; then
    echo "[1/11] Installing standalone Micromamba..."
    mkdir -p "${HOME}/.local/bin"
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    if command -v curl >/dev/null 2>&1; then
        curl -Ls "https://micro.mamba.pm/api/micromamba/linux-64/latest" \
            | tar -xj -C "$TMP_DIR" bin/micromamba
    else
        wget -qO- "https://micro.mamba.pm/api/micromamba/linux-64/latest" \
            | tar -xj -C "$TMP_DIR" bin/micromamba
    fi

    install -m 0755 "$TMP_DIR/bin/micromamba" "$MICROMAMBA_BIN"
else
    echo "[1/11] Micromamba already installed."
fi

"$MICROMAMBA_BIN" --version

create_env () {
    local env="$1"
    local file="$2"

    if "$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" env list \
        | awk '{print $1}' | grep -Fxq "$env"; then
        echo "Updating $env..."
        "$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" \
            env update -n "$env" -f "$file" -y --prune
    else
        echo "Creating $env..."
        "$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" \
            create -n "$env" -f "$file" -y --strict-channel-priority
    fi
}

# ---------------------------------------------------------------------------
# Core environment: Python backend + common bioinformatics tools + Nextflow.
# ---------------------------------------------------------------------------
echo "[2/11] Core environment..."
create_env ctdna_core "$PROJECT_DIR/environment_core.yml"

echo "Installing/updating Python backend packages in ctdna_core..."
"$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" run -n ctdna_core \
    python -m pip install --upgrade -r "$PROJECT_DIR/requirements_backend.txt"

"$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" run -n ctdna_core \
    python -m pip check

# ---------------------------------------------------------------------------
# Separate environments required because of incompatible runtime stacks.
# ---------------------------------------------------------------------------
echo "[3/11] Manta environment..."
create_env ctdna_manta "$PROJECT_DIR/environment_manta.yml"

echo "[4/11] GATK environment..."
create_env ctdna_gatk "$PROJECT_DIR/environment_gatk.yml"

echo "[5/11] VEP environment..."
create_env ctdna_vep "$PROJECT_DIR/environment_vep.yml"

echo "[6/11] GRIDSS2 environment..."
create_env ctdna_gridss "$PROJECT_DIR/environment_gridss.yml"

echo "[7/11] DELLY environment..."
create_env ctdna_delly "$PROJECT_DIR/environment_delly.yml"

echo "[8/11] SvABA environment..."
create_env ctdna_svaba "$PROJECT_DIR/environment_svaba.yml"

# ---------------------------------------------------------------------------
# Transparent wrappers placed in the core environment.
# ---------------------------------------------------------------------------
echo "[9/11] Creating transparent wrappers..."
CORE_BIN="${MAMBA_ROOT_PREFIX}/envs/ctdna_core/bin"
mkdir -p "$CORE_BIN" "${HOME}/.local/bin"

cat > "${CORE_BIN}/configManta.py" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_manta configManta.py "\$@"
EOF2

cat > "${CORE_BIN}/ctdna-manta-run" <<EOF2
#!/usr/bin/env bash
WORKFLOW="\$1"
shift
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_manta python "\$WORKFLOW" "\$@"
EOF2

cat > "${CORE_BIN}/gatk" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_gatk gatk "\$@"
EOF2

cat > "${CORE_BIN}/vep" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_vep vep "\$@"
EOF2

cat > "${CORE_BIN}/vep_install" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_vep vep_install "\$@"
EOF2

cat > "${CORE_BIN}/gridss" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_gridss gridss "\$@"
EOF2

cat > "${CORE_BIN}/delly" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_delly delly "\$@"
EOF2

cat > "${CORE_BIN}/svaba" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_svaba svaba "\$@"
EOF2

chmod +x \
    "${CORE_BIN}/configManta.py" \
    "${CORE_BIN}/ctdna-manta-run" \
    "${CORE_BIN}/gatk" \
    "${CORE_BIN}/vep" \
    "${CORE_BIN}/vep_install" \
    "${CORE_BIN}/gridss" \
    "${CORE_BIN}/delly" \
    "${CORE_BIN}/svaba"

# Optional Agilent AGeNT integration.
# AGeNT is downloaded separately from Agilent. If AGENT_SH_PATH points to its
# agent.sh launcher, this installer makes it visible inside ctdna_core.
if [[ -n "${AGENT_SH_PATH:-}" ]]; then
    if [[ ! -f "$AGENT_SH_PATH" ]]; then
        echo "ERROR: AGENT_SH_PATH does not exist: $AGENT_SH_PATH"
        exit 1
    fi
    cat > "${CORE_BIN}/agent.sh" <<EOF2
#!/usr/bin/env bash
exec "${AGENT_SH_PATH}" "\$@"
EOF2
    chmod +x "${CORE_BIN}/agent.sh"
fi

# Convenient Nextflow launcher that always enters the correct core environment.
cat > "${HOME}/.local/bin/nextflow" <<EOF2
#!/usr/bin/env bash
exec "${MICROMAMBA_BIN}" -r "${MAMBA_ROOT_PREFIX}" run -n ctdna_core "${CORE_BIN}/nextflow" "\$@"
EOF2
chmod +x "${HOME}/.local/bin/nextflow"

# ---------------------------------------------------------------------------
# Verify Python imports and executable tools.
# ---------------------------------------------------------------------------
echo "[10/11] Verifying Python backend..."
"$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" run -n ctdna_core python - <<'PY'
import matplotlib
import networkx
import numpy
import pandas
import pysam
import tkinter
print("  [OK] Python imports")
PY

echo "[11/11] Verifying command-line tools..."
TOOLS=(
    python
    java
    nextflow
    fastqc
    multiqc
    cutadapt
    bwa
    bwa-mem2
    samtools
    bcftools
    fgbio
    spades.py
    minimap2
    cnvkit.py
    gzip
    configManta.py
    ctdna-manta-run
    gridss
    delly
    svaba
    gatk
    vep
    vep_install
)

failed=0
for tool in "${TOOLS[@]}"; do
    if "$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" run -n ctdna_core \
        bash -lc "command -v '$tool' >/dev/null 2>&1"; then
        echo "  [OK] $tool"
    else
        echo "  [ERROR] $tool not found"
        failed=1
    fi
done

# AGeNT is optional and cannot be installed automatically without obtaining it
# from Agilent. It is required only for the Agilent SureSelect XT HS2 AGeNT mode.
if "$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" run -n ctdna_core \
    bash -lc "command -v agent.sh >/dev/null 2>&1"; then
    echo "  [OK] agent.sh (Agilent AGeNT optional mode available)"
else
    echo "  [OPTIONAL] agent.sh not found."
    echo "             Generic/Cutadapt modes work normally."
    echo "             Agilent XT HS2 AGeNT mode requires a separate AGeNT download."
    echo "             Rerun with AGENT_SH_PATH=/path/to/agent.sh if needed."
fi

# VEP software is installed, but its large species/assembly cache is reference
# data and is intentionally not downloaded automatically.
if [[ -d "${HOME}/.vep" ]]; then
    echo "  [INFO] VEP cache directory exists: ${HOME}/.vep"
else
    echo "  [OPTIONAL] No VEP cache found at ${HOME}/.vep."
    echo "             Offline VEP annotation requires a matching local cache."
fi

echo
"$MICROMAMBA_BIN" -r "$MAMBA_ROOT_PREFIX" run -n ctdna_core nextflow -version || failed=1

echo
if [[ "$failed" -ne 0 ]]; then
    echo "Installation completed, but one or more REQUIRED verification checks failed."
    exit 1
fi

echo "Installation and required-tool verification finished successfully."
echo
echo "Reference note for GRIDSS2:"
echo "  Step 06 requires a classic BWA index for the exact reference FASTA."
echo "  Create it once with: bwa index /path/to/reference.fa"
echo "  The resulting .amb/.ann/.bwt/.pac/.sa files should stay beside the FASTA."
echo
if [[ ":$PATH:" != *":${HOME}/.local/bin:"* ]]; then
    echo "NOTE: ${HOME}/.local/bin is not currently in PATH."
    echo "You can still launch Nextflow with: ${HOME}/.local/bin/nextflow"
else
    echo "Nextflow launcher: nextflow"
fi
echo
