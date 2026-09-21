import os
import string
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import numpy as np
import pandas as pd

@dataclass
class DatasetConfig:
    output_dir: Path
    seed: int = 12345
    number_of_classes: int = 3
    training_samples_per_class: int = 50
    known_test_samples_per_class: int = 12
    ambiguous_samples_per_pair: int = 4
    markers_per_class: int = 12
    noise_features: int = 50
    high_mean: float = 8.0
    low_mean: float = 2.0
    marker_sd: float = 0.9
    noise_mean: float = 5.0
    noise_sd: float = 1.5
    missing_fraction: float = 0.01


def class_names(n):
    if n > 26:
        raise ValueError("Number of classes must be 26 or fewer.")
    return [f"Class_{string.ascii_uppercase[i]}" for i in range(n)]


def marker_name(class_name, index):
    letter = class_name.split("_")[-1]
    return f"{letter}_marker_{index:03d}"


def build_feature_sets(cfg):
    classes = class_names(cfg.number_of_classes)
    markers = {
        cls: [marker_name(cls, i) for i in range(1, cfg.markers_per_class + 1)]
        for cls in classes
    }
    noise = [f"Noise_{i:03d}" for i in range(1, cfg.noise_features + 1)]
    return classes, markers, noise


def make_training_rows(cfg, rng, classes, markers, noise):
    rows = []
    for cls in classes:
        short = cls.split("_")[-1]
        for i in range(1, cfg.training_samples_per_class + 1):
            row = {"SampleID": f"Train_{short}_{i:03d}", "Class": cls}
            for owner in classes:
                mean = cfg.high_mean if owner == cls else cfg.low_mean
                for feature in markers[owner]:
                    row[feature] = rng.normal(mean, cfg.marker_sd)
            for feature in noise:
                row[feature] = rng.normal(cfg.noise_mean, cfg.noise_sd)
            rows.append(row)
    return pd.DataFrame(rows)


def make_test_row(cfg, rng, sample_id, weights, known_class, classes, markers, noise):
    row = {"SampleID": sample_id, "KnownClass": known_class}
    for owner in classes:
        weight = float(weights.get(owner, 0.0))
        mean = cfg.low_mean + (cfg.high_mean - cfg.low_mean) * weight
        for feature in markers[owner]:
            row[feature] = rng.normal(mean, cfg.marker_sd * 0.9)
    for feature in noise:
        row[feature] = rng.normal(cfg.noise_mean, cfg.noise_sd)
    return row


def make_test_rows(cfg, rng, classes, markers, noise):
    rows = []
    for cls in classes:
        short = cls.split("_")[-1]
        weights = {name: 1.0 if name == cls else 0.0 for name in classes}
        for i in range(1, cfg.known_test_samples_per_class + 1):
            rows.append(
                make_test_row(
                    cfg,
                    rng,
                    f"Test_{short}_{i:03d}",
                    weights,
                    cls,
                    classes,
                    markers,
                    noise,
                )
            )
    for pair_index in range(len(classes) - 1):
        left = classes[pair_index]
        right = classes[pair_index + 1]
        left_short = left.split("_")[-1]
        right_short = right.split("_")[-1]
        for i in range(1, cfg.ambiguous_samples_per_pair + 1):
            delta = 0.04 if i % 2 else -0.04
            left_weight = 0.50 + delta
            right_weight = 1.0 - left_weight
            weights = {name: 0.0 for name in classes}
            weights[left] = left_weight
            weights[right] = right_weight
            rows.append(
                make_test_row(
                    cfg,
                    rng,
                    f"Ambiguous_{left_short}_{right_short}_{i:03d}",
                    weights,
                    "",
                    classes,
                    markers,
                    noise,
                )
            )
    return pd.DataFrame(rows)


def add_missing_values(cfg, rng, trainer, feature_columns):
    if cfg.missing_fraction <= 0:
        return trainer
    result = trainer.copy()
    total_cells = len(result) * len(feature_columns)
    n_missing = int(round(total_cells * cfg.missing_fraction))
    if n_missing <= 0:
        return result
    flat_indices = rng.choice(total_cells, size=min(n_missing, total_cells), replace=False)
    n_features = len(feature_columns)
    for flat_index in flat_indices:
        row_index = int(flat_index // n_features)
        feature_index = int(flat_index % n_features)
        result.at[row_index, feature_columns[feature_index]] = np.nan
    return result


def signal_validation(trainer, classes, markers, noise):
    records = []
    for cls in classes:
        own = trainer.loc[trainer["Class"] == cls, markers[cls]].to_numpy(dtype=float)
        other = trainer.loc[trainer["Class"] != cls, markers[cls]].to_numpy(dtype=float)
        own_mean = float(np.nanmean(own))
        other_mean = float(np.nanmean(other))
        records.append(
            {
                "Class": cls,
                "OwnMarkerMeanInClass": own_mean,
                "OwnMarkerMeanOutsideClass": other_mean,
                "Difference": own_mean - other_mean,
            }
        )
    noise_values = trainer[noise].to_numpy(dtype=float) if noise else np.empty((len(trainer), 0))
    noise_mean = float(np.nanmean(noise_values)) if noise_values.size else np.nan
    return pd.DataFrame(records), noise_mean


def generate_dataset(cfg):
    if cfg.number_of_classes < 2:
        raise ValueError("At least 2 classes are required.")
    if cfg.training_samples_per_class < 5:
        raise ValueError("Use at least 5 training samples per class.")
    if cfg.known_test_samples_per_class < 1:
        raise ValueError("Use at least 1 known test sample per class.")
    if cfg.markers_per_class < 2:
        raise ValueError("Use at least 2 marker features per class.")
    if cfg.noise_features < 0:
        raise ValueError("Noise feature count cannot be negative.")
    if not 0 <= cfg.missing_fraction < 0.5:
        raise ValueError("Missing fraction must be between 0 and 0.5.")
    if cfg.high_mean <= cfg.low_mean:
        raise ValueError("High marker mean must be greater than low marker mean.")
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(cfg.seed)
    classes, markers, noise = build_feature_sets(cfg)
    trainer = make_training_rows(cfg, rng, classes, markers, noise)
    classify = make_test_rows(cfg, rng, classes, markers, noise)
    feature_columns = [feature for cls in classes for feature in markers[cls]] + noise
    trainer = add_missing_values(cfg, rng, trainer, feature_columns)
    trainer[feature_columns] = trainer[feature_columns].round(4)
    classify[feature_columns] = classify[feature_columns].round(4)
    trainer_path = cfg.output_dir / "Input_Trainer.tabtxt"
    classify_path = cfg.output_dir / "Input_ToClassify.tabtxt"
    trainer.to_csv(trainer_path, sep="\t", index=False, na_rep="NA")
    classify.to_csv(classify_path, sep="\t", index=False, na_rep="NA")
    signal_rows = []
    for cls in classes:
        for feature in markers[cls]:
            signal_rows.append(
                {
                    "Feature": feature,
                    "ExpectedClass": cls,
                    "Signal": "High in expected class and low in all other classes",
                }
            )
    for feature in noise:
        signal_rows.append(
            {
                "Feature": feature,
                "ExpectedClass": "None",
                "Signal": "Noise feature with no intended class association",
            }
        )
    signal_map = pd.DataFrame(signal_rows)
    signal_map_path = cfg.output_dir / "Known_Signal_Map.tabtxt"
    signal_map.to_csv(signal_map_path, sep="\t", index=False)
    expected_rows = []
    for _, row in classify.iterrows():
        if row["KnownClass"]:
            expected_rows.append(
                {
                    "SampleID": row["SampleID"],
                    "ExpectedClass": row["KnownClass"],
                    "ExpectedBehavior": "Most or all successful algorithms should recover this class",
                }
            )
        else:
            expected_rows.append(
                {
                    "SampleID": row["SampleID"],
                    "ExpectedClass": "Ambiguous",
                    "ExpectedBehavior": "Lower confidence and/or disagreement is expected between the two adjacent classes encoded in the SampleID",
                }
            )
    expected_table = pd.DataFrame(expected_rows)
    expected_table_path = cfg.output_dir / "Expected_Classifications.tabtxt"
    expected_table.to_csv(expected_table_path, sep="\t", index=False)
    validation, noise_mean = signal_validation(trainer, classes, markers, noise)
    validation_path = cfg.output_dir / "Embedded_Signal_Validation.tabtxt"
    validation.to_csv(validation_path, sep="\t", index=False)
    summary = pd.DataFrame(
        {
            "Item": [
                "Random seed",
                "Classes",
                "Training samples",
                "Known test samples",
                "Ambiguous test samples",
                "Marker features per class",
                "Total marker features",
                "Noise features",
                "Total predictor features",
                "Requested missing fraction",
                "High marker mean",
                "Low marker mean",
                "Marker SD",
                "Noise mean",
                "Noise SD",
            ],
            "Value": [
                cfg.seed,
                cfg.number_of_classes,
                len(trainer),
                int((classify["KnownClass"] != "").sum()),
                int((classify["KnownClass"] == "").sum()),
                cfg.markers_per_class,
                cfg.number_of_classes * cfg.markers_per_class,
                cfg.noise_features,
                len(feature_columns),
                cfg.missing_fraction,
                cfg.high_mean,
                cfg.low_mean,
                cfg.marker_sd,
                cfg.noise_mean,
                cfg.noise_sd,
            ],
        }
    )
    summary_path = cfg.output_dir / "Dataset_Summary.tabtxt"
    summary.to_csv(summary_path, sep="\t", index=False)
    marker_differences = validation["Difference"].tolist()
    expected_text = [
        "Synthetic supervised-classification validation dataset",
        "",
        f"Training samples: {len(trainer)}",
        f"Samples to classify: {len(classify)}",
        f"Classes: {', '.join(classes)}",
        f"Predictor features: {len(feature_columns)}",
        "",
        "Known signal:",
    ]
    for cls in classes:
        expected_text.append(
            f"{cls}: {', '.join(markers[cls][:min(5, len(markers[cls]))])}"
            + (" ..." if len(markers[cls]) > 5 else "")
            + f" are intentionally high in {cls} and low in the other classes."
        )
    expected_text.extend(
        [
            "",
            "Expected results:",
            "Clear KnownClass samples should usually be classified correctly by most or all successful algorithms.",
            "Cross-validated performance should be high because the class-specific signal is deliberately strong.",
            "Class-specific marker features should rank above most Noise_* features in variable-importance results.",
            "Ambiguous_* samples are deliberate mixtures of adjacent classes and should tend to have reduced probability margin, reduced algorithm agreement, or model disagreement.",
            "The KnownClass field is blank for ambiguous samples so they are excluded from external-validation accuracy.",
            "",
            "Embedded-signal check from the generated training matrix:",
        ]
    )
    for row in validation.itertuples(index=False):
        expected_text.append(
            f"{row.Class}: own-marker mean={row.OwnMarkerMeanInClass:.3f}, outside-class mean={row.OwnMarkerMeanOutsideClass:.3f}, difference={row.Difference:.3f}"
        )
    expected_text.append(f"Overall noise-feature mean={noise_mean:.3f}" if np.isfinite(noise_mean) else "No noise features were generated.")
    expected_text.append("")
    expected_text.append("This dataset is synthetic and is intended for software validation and demonstration, not clinical validation.")
    expected_path = cfg.output_dir / "Expected_Findings.txt"
    expected_path.write_text("\n".join(expected_text), encoding="utf-8")
    return {
        "trainer": trainer_path,
        "classify": classify_path,
        "signal_map": signal_map_path,
        "expected_table": expected_table_path,
        "validation": validation_path,
        "summary": summary_path,
        "expected": expected_path,
        "training_samples": len(trainer),
        "test_samples": len(classify),
        "features": len(feature_columns),
        "minimum_marker_difference": min(marker_differences),
    }


class GeneratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Supervised Classification Synthetic Test Data Generator")
        self.root.geometry("980x820")
        self.root.minsize(900, 720)
        self.output_var = tk.StringVar(value=str(Path.cwd() / "Synthetic_Test_Data"))
        self.preset_var = tk.StringVar(value="Standard")
        self.seed_var = tk.StringVar(value="12345")
        self.classes_var = tk.StringVar(value="3")
        self.train_var = tk.StringVar(value="50")
        self.test_var = tk.StringVar(value="12")
        self.ambiguous_var = tk.StringVar(value="4")
        self.markers_var = tk.StringVar(value="12")
        self.noise_var = tk.StringVar(value="50")
        self.high_var = tk.StringVar(value="8.0")
        self.low_var = tk.StringVar(value="2.0")
        self.marker_sd_var = tk.StringVar(value="0.9")
        self.noise_mean_var = tk.StringVar(value="5.0")
        self.noise_sd_var = tk.StringVar(value="1.5")
        self.missing_var = tk.StringVar(value="0.01")
        self.status_var = tk.StringVar(value="Ready")
        self.build_ui()

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        title = tk.Label(
            outer,
            text="Synthetic Validation Data for 8-Algorithm Supervised Classification",
            font=("Segoe UI", 15, "bold"),
            bg="#d9ecff",
            fg="#17324d",
            padx=10,
            pady=10,
        )
        title.pack(fill="x", pady=(0, 10))
        output_frame = ttk.LabelFrame(outer, text="Output", padding=10)
        output_frame.pack(fill="x", pady=5)
        ttk.Entry(output_frame, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(output_frame, text="Browse", command=self.choose_output).pack(side="left")
        preset_frame = ttk.LabelFrame(outer, text="Dataset size", padding=10)
        preset_frame.pack(fill="x", pady=5)
        ttk.Label(preset_frame, text="Preset").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        preset = ttk.Combobox(preset_frame, textvariable=self.preset_var, values=["Standard", "Large", "Stress"], state="readonly", width=14)
        preset.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        preset.bind("<<ComboboxSelected>>", self.apply_preset)
        fields = [
            ("Classes", self.classes_var),
            ("Training samples / class", self.train_var),
            ("Known test samples / class", self.test_var),
            ("Ambiguous samples / adjacent pair", self.ambiguous_var),
            ("Markers / class", self.markers_var),
            ("Noise features", self.noise_var),
            ("Random seed", self.seed_var),
        ]
        for index, (label, variable) in enumerate(fields, start=1):
            row = 1 + (index - 1) // 4
            col = ((index - 1) % 4) * 2
            ttk.Label(preset_frame, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=4)
            ttk.Entry(preset_frame, textvariable=variable, width=12).grid(row=row, column=col + 1, sticky="w", padx=4, pady=4)
        signal_frame = ttk.LabelFrame(outer, text="Embedded signal", padding=10)
        signal_frame.pack(fill="x", pady=5)
        signal_fields = [
            ("High class-marker mean", self.high_var),
            ("Low off-class marker mean", self.low_var),
            ("Marker SD", self.marker_sd_var),
            ("Noise mean", self.noise_mean_var),
            ("Noise SD", self.noise_sd_var),
            ("Training missing fraction", self.missing_var),
        ]
        for index, (label, variable) in enumerate(signal_fields):
            row = index // 3
            col = (index % 3) * 2
            ttk.Label(signal_frame, text=label).grid(row=row, column=col, sticky="w", padx=4, pady=4)
            ttk.Entry(signal_frame, textvariable=variable, width=12).grid(row=row, column=col + 1, sticky="w", padx=4, pady=4)
        explanation = tk.Text(outer, height=10, wrap="word", bg="#f7fbff", fg="#1f2d3d", relief="solid", borderwidth=1)
        explanation.pack(fill="both", expand=True, pady=8)
        explanation.insert(
            "1.0",
            "The generated matrix contains a known class-specific signal rather than arbitrary random labels. Each class receives its own marker block with a high mean in that class and a low mean in every other class. Noise_* variables have no intended class association. Clear test samples include KnownClass for external validation. Ambiguous samples are mixtures of adjacent classes and intentionally have blank KnownClass. A correct classifier should recover the clear classes, rank the marker blocks above most noise features, and show reduced confidence or agreement for ambiguous mixtures.\n\nThe generator also writes Known_Signal_Map.tabtxt, Expected_Classifications.tabtxt, Embedded_Signal_Validation.tabtxt, Dataset_Summary.tabtxt, and Expected_Findings.txt so the intended result is explicit and reproducible.",
        )
        explanation.configure(state="disabled")
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=8)
        self.generate_button = tk.Button(buttons, text="Generate Test Data", command=self.generate, bg="#bfe3c0", fg="#102b12", font=("Segoe UI", 11, "bold"), padx=14, pady=6)
        self.generate_button.pack(side="left", padx=(0, 8))
        tk.Button(buttons, text="Open Output Folder", command=self.open_output, bg="#d9ecff", padx=12, pady=6).pack(side="left", padx=4)
        tk.Button(buttons, text="Close", command=self.root.destroy, bg="#eeeeee", padx=12, pady=6).pack(side="right")
        status = tk.Label(outer, textvariable=self.status_var, anchor="w", bg="#fff4cc", fg="#4a3a00", padx=8, pady=6)
        status.pack(fill="x", pady=(4, 0))

    def choose_output(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(Path.cwd()))
        if selected:
            self.output_var.set(selected)

    def apply_preset(self, event=None):
        presets = {
            "Standard": (50, 12, 4, 12, 50),
            "Large": (120, 30, 8, 20, 120),
            "Stress": (300, 60, 12, 30, 300),
        }
        train, test, ambiguous, markers, noise = presets[self.preset_var.get()]
        self.train_var.set(str(train))
        self.test_var.set(str(test))
        self.ambiguous_var.set(str(ambiguous))
        self.markers_var.set(str(markers))
        self.noise_var.set(str(noise))

    def config_from_gui(self):
        return DatasetConfig(
            output_dir=Path(self.output_var.get()).expanduser(),
            seed=int(self.seed_var.get()),
            number_of_classes=int(self.classes_var.get()),
            training_samples_per_class=int(self.train_var.get()),
            known_test_samples_per_class=int(self.test_var.get()),
            ambiguous_samples_per_pair=int(self.ambiguous_var.get()),
            markers_per_class=int(self.markers_var.get()),
            noise_features=int(self.noise_var.get()),
            high_mean=float(self.high_var.get()),
            low_mean=float(self.low_var.get()),
            marker_sd=float(self.marker_sd_var.get()),
            noise_mean=float(self.noise_mean_var.get()),
            noise_sd=float(self.noise_sd_var.get()),
            missing_fraction=float(self.missing_var.get()),
        )

    def generate(self):
        try:
            self.generate_button.configure(state="disabled")
            self.status_var.set("Generating dataset...")
            self.root.update_idletasks()
            result = generate_dataset(self.config_from_gui())
            self.status_var.set(
                f"Created {result['training_samples']} training samples, {result['test_samples']} test samples, and {result['features']} predictor features. Minimum embedded marker separation: {result['minimum_marker_difference']:.3f}."
            )
            messagebox.showinfo(
                "Generation complete",
                "Synthetic validation data were created successfully.\n\n"
                f"Training samples: {result['training_samples']}\n"
                f"Test samples: {result['test_samples']}\n"
                f"Predictor features: {result['features']}\n"
                f"Minimum class-marker mean separation: {result['minimum_marker_difference']:.3f}\n\n"
                f"Output: {self.output_var.get()}",
            )
        except Exception as exc:
            self.status_var.set(f"Error: {exc}")
            messagebox.showerror("Generation failed", str(exc))
        finally:
            self.generate_button.configure(state="normal")

    def open_output(self):
        path = Path(self.output_var.get()).expanduser()
        if not path.exists():
            messagebox.showwarning("Folder not found", "Generate the data first or select an existing output folder.")
            return
        if os.name == "nt":
            os.startfile(path)
        elif os.uname().sysname == "Darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')


def main():
    root = tk.Tk()
    GeneratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
