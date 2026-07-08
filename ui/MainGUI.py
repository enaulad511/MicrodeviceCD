# -*- coding: utf-8 -*-

__author__ = "Edisson A. Naula"
__date__ = "$ 08/10/2025  at 09:35 a.m. $"

from ui.PcrFrame import PCRFrame
from Drivers.ClientUDP import UdpClient
from templates.constants import font_buttons_small, font_footer, font_options, font_text
from ui.ConfigFrame import ConfigFrame
from ui.TemperatureFrame import TemperatureFrame

import platform

import ttkbootstrap as ttk
from PIL import Image, ImageTk

from templates.constants import (
    font_buttons,
    font_entry,
    font_labels,
    font_labels_frame,
    font_tabs,
    main_tabs_icons,
    main_tabs_texts,
    tab_icons,
    tab_texts,
)
from ui.DiscFrame import ControlDiscFrame
from ui.ElectrochemicalFrame import ElectrochemicalFrame
from ui.FluorecenseLEDFrame import ControlFluorescenteFrame
from ui.FrameInit import StartImageFrame
from ui.LEDFrame import ControleLEDFrame
from ui.PhotoreceptorFrame import PhotoreceptorFrame
from ui.QuickControlFrame import QuickControlFrame


def configure_styles():
    style = ttk.Style()

    style.configure("Custom.TButton", font=font_buttons)
    style.configure("Custom.TLabel", font=font_labels)
    style.configure("Custom.TEntry", font=font_entry)
    style.configure("Custom.TLabelframe.Label", font=font_labels_frame)
    style.configure("Custom.TNotebook.Tab", font=font_tabs)
    style.configure("Custom.TCombobox.Text", background="green", font=font_entry)
    style.configure("info.TButton", font=font_buttons)
    style.configure("success.TButton", font=font_buttons)
    style.configure("danger.TButton", font=font_buttons)
    style.configure("success.TButton", font=font_buttons)
    style.configure("primary.TButton", font=font_buttons)
    style.configure("secondary.TButton", font=font_buttons)
    style.configure("CustomPrimary.TButton", font=font_buttons_small)
    style.configure("Custom.Treeview", font=("Arial", 18), rowheight=30)
    style.configure("Custom.Treeview.Heading", font=("Arial", 18, "bold"))
    style.configure("Vertical.TScrollbar", arrowsize=20)
    style.configure("Custom.TCheckbutton", font=font_text)
    style.configure("Custom.TRadiobutton", font=font_options)
    return style


def load_images():
    img_path_dict = {
        "arrow_up": r"files/img/arrow_up.png",
        "arrow_down": r"files/img/arrow_down.png",
        "rotate": r"files/img/rotate-icon.png",
        "rotate_end": r"files/img/rotate-icon-tope.png",
        "config": r"files/img/config.png",
        "save": r"files/img/save_btn.png",
        "control": r"files/img/remote-control.jpg",
        "link": r"files/img/link.png",
        "default": r"files/img/no_image.png",
    }
    images = {}
    for key, path in img_path_dict.items():
        try:
            img = Image.open(path)
        except FileNotFoundError:
            path = img_path_dict["default"]
            img = Image.open(path)
        img = img.resize((50, 50))
        images[key] = ImageTk.PhotoImage(img)
    return images


class MainGUI(ttk.Window):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.frame_m_control = None
        self.config_frame = None
        self.project_key = None
        self.title("\u03bcAA")
        self.style_gui = configure_styles()
        self.ip_sender = "localhost"
        self.client_tester = None
        self.protocol("WM_DELETE_WINDOW", self.on_close_window)
        self.option_add("*TCombobox*Listbox.font", font_text)
        self.option_add("*Combobox*Listbox.font", font_text)
        self.ads = None
        self.analysis_window = None
        # --------------------Start Animation -------------------
        # self.show_gif_toplevel()
        self.after(0, self.maximize_window)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        # self.images = load_images()
        # --------------------notebook-------------------
        self.connected = ttk.BooleanVar(value=False)
        self.frame_content = ttk.Frame(self)
        self.frame_content.grid(row=0, column=0, sticky="nsew", padx=(5, 10), pady=(1, 1))
        self.frame_content.columnconfigure(0, weight=1)
        self.frame_content.rowconfigure(0, weight=1)
        # ------------------main tabs-------------------
        self.main_notebook = ttk.Notebook(self.frame_content)
        self.main_notebook.configure(style="Custom.TNotebook")
        self.main_notebook.grid(row=0, column=0, sticky="nsew")
        self.main_notebook.columnconfigure(0, weight=1)
        self.main_notebook.rowconfigure(0, weight=1)
        self.main_notebook.bind("<<NotebookTabChanged>>", self.on_main_tab_changed)

        # ------------------PCR tab-------------------
        self.tab_pcr = PCRFrame(self.main_notebook, self.ads)
        self.main_notebook.add(self.tab_pcr, text=main_tabs_texts[0], padding=1)
        # ------------------Electrochemical tab-------------------
        self.tab_electrochemical = ElectrochemicalFrame(self.main_notebook, self.callback_ip)
        self.main_notebook.add(self.tab_electrochemical, text=main_tabs_texts[1], padding=1)
        # ------------------Manual Control tab-------------------
        self.tab_manual_control = ttk.Frame(self.main_notebook)
        self.main_notebook.add(self.tab_manual_control, text=main_tabs_texts[2], padding=1)
        self.tab_manual_control.columnconfigure(0, weight=1)
        self.tab_manual_control.rowconfigure(0, weight=1)
        # ------------------Manual Control tabs-------------------
        self.notebook = ttk.Notebook(self.tab_manual_control)
        self.notebook.configure(style="Custom.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew", pady=10)
        self.notebook.columnconfigure(0, weight=1)
        self.notebook.rowconfigure(0, weight=1)
        self.callbacks_manual_control = {
            # "change_tab_text": self.change_tab_text,
            # "change_title": self.change_title,
            # "init_tabs": self.init_tabs_callback,
            # "change_project": self.change_project_key,
            # "test_connection_callback":  self.test_connection,
            # "save_project_callback": self.save_project,
            # "on_geometry_changed": self.on_geometry_changed,
        }
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
        print("init tabs")

        self.tab_quick = QuickControlFrame(
            self.notebook, self.ads, lock_tabs_callback=self.set_tabs_locked
        )
        self.notebook.add(self.tab_quick, text=tab_texts[0])
        print("init tabs Quick Control")

        self.tab1 = ControleLEDFrame(self.notebook)
        self.notebook.add(self.tab1, text=tab_texts[1])
        print("init tabs LED")

        self.tab2 = ControlFluorescenteFrame(self.notebook)
        self.notebook.add(self.tab2, text=tab_texts[2])
        print("init tabs Fluorescence")

        self.tab3 = ControlDiscFrame(self.notebook)
        self.notebook.add(self.tab3, text=tab_texts[3])
        print("init tabs Disc")

        self.tab4 = PhotoreceptorFrame(self.notebook, self.ads)
        self.notebook.add(self.tab4, text=tab_texts[4])
        print("init tabs Photoreceptor")

        self.tab5 = TemperatureFrame(self.notebook, sensor_reader="termocupula")
        self.notebook.add(self.tab5, text=tab_texts[5])
        # # --------------------footer-------------------
        self.frame_footer = ttk.Frame(self)
        self.frame_footer.grid(row=1, column=0, sticky="nswe", padx=5)
        self.txt_connected = ttk.StringVar(value="Disc Disconnected")
        ttk.Label(
            self.frame_footer,
            textvariable=self.txt_connected,
            font=font_footer,
            style="Custom.TLabel",
        ).grid(row=0, column=0, sticky="ns", padx=15, pady=1)
        ttk.Button(
            self.frame_footer,
            text="🔄️Test Connection Disc",
            style="CustomPrimary.TButton",
            command=self.on_button_test_disc,
        ).grid(row=0, column=1, sticky="e", padx=15, pady=1)
        ttk.Button(
            self.frame_footer,
            text="Configuration",
            style="CustomPrimary.TButton",
            command=self.open_configurations,
        ).grid(row=0, column=2, sticky="e", padx=15, pady=1)
        ttk.Button(
            self.frame_footer,
            text="🔬 Analyze",
            style="CustomPrimary.TButton",
            command=self.open_analysis_window,
        ).grid(row=0, column=3, sticky="e", padx=15, pady=1)
        # ----------------------after init ----------------------
        self.after(2000, self.on_button_test_disc)

    def open_analysis_window(self):
        if self.analysis_window is not None:
            try:
                if self.analysis_window.winfo_exists():
                    self.analysis_window.lift()
                    return
            except Exception:
                pass
        from ui.analysis import AnalysisWindow

        self.analysis_window = AnalysisWindow(self, plotter=self, pcr_frame=self.tab_pcr)

    def callback_ip(self):
        return self.ip_sender

    def on_tab_changed(self, event):
        selected_index = self.notebook.index(self.notebook.select())
        for i, text in enumerate(tab_texts):
            if i == selected_index:
                icon = tab_icons.get(text, "")
                self.notebook.tab(i, text=f"{icon} {text}")
            else:
                self.notebook.tab(i, text=text)

    def set_tabs_locked(self, locked):
        """Bloquea/desbloquea las demás tabs mientras Quick Control tiene
        actuadores o lecturas activas. Aplica a AMBOS notebooks: las tabs
        hermanas del Manual Control y las principales (PCR/Electrochemical
        también usan motor/UDP). La tab Manual Control (índice 2) y la propia
        Quick Control (índice 0) quedan siempre habilitadas."""
        state = "disabled" if locked else "normal"
        try:
            for i, _ in enumerate(main_tabs_texts):
                if i != 2:  # Manual Control aloja a Quick Control
                    self.main_notebook.tab(i, state=state)
            for i, _ in enumerate(tab_texts):
                if i != 0:  # Quick Control
                    self.notebook.tab(i, state=state)
        except Exception as e:
            print(f"Error locking tabs: {e}")

    def on_main_tab_changed(self, event):
        selected_index = self.main_notebook.index(self.main_notebook.select())
        for i, text in enumerate(main_tabs_texts):
            if i == selected_index:
                icon = main_tabs_icons.get(text, "")
                self.main_notebook.tab(i, text=f"{icon} {text}")
            else:
                self.main_notebook.tab(i, text=text)

    def maximize_window(self):
        self.attributes("-fullscreen", False)

        print(
            self.winfo_width(),
            self.winfo_height(),
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
        )

        system = platform.system()

        if system == "Windows":
            self.state("zoomed")

        else:
            # Linux / macOS
            self.state("normal")

            # Esperar a que el WM cree la ventana
            self.update_idletasks()
            self.wait_visibility(self)

            # Intentar maximizar vía WM
            try:
                self.attributes("-zoomed", True)
                self.update()
            finally:
                # Verificación REAL
                w = self.winfo_width()
                h = self.winfo_height()
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()

                # Si el WM ignoró "-zoomed", forzamos fallback
                if w < sw or h < sh:
                    self.geometry(f"{sw}x{sh}+0+0")

    def show_gif_toplevel(self):
        # GifFrameApp(self)
        StartImageFrame(self)

    def open_configurations(self):
        # config_frame = ConfigFrame(self)
        if self.config_frame is None:
            self.config_frame = ConfigFrame(self)  # pyrefly: ignore
            self.config_frame.lift()
            self.config_frame.focus_force()
        else:
            self.config_frame.lift()
            self.config_frame.focus_force()

    def on_button_test_disc(self):
        # self.thread_tester_con = threading.Thread(target=self.try_connect_disc)
        # self.thread_tester_con.start()
        self.try_connect_disc()

    def on_message_tester(self, text, address, temps_list):
        # Basta con recibir el broadcast del disco para confirmar conexión y su IP;
        # no depende de un sensor en particular (cualquiera de las tres temperaturas
        # sirve — la termocupla puede venir ausente y las IR presentes, o viceversa).
        lf = next((t for t in temps_list[:3] if t is not None), None)
        if lf is not None:
            self.ip_sender = str(address[0])
            print("ip sender: ", self.ip_sender, " temp: ", lf)
            self.txt_connected.set("Disc Connected")
        else:
            print("Error at testing connection...")
            self.txt_connected.set("Disc Disconnected")
        if self.client_tester is not None:
            self.client_tester.stop_testing()
            self.client_tester = None

    def on_test_timeout(self):
        print("[MainGUI] Disc connection test timed out (no broadcast received).")
        self.txt_connected.set("Disc Disconnected")
        if self.client_tester is not None:
            self.client_tester.stop_testing()
            self.client_tester = None

    def try_connect_disc(self):
        if self.client_tester is not None:
            print("Stop client tester")
            self.client_tester.stop()
            self.client_tester = None
            return
        self.client_tester = UdpClient(
            port=5005,
            buffer_size=512,
            allow_broadcast=True,  # Important for broadcast payloads
            local_ip="",  # "" listens on all interfaces (wlan0, eth0, etc.)
            recv_timeout_sec=1.0,  # lets loop check stop flag periodically
            on_message=lambda t, a, t_d: self.on_message_tester(t, a, t_d),
            parse_float=True,  # Arduino sends a numeric string
            auto_stop_after_sec=5.0,  # solo para test de conexión: se cierra si no llega broadcast
            on_timeout=self.on_test_timeout,
        )
        self.client_tester.start()

    def on_close_window(self):
        self.destroy()
        self.quit()


if __name__ == "__main__":
    app = ttk.Window(themename="flatly")
    app.title("MicroAA Main GUI")
    app.geometry("1200x800")
    frame_test = ttk.Frame(app)
    frame_test.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
    selector = ttk.Combobox(
        frame_test,
        values=["PCR", "Electrochemical", "Manual Control"],
        state="readonly",
        width=30,
        style="Custom.TCombobox",
    )
    selector.grid(row=0, column=0, padx=10, pady=10, sticky="w")
