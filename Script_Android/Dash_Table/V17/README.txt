Dash Table Gym patched source v25

Base: user-provided DashTableAPK_Source_v13.zip.
Layout is preserved from v13.

Changes:
1. Added Transpose button.
2. In Edit mode, long-pressing a cell selects all text in that cell.
3. Sorting by long press is active only in ReadOnly mode.
4. App label is Dash Table Gym.
5. App icon uses the original custom_app_icon.jpg extracted from the provided Dash Table Gym.apk.
6. gradlew.bat was added.
7. applicationId is local.weighttable.dashgym to avoid Android rejecting install over an older same-package app signed with a different key.
8. Save/Load now stores and restores table settings together with table data, including:
   - column widths
   - checkmark column width
   - row height
   - row spacing
   - checkmark text size
   - check/remove hold time
   - vibration/beep settings
   - multiline setting
   - editable/read-only cell and header colors
   - double header height setting
   - read-only/settings mode state

Build:
    gradlew.bat assembleDebug

Install this APK:
    app/build/outputs/apk/debug/app-debug.apk

If you want to keep the exact old package name local.weighttable, uninstall the old app first or use the same signing key as the original APK.
