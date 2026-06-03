from tkinter import font

import ttkbootstrap as ttk


def only_numeric(P):
    return P == "" or P.replace(".", "", 1).isdigit()


class NumericKeyboard(ttk.Frame):
    """Teclado numérico flotante.

    Posicionamiento: siempre debajo del entry activo, en coords del `parent`.
    Si se provee `scroll_host` (un ScrolledFrame), hace auto-scroll cuando el
    teclado completo no cabe debajo del entry dentro del viewport visible y
    se oculta solo al detectar scroll del usuario (rueda o barra) para no
    quedar desfasado del contenido.
    """

    PAD = 4

    def __init__(self, parent, scroll_host=None, width=260, height=150):
        super().__init__(parent, relief="raised")
        self.host = parent
        self.scroll_host = scroll_host
        self.kb_w = width
        self.kb_h = height
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

        self.place_forget()

        # Ocultar el teclado cuando el usuario scrollea: queda desfasado del
        # entry porque vive en coords del host, no del contenido scrolleado.
        if scroll_host is not None:
            scroll_host.bind("<MouseWheel>", self._hide_on_scroll, add="+")
            container = getattr(scroll_host, "container", None)
            if container is not None:
                container.bind("<MouseWheel>", self._hide_on_scroll, add="+")
            vscroll = getattr(scroll_host, "vscroll", None)
            if vscroll is not None:
                vscroll.bind("<B1-Motion>", self._hide_on_scroll, add="+")

    def attach(self, entries):
        """Bindea <Button-1> en cada entry para que muestre el teclado solo al hacer click/tap."""
        for entry in entries:
            entry.bind("<Button-1>", self._on_entry_click)

    def set_target(self, entry):
        """Establece el Entry activo."""
        self.target_entry = entry

    def _on_entry_click(self, event):
        entry = event.widget
        self.set_target(entry)
        self.show_for(entry)

    def show_for(self, entry):
        """Muestra el teclado debajo del entry, scrolleando si hace falta."""
        self.host.update_idletasks()

        # Auto-scroll: si el teclado no cabe debajo del entry dentro del
        # viewport visible, scrollea el contenido lo justo para que entren.
        # Si el contenido ya está al fondo (yview_moveto clampea), el clamp
        # de y más abajo se encarga de que el teclado siga siendo accesible.
        if self.scroll_host is not None:
            container = getattr(self.scroll_host, "container", None)
            vscroll = getattr(self.scroll_host, "vscroll", None)
            if container is not None and vscroll is not None:
                viewport_bottom = container.winfo_rooty() + container.winfo_height()
                entry_bottom = entry.winfo_rooty() + entry.winfo_height()
                overflow = (entry_bottom + self.kb_h + self.PAD) - viewport_bottom
                if overflow > 0:
                    inner_h = self.scroll_host.winfo_height()
                    if inner_h > 0:
                        current_first = vscroll.get()[0]
                        self.scroll_host.yview_moveto(current_first + overflow / inner_h)
                        self.host.update_idletasks()

        # Siempre debajo del entry, en coords del host.
        x = entry.winfo_rootx() - self.host.winfo_rootx()
        y = entry.winfo_rooty() - self.host.winfo_rooty() + entry.winfo_height() + self.PAD

        # Clamp al viewport visible: si el teclado todavía se sale (porque el
        # auto-scroll ya estaba al máximo), subimos el teclado para que entre
        # completo aunque tape parte del entry — preferimos teclas accesibles
        # sobre ver el entry.
        viewport_top, viewport_bottom = self._viewport_y_in_host()
        if y + self.kb_h > viewport_bottom:
            y = viewport_bottom - self.kb_h
        if y < viewport_top:
            y = viewport_top

        max_x = self.host.winfo_width() - self.kb_w
        if max_x > 0:
            x = max(0, min(x, max_x))
        self.place(x=x, y=y, width=self.kb_w, height=self.kb_h)
        self.lift()

    def _viewport_y_in_host(self):
        """Devuelve (top, bottom) del área visible en coords del host."""
        if self.scroll_host is not None:
            container = getattr(self.scroll_host, "container", None)
            if container is not None:
                top = container.winfo_rooty() - self.host.winfo_rooty()
                return top, top + container.winfo_height()
        return 0, self.host.winfo_height()

    def _hide_on_scroll(self, _event=None):
        try:
            if self.winfo_ismapped():
                self.place_forget()
        except Exception as e:
            print(e)

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
            self.place_forget()

        else:
            self.target_entry.insert("end", char)


if __name__ == "__main__":
    app = ttk.Window()
    entry = ttk.Entry(app)
    entry.pack(pady=20)
    keyboard = NumericKeyboard(app)
    keyboard.attach([entry])
    app.mainloop()


__author__ = "Edisson A. Naula"
__date__ = "$ 21/10/2025 at 11:30 a.m. $"
