# Component-Based Docker Image Builder

**A graphical application for creating, inspecting, modifying, and validating Docker images from reusable software components.**

Component-Based Docker Image Builder is a Python/Tkinter desktop application for assembling custom Linux Docker environments. It brings together existing Docker images, precompiled executables, source code, Java applications, operating-system packages, language runtimes, and shared libraries in a single visual workflow.

The application is designed for general scientific and technical software, including bioinformatics and genomics environments that combine tools written in C/C++, Python, R, Perl, and Java.

## Features

- **Visual Docker image construction:** Configure a runtime base, add software components, generate a Dockerfile, build an image, and export it as a `.tar` archive.
- **Existing-image inspection:** Load Docker image archives and inventory installed executables, OS packages, Java archives, and software versions.
- **Component-based assembly:** Add precompiled binaries, directories, JAR applications, source-code projects, and OS packages with configurable destination paths.
- **Separate build and runtime environments:** Compile software in a selected builder image and include the resulting artifacts in a different, typically smaller runtime image.
- **Language environments:** Configure Java, Python, R, Perl, and associated packages, including R/Bioconductor software.
- **Dependency discovery:** Examine package requirements, native shared libraries, language runtimes, and component-to-component relationships.
- **Flexible component management:** Add, edit, enable, disable, or remove components; review dependency changes and identify possible replacement providers.
- **Manual installation confirmation:** Record user-confirmed software versions and executable paths separately from automatically verified results.
- **Configurable build policies:** Choose offline operation or approve network downloads; select strict, permissive, or assembly-only build modes.
- **Software verification:** Automatically probe versions, help commands, installation status, and supported self-tests; add custom tests for particular applications.
- **Image revision and compaction:** Revisit an already built image, apply component changes, and compact the resulting image.
- **Project persistence:** Save and reopen project configurations as JSON, with component metadata and provenance.
- **Image export:** Export a completed Docker image as a portable Docker `.tar` archive.

## Requirements

- Windows with **Python 3** and **Tkinter**.
- **Docker Desktop** installed and running, using Linux containers.
- The Python source files from this repository stored together in the same directory.

The GUI uses Python's standard-library modules, so its main interface does not require a separate Python package installation step.

## Start the application

Download or clone the repository, open a terminal in the directory containing the Python files, and run:

```powershell
python Docker_Component_Image_Builder_GUI.py
```

The application opens a seven-tab interface covering project configuration, image inventory, software components, compilation, runtime libraries, image building, and verification.

## Quick start

### 1. Prepare a base image

Docker images can be saved as archives for selection in the GUI. For example:

```powershell
docker pull ubuntu:24.04
docker save -o ubuntu_24.04.tar ubuntu:24.04
```

You can also prepare a distinct build environment:

```powershell
docker pull gcc:14
docker save -o gcc_14.tar gcc:14
```

### 2. Select the project and images

Open **Tab 1 — Project / Base** and choose:

1. A project directory.
2. A folder for the final exported Docker image.
3. The runtime base image archive (`.tar`).
4. An optional separate builder image archive (`.tar`).
5. Your network and dependency-handling preferences.

Use **Tab 2 — Base Inventory** to load the selected images into Docker and inspect their operating system, architecture, executables, packages, and detected versions.

### 3. Assemble components

In **Tab 3 — Add Components**, add files or software requirements to the project:

- Existing executable files and directories.
- Application JAR files.
- Source directories to compile.
- Operating-system packages and language-runtime components.
- Custom language environments through **Language runtimes / Custom setup**.

Specify destination paths and use **Resolve dependencies** to review software requirements. Existing image components can also be examined, edited, enabled or disabled, and selected for removal.

### 4. Compile source code, if needed

In **Tab 4 — Compile Sources**, select a source component, detect or specify its build system, set its build command and output path, and choose **Compile Source and Save Output**.

Compilation takes place in the builder environment. The compiled files are made available for inclusion in the runtime image.

### 5. Review runtime dependencies

Use **Tab 5 — Runtime Libraries** to inspect required packages, missing libraries, and available providers. You can add requirements to Tab 3, review dependency changes, or manually confirm installed components.

### 6. Build the Docker image

In **Tab 6 — Build Docker Image**:

1. Enter a name for the final image.
2. Select a build-context folder.
3. Click **Generate Dockerfile** to assemble the build instructions.
4. Click **Show Dockerfile** to inspect the generated configuration.
5. Click **Build Final Image**.

The same tab offers commands for checking OS packages, revising an existing built image, and compacting it.

### 7. Verify and export

In **Tab 7 — Verify / Export**, click **Auto-check all components** or **Check selected**. The program can inspect installation status, executable versions, help/startup behavior, and configured functional tests.

Use **Add project test** to define additional checks, **Save report** to retain verification results, and **Export image .tar** to save the image for later loading or distribution.

To import an exported archive into Docker:

```powershell
docker load -i my_genomics_image.tar
```

## Example 1 — Assemble an RNA-seq analysis environment

A typical RNA-seq environment combines command-line aligners, count-generation utilities, and R packages.

| Component | Example role | How to add it |
| --- | --- | --- |
| STAR | RNA-seq alignment | Precompiled executable or source component |
| SAMtools | BAM/SAM processing | Executable or OS package |
| featureCounts | Gene-level read counting | Precompiled executable or source component |
| Python | Analysis scripts and utilities | Language runtime |
| R | Statistical analysis | Language runtime |
| DESeq2 | Differential gene expression | R/Bioconductor package |
| DEXSeq | Differential exon usage | R/Bioconductor package |

**Illustrative workflow:**

1. Select an Ubuntu or Debian runtime base.
2. Add STAR, SAMtools, and featureCounts in Tab 3 with their intended executable destinations, such as `/usr/local/bin/`.
3. Open **Language runtimes / Custom setup** to configure R and the required Bioconductor packages.
4. Review shared-library and OS package requirements in Tab 5.
5. Generate and build the Docker image in Tab 6.
6. Verify the installed executables and R packages in Tab 7.

The result is a single Docker environment containing the tools selected for an RNA-seq analysis workflow.

## Example 2 — Combine Java applications requiring different runtimes

Some scientific tools have different Java requirements. For example:

| Application | Example requirement |
| --- | --- |
| `GenomeReport.jar` | Java 17 or newer |
| `LegacySummary.jar` | Java 8 or newer |

An image can be configured with multiple Java runtime versions and their corresponding executable locations.

1. Import the JAR applications as components.
2. Configure Java runtimes through **Language runtimes / Custom setup**.
3. Review the detected Java requirements.
4. Record available runtime versions and paths with **Manually confirm installed**, when appropriate.
5. Build and verify the resulting image.

For an already populated image, the component-management interface can also review removal of a runtime and record an alternative component proposed to satisfy an application's dependency.

## Example 3 — Compile a C/C++ bioinformatics program

A source project may require a compiler, build tools, and development libraries that are not needed to run its final executable.

1. Select a builder image containing the appropriate compiler toolchain.
2. Select a separate runtime image for the final program.
3. Add the source directory as a **source component** in Tab 3.
4. In Tab 4, use **Detect build system & output** or supply a custom build command.
5. Compile the source and capture the output artifact.
6. Review its native-library requirements in Tab 5.
7. Build the final runtime image in Tab 6.

The builder is used for compilation, while the final Docker image receives the compiled application and its configured runtime dependencies.

## Example 4 — Inspect and modify an existing Docker image

The program can be used to update an environment that already contains software.

**Example:** An existing image contains Java 8, Java 17, several scientific JAR files, and command-line utilities.

1. Save the existing Docker image as a `.tar` archive.
2. Open it as the runtime base in Tabs 1 and 2.
3. Inspect installed components and versions in **Base Inventory**.
4. In Tab 3, choose the relevant inventory category and select a component to modify or remove.
5. Use **Review removal dependencies / substitutes** to inspect affected requirements and choose possible replacement providers.
6. Add any new components or runtimes required for the updated image.
7. Rebuild or revise the image and run the verification checks.

This workflow supports incremental changes to an existing scientific software environment.

## Example 5 — Build with a custom verification test

Verification can go beyond checking whether an executable exists.

For example, a command-line program may provide:

```bash
toolname --version
toolname --help
```

In **Tab 7 — Verify / Export**, the automatic tests can be reviewed and edited. Use **Add project test** to supply a command, test inputs, and an expected result for a scientific application.

This allows an image to carry checks that are relevant to the software it contains.

## Interface overview

| Tab | Purpose |
| --- | --- |
| **1. Project / Base** | Configure project folders, runtime and builder archives, network policy, and build mode. |
| **2. Base Inventory** | Load images, inspect installed software, and examine detected versions. |
| **3. Add Components** | Manage binaries, JARs, sources, packages, and runtime components; resolve and review dependencies. |
| **4. Compile Sources** | Build source-code components in a separate builder image and capture outputs. |
| **5. Runtime Libraries** | Review OS packages, shared libraries, and component dependency requirements. |
| **6. Build Docker Image** | Generate the Dockerfile, assemble the image, revise builds, and compact images. |
| **7. Verify / Export** | Run software checks, add custom tests, save reports, and export a Docker archive. |

## Build and network options

The project interface provides three build modes:

- **Strict:** Require dependencies during the image-building process.
- **Permissive:** Build while recording outstanding requirements.
- **Assembly only:** Assemble selected components without installing additional packages.

Network controls allow an offline workflow or confirmation before downloading packages. Component setup, installation checks, and build outputs are tracked within the project state.

## Project configuration and provenance

Use **Save project JSON** in Tab 1 to store the application configuration and **Load project JSON** to resume work.

The project records component choices, environment settings, installation information, and verification data. Manual confirmations are distinguished from automatically discovered installation results, making it possible to record both detected and user-specified software information.

## Applications

The component-based approach can be used to construct environments for:

- Bulk and single-cell RNA sequencing.
- Genomics and variant-analysis tools.
- R/Bioconductor statistical workflows.
- Custom C/C++ analysis utilities.
- Python and Perl bioinformatics applications.
- Java-based scientific software.
- Scientific pipelines that combine programs from several programming languages.

The application is intended to make Docker environment assembly, software inventory, dependency review, and validation accessible through a unified graphical interface.
