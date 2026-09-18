@echo off
setlocal EnableExtensions
set "FAILED=0"
title ctDNA WSL1 verification V4 explicit labels

echo ============================================================
echo  ctDNA pipeline - WSL1 / toolchain verification
echo  VERIFIER BUILD: V4-EXPLICIT-LABELS-2026-08-15
echo ============================================================
echo.

echo [1] WSL distributions:
wsl.exe -l -v
if errorlevel 1 goto :fatal
echo.

echo [2] Linux identity and /mnt/c:
wsl.exe bash -lc "echo USER=$USER; uname -a; test -d /mnt/c && echo OK: /mnt/c exists || { echo ERROR: /mnt/c missing; exit 1; }"
if errorlevel 1 goto :fatal
echo.

echo [3] Micromamba and ctdna_core:
wsl.exe bash -lc "test -x $HOME/.local/bin/micromamba || { echo ERROR: micromamba missing; exit 1; }; $HOME/.local/bin/micromamba --version; $HOME/.local/bin/micromamba -r $HOME/micromamba run -n ctdna_core python --version"
if errorlevel 1 goto :fatal
echo.

echo [4] Python backend imports:
wsl.exe bash -lc "$HOME/.local/bin/micromamba -r $HOME/micromamba run -n ctdna_core python -c 'import pandas,numpy,pysam,matplotlib,networkx,tkinter; print(\"OK: Python imports\")'"
if errorlevel 1 goto :fatal
echo.

echo [5] Required command-line tools:
echo     Each program name is printed BEFORE its test.
echo.

call :check "Java" "java"
call :check "Nextflow" "nextflow"
call :check "FastQC" "fastqc"
call :check "MultiQC" "multiqc"
call :check "Cutadapt" "cutadapt"
call :check "BWA classic" "bwa"
call :check "BWA-MEM2" "bwa-mem2"
call :check "samtools" "samtools"
call :check "bcftools" "bcftools"
call :check "fgbio" "fgbio"
call :check "SPAdes" "spades.py"
call :check "minimap2" "minimap2"
call :check "CNVkit" "cnvkit.py"
call :check "gzip" "gzip"
call :check "Manta configManta.py" "configManta.py"
call :check "Manta workflow wrapper" "ctdna-manta-run"
call :check "GRIDSS2" "gridss"
call :check "DELLY" "delly"
call :check "SvABA" "svaba"
call :check "GATK" "gatk"
call :check "VEP" "vep"
call :check "VEP installer" "vep_install"

echo.
echo [6] Nextflow version:
wsl.exe bash -lc "$HOME/.local/bin/micromamba -r $HOME/micromamba run -n ctdna_core nextflow -version"
if errorlevel 1 set "FAILED=1"
echo.

echo [7] Optional Agilent AGeNT:
echo PROGRAM: Agilent AGeNT agent.sh
wsl.exe bash -lc "$HOME/.local/bin/micromamba -r $HOME/micromamba run -n ctdna_core bash -lc 'command -v agent.sh >/dev/null 2>&1'"
if errorlevel 1 goto :agent_missing
echo STATUS : OK
goto :agent_done
:agent_missing
echo STATUS : OPTIONAL - NOT INSTALLED
:agent_done
echo.

if "%FAILED%"=="0" goto :success
echo ERROR: One or more REQUIRED command-line tools are missing.
goto :fatal

:success
echo Verification completed successfully.
pause
exit /b 0

:check
echo PROGRAM: %~1
wsl.exe bash -lc "$HOME/.local/bin/micromamba -r $HOME/micromamba run -n ctdna_core bash -lc 'command -v %~2 >/dev/null 2>&1'"
if errorlevel 1 goto :check_missing
echo STATUS : OK
echo.
goto :eof
:check_missing
echo STATUS : MISSING
echo.
set "FAILED=1"
goto :eof

:fatal
echo.
echo ERROR: WSL1 environment verification failed.
pause
exit /b 1
