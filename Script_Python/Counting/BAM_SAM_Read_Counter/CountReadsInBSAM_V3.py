import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import subprocess
import os

def select_folder():
    """Opens a folder selection dialog and updates the entry field."""
    folder_path = filedialog.askdirectory()
    if folder_path:
        folder_entry.delete(0, tk.END)
        folder_entry.insert(0, folder_path)

def count_reads(file_path):
    """Counts total reads in a BAM or SAM file and updates the UI immediately."""
    try:
        wsl_file_path = file_path.replace("\\", "/").replace("C:/", "/mnt/c/")

        if file_path.endswith(".bam"):
            # Count reads in BAM file using samtools
            result = subprocess.run(
                f"wsl samtools view -c {wsl_file_path}",
                shell=True,
                capture_output=True,
                text=True
            )
        elif file_path.endswith(".sam"):
            # Count reads in SAM file using grep (excluding headers)
            result = subprocess.run(
                f"wsl grep -vc '^@' {wsl_file_path}",
                shell=True,
                capture_output=True,
                text=True
            )
        else:
            return None

        read_count = int(result.stdout.strip())
        return read_count

    except Exception as e:
        messagebox.showerror("Error", f"Error counting reads in {file_path}: {str(e)}")
        return None

def run_read_count():
    """Counts reads in all BAM/SAM files in the selected folder and displays results immediately."""
    input_folder = folder_entry.get()

    if not input_folder:
        messagebox.showerror("Input Error", "Please select a folder containing BAM/SAM files.")
        return

    # Find all BAM and SAM files in the folder
    files = [f for f in os.listdir(input_folder) if f.endswith(".bam") or f.endswith(".sam")]

    if not files:
        messagebox.showerror("Error", "No BAM or SAM files found in the selected folder.")
        return

    results = []
    output_file_path = os.path.join(input_folder, "read_counts.txt")

    # Clear previous output
    output_textbox.config(state=tk.NORMAL)
    output_textbox.delete("1.0", tk.END)

    for file_name in files:
        file_path = os.path.join(input_folder, file_name)
        total_reads = count_reads(file_path)

        if total_reads is not None:
            result_text = f"{file_name}: {total_reads} reads"
            results.append(result_text)

            # Display result immediately in the text box
            output_textbox.insert(tk.END, result_text + "\n")
            output_textbox.update_idletasks()  # Force GUI update to show the result immediately

    # Write results to a text file
    try:
        with open(output_file_path, "w") as f:
            f.write("\n".join(results) + "\n")
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save results to file: {str(e)}")
        return

    output_textbox.config(state=tk.DISABLED)

    messagebox.showinfo("Success", f"Counted reads in {len(results)} file(s).\nResults saved to:\n{output_file_path}")

# GUI setup
root = tk.Tk()
root.title("BAM/SAM Read Counter")
root.geometry("700x500")  # Set default window size
root.resizable(True, True)  # Allow resizing of the window

# Configure grid to make the text box expand
root.grid_rowconfigure(2, weight=1)
root.grid_columnconfigure(1, weight=1)

# Folder selection
tk.Label(root, text="Select BAM/SAM Folder:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
folder_entry = tk.Entry(root, width=50)
folder_entry.grid(row=0, column=1, padx=10, pady=10, sticky="we")
tk.Button(root, text="Browse", command=select_folder).grid(row=0, column=2, padx=10, pady=10)

# Run button
tk.Button(root, text="Count Reads", command=run_read_count).grid(row=1, column=1, pady=10)

# Output label
tk.Label(root, text="Read Counts:").grid(row=2, column=0, padx=10, pady=5, sticky="nw")

# Output box with scrollbars
frame = tk.Frame(root)
frame.grid(row=2, column=1, columnspan=2, padx=10, pady=5, sticky="nsew")

output_textbox = scrolledtext.ScrolledText(frame, height=15, width=70, state=tk.DISABLED, wrap=tk.WORD)
output_textbox.pack(fill=tk.BOTH, expand=True)

root.mainloop()
