# NextDash   visual Nextflow workflow builder

NextDash is a desktop Graphical User Interface for designing sample-aware [Nextflow](https://www.nextflow.io/) workflows as a spreadsheet-like diagram. The idea is a bit like building with Lego: start with small data and program blocks, put them together from left to right, then add the special blocks only when the workflow needs to wait, group, or join samples. I find this visual way of building a Nextflow pipeline more intuitive and more comprehensive than trying to describe the whole workflow only with comandes in a text file. It lets the user focus first on the logic and scientific part of the pipeline: what data goes where, which analysis is run, which samples must wait, and which samples must be paired. This can be easier to understand than reading a `main.nf` directly, and it can reveal flow or pairing mistakes that may not be easy to see in text-only programation. You can see the data, the programs, and the points where samples must meet before generating anything. NextDash turns the validated visual graph into a runnable `main.nf` and an input manifest, without requiring users to write the pipeline structure by hand.

NextDash is specialised for genomics and cancer-research pipelines, where the same biological logic is repeated across many samples and need parallelism but some steps must later combine them for cohort comparison. Typical workflows include FASTQ quality control and trimming, read mapping to a reference genome, BAM sorting/indexing, gene or feature counting, RNA-seq differential expression, germline or somatic variant calling, tumor/normal mutation identification, copy-number analysis, variant annotation, mutation filtering, and cohort-level reports... For example, a simple workflow can be `FASTQ` → mapping program → `BAM` → counting program → `COUNTS`; a more advanced cancer workflow can join a `TUMOR` sample with its matching `NORMAL` sample from the same patient and a shared custom `REF` typical of this tumor genome before running a somatic mutation caller. The generated workflow still runs the tools that you choose NextDash helps make the scientific flow visible and reproducible.

The reading direction is **left to right**. A block whose label starts with a **letter** is a data flow, for example `RAW`, `FASTQ`, `TUMOR`, or `FINAL`. A block whose label starts with a **number** is a program, for example `1`, `1.Star`, or `05`. This small rule is how NextDash knows if a block is a file/data stream or a command that consumes data and produces new data. Its the first thing to remember when working with Nextflow pipelines.

Colors are also part of the language of the diagram: blue is a per-sample data flow moving in parallel, purple is a program, teal is a shared resource, light green is a **non** parallel flow, yellow/orange is WAS, green is WASG, pink is WASJ, red means a validation problem, and gray is a wire that does not have other function than joigning. You dont need to memorise all of it at once; the color key is shown at the top of the application and again in the validation diagram.

It is especially useful when a workflow mixes per-sample processing with synchronization steps:

- **WAS**   wait for all participating streams, after they all arrive they are released one at a time (used as a trigger).
- **WASG**   wait for all samples and process them together as one cohort/group task (e.g. count or identify a global effect).
- **WASJ**   wait for related streams and join them by metadata (for example, pair Tumor and Normal by `patient_id`) (e.g. take a parallel flow and pair the correct samples from the same patient together).

> NextDash generates the Nextflow workflow and input manifest. 

## Screenshots

### Figure 1   Easy workflow: build the blocks

![Workflow spreadsheet](Screenshots/Easy_01_BuildingBlocks.jpg)

*Figure 1. This is the simplest possible NextDash workflow: `RAW` → `1` → `FINAL`. Read the row from left to right. `RAW` starts with a letter, so it is a blue root data flow (the input files). `1` starts with a number, so it is the purple program block; in the next tab it can be given a clearer name, such as “QualityControl” or “Star”, it could also have been called "1_Star" directly instead of "1". `FINAL` starts with a letter and is therefore the blue output data flow produced by program `1`. This is an easy per-sample process: every RAW sample can be processed independently and in parallel. The buttons above the spreadsheet add rows, columns, WAS/WASG/WASJ blocks, wires, and notes when the workflow grows later.*

### Figure 2   Easy workflow: give meaning to the blocks

![Program and data definitions](Screenshots/Easy_02_Programs_and_Data_configuration.jpg)

*Figure 2. After the blocks have been drawn, **Read Programs + Data from Workflow Spreadsheet** finds the purple program block and the blue data blocks automatically. On the left, program `1` is associated with a real script/executable, its arguments, CPU, memory, time, and optional checkpoint folder. On the right, `RAW` is defined as the root input and `FINAL` as the final/generated output. This separation is useful because the picture stays simple while the paths and command-line details stay in one place. For this example, the flow is still easy: files enter as `RAW`, program `1` runs once per sample, and the result is named `FINAL`.*

### Figure 3   Easy workflow: validate what NextDash understood

![Validation and interpreted diagram](Screenshots/Easy_03_PressValidate_All.jpg)

*Figure 3. Pressing **Validate all** checks that the visual blocks, program definitions, data definitions, and (when present) metadata rules agree. The report at left says this small example has one program, two data words, one root input, and no WAS/WASG/WASJ blocks. The large diagram at right is NextDash's interpretation of the spreadsheet: blue `RAW` enters purple program `1`/`Prog1`, which produces blue `FINAL`. This view should be checked before generating because it makes the direction of every flow obvious. If the intended route is not shown left to right here, fix the spreadsheet before continuing.*

### Figure 4   Easy workflow: generate the Nextflow project

![Generated project](Screenshots/Easy_04_Press_Generate_Project.jpg)

*Figure 4. This last tab converts the validated blocks into files that Nextflow can run. The selected output folder receives `main.nf`, `input_manifest.tsv`, `NextDash.tabtxt`, and `DEFINITIONS.txt`, as shown in the confirmation box. In this example the output is copied to `results`, Windows paths are converted for WSL, and generated files can be overwritten. The cache section is shown too: task cache data can be measured and removed only after the run has stopped. It is still the same small `RAW` → `1` → `FINAL` workflow; generation does not change the logic, it simply writes it as Nextflow code.*

### Figure 5   WAS: a slightly more complicated wait

![WAS building blocks](Screenshots/WAS_01_BuildingBlocks.jpg)

*Figure 5. This example has three incoming blue data flows: `A`, `B`, and `C`. They are processed by purple programs `1`, `2`, and `1`, producing `A_DONE`, `B_DONE`, and `C_DONE`. The vertical yellow/orange `WAS` block tells NextDash to wait until all participating flows have reached this point. After the wait, the primary flow continues through purple program `3` to blue `FINAL`. This is more complicated than Figure 1 because several sample streams must be ready together, but the basic rule has not changed: letter-first labels are data, number-first labels are programs, and the diagram is read from left to right.*

### Figure 6   WASG: make one cohort-level task

![WASG building blocks](Screenshots/WASG_01_BuildingBlocks.jpg)

*Figure 6. `RAW` is first a blue per-sample flow. The green `WASG` block waits for all RAW samples and groups them into one cohort task. Purple program `4` then runs once for the whole group, not once per sample, and writes the light-green `GROUPED` result. Light green is important here: it shows that the downstream flow is serial/cohort-level rather than the original parallel sample flow. This is useful for steps such as cohort QC, combined counts, or a global report.*

### Figure 7   WASJ: join related samples plus a shared resource

![WASJ building blocks](Screenshots/WASJ_01_BuildingBlocks.jpg)

*Figure 7. This is the more complicated example. `TUMOR` and `NORMAL` are blue per-sample data flows; `REF` is teal because it is one shared resource, such as the same reference genome used for all pairs. The vertical pink `WASJ` block waits for the needed inputs and joins Tumor with Normal using metadata rather than file order. Purple program `5` receives the joined group and produces `JOINED`; purple program `3` then continues from `JOINED` to `FINAL`. The pink block does not guess pairs by row position its configuration is shown in Figure 8. This avoids quietly matching the wrong samples when folders are sorted differently.*

### Figure 8   WASJ: configure and check the metadata join

![WASJ metadata and pairing](Screenshots/WASJ_03_Metada_and_Pairing.jpg)

*Figure 8. This tab gives the pink WASJ block its biological meaning. The selected block receives three streams: `TUMOR`, `NORMAL`, and `REF`. The sample table supplies a file column and uses `Patient_id` as the join key, so records belonging to the same patient are paired. `Disease` is selected as a difference key: `TUMOR` expects `Disease=Tumor`, while `NORMAL` expects `Disease=Control`; `REF` remains a shared resource. Save the configuration and use **Preview / validate pairing** before generating. The extra setup is worth doing for a complicated join because it makes the pairing explicit and repeatable, instead of relying on filenames being in the same order.*

### A quick visual reminder

The three special blocks solve different problems: **WAS** waits and then releases the primary sample flow, **WASG** waits and creates one grouped/cohort task, and **WASJ** waits and pairs related records using selected metadata fields. For all three, the ordinary data/program blocks still read left to right.

## When are WAS, WASG, and WASJ useful in genomics?

Think of these blocks as three different questions:

- **WAS:** “Should we wait until the whole study is ready before continuing with each patient/sample?”
- **WASG:** “Do we need one result for the whole study group?”
- **WASJ:** “Which files belong to the same patient or biological sample?”

Only use a special block when it reflects a real scientific need. The examples below use technical labels, but the important part is the biological question.

### WAS   first wait for the study, then continue sample by sample

Use **WAS** when you want to hold the next stage until the required work has finished for **all samples**, but afterwards you still want one result per sample. In plain language: “do not issue the individual results until the study has reached this checkpoint.”

For example, in a sequencing study, every patient sample may first go through two checks: the sequencing reads are mapped to the genome, and a quality check confirms that the sample is usable.

```text
Raw sequencing reads → mapping → aligned reads
Raw sequencing reads → quality check → QC result
All required results → WAS → one downstream report for each patient/sample
```

`FASTQ` is commonly used to mean raw sequencing reads and `BAM` commonly means reads already aligned to the reference genome; the labels in NextDash can use clearer local names if preferred. The yellow/orange WAS block makes the checkpoint visible. Once the checkpoint is passed, the main sample flow continues separately for each patient. This is helpful when no individual report should move forward until all required samples have completed the initial QC/preparation stage.

### WASG   make one answer for the whole study group

Use **WASG** when the next step needs **every sample together** and should run only once. In plain language: “collect the study results, then make one cohort-level answer.” The output is light green because it is no longer one result per patient/sample.

Examples that are easy to recognise:

- **One quality-control report for the study:** collect all sample QC results and make one MultiQC report for the laboratory or project.
- **RNA-seq comparison:** first count genes in each sample, then combine all counts into one table to compare tumour versus control, treatment versus untreated, or other groups.
- **Joint variant analysis:** collect variant information from all patients before making a shared cohort call set.
- **Cancer cohort summary:** combine individual mutation or copy-number results into one table or plot showing what is seen across the cohort.

For example:

```text
Each RNA-seq sample → gene counting → one count file per sample
All count files → WASG → group comparison → one differential-expression result
```

Without WASG, the group comparison could accidentally run once per sample, which does not answer the scientific question. The green block says clearly that the program after it needs the complete cohort.

### WASJ   match samples that belong together

Use **WASJ** when a program needs samples that belong to the **same patient** or the same biological unit. In plain language: “find the correct partner before running the comparison.”

The most common cancer-genomics example is matched tumour/normal mutation calling:

```text
Tumour DNA from patient 01  ─┐
Normal DNA from patient 01  ─┼→ WASJ → mutation comparison → patient 01 mutation list
Reference genome            ─┘
```

The same thing happens independently for patient 02, patient 03, and so on. The teal reference genome is shared by everyone; it is not matched to one patient. In the metadata table, `patient_id` tells NextDash which tumour and normal belong together. A second column, such as `sample_type`, says which file is `Tumor` and which is `Normal`. This avoids a serious error: accidentally comparing patient 01's tumour with patient 02's normal sample just because the files happened to be next to each other in a folder.

Other clear WASJ examples are:

- **Cancer at two time points:** match diagnosis and relapse samples from the same patient to look for newly acquired mutations.
- **Before/after treatment:** match samples from the same person before and after therapy.
- **DNA and RNA from the same tumour:** match the DNA result with RNA sequencing from the same patient when checking whether a mutation also has expression or fusion evidence.
- **Paired case/control experiments:** match samples from the same donor, organoid, or experimental unit before comparing them.

In Tab 3, choose the file/sample column, the joining field (for example `patient_id`), and the values that distinguish the inputs (for example `Tumor` and `Normal`). Then use **Preview / validate pairing**. It takes a little extra setup, but it makes the biological pairing visible and much safer.

## Requirements

- Python 3 with Tkinter (the GUI has no third-party Python package dependencies).
- Nextflow to run or manually stub-validate a generated pipeline.
- On Windows, a working WSL installation is recommended. NextDash can convert Windows input/output paths to `/mnt/<drive>/...` paths for the generated workflow.
- Every program configured in the app must be available in the environment where the generated pipeline runs. NextDash supports Linux executables, Python 3 scripts, R scripts, and Bash scripts.

## Start the application

From this repository:

```powershell
py -3 .\nextdash_V8.py
```

If your system uses `python` instead of the Python launcher:

```powershell
python .\nextdash_V8.py
```

On Linux/macOS, run `python3 nextdash_V8.py`. If Tkinter is not installed on Linux, install your distribution's `python3-tk` package first.

## Quick start

1. In **Tab 1   Workflow spreadsheet**, draw the data flow from left to right. Use a word beginning with a letter for a data stream and a token beginning with a number for a program ID.
2. Use `|` and `-` only to route a flow vertically or horizontally; use `#` to add a non-executing note.
3. Click **Read Programs + Data from Workflow Spreadsheet** in **Tab 2**. Define each program's path, arguments, CPU/memory/time settings, and each root data input.
4. For a WASJ workflow, configure the sample metadata table, join key, difference key(s), and expected values for each incoming stream in **Tab 3**.
5. Click **Validate all** in **Tab 4** and resolve every error. The interpreted diagram is the best way to confirm that the GUI understood the intended graph.
6. In **Tab 5**, choose an output folder and click **Generate project**.
7. Run the generated project with Nextflow:

   ```bash
   cd /path/to/generated-project
   nextflow run main.nf
   ```

   If task caching was enabled when the project was generated, rerun with `nextflow run main.nf -resume` to reuse successful tasks.

   To have Nextflow check scheduling/staging without launching the configured analysis commands, use:

   ```bash
   nextflow run main.nf -stub-run
   ```

The **Examples…** menu includes working starting diagrams for WAS, WASG, WASJ, and a mixed workflow.

## Building blocks and colors

| Item | Meaning |
| --- | --- |
| `FASTQ`, `BAM`, `RESULT` | Data word / data stream. Root data words are sources; downstream words are generated data. |
| `1`, `1.Star`, `05` | Program ID. The number-first form distinguishes programs from data words. |
| `WAS` | Wait for all participating streams, then continue the primary stream per sample. |
| `WASG` | Wait for all samples and create one group/cohort task. |
| `WASJ` | Wait, then join records using metadata not row or file order. |
| `|`, `-` | Vertical and horizontal wires for a clearer diagram. |
| `# note` | Comment only; not executed. |

| Color | Meaning |
| --- | --- |
| Blue | Per-sample stream that can run in parallel. |
| Light green | Cohort/serial flow, typically downstream of WASG. |
| Teal | Shared root resource, such as one reference genome reused by tasks. |
| Purple | Program. |
| Yellow/orange | WAS barrier. |
| Green | WASG barrier. |
| Pink | WASJ barrier. |
| Red | Validation error. |
| Gray | Diagram wire. |

## Configure programs

Each program ID needs a real executable or script and an argument template. Named placeholders are recommended because they make multi-input processes explicit:

```text
--tumor {TUMOR} --normal {NORMAL} -o {output}
```

Useful placeholders include:

| Placeholder | Meaning |
| --- | --- |
| `{input}`, `{input1}`, `{input2}` | Logical input streams. |
| `{DATA}` | A named data stream, such as `{TUMOR}` or `{READS}`. |
| `{DATA_1}`, `{DATA_2}` | Individual files in a grouped input. Members are ordered alphabetically by filename. |
| `{inputs}` | All staged files after WASG. |
| `{group_manifest}` | TSV manifest of a WASG group. |
| `{output}` | The generated output file path. |
| `{sample}` | Current sample ID. |
| `{cpus}` | CPUs allocated to the Nextflow task. |

Use doubled braces for literal braces in a command template, for example `{{"key": 1}}`.

## Configure data

For root inputs, provide a file, folder, or glob plus an optional extension filter. `**` searches nested folders recursively. A sample-ID regex can derive sample names from filenames.

For paired-end inputs, a typical configuration is:

- Sample-ID regex: `(.+)_R[12]\.fastq\.gz`
- Enable **Group same sample ID**
- Set **Files/sample** to `2`
- Reference the members as `{READS_1}` and `{READS_2}` in the program arguments

Grouped members are sorted alphabetically. They are not automatically interpreted as R1/R2, lane, or assay categories, so use a naming scheme and argument template that make the desired ordering unambiguous.

A root input can also be configured as **Shared single resource**, for example a reference FASTA. A shared resource is one existing file that is reused across relevant tasks; it is not a product of WAS, WASG, or WASJ.

For generated/final data, set an output template and, optionally, a published-output folder. Per-sample templates must include `{lineage}` or `{sample}`. Available fields are `{lineage}`, `{sample}`, `{program}`, and `{data}`.

## WASJ metadata pairing

WASJ pairing is metadata-driven. It does not assume that two directories are in the same order.

1. Select the WASJ block in Tab 3.
2. Load a CSV/TSV metadata table.
3. Choose either a file column (preferred) or sample-ID column to map files to metadata records.
4. Select a **Join key** such as `patient_id`.
5. Select one or more **Difference keys**, such as `condition`, `assay`, or `timepoint`.
6. Define expected values for each input stream, for example `condition=Tumor` for `TUMOR` and `condition=Normal` for `NORMAL`.
7. Use **Preview / validate pairing** before generating.

## Generated project

Generating a project writes these files into the selected output folder:

| File | Purpose |
| --- | --- |
| `main.nf` | Generated Nextflow DSL2 workflow. |
| `input_manifest.tsv` | Input files, sample IDs, lineage, and metadata used at runtime. |
| `NextDash.tabtxt` | Tab-separated copy of the visual workflow grid. |
| `DEFINITIONS.txt` | Readable summary of programs, data, and WASJ configuration. |

You can also save the editable GUI state as `*.nextdash.json`, which preserves the grid, definitions, WASJ configuration, and generation settings. Save this alongside your generated project for reproducibility.

By default, published task outputs are copied, which keeps results usable after the Nextflow work cache is removed. Nextflow task caching is optional; enable it only if you plan to rerun with `-resume`. The app can report and safely remove its generated project's `work/` and `.nextflow/cache/` directories after all runs have stopped.

## Validation and troubleshooting

- Run **Validate all** before every generation. It checks graph structure, missing definitions, paths, metadata pairing, output publication conflicts, and runtime-safe identifiers.
- Use **Read CLI help / accepted options…** on a selected program to try its `--help`/`-h` output with a short timeout.
- Run `nextflow run main.nf -stub-run` to have Nextflow parse and stage the generated workflow without running the real analysis commands.
- Leave **Convert Windows paths to `/mnt/<drive>/...`** enabled when generating a pipeline that runs under WSL.
- If `nextflow` is not found during stub validation, install/configure Nextflow inside the WSL distribution used to run the pipeline.
- If generation says files already exist, choose a new output folder or enable **Overwrite generated files** deliberately.

## Current scope

NextDash is a graphical workflow generator, not an environment manager. It does not install Nextflow, containers, Conda environments, or analysis tools, and it does not execute the final analysis pipeline from the GUI. Review the generated `main.nf` and use your normal Nextflow profile/container/environment setup before running production data.

## Repository layout

```text
nextdash_V8.py   # Standalone Tkinter application and Nextflow renderer
README.md        # Project documentation
Screenshots/     # UI and workflow examples used above
```

## Contributing

Before opening a change, confirm that the application still compiles:

```powershell
py -3 -m py_compile .\nextdash_V8.py
```

When changing workflow rendering, also validate a representative generated pipeline with `nextflow run main.nf -stub-run` and add/update a screenshot or reproducible example when appropriate.
