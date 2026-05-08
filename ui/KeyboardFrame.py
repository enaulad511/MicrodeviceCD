from tkinter import font
import ttkbootstrap as ttk


def only_numeric(P):
    return P == "" or P.replace(".", "", 1).isdigit()


def on_entry_focus(event):
    keyboard.set_target(event.widget)
    keyboard.place(x=0, y=400, width=300, height=250)


class NumericKeyboard(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, relief="raised")
        self.target_entry = None

        buttons = [
            ["7", "8", "9", "OK"],
            ["4", "5", "6", "e"],
            ["1", "2", "3", "-"],
            ["±", "0", ".", "⌫"],
        ]

        for r, row in enumerate(buttons):
            for c, char in enumerate(row):
                btn = ttk.Button(
                    self,
                    text=char,
                    command=lambda ch=char: self.on_press(ch),
                    style="CustomPrimary.TButton",
                )
                btn.grid(row=r, column=c, ipadx=10, ipady=10, sticky="nsew")
        for i in range(4):
            self.columnconfigure(i, weight=1)
        for i in range(len(buttons)):
            self.rowconfigure(i, weight=1)

    def set_target(self, entry):
        """Establece el Entry activo"""
        self.target_entry = entry

    def on_press(self, char):
        if not self.target_entry:
            return

        if char == "⌫":
            current = self.target_entry.get()
            self.target_entry.delete(0, "end")
            self.target_entry.insert(0, current[:-1])

        elif char == "±":
            current = self.target_entry.get()
            new = current[1:] if current.startswith("-") else "-" + current
            self.target_entry.delete(0, "end")
            self.target_entry.insert(0, new)

        elif char == "OK":
            self.place_forget()  # ocultar teclado (opcional)

        else:
            self.target_entry.insert("end", char)


if __name__ == "__main__":
    app = ttk.Window()
    entry = ttk.Entry(app)
    entry.pack(pady=20)
    entry.bind("<FocusIn>", on_entry_focus)
    keyboard = NumericKeyboard(app)
    keyboard.place(x=0, y=400, width=300, height=250)  # ajusta posición
    keyboard.place_forget()  # ocultarlo al inicio
    app.mainloop()

    print(
        app.winfo_width(),
        app.winfo_height(),
        app.winfo_screenwidth(),
        app.winfo_screenheight(),
    )
    # 1 1 800 400

    # vcmd = root.register(only_numeric)
    # entry.config(validate="key", validatecommand=(vcmd, "%P"))
