# Elastic-net logistic/multinomial regression results

This model estimates linear class scores with a combination of ridge and lasso regularization. `alpha` controls the mixture of the two penalties and `lambda` controls the amount of shrinkage.

## Prediction results

- `Classifications.tabtxt` contains the predicted class, maximum probability, second-best class, second-best probability, and probability margin for every sample.
- `Class_Probabilities.tabtxt` contains one probability column for each class.
- `Classification_Confidence_Barplot.png` displays the maximum predicted probability by sample.
- `Classification_Probability_Heatmap.png` displays all class probabilities by sample.
- `Predicted_Class_Counts.png` shows the number of samples assigned to each class.

## Cross-validation results

- `CrossValidated_Training_Predictions.tabtxt` contains the combined out-of-fold prediction for each training sample.
- `CrossValidated_Overall_Metrics.tabtxt` contains accuracy, Cohen's kappa, macro precision, macro recall, macro F1, and mean one-vs-all balanced accuracy.
- `CrossValidated_PerClass_Metrics.tabtxt` contains TP, TN, FP, FN, sensitivity, specificity, precision, F1, and balanced accuracy for each class.
- `CrossValidated_Confusion_Matrix.tabtxt` and its heatmap compare known training classes with out-of-fold predictions.
- `CrossValidated_OOF_Probability_Heatmap.png` displays mean out-of-fold probabilities.

## Model and tuning results

- `Best_Tuning_Parameters.tabtxt` contains the selected `alpha` and `lambda`.
- `Tuning_Results.tabtxt` contains the performance calculated for the candidate parameter values.
- `Resampling_Results.tabtxt` contains metrics from the repeated cross-validation resamples.
- `Variable_Importance.tabtxt` and `Top_Variable_Importance.png` contain the model's variable-importance values.
- `Model_Summary.txt` contains a text representation of the fitted model.
- `Trained_Model.rds` contains the saved fitted model.

## External-validation results

When the classification input contains non-empty `KnownClass` values, the external-validation tables compare those classes with the model predictions. They include overall metrics, per-class metrics, a confusion matrix, and a confusion-matrix heatmap.

## Variable-importance figure

![Elastic-net top variable importance](Top_Variable_Importance.png)

The figure displays the 30 predictors with the largest elastic-net importance values. The plotted variables are class-marker features from all three marker blocks. The nearly equal bar lengths reflect the similarly strong signals embedded across those marker variables.

## Result figures

### `Classification_Confidence_Barplot.png`

![Classification confidence](Classification_Confidence_Barplot.png)

Each bar represents one classification sample. Bar height is the largest class probability assigned by the model, and bar color identifies the predicted class. The clear synthetic samples have tall bars, while the ambiguous samples contain lower maximum probabilities.

### `Classification_Probability_Heatmap.png`

![Classification probabilities](Classification_Probability_Heatmap.png)

Rows represent classification samples and columns represent classes. Each printed number is the probability assigned to that class, and darker cells represent larger probabilities. Clear samples form high-probability class blocks; ambiguous samples divide probability between the two classes used in their synthetic mixture.

### `CrossValidated_Confusion_Matrix_Heatmap.png`

![Cross-validated confusion matrix](CrossValidated_Confusion_Matrix_Heatmap.png)

Rows are known training classes and columns are out-of-fold predicted classes. Cell values are sample counts. Counts on the main diagonal are correct cross-validated predictions, while off-diagonal cells represent class assignments to a different class.

### `CrossValidated_OOF_Probability_Heatmap.png`

![Cross-validated out-of-fold probabilities](CrossValidated_OOF_Probability_Heatmap.png)

Rows are training samples and columns are classes. The cells contain mean out-of-fold probabilities combined across the repeated cross-validation predictions. The dark block associated with each sample's known class shows the probability pattern produced without predicting that sample from a model fitted on the same fold.

### `ExternalValidation_Confusion_Matrix_Heatmap.png`

![External-validation confusion matrix](ExternalValidation_Confusion_Matrix_Heatmap.png)

Rows are the non-empty `KnownClass` values from the classification input and columns are model predictions. Cell values are counts. The displayed synthetic result places the clear labeled test samples on the diagonal.

### `Predicted_Class_Counts.png`

![Predicted class counts](Predicted_Class_Counts.png)

The bars count how many classification samples were assigned to each class by this algorithm. These totals include both the clear and ambiguous synthetic samples.

### `Tuning_Performance.png`

![Tuning performance](Tuning_Performance.png)

This plot displays the cross-validation selection metric across the model's candidate tuning values. The parameter values shown in `Best_Tuning_Parameters.tabtxt` correspond to the selected tuning result.

