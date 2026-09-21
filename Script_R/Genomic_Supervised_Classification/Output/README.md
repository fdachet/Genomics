# Output contents

This directory contains the recorded inputs, individual model results, and combined classification summary.

| Folder | Description |
| --- | --- |
| `00_Input_Checks` | Input validation, name mappings, predictor filtering, class counts, and fold assignments. |
| `01_ElasticNet_Logistic` | Elastic-net model, tuning, predictions, probabilities, metrics, and plots. |
| `02_RandomForest` | Random-forest model, tuning, predictions, probabilities, metrics, and plots. |
| `03_SVM` | Radial SVM model, tuning, predictions, probabilities, metrics, and plots. |
| `04_GradientBoosting` | Native XGBoost model, tuning, predictions, probabilities, metrics, and plots. |
| `05_PLSDA` | PLS-DA model, tuning, predictions, probabilities, metrics, and plots. |
| `06_LDA` | PCA-preprocessed LDA model, predictions, probabilities, metrics, and plots. |
| `07_kNN` | kNN model, tuning, predictions, probabilities, metrics, and plots. |
| `08_NearestShrunkenCentroid` | PAM model, tuning, predictions, probabilities, metrics, and plots. |
| `09_Summary` | Combined algorithm performance, predictions, consensus results, validation metrics, and PCA plots. |

`Run_Log.txt` contains timestamped pipeline messages. `Run_Configuration.tabtxt` contains the input paths and model settings. `SessionInfo.txt` contains the R and package environment.

