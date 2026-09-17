package local.weighttable;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.net.Uri;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TableLayout;
import android.widget.TableRow;
import android.widget.TextView;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class MainActivity extends Activity {
    private static final int REQUEST_SAVE_TSV = 1001;
    private static final int REQUEST_LOAD_TSV = 1002;
    private static final String FILE_MAGIC_LINE = "#DashTableGymFile\t2";
    private static final String FILE_SECTION_DATA_LINE = "#DashTableGymData";
    private static final String FILE_SETTING_PREFIX = "#DashTableGymSetting\t";
    private static final int STARTING_ROW_COUNT = 10;
    private static final int MIN_DATA_COLUMN_COUNT = 3;

    private static final int DEFAULT_COLUMN_1_WIDTH_DP = 190;
    private static final int DEFAULT_COLUMN_2_WIDTH_DP = 170;
    private static final int DEFAULT_COLUMN_3_WIDTH_DP = 150;
    private static final int DEFAULT_ADDED_COLUMN_WIDTH_DP = 145;
    private static final int DEFAULT_CHECKMARK_COLUMN_WIDTH_DP = 130;
    private static final int DEFAULT_ROW_HEIGHT_DP = 54;
    private static final int DEFAULT_ROW_SPACING_DP = 5;
    private static final int DEFAULT_CHECKMARK_TEXT_SIZE_SP = 36;
    private static final int DEFAULT_CHECK_HOLD_MS = 1000;
    private static final int DEFAULT_REMOVE_HOLD_MS = 2000;
    private static final int DEFAULT_VIBRATION_MS = 400;
    private static final int FIXED_VIBRATION_PULSE_COUNT = 2;
    private static final int FIXED_VIBRATION_GAP_MS = 0;
    private static final int FIXED_VIBRATION_START_DELAY_MS = 0;

    private static final int MIN_COLUMN_WIDTH_DP = 45;
    private static final int MAX_COLUMN_WIDTH_DP = 600;
    private static final int MIN_ROW_HEIGHT_DP = 30;
    private static final int MAX_ROW_HEIGHT_DP = 250;
    private static final int MIN_ROW_SPACING_DP = 0;
    private static final int MAX_ROW_SPACING_DP = 80;
    private static final int MIN_CHECKMARK_TEXT_SIZE_SP = 12;
    private static final int MAX_CHECKMARK_TEXT_SIZE_SP = 120;
    private static final int MIN_HOLD_MS = 100;
    private static final int MAX_HOLD_MS = 60000;
    private static final int MIN_VIBRATION_MS = 1;
    private static final int MAX_VIBRATION_MS = 10000;

    private static final int COLOR_SCREEN_BG = Color.rgb(245, 247, 250);
    private static final int COLOR_HEADER_BG = Color.rgb(226, 232, 240);
    private static final int COLOR_EDITABLE_BG = Color.WHITE;
    private static final int COLOR_PROTECTED_BG = Color.rgb(241, 245, 249);
    private static final int COLOR_CHECK_BG = Color.rgb(240, 253, 244);
    private static final int COLOR_BORDER = Color.rgb(148, 163, 184);
    private static final int COLOR_GREEN = Color.rgb(22, 163, 74);
    private static final int COLOR_TEXT = Color.rgb(15, 23, 42);

    private static final int DEFAULT_HEADER_EDITABLE_BG = COLOR_HEADER_BG;
    private static final int DEFAULT_HEADER_READONLY_BG = COLOR_HEADER_BG;
    private static final int DEFAULT_DATA_EDITABLE_BG = COLOR_EDITABLE_BG;
    private static final int DEFAULT_DATA_READONLY_BG = COLOR_PROTECTED_BG;

    private final List<String> dataHeaders = new ArrayList<>();
    private String checkmarkHeader = "15 reps";
    private final List<Integer> dataColumnWidthsDp = new ArrayList<>();
    private int checkmarkColumnWidthDp = DEFAULT_CHECKMARK_COLUMN_WIDTH_DP;

    private final List<RowData> rows = new ArrayList<>();
    private final List<EditText> headerCells = new ArrayList<>();
    private final List<EditText> editableCells = new ArrayList<>();
    private final List<TextView> checkCells = new ArrayList<>();
    private final List<EditText> dataColumnWidthInputs = new ArrayList<>();

    private SharedPreferences preferences;
    private TableLayout table;
    private CheckBox settingsCheckBox;
    private CheckBox readOnlyCheckBox;
    private ScrollView settingsScrollView;
    private LinearLayout settingsPanel;
    private LinearLayout actionControls;
    private LinearLayout sizeControls;
    private LinearLayout settingsModeControls;
    private EditText checkmarkColumnWidthInput;
    private EditText rowHeightInput;
    private EditText rowSpacingInput;
    private EditText checkmarkTextSizeInput;
    private EditText checkHoldMsInput;
    private EditText removeHoldMsInput;
    private EditText vibrationMsInput;
    private CheckBox vibrationCheckBox;
    private CheckBox beepCheckBox;
    private CheckBox multiLineCellsCheckBox;
    private Button editableDataColorButton;
    private Button readOnlyDataColorButton;
    private Button editableHeaderColorButton;
    private Button readOnlyHeaderColorButton;

    private final Handler sizeChangeHandler = new Handler(Looper.getMainLooper());
    private Runnable pendingSizeChange;
    private boolean settingsMode = false;
    private boolean readOnlyMode = false;
    private int rowHeightDp = DEFAULT_ROW_HEIGHT_DP;
    private boolean doubleHeaderHeight = false;
    private int rowSpacingDp = DEFAULT_ROW_SPACING_DP;
    private int checkmarkTextSizeSp = DEFAULT_CHECKMARK_TEXT_SIZE_SP;
    private int checkHoldMs = DEFAULT_CHECK_HOLD_MS;
    private int removeHoldMs = DEFAULT_REMOVE_HOLD_MS;
    private int vibrationMs = DEFAULT_VIBRATION_MS;
    private boolean vibrationEnabled = true;
    private boolean beepEnabled = false;
    private boolean multiLineCellsEnabled = false;
    private int editableDataBgColor = DEFAULT_DATA_EDITABLE_BG;
    private int readOnlyDataBgColor = DEFAULT_DATA_READONLY_BG;
    private int editableHeaderBgColor = DEFAULT_HEADER_EDITABLE_BG;
    private int readOnlyHeaderBgColor = DEFAULT_HEADER_READONLY_BG;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        preferences = getSharedPreferences("weight_table_state", MODE_PRIVATE);
        loadInternalState();
        buildScreen();
        rebuildTable();
    }

    @Override
    protected void onPause() {
        super.onPause();
        readViewsIntoModel();
        saveInternalState();
    }

    private void buildScreen() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(8), dp(8), dp(8), dp(8));
        root.setBackgroundColor(COLOR_SCREEN_BG);

        TextView title = new TextView(this);
        title.setText("Weight Table");
        title.setTextColor(COLOR_TEXT);
        title.setTextSize(22);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setGravity(Gravity.CENTER_VERTICAL);
        root.addView(title, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        LinearLayout topControlRow = new LinearLayout(this);
        topControlRow.setOrientation(LinearLayout.HORIZONTAL);
        topControlRow.setGravity(Gravity.CENTER_VERTICAL);
        topControlRow.setPadding(0, dp(8), 0, dp(4));
        root.addView(topControlRow, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        settingsCheckBox = new CheckBox(this);
        settingsCheckBox.setText("Settings");
        settingsCheckBox.setTextSize(16);
        settingsCheckBox.setTextColor(COLOR_TEXT);
        settingsCheckBox.setChecked(settingsMode);
        topControlRow.addView(settingsCheckBox, new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
        ));

        readOnlyCheckBox = new CheckBox(this);
        readOnlyCheckBox.setText("ReadOnly");
        readOnlyCheckBox.setTextSize(16);
        readOnlyCheckBox.setTextColor(COLOR_TEXT);
        readOnlyCheckBox.setChecked(readOnlyMode);
        topControlRow.addView(readOnlyCheckBox, new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
        ));

        settingsScrollView = new ScrollView(this);
        settingsScrollView.setFillViewport(false);
        settingsPanel = new LinearLayout(this);
        settingsPanel.setOrientation(LinearLayout.VERTICAL);
        settingsPanel.setPadding(0, dp(2), 0, dp(6));
        settingsScrollView.addView(settingsPanel, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.MATCH_PARENT,
                ScrollView.LayoutParams.WRAP_CONTENT
        ));
        root.addView(settingsScrollView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(260)
        ));

        settingsModeControls = new LinearLayout(this);
        settingsModeControls.setOrientation(LinearLayout.VERTICAL);
        settingsModeControls.setPadding(0, dp(2), 0, dp(4));
        settingsPanel.addView(settingsModeControls, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        buildProtectedModeControls();

        actionControls = new LinearLayout(this);
        actionControls.setOrientation(LinearLayout.VERTICAL);
        actionControls.setPadding(0, dp(2), 0, dp(4));
        settingsPanel.addView(actionControls, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        buildActionControls();

        sizeControls = new LinearLayout(this);
        sizeControls.setOrientation(LinearLayout.VERTICAL);
        sizeControls.setPadding(0, dp(2), 0, dp(6));
        settingsPanel.addView(sizeControls, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        buildSizeControls();

        ScrollView verticalScroll = new ScrollView(this);
        HorizontalScrollView horizontalScroll = new HorizontalScrollView(this);
        table = new TableLayout(this);
        table.setStretchAllColumns(false);
        horizontalScroll.addView(table, new HorizontalScrollView.LayoutParams(
                HorizontalScrollView.LayoutParams.WRAP_CONTENT,
                HorizontalScrollView.LayoutParams.WRAP_CONTENT
        ));
        verticalScroll.addView(horizontalScroll, new ScrollView.LayoutParams(
                ScrollView.LayoutParams.WRAP_CONTENT,
                ScrollView.LayoutParams.WRAP_CONTENT
        ));
        root.addView(verticalScroll, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
        ));

        setContentView(root);

        settingsCheckBox.setOnCheckedChangeListener((buttonView, isChecked) -> {
            readViewsIntoModel();
            settingsMode = isChecked;
            applyProtectedMode();
            saveInternalState();
        });

        readOnlyCheckBox.setOnCheckedChangeListener((buttonView, isChecked) -> {
            readViewsIntoModel();
            readOnlyMode = isChecked;
            applyProtectedMode();
            saveInternalState();
        });
    }

    private void buildProtectedModeControls() {
        if (settingsModeControls == null) {
            return;
        }

        settingsModeControls.removeAllViews();

        LinearLayout row = makeSettingsModeRow();
        Button doubleHeaderButton = addProtectedModeButton(row, "Label height 1.5x: OFF");
        doubleHeaderButton.setOnClickListener(view -> {
            readViewsIntoModel();
            doubleHeaderHeight = !doubleHeaderHeight;
            updateDoubleHeaderButtonText(doubleHeaderButton);
            rebuildTable();
            saveInternalState();
        });
        updateDoubleHeaderButtonText(doubleHeaderButton);

        multiLineCellsCheckBox = addSettingsCheckBox(row, "Multiline cells", multiLineCellsEnabled);
    }

    private LinearLayout makeSettingsModeRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(2), 0, dp(2));
        settingsModeControls.addView(row, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        return row;
    }

    private Button addProtectedModeButton(LinearLayout row, String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(13);
        button.setGravity(Gravity.CENTER);
        button.setSingleLine(false);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
        );
        params.setMargins(dp(3), 0, dp(3), 0);
        row.addView(button, params);
        return button;
    }

    private void updateDoubleHeaderButtonText(Button button) {
        if (button != null) {
            button.setText(doubleHeaderHeight ? "Label height 1.5x: ON" : "Label height 1.5x: OFF");
        }
    }

    private void buildActionControls() {
        actionControls.removeAllViews();

        LinearLayout firstRow = makeButtonRow();
        Button saveButton = addButton(firstRow, "Save");
        Button loadButton = addButton(firstRow, "Load");

        LinearLayout secondRow = makeButtonRow();
        Button addRowButton = addButton(secondRow, "+Row");
        Button removeRowButton = addButton(secondRow, "-Row");

        LinearLayout thirdRow = makeButtonRow();
        Button addColumnButton = addButton(thirdRow, "+Column");
        Button removeColumnButton = addButton(thirdRow, "-Column");

        LinearLayout fourthRow = makeButtonRow();
        Button clearCheckmarksButton = addButton(fourthRow, "Clear all checkmarks");
        Button transposeButton = addButton(fourthRow, "Transpose");

        saveButton.setOnClickListener(view -> {
            readViewsIntoModel();
            rebuildTable();
            saveInternalState();
            startSaveTsv();
        });

        loadButton.setOnClickListener(view -> startLoadTsv());

        addRowButton.setOnClickListener(view -> {
            readViewsIntoModel();
            rows.add(new RowData(dataHeaders.size()));
            rebuildTable();
            saveInternalState();
        });

        removeRowButton.setOnClickListener(view -> {
            readViewsIntoModel();
            if (rows.size() > 1) {
                rows.remove(rows.size() - 1);
                rebuildTable();
                saveInternalState();
            } else {
                toast("At least one row is required.");
            }
        });

        addColumnButton.setOnClickListener(view -> {
            readViewsIntoModel();
            int newColumnIndex = dataHeaders.size();
            dataHeaders.add(defaultDataHeader(newColumnIndex));
            dataColumnWidthsDp.add(DEFAULT_ADDED_COLUMN_WIDTH_DP);
            for (RowData row : rows) {
                row.values.add("");
            }
            buildSizeControls();
            rebuildTable();
            saveInternalState();
        });

        removeColumnButton.setOnClickListener(view -> {
            readViewsIntoModel();
            if (dataHeaders.size() <= MIN_DATA_COLUMN_COUNT) {
                toast("The original 3 data columns cannot be removed.");
                return;
            }
            int lastIndex = dataHeaders.size() - 1;
            dataHeaders.remove(lastIndex);
            if (lastIndex < dataColumnWidthsDp.size()) {
                dataColumnWidthsDp.remove(lastIndex);
            }
            for (RowData row : rows) {
                if (lastIndex < row.values.size()) {
                    row.values.remove(lastIndex);
                }
            }
            ensureModelShape();
            buildSizeControls();
            rebuildTable();
            saveInternalState();
        });

        clearCheckmarksButton.setOnClickListener(view -> {
            readViewsIntoModel();
            for (RowData row : rows) {
                row.checked = false;
            }
            rebuildTable();
            saveInternalState();
            toast("All checkmarks cleared.");
        });

        transposeButton.setOnClickListener(view -> {
            readViewsIntoModel();
            transposeDataArray();
            buildSizeControls();
            rebuildTable();
            saveInternalState();
            toast("Table transposed.");
        });
    }

    private LinearLayout makeButtonRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(2), 0, dp(2));
        actionControls.addView(row, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        return row;
    }

    private Button addButton(LinearLayout row, String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(13);
        button.setSingleLine(false);
        button.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
        );
        params.setMargins(dp(3), 0, dp(3), 0);
        row.addView(button, params);
        return button;
    }

    private void buildSizeControls() {
        if (sizeControls == null) {
            return;
        }

        ensureModelShape();
        dataColumnWidthInputs.clear();
        sizeControls.removeAllViews();

        LinearLayout currentRow = null;
        int controlsInRow = 0;

        for (int i = 0; i < dataHeaders.size(); i++) {
            if (controlsInRow == 0) {
                currentRow = makeSettingsRow();
            }
            EditText input = addNumberBox(currentRow, "Column " + (i + 1) + " width", dataColumnWidthsDp.get(i));
            dataColumnWidthInputs.add(input);
            controlsInRow = (controlsInRow + 1) % 2;
        }

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        checkmarkColumnWidthInput = addNumberBox(currentRow, "Checkmark width", checkmarkColumnWidthDp);
        controlsInRow = (controlsInRow + 1) % 2;

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        rowHeightInput = addNumberBox(currentRow, "Row height", rowHeightDp);
        controlsInRow = (controlsInRow + 1) % 2;

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        rowSpacingInput = addNumberBox(currentRow, "Row spacing", rowSpacingDp);
        controlsInRow = (controlsInRow + 1) % 2;

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        checkmarkTextSizeInput = addNumberBox(currentRow, "Checkmark size", checkmarkTextSizeSp);
        controlsInRow = (controlsInRow + 1) % 2;

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        checkHoldMsInput = addNumberBox(currentRow, "Check hold ms", checkHoldMs);
        controlsInRow = (controlsInRow + 1) % 2;

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        removeHoldMsInput = addNumberBox(currentRow, "Remove hold ms", removeHoldMs);
        controlsInRow = (controlsInRow + 1) % 2;

        if (controlsInRow == 0) {
            currentRow = makeSettingsRow();
        }
        vibrationMsInput = addNumberBox(currentRow, "Vibration ms", vibrationMs);

        LinearLayout optionRow1 = makeSettingsRow();
        vibrationCheckBox = addSettingsCheckBox(optionRow1, "Vibration", vibrationEnabled);
        beepCheckBox = addSettingsCheckBox(optionRow1, "Beep", beepEnabled);

        LinearLayout optionRow2 = makeSettingsRow();
        Button testVibrationButton = addButton(optionRow2, "Test vibration");
        testVibrationButton.setOnClickListener(view -> {
            readViewsIntoModel();
            playCellActionFeedback(view);
            saveInternalState();
        });

        LinearLayout colorRow1 = makeSettingsRow();
        editableDataColorButton = addColorButton(colorRow1, "Editable data color", editableDataBgColor);
        readOnlyDataColorButton = addColorButton(colorRow1, "ReadOnly data color", readOnlyDataBgColor);

        LinearLayout colorRow2 = makeSettingsRow();
        editableHeaderColorButton = addColorButton(colorRow2, "Editable label color", editableHeaderBgColor);
        readOnlyHeaderColorButton = addColorButton(colorRow2, "ReadOnly label color", readOnlyHeaderBgColor);
    }

    private LinearLayout makeSettingsRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        sizeControls.addView(row, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));
        return row;
    }

    private Button addColorButton(LinearLayout parent, String label, int currentColor) {
        Button button = new Button(this);
        button.setText(label + "\n" + colorToHex(currentColor));
        button.setAllCaps(false);
        button.setTextSize(12);
        button.setSingleLine(false);
        button.setGravity(Gravity.CENTER);
        button.setPadding(dp(4), dp(2), dp(4), dp(2));
        button.setBackground(makeCellBackground(currentColor));
        button.setTextColor(contrastTextColor(currentColor));
        button.setOnClickListener(view -> {
            if (button == editableDataColorButton) {
                showColorDialog("Editable data color", editableDataBgColor, color -> {
                    editableDataBgColor = color;
                    updateColorButtons();
                    rebuildTable();
                    saveInternalState();
                });
            } else if (button == readOnlyDataColorButton) {
                showColorDialog("ReadOnly data color", readOnlyDataBgColor, color -> {
                    readOnlyDataBgColor = color;
                    updateColorButtons();
                    rebuildTable();
                    saveInternalState();
                });
            } else if (button == editableHeaderColorButton) {
                showColorDialog("Editable label color", editableHeaderBgColor, color -> {
                    editableHeaderBgColor = color;
                    updateColorButtons();
                    rebuildTable();
                    saveInternalState();
                });
            } else if (button == readOnlyHeaderColorButton) {
                showColorDialog("ReadOnly label color", readOnlyHeaderBgColor, color -> {
                    readOnlyHeaderBgColor = color;
                    updateColorButtons();
                    rebuildTable();
                    saveInternalState();
                });
            }
        });

        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0,
                dp(54),
                1f
        );
        params.setMargins(dp(3), dp(2), dp(3), dp(2));
        parent.addView(button, params);
        return button;
    }

    private void updateColorButtons() {
        updateColorButton(editableDataColorButton, "Editable data color", editableDataBgColor);
        updateColorButton(readOnlyDataColorButton, "ReadOnly data color", readOnlyDataBgColor);
        updateColorButton(editableHeaderColorButton, "Editable label color", editableHeaderBgColor);
        updateColorButton(readOnlyHeaderColorButton, "ReadOnly label color", readOnlyHeaderBgColor);
    }

    private void updateColorButton(Button button, String label, int color) {
        if (button == null) {
            return;
        }
        button.setText(label + "\n" + colorToHex(color));
        button.setBackground(makeCellBackground(color));
        button.setTextColor(contrastTextColor(color));
    }

    private void showColorDialog(String title, int currentColor, ColorCallback callback) {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(12);
        panel.setPadding(pad, pad, pad, pad);

        TextView note = new TextView(this);
        note.setText("Enter a color as #RRGGBB or choose a preset.");
        note.setTextColor(COLOR_TEXT);
        note.setTextSize(14);
        panel.addView(note, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        EditText hexInput = new EditText(this);
        hexInput.setText(colorToHex(currentColor));
        hexInput.setTextSize(16);
        hexInput.setSingleLine(true);
        hexInput.setSelectAllOnFocus(true);
        hexInput.setGravity(Gravity.CENTER);
        hexInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        panel.addView(hexInput, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(46)
        ));

        int[] presets = new int[]{
                Color.WHITE,
                Color.rgb(241, 245, 249),
                Color.rgb(226, 232, 240),
                Color.rgb(254, 249, 195),
                Color.rgb(220, 252, 231),
                Color.rgb(219, 234, 254),
                Color.rgb(252, 231, 243),
                Color.rgb(255, 237, 213),
                Color.rgb(15, 23, 42),
                Color.rgb(30, 41, 59)
        };

        LinearLayout presetGrid = new LinearLayout(this);
        presetGrid.setOrientation(LinearLayout.VERTICAL);
        presetGrid.setPadding(0, dp(8), 0, 0);
        panel.addView(presetGrid, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        LinearLayout row = null;
        for (int i = 0; i < presets.length; i++) {
            if (i % 2 == 0) {
                row = new LinearLayout(this);
                row.setOrientation(LinearLayout.HORIZONTAL);
                presetGrid.addView(row, new LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT
                ));
            }
            int presetColor = presets[i];
            Button presetButton = new Button(this);
            presetButton.setText(colorToHex(presetColor));
            presetButton.setAllCaps(false);
            presetButton.setTextSize(12);
            presetButton.setGravity(Gravity.CENTER);
            presetButton.setBackground(makeCellBackground(presetColor));
            presetButton.setTextColor(contrastTextColor(presetColor));
            presetButton.setOnClickListener(view -> {
                hexInput.setText(colorToHex(presetColor));
                hexInput.setSelection(hexInput.getText().length());
            });
            LinearLayout.LayoutParams presetParams = new LinearLayout.LayoutParams(0, dp(44), 1f);
            presetParams.setMargins(dp(3), dp(3), dp(3), dp(3));
            if (row != null) {
                row.addView(presetButton, presetParams);
            }
        }

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(title)
                .setView(panel)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Apply", null)
                .create();

        dialog.setOnShowListener(dialogInterface -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            try {
                int color = parseHexColor(hexInput.getText().toString());
                callback.onColorSelected(color);
                dialog.dismiss();
            } catch (Exception exception) {
                toast("Use color format #RRGGBB.");
            }
        }));

        dialog.show();
    }

    private int parseHexColor(String text) {
        String cleaned = text == null ? "" : text.trim();
        if (cleaned.length() == 6 && !cleaned.startsWith("#")) {
            cleaned = "#" + cleaned;
        }
        if (cleaned.length() != 7 || !cleaned.startsWith("#")) {
            throw new IllegalArgumentException("Invalid color");
        }
        return Color.parseColor(cleaned);
    }

    private String colorToHex(int color) {
        return String.format("#%02X%02X%02X", Color.red(color), Color.green(color), Color.blue(color));
    }

    private int contrastTextColor(int color) {
        int red = Color.red(color);
        int green = Color.green(color);
        int blue = Color.blue(color);
        int luminance = (red * 299 + green * 587 + blue * 114) / 1000;
        return luminance >= 140 ? Color.rgb(15, 23, 42) : Color.WHITE;
    }

    private EditText addNumberBox(LinearLayout parent, String label, int value) {
        LinearLayout wrapper = new LinearLayout(this);
        wrapper.setOrientation(LinearLayout.VERTICAL);
        wrapper.setGravity(Gravity.CENTER_VERTICAL);
        wrapper.setPadding(0, dp(2), dp(8), dp(2));

        TextView labelView = new TextView(this);
        labelView.setText(label + "=");
        labelView.setTextColor(COLOR_TEXT);
        labelView.setTextSize(11);
        labelView.setSingleLine(true);
        wrapper.addView(labelView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        EditText input = new EditText(this);
        input.setText(String.valueOf(value));
        input.setTextSize(12);
        input.setSingleLine(true);
        input.setSelectAllOnFocus(true);
        input.setInputType(InputType.TYPE_CLASS_NUMBER);
        input.setGravity(Gravity.CENTER);
        input.setPadding(dp(4), 0, dp(4), 0);
        input.setBackground(makeCellBackground(COLOR_EDITABLE_BG));
        wrapper.addView(input, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(36)
        ));

        input.setOnFocusChangeListener((view, hasFocus) -> {
            if (!hasFocus) {
                applySettingsFromInputs();
            }
        });

        input.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
                // Do not rebuild/clamp while the user is still typing.
                // This prevents values like "1" from being immediately changed to the minimum.
            }

            @Override
            public void afterTextChanged(Editable s) {
            }
        });

        LinearLayout.LayoutParams wrapperParams = new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
        );
        parent.addView(wrapper, wrapperParams);
        return input;
    }

    private CheckBox addSettingsCheckBox(LinearLayout parent, String label, boolean checked) {
        CheckBox checkBox = new CheckBox(this);
        checkBox.setText(label);
        checkBox.setTextSize(13);
        checkBox.setTextColor(COLOR_TEXT);
        checkBox.setGravity(Gravity.CENTER_VERTICAL);
        checkBox.setChecked(checked);
        checkBox.setPadding(dp(4), 0, dp(4), 0);
        checkBox.setOnCheckedChangeListener((buttonView, isChecked) -> {
            boolean oldMultiLineCellsEnabled = multiLineCellsEnabled;
            if (vibrationCheckBox != null) {
                vibrationEnabled = vibrationCheckBox.isChecked();
            }
            if (beepCheckBox != null) {
                beepEnabled = beepCheckBox.isChecked();
            }
            if (multiLineCellsCheckBox != null) {
                multiLineCellsEnabled = multiLineCellsCheckBox.isChecked();
            }
            if (oldMultiLineCellsEnabled != multiLineCellsEnabled) {
                readViewsIntoModel();
                rebuildTable();
            }
            saveInternalState();
        });

        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                0,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                1f
        );
        params.setMargins(dp(3), dp(2), dp(3), dp(2));
        parent.addView(checkBox, params);
        return checkBox;
    }

    private void applySettingsFromInputs() {
        if (!settingsMode) {
            return;
        }
        if (pendingSizeChange != null) {
            sizeChangeHandler.removeCallbacks(pendingSizeChange);
            pendingSizeChange = null;
        }
        readViewsIntoModel();
        rebuildTable();
        saveInternalState();
    }

    private void scheduleSizeChangeApply() {
        if (!settingsMode) {
            return;
        }
        if (pendingSizeChange != null) {
            sizeChangeHandler.removeCallbacks(pendingSizeChange);
        }
        pendingSizeChange = () -> {
            readViewsIntoModel();
            rebuildTable();
            saveInternalState();
        };
        sizeChangeHandler.postDelayed(pendingSizeChange, 500);
    }

    private void rebuildTable() {
        if (table == null) {
            return;
        }

        ensureModelShape();
        headerCells.clear();
        editableCells.clear();
        checkCells.clear();
        table.removeAllViews();

        TableRow headerRow = new TableRow(this);
        headerRow.setBaselineAligned(false);
        int headerHeightDp = doubleHeaderHeight ? Math.round(rowHeightDp * 1.5f) : rowHeightDp;
        for (int c = 0; c < dataHeaders.size(); c++) {
            EditText header = makeEditableCell(dataHeaders.get(c), true);
            header.setTag(new CellTag(-1, c));
            header.setTypeface(Typeface.DEFAULT_BOLD);
            headerCells.add(header);
            headerRow.addView(header, makeCellLayout(c, headerHeightDp));
        }

        EditText checkmarkHeaderCell = makeEditableCell(checkmarkHeader, true);
        checkmarkHeaderCell.setTag(new CellTag(-1, dataHeaders.size()));
        checkmarkHeaderCell.setTypeface(Typeface.DEFAULT_BOLD);
        headerCells.add(checkmarkHeaderCell);
        headerRow.addView(checkmarkHeaderCell, makeCellLayout(dataHeaders.size(), headerHeightDp));
        table.addView(headerRow);

        for (int r = 0; r < rows.size(); r++) {
            RowData rowData = rows.get(r);
            TableRow row = new TableRow(this);
            row.setBaselineAligned(false);

            for (int c = 0; c < dataHeaders.size(); c++) {
                EditText cell = makeEditableCell(rowData.values.get(c), false);
                cell.setTag(new CellTag(r, c));
                editableCells.add(cell);
                row.addView(cell, makeBodyCellLayout(c, rowHeightDp, r));
            }

            TextView checkCell = makeCheckCell(rowData.checked, r);
            checkCells.add(checkCell);
            row.addView(checkCell, makeBodyCellLayout(dataHeaders.size(), rowHeightDp, r));
            table.addView(row);
        }

        applyProtectedMode();
    }

    private EditText makeEditableCell(String text, boolean isHeader) {
        EditText editText = new EditText(this);
        editText.setText(text == null ? "" : text);
        editText.setTextSize(isHeader ? 15 : 14);
        int backgroundColor = isHeader ? editableHeaderBgColor : editableDataBgColor;
        editText.setTextColor(contrastTextColor(backgroundColor));
        applyTextLineLayout(editText, isHeader);
        editText.setMinHeight(0);
        editText.setMinimumHeight(0);
        editText.setIncludeFontPadding(false);
        editText.setPadding(dp(8), dp(3), dp(8), dp(3));
        editText.setGravity(Gravity.CENTER);
        applyEditTextInputType(editText, isHeader);
        editText.setSelectAllOnFocus(false);
        editText.setBackground(makeCellBackground(backgroundColor));
        editText.setOnLongClickListener(view -> handleEditableCellLongPress((EditText) view));
        return editText;
    }

    private boolean handleEditableCellLongPress(EditText editText) {
        if (readOnlyMode) {
            Object tag = editText.getTag();
            if (tag instanceof CellTag) {
                CellTag cellTag = (CellTag) tag;
                sortRowsByColumn(cellTag.column);
            }
            return true;
        }

        editText.requestFocus();
        editText.post(() -> {
            editText.setSelection(0, editText.getText().length());
            editText.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);
        });
        return true;
    }

    private void sortRowsByColumn(int columnIndex) {
        readViewsIntoModel();
        ensureModelShape();

        if (columnIndex >= 0 && columnIndex < dataHeaders.size()) {
            Collections.sort(rows, (left, right) -> compareCellText(
                    left.values.get(columnIndex),
                    right.values.get(columnIndex)
            ));
            rebuildTable();
            saveInternalState();
            toast("Sorted by " + dataHeaders.get(columnIndex) + ".");
        } else if (columnIndex == dataHeaders.size()) {
            Collections.sort(rows, (left, right) -> Boolean.compare(left.checked, right.checked));
            rebuildTable();
            saveInternalState();
            toast("Sorted by " + checkmarkHeader + ".");
        }
    }

    private int compareCellText(String left, String right) {
        String leftText = left == null ? "" : left.trim();
        String rightText = right == null ? "" : right.trim();
        Double leftNumber = parseNumberOrNull(leftText);
        Double rightNumber = parseNumberOrNull(rightText);
        if (leftNumber != null && rightNumber != null) {
            return Double.compare(leftNumber, rightNumber);
        }
        return leftText.compareToIgnoreCase(rightText);
    }

    private Double parseNumberOrNull(String text) {
        if (text == null || text.length() == 0) {
            return null;
        }
        try {
            return Double.parseDouble(text.replace(",", ""));
        } catch (Exception ignored) {
            return null;
        }
    }

    private void applyTextLineLayout(EditText editText, boolean isHeader) {
        if (isHeader && doubleHeaderHeight) {
            editText.setSingleLine(false);
            editText.setMaxLines(2);
            editText.setMinLines(2);
            editText.setHorizontallyScrolling(false);
        } else if (!isHeader && multiLineCellsEnabled) {
            editText.setSingleLine(false);
            editText.setMaxLines(5);
            editText.setMinLines(1);
            editText.setHorizontallyScrolling(false);
        } else {
            editText.setSingleLine(true);
            editText.setMaxLines(1);
            editText.setMinLines(1);
            editText.setHorizontallyScrolling(true);
        }
    }

    private void applyEditTextInputType(EditText editText, boolean isHeader) {
        if ((isHeader && doubleHeaderHeight) || (!isHeader && multiLineCellsEnabled)) {
            editText.setInputType(InputType.TYPE_CLASS_TEXT
                    | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                    | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        } else {
            editText.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        }
    }

    private int currentBodyBackgroundColor() {
        return readOnlyMode ? readOnlyDataBgColor : editableDataBgColor;
    }

    private TextView makeCheckCell(boolean checked, int rowIndex) {
        TextView textView = new TextView(this);
        textView.setGravity(Gravity.CENTER);
        textView.setTextSize(checkmarkTextSizeSp);
        textView.setIncludeFontPadding(false);
        textView.setMinHeight(0);
        textView.setMinimumHeight(0);
        textView.setTypeface(Typeface.DEFAULT_BOLD);
        textView.setTextColor(COLOR_GREEN);
        textView.setPadding(dp(8), 0, dp(8), 0);
        textView.setBackground(makeCellBackground(currentBodyBackgroundColor()));
        textView.setText(checked ? "V" : "");
        textView.setHapticFeedbackEnabled(true);
        textView.setTag(rowIndex);
        attachCheckHoldBehavior(textView);
        return textView;
    }

    private TableRow.LayoutParams makeCellLayout(int columnIndex, int heightDp) {
        TableRow.LayoutParams params = new TableRow.LayoutParams(
                dp(widthForColumn(columnIndex)),
                dp(heightDp)
        );
        params.setMargins(dp(1), dp(1), dp(1), dp(1));
        return params;
    }

    private TableRow.LayoutParams makeBodyCellLayout(int columnIndex, int cellHeightDp, int rowIndex) {
        int topMarginDp = rowIndex == 0 ? 0 : rowSpacingDp;
        int bottomMarginDp = 0;

        TableRow.LayoutParams params = new TableRow.LayoutParams(
                dp(widthForColumn(columnIndex)),
                dp(cellHeightDp)
        );
        params.setMargins(dp(1), dp(topMarginDp), dp(1), dp(bottomMarginDp));
        return params;
    }

    private int widthForColumn(int columnIndex) {
        if (columnIndex >= 0 && columnIndex < dataColumnWidthsDp.size()) {
            return dataColumnWidthsDp.get(columnIndex);
        }
        return checkmarkColumnWidthDp;
    }

    private GradientDrawable makeCellBackground(int fillColor) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fillColor);
        drawable.setStroke(dp(1), COLOR_BORDER);
        drawable.setCornerRadius(dp(3));
        return drawable;
    }

    private void attachCheckHoldBehavior(TextView cell) {
        Handler handler = new Handler(Looper.getMainLooper());
        final Runnable[] pending = new Runnable[1];
        final boolean[] actionCompleted = new boolean[1];

        cell.setOnTouchListener((view, event) -> {
            TextView touchedCell = (TextView) view;
            int action = event.getActionMasked();

            if (action == MotionEvent.ACTION_DOWN) {
                view.getParent().requestDisallowInterceptTouchEvent(true);
                actionCompleted[0] = false;
                boolean currentlyChecked = "V".contentEquals(touchedCell.getText());
                int delayMs = currentlyChecked ? removeHoldMs : checkHoldMs;

                pending[0] = () -> {
                    Integer rowIndex = (Integer) touchedCell.getTag();
                    if (rowIndex != null && rowIndex >= 0 && rowIndex < rows.size()) {
                        if (currentlyChecked) {
                            rows.get(rowIndex).checked = false;
                            touchedCell.setText("");
                            playCellActionFeedback(touchedCell);
                            toast("Checkmark removed.");
                        } else {
                            rows.get(rowIndex).checked = true;
                            touchedCell.setText("V");
                            playCellActionFeedback(touchedCell);
                            toast("Checkmark added.");
                        }
                        actionCompleted[0] = true;
                        saveInternalState();
                    }
                };

                handler.postDelayed(pending[0], delayMs);
                return true;
            }

            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                view.getParent().requestDisallowInterceptTouchEvent(false);
                if (!actionCompleted[0] && pending[0] != null) {
                    handler.removeCallbacks(pending[0]);
                }
                pending[0] = null;
                return true;
            }

            return true;
        });
    }

    private void playCellActionFeedback(View sourceView) {
        if (vibrationEnabled) {
            vibrateBriefly(sourceView);
        }
        if (beepEnabled) {
            beepBriefly();
        }
    }

    private void vibrateBriefly(View sourceView) {
        int durationMs = boundInt(vibrationMs, MIN_VIBRATION_MS, MAX_VIBRATION_MS);
        boolean directVibrationStarted = false;

        try {
            Vibrator vibrator = getDeviceVibrator();
            if (vibrator != null && vibrator.hasVibrator()) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    vibrator.vibrate(makeFixedTwoPulseEffect(durationMs));
                } else {
                    vibrator.vibrate(makeFixedTwoPulsePattern(durationMs), -1);
                }
                directVibrationStarted = true;
            }
        } catch (Exception ignored) {
            directVibrationStarted = false;
        }

        if (!directVibrationStarted && sourceView != null) {
            performHapticFeedback(sourceView);
        }
    }

    private Vibrator getDeviceVibrator() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            VibratorManager vibratorManager = (VibratorManager) getSystemService(Context.VIBRATOR_MANAGER_SERVICE);
            return vibratorManager == null ? null : vibratorManager.getDefaultVibrator();
        }
        return (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
    }

    private VibrationEffect makeFixedTwoPulseEffect(int durationMs) {
        long[] timings = makeFixedTwoPulsePattern(durationMs);
        int[] amplitudes = new int[timings.length];
        for (int i = 0; i < amplitudes.length; i++) {
            amplitudes[i] = (i % 2 == 0) ? 0 : VibrationEffect.DEFAULT_AMPLITUDE;
        }
        return VibrationEffect.createWaveform(timings, amplitudes, -1);
    }

    private long[] makeFixedTwoPulsePattern(int durationMs) {
        int safeDurationMs = boundInt(durationMs, MIN_VIBRATION_MS, MAX_VIBRATION_MS);
        return new long[]{
                FIXED_VIBRATION_START_DELAY_MS,
                safeDurationMs,
                FIXED_VIBRATION_GAP_MS,
                safeDurationMs
        };
    }

    private void performHapticFeedback(View sourceView) {
        try {
            sourceView.setHapticFeedbackEnabled(true);
            sourceView.performHapticFeedback(
                    HapticFeedbackConstants.LONG_PRESS,
                    HapticFeedbackConstants.FLAG_IGNORE_VIEW_SETTING
            );
        } catch (Exception ignored) {
        }
    }

    private void beepBriefly() {
        ToneGenerator toneGenerator = null;
        try {
            toneGenerator = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80);
            toneGenerator.startTone(ToneGenerator.TONE_PROP_BEEP, 120);
        } catch (Exception ignored) {
        } finally {
            if (toneGenerator != null) {
                final ToneGenerator generatorToRelease = toneGenerator;
                new Handler(Looper.getMainLooper()).postDelayed(generatorToRelease::release, 180);
            }
        }
    }

    private void applyProtectedMode() {
        if (settingsScrollView != null) {
            settingsScrollView.setVisibility(settingsMode ? View.VISIBLE : View.GONE);
        }
        if (settingsCheckBox != null) {
            settingsCheckBox.setChecked(settingsMode);
        }
        if (readOnlyCheckBox != null) {
            readOnlyCheckBox.setChecked(readOnlyMode);
        }
        boolean editable = !readOnlyMode;
        for (EditText header : headerCells) {
            setEditTextEditable(header, editable, true);
        }
        for (EditText cell : editableCells) {
            setEditTextEditable(cell, editable, false);
        }
        int checkCellBackground = currentBodyBackgroundColor();
        for (TextView checkCell : checkCells) {
            checkCell.setBackground(makeCellBackground(checkCellBackground));
        }
    }

    private void setEditTextEditable(EditText editText, boolean editable, boolean isHeader) {
        if (editable) {
            editText.setFocusable(true);
            editText.setFocusableInTouchMode(true);
            editText.setCursorVisible(true);
            editText.setLongClickable(true);
            applyEditTextInputType(editText, isHeader);
            applyTextLineLayout(editText, isHeader);
            int backgroundColor = isHeader ? editableHeaderBgColor : editableDataBgColor;
            editText.setTextColor(contrastTextColor(backgroundColor));
            editText.setGravity(Gravity.CENTER);
            editText.setBackground(makeCellBackground(backgroundColor));
        } else {
            editText.clearFocus();
            editText.setFocusable(false);
            editText.setFocusableInTouchMode(false);
            editText.setCursorVisible(false);
            editText.setLongClickable(true);
            editText.setInputType(InputType.TYPE_NULL);
            applyTextLineLayout(editText, isHeader);
            int backgroundColor = isHeader ? readOnlyHeaderBgColor : readOnlyDataBgColor;
            editText.setTextColor(contrastTextColor(backgroundColor));
            editText.setGravity(Gravity.CENTER);
            editText.setBackground(makeCellBackground(backgroundColor));
        }
    }

    private void readViewsIntoModel() {
        readSizeInputsIntoModel();

        if (table == null || table.getChildCount() == 0) {
            return;
        }

        for (int c = 0; c < headerCells.size(); c++) {
            String value = headerCells.get(c).getText().toString();
            if (c < dataHeaders.size()) {
                dataHeaders.set(c, value);
            } else {
                checkmarkHeader = value.length() == 0 ? "15 reps" : value;
            }
        }

        for (EditText editText : editableCells) {
            Object tag = editText.getTag();
            if (!(tag instanceof CellTag)) {
                continue;
            }
            CellTag cellTag = (CellTag) tag;
            if (cellTag.row >= 0 && cellTag.row < rows.size()
                    && cellTag.column >= 0 && cellTag.column < dataHeaders.size()) {
                rows.get(cellTag.row).values.set(cellTag.column, editText.getText().toString());
            }
        }
    }

    private void readSizeInputsIntoModel() {
        ensureModelShape();
        readRowSpacingInputIntoModel();
        for (int i = 0; i < dataColumnWidthInputs.size() && i < dataColumnWidthsDp.size(); i++) {
            int value = readBoundedInt(dataColumnWidthInputs.get(i), dataColumnWidthsDp.get(i), MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP);
            dataColumnWidthsDp.set(i, value);
        }
        checkmarkColumnWidthDp = readBoundedInt(checkmarkColumnWidthInput, checkmarkColumnWidthDp, MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP);
        rowHeightDp = readBoundedInt(rowHeightInput, rowHeightDp, MIN_ROW_HEIGHT_DP, MAX_ROW_HEIGHT_DP);
        checkmarkTextSizeSp = readBoundedInt(checkmarkTextSizeInput, checkmarkTextSizeSp, MIN_CHECKMARK_TEXT_SIZE_SP, MAX_CHECKMARK_TEXT_SIZE_SP);
        checkHoldMs = readBoundedInt(checkHoldMsInput, checkHoldMs, MIN_HOLD_MS, MAX_HOLD_MS);
        removeHoldMs = readBoundedInt(removeHoldMsInput, removeHoldMs, MIN_HOLD_MS, MAX_HOLD_MS);
        vibrationMs = readBoundedInt(vibrationMsInput, vibrationMs, MIN_VIBRATION_MS, MAX_VIBRATION_MS);
        if (vibrationCheckBox != null) {
            vibrationEnabled = vibrationCheckBox.isChecked();
        }
        if (beepCheckBox != null) {
            beepEnabled = beepCheckBox.isChecked();
        }
        if (multiLineCellsCheckBox != null) {
            multiLineCellsEnabled = multiLineCellsCheckBox.isChecked();
        }
    }

    private void readRowSpacingInputIntoModel() {
        rowSpacingDp = readBoundedInt(rowSpacingInput, rowSpacingDp, MIN_ROW_SPACING_DP, MAX_ROW_SPACING_DP);
    }

    private int readBoundedInt(EditText input, int fallback, int min, int max) {
        if (input == null) {
            return fallback;
        }
        String text = input.getText().toString().trim();
        if (text.length() == 0) {
            return fallback;
        }
        try {
            int value = Integer.parseInt(text);
            if (value < min) {
                value = min;
            }
            if (value > max) {
                value = max;
            }
            if (!String.valueOf(value).equals(text) && !input.hasFocus()) {
                input.setText(String.valueOf(value));
                input.setSelection(input.getText().length());
            }
            return value;
        } catch (Exception ignored) {
            if (!input.hasFocus()) {
                input.setText(String.valueOf(fallback));
                input.setSelection(input.getText().length());
            }
            return fallback;
        }
    }

    private void transposeDataArray() {
        ensureModelShape();
        if (dataHeaders.isEmpty()) {
            return;
        }

        List<List<String>> matrix = new ArrayList<>();
        List<String> headerRow = new ArrayList<>();
        for (String header : dataHeaders) {
            headerRow.add(header == null ? "" : header);
        }
        matrix.add(headerRow);

        for (RowData row : rows) {
            List<String> values = new ArrayList<>();
            for (int c = 0; c < dataHeaders.size(); c++) {
                values.add(c < row.values.size() && row.values.get(c) != null ? row.values.get(c) : "");
            }
            matrix.add(values);
        }

        int newColumnCount = Math.max(MIN_DATA_COLUMN_COUNT, matrix.size());
        int newRowCount = dataHeaders.size();

        List<String> newHeaders = new ArrayList<>();
        List<RowData> newRows = new ArrayList<>();

        for (int newColumn = 0; newColumn < newColumnCount; newColumn++) {
            String header = "";
            if (newColumn < matrix.size() && !matrix.get(newColumn).isEmpty()) {
                header = matrix.get(newColumn).get(0);
            }
            newHeaders.add(header);
        }

        for (int oldColumn = 1; oldColumn < newRowCount; oldColumn++) {
            RowData newRow = new RowData(newColumnCount);
            for (int newColumn = 0; newColumn < newColumnCount; newColumn++) {
                String value = "";
                if (newColumn < matrix.size() && oldColumn < matrix.get(newColumn).size()) {
                    value = matrix.get(newColumn).get(oldColumn);
                }
                newRow.values.set(newColumn, value);
            }
            newRows.add(newRow);
        }

        if (newRows.isEmpty()) {
            newRows.add(new RowData(newColumnCount));
        }

        dataHeaders.clear();
        dataHeaders.addAll(newHeaders);
        rows.clear();
        rows.addAll(newRows);

        dataColumnWidthsDp.clear();
        for (int i = 0; i < dataHeaders.size(); i++) {
            dataColumnWidthsDp.add(defaultWidthForColumn(i));
        }
        for (RowData row : rows) {
            row.checked = false;
        }
        ensureModelShape();
    }

    private int defaultWidthForColumn(int index) {
        if (index == 0) {
            return DEFAULT_COLUMN_1_WIDTH_DP;
        }
        if (index == 1) {
            return DEFAULT_COLUMN_2_WIDTH_DP;
        }
        if (index == 2) {
            return DEFAULT_COLUMN_3_WIDTH_DP;
        }
        return DEFAULT_ADDED_COLUMN_WIDTH_DP;
    }

    private void startSaveTsv() {
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("text/plain");
        intent.putExtra(Intent.EXTRA_TITLE, "weight_table.tsv");
        try {
            startActivityForResult(intent, REQUEST_SAVE_TSV);
        } catch (Exception exception) {
            toast("Cannot open save dialog: " + exception.getMessage());
        }
    }

    private void startLoadTsv() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("text/*");
        try {
            startActivityForResult(intent, REQUEST_LOAD_TSV);
        } catch (Exception exception) {
            toast("Cannot open load dialog: " + exception.getMessage());
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }

        Uri uri = data.getData();
        if (requestCode == REQUEST_SAVE_TSV) {
            writeTsvToUri(uri);
        } else if (requestCode == REQUEST_LOAD_TSV) {
            readTsvFromUri(uri);
        }
    }

    private void writeTsvToUri(Uri uri) {
        try (OutputStream outputStream = getContentResolver().openOutputStream(uri, "wt")) {
            if (outputStream == null) {
                toast("Cannot open selected file for writing.");
                return;
            }
            String text = toTsvText();
            outputStream.write(text.getBytes(StandardCharsets.UTF_8));
            outputStream.flush();
            toast("Table and settings saved.");
        } catch (Exception exception) {
            toast("Save failed: " + exception.getMessage());
        }
    }

    private void readTsvFromUri(Uri uri) {
        try (InputStream inputStream = getContentResolver().openInputStream(uri)) {
            if (inputStream == null) {
                toast("Cannot open selected file for reading.");
                return;
            }
            String text = readAllText(inputStream);
            fromTsvText(text);
            buildSizeControls();
            rebuildTable();
            saveInternalState();
            toast("Table and settings loaded.");
        } catch (Exception exception) {
            toast("Load failed: " + exception.getMessage());
        }
    }

    private String readAllText(InputStream inputStream) throws Exception {
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line).append('\n');
            }
        }
        return builder.toString();
    }

    private String toTsvText() {
        readViewsIntoModel();
        ensureModelShape();
        StringBuilder builder = new StringBuilder();

        appendExportSettings(builder);
        builder.append(FILE_SECTION_DATA_LINE).append('\n');

        for (int c = 0; c < dataHeaders.size(); c++) {
            if (c > 0) {
                builder.append('\t');
            }
            builder.append(cleanTsv(dataHeaders.get(c)));
        }
        builder.append('\t').append(cleanTsv(checkmarkHeader)).append('\n');

        for (RowData row : rows) {
            for (int c = 0; c < dataHeaders.size(); c++) {
                if (c > 0) {
                    builder.append('\t');
                }
                builder.append(cleanTsv(row.values.get(c)));
            }
            builder.append('\t').append(row.checked ? "V" : "").append('\n');
        }
        return builder.toString();
    }

    private void appendExportSettings(StringBuilder builder) {
        builder.append(FILE_MAGIC_LINE).append('\n');
        appendSetting(builder, "settings_mode", settingsMode);
        appendSetting(builder, "read_only_mode", readOnlyMode);
        appendSetting(builder, "row_height_dp", rowHeightDp);
        appendSetting(builder, "row_spacing_dp", rowSpacingDp);
        appendSetting(builder, "checkmark_text_size_sp", checkmarkTextSizeSp);
        appendSetting(builder, "check_hold_ms", checkHoldMs);
        appendSetting(builder, "remove_hold_ms", removeHoldMs);
        appendSetting(builder, "vibration_ms", vibrationMs);
        appendSetting(builder, "vibration_enabled", vibrationEnabled);
        appendSetting(builder, "beep_enabled", beepEnabled);
        appendSetting(builder, "multiline_cells_enabled", multiLineCellsEnabled);
        appendSetting(builder, "editable_data_bg_color", editableDataBgColor);
        appendSetting(builder, "readonly_data_bg_color", readOnlyDataBgColor);
        appendSetting(builder, "editable_header_bg_color", editableHeaderBgColor);
        appendSetting(builder, "readonly_header_bg_color", readOnlyHeaderBgColor);
        appendSetting(builder, "double_header_height", doubleHeaderHeight);
        appendSetting(builder, "checkmark_column_width_dp", checkmarkColumnWidthDp);
        appendSetting(builder, "data_column_widths_dp", widthsToCsv());
    }

    private void appendSetting(StringBuilder builder, String key, Object value) {
        builder.append(FILE_SETTING_PREFIX)
                .append(cleanTsv(key))
                .append('\t')
                .append(cleanTsv(String.valueOf(value)))
                .append('\n');
    }

    private String cleanTsv(String value) {
        if (value == null) {
            return "";
        }
        return value.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ').trim();
    }

    private void fromTsvText(String text) {
        String tableText = extractAndApplyFileSettings(text == null ? "" : text);
        rows.clear();
        dataHeaders.clear();
        String[] lines = tableText.replace("\r\n", "\n").replace('\r', '\n').split("\n", -1);

        int maxColumns = 0;
        for (int i = 0; i < lines.length; i++) {
            if (i == lines.length - 1 && lines[i].length() == 0) {
                continue;
            }
            String[] parts = lines[i].split("\t", -1);
            if (parts.length > maxColumns) {
                maxColumns = parts.length;
            }
        }

        int dataColumnCount = Math.max(MIN_DATA_COLUMN_COUNT, Math.max(0, maxColumns - 1));
        boolean hasHeader = lines.length > 0 && lines[0].trim().length() > 0;
        String[] loadedHeaders = hasHeader ? lines[0].split("\t", -1) : new String[0];

        for (int c = 0; c < dataColumnCount; c++) {
            if (c < loadedHeaders.length - 1 && loadedHeaders[c].trim().length() > 0) {
                dataHeaders.add(loadedHeaders[c]);
            } else {
                dataHeaders.add(defaultDataHeader(c));
            }
        }

        if (hasHeader && loadedHeaders.length > dataColumnCount && loadedHeaders[dataColumnCount].trim().length() > 0) {
            checkmarkHeader = loadedHeaders[dataColumnCount];
        } else if (hasHeader && loadedHeaders.length > 0 && loadedHeaders[loadedHeaders.length - 1].trim().length() > 0) {
            checkmarkHeader = loadedHeaders[loadedHeaders.length - 1];
        } else {
            checkmarkHeader = "15 reps";
        }

        int firstDataLine = hasHeader ? 1 : 0;
        for (int i = firstDataLine; i < lines.length; i++) {
            String line = lines[i];
            if (line.length() == 0 && i == lines.length - 1) {
                continue;
            }
            String[] parts = line.split("\t", -1);
            RowData row = new RowData(dataColumnCount);
            for (int c = 0; c < dataColumnCount; c++) {
                row.values.set(c, c < parts.length ? parts[c] : "");
            }
            row.checked = parts.length > dataColumnCount && isCheckedText(parts[dataColumnCount]);
            rows.add(row);
        }

        if (rows.isEmpty()) {
            for (int i = 0; i < STARTING_ROW_COUNT; i++) {
                rows.add(new RowData(dataColumnCount));
            }
        }
        ensureModelShape();
    }

    private String extractAndApplyFileSettings(String text) {
        String normalized = text.replace("\r\n", "\n").replace('\r', '\n');
        String[] lines = normalized.split("\n", -1);
        StringBuilder tableBuilder = new StringBuilder();
        boolean foundNewFormat = false;
        boolean inDataSection = false;

        for (String line : lines) {
            if (!inDataSection) {
                if (line.equals(FILE_MAGIC_LINE)) {
                    foundNewFormat = true;
                    continue;
                }
                if (line.startsWith(FILE_SETTING_PREFIX)) {
                    foundNewFormat = true;
                    applyImportedSettingLine(line);
                    continue;
                }
                if (line.equals(FILE_SECTION_DATA_LINE)) {
                    foundNewFormat = true;
                    inDataSection = true;
                    continue;
                }
                if (foundNewFormat && line.trim().length() == 0) {
                    continue;
                }
            }
            tableBuilder.append(line).append('\n');
        }

        if (!foundNewFormat) {
            return text;
        }
        return tableBuilder.toString();
    }

    private void applyImportedSettingLine(String line) {
        String[] parts = line.split("\t", 3);
        if (parts.length < 3) {
            return;
        }
        applyImportedSetting(parts[1], parts[2]);
    }

    private void applyImportedSetting(String key, String value) {
        try {
            if ("settings_mode".equals(key)) {
                settingsMode = parseBoolean(value, settingsMode);
            } else if ("read_only_mode".equals(key)) {
                readOnlyMode = parseBoolean(value, readOnlyMode);
            } else if ("row_height_dp".equals(key)) {
                rowHeightDp = boundInt(Integer.parseInt(value.trim()), MIN_ROW_HEIGHT_DP, MAX_ROW_HEIGHT_DP);
            } else if ("row_spacing_dp".equals(key)) {
                rowSpacingDp = boundInt(Integer.parseInt(value.trim()), MIN_ROW_SPACING_DP, MAX_ROW_SPACING_DP);
            } else if ("checkmark_text_size_sp".equals(key)) {
                checkmarkTextSizeSp = boundInt(Integer.parseInt(value.trim()), MIN_CHECKMARK_TEXT_SIZE_SP, MAX_CHECKMARK_TEXT_SIZE_SP);
            } else if ("check_hold_ms".equals(key)) {
                checkHoldMs = boundInt(Integer.parseInt(value.trim()), MIN_HOLD_MS, MAX_HOLD_MS);
            } else if ("remove_hold_ms".equals(key)) {
                removeHoldMs = boundInt(Integer.parseInt(value.trim()), MIN_HOLD_MS, MAX_HOLD_MS);
            } else if ("vibration_ms".equals(key)) {
                vibrationMs = boundInt(Integer.parseInt(value.trim()), MIN_VIBRATION_MS, MAX_VIBRATION_MS);
            } else if ("vibration_enabled".equals(key)) {
                vibrationEnabled = parseBoolean(value, vibrationEnabled);
            } else if ("beep_enabled".equals(key)) {
                beepEnabled = parseBoolean(value, beepEnabled);
            } else if ("multiline_cells_enabled".equals(key)) {
                multiLineCellsEnabled = parseBoolean(value, multiLineCellsEnabled);
            } else if ("editable_data_bg_color".equals(key)) {
                editableDataBgColor = Integer.parseInt(value.trim());
            } else if ("readonly_data_bg_color".equals(key)) {
                readOnlyDataBgColor = Integer.parseInt(value.trim());
            } else if ("editable_header_bg_color".equals(key)) {
                editableHeaderBgColor = Integer.parseInt(value.trim());
            } else if ("readonly_header_bg_color".equals(key)) {
                readOnlyHeaderBgColor = Integer.parseInt(value.trim());
            } else if ("double_header_height".equals(key)) {
                doubleHeaderHeight = parseBoolean(value, doubleHeaderHeight);
            } else if ("checkmark_column_width_dp".equals(key)) {
                checkmarkColumnWidthDp = boundInt(Integer.parseInt(value.trim()), MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP);
            } else if ("data_column_widths_dp".equals(key)) {
                setDataColumnWidthsFromCsv(value);
            }
        } catch (Exception ignored) {
            // Keep the current/default setting if the imported setting value is malformed.
        }
    }

    private boolean parseBoolean(String value, boolean fallback) {
        if (value == null) {
            return fallback;
        }
        String cleaned = value.trim();
        if (cleaned.equalsIgnoreCase("true") || cleaned.equals("1") || cleaned.equalsIgnoreCase("yes") || cleaned.equalsIgnoreCase("on")) {
            return true;
        }
        if (cleaned.equalsIgnoreCase("false") || cleaned.equals("0") || cleaned.equalsIgnoreCase("no") || cleaned.equalsIgnoreCase("off")) {
            return false;
        }
        return fallback;
    }

    private void setDataColumnWidthsFromCsv(String csv) {
        dataColumnWidthsDp.clear();
        if (csv == null) {
            return;
        }
        String[] parts = csv.split(",", -1);
        for (String part : parts) {
            try {
                int value = Integer.parseInt(part.trim());
                dataColumnWidthsDp.add(boundInt(value, MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP));
            } catch (Exception ignored) {
                dataColumnWidthsDp.add(DEFAULT_ADDED_COLUMN_WIDTH_DP);
            }
        }
    }

    private boolean isCheckedText(String text) {
        if (text == null) {
            return false;
        }
        String cleaned = text.trim();
        return cleaned.equalsIgnoreCase("V")
                || cleaned.equals("✓")
                || cleaned.equalsIgnoreCase("X")
                || cleaned.equalsIgnoreCase("TRUE")
                || cleaned.equals("1")
                || cleaned.equalsIgnoreCase("YES");
    }

    private void loadInternalState() {
        settingsMode = preferences.getBoolean("settings_mode", false);
        readOnlyMode = preferences.getBoolean("read_only_mode", preferences.getBoolean("protected_mode", false));
        rowHeightDp = preferences.getInt("row_height_dp", DEFAULT_ROW_HEIGHT_DP);
        rowSpacingDp = preferences.getInt("row_spacing_dp", DEFAULT_ROW_SPACING_DP);
        checkmarkTextSizeSp = preferences.getInt("checkmark_text_size_sp", DEFAULT_CHECKMARK_TEXT_SIZE_SP);
        checkHoldMs = preferences.getInt("check_hold_ms", preferences.getInt("check_hold_seconds", 1) * 1000);
        removeHoldMs = preferences.getInt("remove_hold_ms", preferences.getInt("remove_hold_seconds", 2) * 1000);
        vibrationMs = preferences.getInt("vibration_ms", DEFAULT_VIBRATION_MS);
        vibrationEnabled = preferences.getBoolean("vibration_enabled", true);
        beepEnabled = preferences.getBoolean("beep_enabled", false);
        multiLineCellsEnabled = preferences.getBoolean("multiline_cells_enabled", false);
        editableDataBgColor = preferences.getInt("editable_data_bg_color", DEFAULT_DATA_EDITABLE_BG);
        readOnlyDataBgColor = preferences.getInt("readonly_data_bg_color", DEFAULT_DATA_READONLY_BG);
        editableHeaderBgColor = preferences.getInt("editable_header_bg_color", DEFAULT_HEADER_EDITABLE_BG);
        readOnlyHeaderBgColor = preferences.getInt("readonly_header_bg_color", DEFAULT_HEADER_READONLY_BG);
        doubleHeaderHeight = preferences.getBoolean("double_header_height", false);
        checkmarkColumnWidthDp = preferences.getInt(
                "checkmark_column_width_dp",
                preferences.getInt("column_4_width_dp", DEFAULT_CHECKMARK_COLUMN_WIDTH_DP)
        );

        String savedTsv = preferences.getString("table_tsv", "");
        if (savedTsv != null && savedTsv.trim().length() > 0) {
            fromTsvText(savedTsv);
        } else {
            initializeDefaultTable();
        }
        loadColumnWidthsFromPreferences();
        ensureModelShape();
    }

    private void initializeDefaultTable() {
        dataHeaders.clear();
        dataHeaders.add("Machine");
        dataHeaders.add("#Location");
        dataHeaders.add("Weight");
        checkmarkHeader = "15 reps";

        rows.clear();
        for (int i = 0; i < STARTING_ROW_COUNT; i++) {
            rows.add(new RowData(MIN_DATA_COLUMN_COUNT));
        }

        dataColumnWidthsDp.clear();
        dataColumnWidthsDp.add(DEFAULT_COLUMN_1_WIDTH_DP);
        dataColumnWidthsDp.add(DEFAULT_COLUMN_2_WIDTH_DP);
        dataColumnWidthsDp.add(DEFAULT_COLUMN_3_WIDTH_DP);
        checkmarkColumnWidthDp = DEFAULT_CHECKMARK_COLUMN_WIDTH_DP;
    }

    private void loadColumnWidthsFromPreferences() {
        dataColumnWidthsDp.clear();
        String savedWidths = preferences.getString("data_column_widths_dp", "");
        if (savedWidths != null && savedWidths.trim().length() > 0) {
            String[] parts = savedWidths.split(",", -1);
            for (String part : parts) {
                try {
                    int value = Integer.parseInt(part.trim());
                    dataColumnWidthsDp.add(boundInt(value, MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP));
                } catch (Exception ignored) {
                    dataColumnWidthsDp.add(DEFAULT_ADDED_COLUMN_WIDTH_DP);
                }
            }
        }

        if (dataColumnWidthsDp.isEmpty()) {
            dataColumnWidthsDp.add(preferences.getInt("column_1_width_dp", DEFAULT_COLUMN_1_WIDTH_DP));
            dataColumnWidthsDp.add(preferences.getInt("column_2_width_dp", DEFAULT_COLUMN_2_WIDTH_DP));
            dataColumnWidthsDp.add(preferences.getInt("column_3_width_dp", DEFAULT_COLUMN_3_WIDTH_DP));
        }
        ensureModelShape();
    }

    private void saveInternalState() {
        SharedPreferences.Editor editor = preferences.edit();
        editor.putBoolean("settings_mode", settingsMode);
        editor.putBoolean("read_only_mode", readOnlyMode);
        editor.putBoolean("protected_mode", readOnlyMode);
        editor.putInt("row_height_dp", rowHeightDp);
        editor.putInt("row_spacing_dp", rowSpacingDp);
        editor.putInt("checkmark_text_size_sp", checkmarkTextSizeSp);
        editor.putInt("check_hold_ms", checkHoldMs);
        editor.putInt("remove_hold_ms", removeHoldMs);
        editor.putInt("vibration_ms", vibrationMs);
        editor.putBoolean("vibration_enabled", vibrationEnabled);
        editor.putBoolean("beep_enabled", beepEnabled);
        editor.putBoolean("multiline_cells_enabled", multiLineCellsEnabled);
        editor.putInt("editable_data_bg_color", editableDataBgColor);
        editor.putInt("readonly_data_bg_color", readOnlyDataBgColor);
        editor.putInt("editable_header_bg_color", editableHeaderBgColor);
        editor.putInt("readonly_header_bg_color", readOnlyHeaderBgColor);
        editor.putBoolean("double_header_height", doubleHeaderHeight);
        editor.putInt("checkmark_column_width_dp", checkmarkColumnWidthDp);
        editor.putString("data_column_widths_dp", widthsToCsv());

        if (dataColumnWidthsDp.size() > 0) {
            editor.putInt("column_1_width_dp", dataColumnWidthsDp.get(0));
        }
        if (dataColumnWidthsDp.size() > 1) {
            editor.putInt("column_2_width_dp", dataColumnWidthsDp.get(1));
        }
        if (dataColumnWidthsDp.size() > 2) {
            editor.putInt("column_3_width_dp", dataColumnWidthsDp.get(2));
        }
        editor.putInt("column_4_width_dp", checkmarkColumnWidthDp);
        editor.putString("table_tsv", toTsvText());
        editor.apply();
    }

    private String widthsToCsv() {
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < dataColumnWidthsDp.size(); i++) {
            if (i > 0) {
                builder.append(',');
            }
            builder.append(dataColumnWidthsDp.get(i));
        }
        return builder.toString();
    }

    private void ensureModelShape() {
        if (dataHeaders.size() < MIN_DATA_COLUMN_COUNT) {
            while (dataHeaders.size() < MIN_DATA_COLUMN_COUNT) {
                dataHeaders.add(defaultDataHeader(dataHeaders.size()));
            }
        }

        while (dataColumnWidthsDp.size() < dataHeaders.size()) {
            int index = dataColumnWidthsDp.size();
            if (index == 0) {
                dataColumnWidthsDp.add(DEFAULT_COLUMN_1_WIDTH_DP);
            } else if (index == 1) {
                dataColumnWidthsDp.add(DEFAULT_COLUMN_2_WIDTH_DP);
            } else if (index == 2) {
                dataColumnWidthsDp.add(DEFAULT_COLUMN_3_WIDTH_DP);
            } else {
                dataColumnWidthsDp.add(DEFAULT_ADDED_COLUMN_WIDTH_DP);
            }
        }
        while (dataColumnWidthsDp.size() > dataHeaders.size()) {
            dataColumnWidthsDp.remove(dataColumnWidthsDp.size() - 1);
        }

        for (int i = 0; i < dataColumnWidthsDp.size(); i++) {
            dataColumnWidthsDp.set(i, boundInt(dataColumnWidthsDp.get(i), MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP));
        }
        checkmarkColumnWidthDp = boundInt(checkmarkColumnWidthDp, MIN_COLUMN_WIDTH_DP, MAX_COLUMN_WIDTH_DP);
        rowHeightDp = boundInt(rowHeightDp, MIN_ROW_HEIGHT_DP, MAX_ROW_HEIGHT_DP);
        rowSpacingDp = boundInt(rowSpacingDp, MIN_ROW_SPACING_DP, MAX_ROW_SPACING_DP);
        checkmarkTextSizeSp = boundInt(checkmarkTextSizeSp, MIN_CHECKMARK_TEXT_SIZE_SP, MAX_CHECKMARK_TEXT_SIZE_SP);
        checkHoldMs = boundInt(checkHoldMs, MIN_HOLD_MS, MAX_HOLD_MS);
        removeHoldMs = boundInt(removeHoldMs, MIN_HOLD_MS, MAX_HOLD_MS);
        vibrationMs = boundInt(vibrationMs, MIN_VIBRATION_MS, MAX_VIBRATION_MS);

        for (RowData row : rows) {
            while (row.values.size() < dataHeaders.size()) {
                row.values.add("");
            }
            while (row.values.size() > dataHeaders.size()) {
                row.values.remove(row.values.size() - 1);
            }
        }
    }

    private String defaultDataHeader(int index) {
        if (index == 0) {
            return "Machine";
        }
        if (index == 1) {
            return "#Location";
        }
        if (index == 2) {
            return "Weight";
        }
        return "Column " + (index + 1);
    }

    private int boundInt(int value, int min, int max) {
        if (value < min) {
            return min;
        }
        if (value > max) {
            return max;
        }
        return value;
    }

    private int dp(int value) {
        if (value == TableRow.LayoutParams.WRAP_CONTENT) {
            return TableRow.LayoutParams.WRAP_CONTENT;
        }
        float density = getResources().getDisplayMetrics().density;
        return Math.round(value * density);
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    private interface ColorCallback {
        void onColorSelected(int color);
    }

    private static class RowData {
        final List<String> values = new ArrayList<>();
        boolean checked = false;

        RowData(int columnCount) {
            for (int i = 0; i < columnCount; i++) {
                values.add("");
            }
        }
    }

    private static class CellTag {
        final int row;
        final int column;

        CellTag(int row, int column) {
            this.row = row;
            this.column = column;
        }
    }
}
