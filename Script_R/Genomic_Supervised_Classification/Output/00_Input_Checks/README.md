# Input-check results

This folder describes the data after the classification script reads and validates the two input matrices.

- `Input_Summary.tabtxt` contains training-sample count, classification-sample count, original and retained predictor counts, removed predictor count, class count, cross-validation settings, and ignored extra columns.
- `Training_Class_Counts.tabtxt` contains the number of training samples assigned to each class.
- `Feature_Filtering_Report.tabtxt` contains the all-missing indicator, zero-variance indicator, missing fraction, removal decision, and removal reason for every training predictor.
- `Class_Name_Mapping.tabtxt` maps original class labels to the R-safe internal labels used by the models.
- `Feature_Name_Mapping.tabtxt` maps original predictor names to R-safe internal names.
- `CrossValidation_Holdout_Assignments.tabtxt` lists the training samples placed in every repeated cross-validation holdout set.

