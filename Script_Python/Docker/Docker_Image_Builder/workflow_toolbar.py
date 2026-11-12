import tkinter as tk


def add_more_menu(parent, commands, background=None, label="More tools"):
    background = background or parent.cget("bg")
    button = tk.Menubutton(parent, text=label + " ▾", bg=background, fg="#243746",
                           relief="raised", bd=1, padx=10, pady=3, direction="below")
    menu = tk.Menu(button, tearoff=False)
    for title, callback in commands:
        if callback is None:
            menu.add_separator()
        else:
            menu.add_command(label=title, command=callback)
    button.configure(menu=menu)
    button.pack(side="left", padx=5)
    return button
