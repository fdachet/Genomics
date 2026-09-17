from __future__ import annotations

ANDROID_STUDIO_DOWNLOADS = "https://developer.android.com/studio#command-line-tools-only"
ANDROID_STUDIO_DOWNLOADS_BASE = "https://developer.android.com/studio"
ANDROID_CMDLINE_WIN_ZIP = "https://dl.google.com/android/repository/commandlinetools-win-14742923_latest.zip"
ANDROID_PLATFORM_TOOLS = "https://developer.android.com/tools/releases/platform-tools"
ANDROID_SDKMANAGER_DOCS = "https://developer.android.com/tools/sdkmanager"
GRADLE_RELEASES = "https://gradle.org/releases/"
GRADLE_89_BIN_ZIP = "https://services.gradle.org/distributions/gradle-8.9-bin.zip"
GRADLE_INSTALL = "https://docs.gradle.org/current/userguide/installation.html"

TEMURIN_DOWNLOADS = "https://adoptium.net/temurin/releases/"
TEMURIN_JDK17_WIN_X64_INSTALLER = "https://api.adoptium.net/v3/installer/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
TEMURIN_JDK21_WIN_X64_INSTALLER = "https://api.adoptium.net/v3/installer/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse"

COMPONENTS = [
    {
        "key": "project_dir",
        "name": "App source-code folder",
        "kind": "folder",
        "required": True,
        "category": "1 - App source code",
        "verify_type": "project",
        "url": "",
        "download": "No program download. Obtain this by extracting a source-code ZIP with your normal ZIP software, then select the extracted project folder in the Project tab.",
        "explain": (
            "This is the editable folder that contains the app before it becomes an APK. It is the input to the APK build. "
            "It is not the APK file. It is not something installed on the phone. It is a folder on Windows, for example: "
            "C:\\Users\\You\\Desktop\\TableTextAPK. A real Android source-code folder normally contains settings.gradle, "
            "build.gradle, an app folder, and app\\src\\main\\AndroidManifest.xml. If you downloaded TableTextAPK_source.zip, "
            "right-click it, extract it, then select the extracted folder that contains settings.gradle."
        ),
        "install": (
            "Extract the Android source-code ZIP with your normal ZIP software. Then use the Project tab or this Browse button "
            "to select the extracted folder that contains settings.gradle. After this field is selected, press Verify."
        ),
    },
    {
        "key": "output_dir",
        "name": "Finished APK output folder",
        "kind": "folder",
        "required": True,
        "category": "1 - App source code",
        "verify_type": "output_dir",
        "url": "",
        "download": "No download.",
        "explain": (
            "This is just where the GUI copies the APK after a successful build. It can be any folder you control, "
            "for example C:\\Users\\You\\Desktop\\APK_Output. It is not part of Android and not part of Gradle."
        ),
        "install": "Create an empty folder anywhere you want, or let the GUI create it when verifying.",
    },
    {
        "key": "java_exe",
        "name": "Java program - java.exe",
        "kind": "file",
        "required": True,
        "category": "2 - Java JDK",
        "verify_type": "command_version",
        "command_args": ["-version"],
        "url": TEMURIN_DOWNLOADS,
        "download": "OpenJDK download page: Eclipse Temurin. Choose JDK 17 or 21 for Windows x64. Direct installer buttons are also available in Install Help. Java 25 may run sdkmanager but fails or is unsafe with Gradle 8.9; use JDK 17 or 21 for Gradle.",
        "explain": (
            "Java/JDK is needed because sdkmanager and Gradle run on Java. For this GUI, prefer JDK 17 or 21. This box must point directly to java.exe. "
            "Typical path: C:\\Program Files\\Eclipse Adoptium\\jdk-17...\\bin\\java.exe. The Verify button runs java.exe -version."
        ),
        "install": (
            "Download Eclipse Temurin JDK 17 or 21, not only JRE. Install it. Then browse to the installed JDK folder, open bin, and select java.exe. "
            "If the installer offers to set JAVA_HOME or PATH, enabling that is convenient but not mandatory for this GUI."
        ),
    },
    {
        "key": "java_home",
        "name": "Java folder - JAVA_HOME",
        "kind": "folder",
        "required": True,
        "category": "2 - Java JDK",
        "verify_type": "java_home",
        "url": TEMURIN_DOWNLOADS,
        "download": "Same JDK as above. This field is the folder, not the executable file.",
        "explain": (
            "JAVA_HOME is the JDK root folder. It is the folder that contains the bin folder. Do not select bin. Do not select java.exe. "
            "Example: C:\\Program Files\\Eclipse Adoptium\\jdk-17.0.18. The GUI uses this to tell Gradle which Java to run."
        ),
        "install": "After installing the JDK, select the folder that contains bin\\java.exe.",
    },
    {
        "key": "android_sdk_root_windows",
        "name": "Android SDK folder",
        "kind": "folder",
        "required": True,
        "category": "3 - Android SDK",
        "verify_type": "sdk_root",
        "url": ANDROID_CMDLINE_WIN_ZIP,
        "download": (
            "Direct ZIP for Windows command-line tools: " + ANDROID_CMDLINE_WIN_ZIP + "\n"
            "Important: this ZIP contains sdkmanager.bat only. It does NOT contain adb.exe, aapt2.exe, apksigner.bat, or zipalign.exe. "
            "Those are installed AFTERWARD by running sdkmanager with packages such as platform-tools and build-tools;35.0.0."
        ),
        "explain": (
            "The Windows Android SDK folder is the main toolbox folder used to compile Android apps. Recommended folder: C:\\Android\\Sdk. "
            "At first, after extracting command-line tools, this folder only has cmdline-tools\\latest\\bin\\sdkmanager.bat. "
            "After you run sdkmanager install packages, it will also contain platform-tools\\adb.exe, platforms\\android-XX, "
            "and build-tools\\XX.X.X\\aapt2.exe / apksigner.bat / zipalign.exe. "
            "So aapt2.exe missing right after downloading command-line tools is NORMAL."
        ),
        "install": (
            "Step 1: Create C:\\Android\\Sdk.\n"
            "Step 2: Download the Windows command-line tools ZIP.\n"
            "Step 3: Extract it so this exact file exists: C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat.\n"
            "Step 4: Do NOT double-click sdkmanager.bat; it is not a GUI. Run it through this GUI button or from Command Prompt.\n"
            "Step 5: Install packages with sdkmanager: platform-tools, platforms;android-35, build-tools;35.0.0. "
            "Only after Step 5 will adb.exe and aapt2.exe exist."
        ),
    },
    {
        "key": "cmdline_tools_zip",
        "name": "Downloaded command-line tools ZIP",
        "kind": "file",
        "required": True,
        "category": "3 - Android SDK",
        "verify_type": "file_exists",
        "url": ANDROID_CMDLINE_WIN_ZIP,
        "download": f"Direct Windows command-line tools ZIP: {ANDROID_CMDLINE_WIN_ZIP}",
        "explain": (
            "This is the ZIP file downloaded from the Android command-line tools page, for example "
            "commandlinetools-win-14742923_latest.zip. It contains sdkmanager.bat plus the lib folder/JAR files. "
            "The GUI can extract it into the correct SDK layout. Do not copy only sdkmanager.bat; the whole extracted cmdline-tools content is needed."
        ),
        "install": (
            "Download the Windows command-line tools ZIP. Then use Install Help -> Extract / repair command-line tools ZIP layout. "
            "The final folder must contain cmdline-tools\\latest\\bin, cmdline-tools\\latest\\lib, and source.properties."
        ),
    },
    {
        "key": "sdkmanager_exe",
        "name": "SDK package installer - sdkmanager.bat",
        "kind": "file",
        "required": True,
        "category": "3 - Android SDK",
        "verify_type": "command_version",
        "command_args": ["--version"],
        "url": ANDROID_CMDLINE_WIN_ZIP,
        "download": f"Direct Windows command-line tools ZIP containing sdkmanager.bat: {ANDROID_CMDLINE_WIN_ZIP}",
        "explain": (
            "sdkmanager.bat is a command-line package installer. Double-clicking it usually appears to do nothing because it expects arguments, "
            "for example --version, --list, --licenses, or package names. It is not a visual installer. "
            "This GUI runs it in the Log tab so you can see the output. It should normally be here: "
            "C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat."
        ),
        "install": (
            "Download the command-line tools ZIP and extract it into the SDK folder layout. Correct layout:\n"
            "C:\\Android\\Sdk\\cmdline-tools\\latest\\bin\\sdkmanager.bat\n"
            "Wrong common layout:\n"
            "C:\\Android\\Sdk\\cmdline-tools\\cmdline-tools\\bin\\sdkmanager.bat\n"
            "If you have the wrong layout, create a folder named latest and move the extracted bin/lib/source.properties files inside latest."
        ),
    },
    {
        "key": "adb_exe",
        "name": "Phone connection tool - adb.exe",
        "kind": "file",
        "required": False,
        "category": "3 - Android SDK",
        "verify_type": "command_version",
        "command_args": ["version"],
        "url": ANDROID_PLATFORM_TOOLS,
        "download": "Installed by running sdkmanager with package: platform-tools. This is NOT inside commandlinetools-win-...zip.",
        "explain": (
            "ADB means Android Debug Bridge. It is used to talk to a connected Android phone, install an APK, view logs, etc. "
            "It is not required only to compile an APK. If verification says adb not found, it means platform-tools is missing or adb.exe was not selected. "
            "Typical path: C:\\Android\\Sdk\\platform-tools\\adb.exe."
        ),
        "install": "Use the Install Help tab button: Install missing SDK packages - Windows. Or run: sdkmanager.bat \"platform-tools\". Then select C:\\Android\\Sdk\\platform-tools\\adb.exe.",
    },
    {
        "key": "aapt2_exe",
        "name": "Resource compiler - aapt2.exe",
        "kind": "file",
        "required": True,
        "category": "3 - Android SDK",
        "verify_type": "command_version",
        "command_args": ["version"],
        "url": ANDROID_STUDIO_DOWNLOADS,
        "download": "Installed by running sdkmanager with package: build-tools;35.0.0. This is NOT inside commandlinetools-win-...zip.",
        "explain": (
            "AAPT2 compiles Android resources: app names, XML layouts, icons, strings, manifest resources. "
            "It is missing immediately after downloading command-line tools because the command-line tools ZIP only provides sdkmanager. "
            "After build-tools is installed, typical path: C:\\Android\\Sdk\\build-tools\\35.0.0\\aapt2.exe."
        ),
        "install": "Use the Install Help tab button: Install missing SDK packages - Windows. Or run: sdkmanager.bat \"build-tools;35.0.0\". Then select C:\\Android\\Sdk\\build-tools\\35.0.0\\aapt2.exe.",
    },
    {
        "key": "apksigner_exe",
        "name": "APK signing tool - apksigner.bat",
        "kind": "file",
        "required": True,
        "category": "3 - Android SDK",
        "verify_type": "command_version",
        "command_args": ["--version"],
        "url": ANDROID_STUDIO_DOWNLOADS,
        "download": "Installed by running sdkmanager with package: build-tools;35.0.0. This is NOT inside commandlinetools-win-...zip.",
        "explain": (
            "Android will not install an unsigned APK. Debug builds are usually signed automatically by Gradle, "
            "but apksigner is part of a complete build-tools installation. It is installed with build-tools, not with the initial command-line tools ZIP. "
            "Typical path: C:\\Android\\Sdk\\build-tools\\35.0.0\\apksigner.bat."
        ),
        "install": "Use the Install Help tab button: Install missing SDK packages - Windows. Or run: sdkmanager.bat \"build-tools;35.0.0\". Then select apksigner.bat from the build-tools folder.",
    },
    {
        "key": "zipalign_exe",
        "name": "APK alignment tool - zipalign.exe",
        "kind": "file",
        "required": True,
        "category": "3 - Android SDK",
        "verify_type": "file_exists",
        "url": ANDROID_STUDIO_DOWNLOADS,
        "download": "Installed by running sdkmanager with package: build-tools;35.0.0. This is NOT inside commandlinetools-win-...zip.",
        "explain": (
            "zipalign optimizes the APK file layout. It is part of Android build-tools, not the initial command-line tools ZIP. Typical path: "
            "C:\\Android\\Sdk\\build-tools\\35.0.0\\zipalign.exe. The verification only checks that the file exists."
        ),
        "install": "Use the Install Help tab button: Install missing SDK packages - Windows. Or run: sdkmanager.bat \"build-tools;35.0.0\". Then select zipalign.exe from the build-tools folder.",
    },
    {
        "key": "gradle_wrapper",
        "name": "Project build script - gradlew.bat",
        "kind": "file",
        "required": False,
        "category": "4 - Gradle build program",
        "verify_type": "gradle_wrapper",
        "url": GRADLE_INSTALL,
        "download": "Usually already included inside the app source-code folder. It is not downloaded separately in normal use.",
        "explain": (
            "Gradle is the build program. The Gradle wrapper is a small script named gradlew.bat inside the source project. "
            "When present, it is the best way to build because it uses the Gradle version expected by that project. "
            "Typical path: C:\\Users\\You\\Desktop\\TableTextAPK\\gradlew.bat. If your source project does not include it, use Global Gradle instead."
        ),
        "install": (
            "First check inside the source-code folder for gradlew.bat. If it exists, select it. If it does not exist, install Global Gradle or generate wrapper files with a working Gradle setup."
        ),
    },

    {
        "key": "gradle_zip",
        "name": "Downloaded Gradle ZIP",
        "kind": "file",
        "required": False,
        "category": "4 - Gradle build program",
        "verify_type": "file_exists",
        "url": GRADLE_89_BIN_ZIP,
        "download": "Direct official Gradle 8.9 binary-only ZIP. This version matches the example Android project better than an arbitrary latest Gradle.",
        "explain": (
            "This is the downloaded Gradle ZIP file, for example C:\\Users\\You\\Downloads\\gradle-8.9-bin.zip. "
            "It is not the APK and it is not the Android SDK. Gradle is the build program that reads build.gradle and creates the APK by calling the Android SDK tools."
        ),
        "install": "Use the Install Help tab button: Open direct Gradle 8.9 binary ZIP. Download it, then select the ZIP here or in Install Help.",
    },
    {
        "key": "gradle_install_root",
        "name": "Gradle install folder",
        "kind": "folder",
        "required": False,
        "category": "4 - Gradle build program",
        "verify_type": "folder_exists",
        "url": GRADLE_INSTALL,
        "download": "No separate download. This is where the Gradle ZIP is extracted, usually C:\\Gradle.",
        "explain": (
            "This is the folder where Gradle versions are stored after extraction. Example: C:\\Gradle. "
            "After extraction, the real program is usually C:\\Gradle\\gradle-8.9\\bin\\gradle.bat."
        ),
        "install": "Create C:\\Gradle or use the Install Help tab button that extracts the downloaded Gradle ZIP automatically.",
    },
    {
        "key": "gradle_exe",
        "name": "Global Gradle - gradle.bat",
        "kind": "file",
        "required": False,
        "category": "4 - Gradle build program",
        "verify_type": "command_version",
        "command_args": ["-v"],
        "url": GRADLE_RELEASES,
        "download": "Gradle releases page. Choose the binary-only ZIP, extract it, then select bin\\gradle.bat.",
        "explain": (
            "Global Gradle is the Gradle program installed somewhere on your computer, independent from any project. "
            "It is only needed when the source project has no gradlew.bat. Typical selected file: C:\\Gradle\\gradle-9.5.1\\bin\\gradle.bat. "
            "The Verify button runs gradle.bat -v."
        ),
        "install": (
            "Download the binary-only Gradle ZIP from the releases page. Extract it to C:\\Gradle. Then select C:\\Gradle\\gradle-version\\bin\\gradle.bat."
        ),
    }
]

COMPONENT_BY_KEY = {component["key"]: component for component in COMPONENTS}
