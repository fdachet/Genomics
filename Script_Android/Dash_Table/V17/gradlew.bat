@echo off
setlocal
cd /d "%~dp0"

if exist "C:\Gradle\gradle-8.9\bin\gradle.bat" (
    call "C:\Gradle\gradle-8.9\bin\gradle.bat" %*
    exit /b %ERRORLEVEL%
)

where gradle >nul 2>nul
if %ERRORLEVEL%==0 (
    call gradle %*
    exit /b %ERRORLEVEL%
)

echo ERROR: Gradle was not found.
echo Install Gradle 8.9, or put gradle.bat on PATH, or install it under C:\Gradle\gradle-8.9\bin\gradle.bat.
exit /b 1
