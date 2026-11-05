"""Windows appearance preferences and styles for the desktop interface."""
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk
import winreg
import unicodedata

MODES = ('System', 'Light', 'Dark')
PREFERENCES = r'Software\Net Booster'
TRANSFER_OPTIONS = {
    'layout': ('TransferLayout', ('auto', 'vertical', 'horizontal')),
    'motion': ('TransferMotion', ('system', 'off')),
    'surface': ('SurfaceStyle', ('solid', 'glass')),
    'speed': ('SpeedUnit', ('mbps', 'mbs', 'mibs', 'kbps', 'auto')),
}
WINDOWS_THEME = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'

PALETTES = {
    'Light': dict(bg='#eef2f7', surface='#ffffff', field='#f8faff', text='#142238',
                  muted='#475a73', line='#cbd5e3', hover='#e1eafb', selected='#dce9ff',
                  accent='#1d51ba', active='#16429b', stripe='#f4f7fc', good='#096747'),
    'Dark': dict(bg='#0c1422', surface='#131f30', field='#0e1929', text='#eef4ff',
                 muted='#aebfd5', line='#35455c', hover='#22334c', selected='#253e65',
                 accent='#83afff', active='#a1c2ff', stripe='#17263a', good='#77d5ac'),
}


def preference():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCES) as key:
            value, _ = winreg.QueryValueEx(key, 'Appearance')
        return value if value in MODES else 'System'
    except OSError:
        return 'System'


def save_preference(value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PREFERENCES) as key:
        winreg.SetValueEx(key, 'Appearance', 0, winreg.REG_SZ, value)


def transfer_preferences():
    result = {}
    for name, (entry, allowed) in TRANSFER_OPTIONS.items():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCES) as key:
                value, _ = winreg.QueryValueEx(key, entry)
        except OSError:
            value = None
        result[name] = value if value in allowed else allowed[0]
    return result


def save_transfer_preference(name, value):
    if not isinstance(name, str) or name not in TRANSFER_OPTIONS:
        raise ValueError('Unknown transfer preference.')
    entry, allowed = TRANSFER_OPTIONS[name]
    if value not in allowed:
        raise ValueError('Invalid transfer preference.')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PREFERENCES) as key:
        winreg.SetValueEx(key, entry, 0, winreg.REG_SZ, value)


def validate_display_name(value):
    if not isinstance(value, str):
        raise ValueError('Enter a display name.')
    value = unicodedata.normalize('NFC', value).strip()
    if not 1 <= len(value) <= 40 or any(unicodedata.category(char).startswith('C') for char in value):
        raise ValueError('Use 1 to 40 visible characters for your name.')
    return value


def display_name():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PREFERENCES) as key:
            value, _ = winreg.QueryValueEx(key, 'DisplayName')
        return validate_display_name(value)
    except (OSError, ValueError):
        return 'My workspace'


def save_display_name(value):
    value = validate_display_name(value)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, PREFERENCES) as key:
        winreg.SetValueEx(key, 'DisplayName', 0, winreg.REG_SZ, value)
    return value


def resolve(mode):
    if mode != 'System':
        return mode
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_THEME) as key:
            light, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return 'Light' if light else 'Dark'
    except OSError:
        return 'Light'


def motion_enabled():
    enabled = wintypes.BOOL()
    return bool(ctypes.windll.user32.SystemParametersInfoW(
        0x1042, 0, ctypes.byref(enabled), 0
    ) and enabled.value)


def apply(root, mode):
    p = PALETTES[mode]
    style = ttk.Style(root)
    style.theme_use('clam')
    root.configure(background=p['bg'])
    root.option_add('*TCombobox*Listbox.background', p['field'])
    root.option_add('*TCombobox*Listbox.foreground', p['text'])
    root.option_add('*TCombobox*Listbox.selectBackground', p['selected'])
    root.option_add('*TCombobox*Listbox.selectForeground', p['text'])
    def update_dropdowns(widget):
        if isinstance(widget, ttk.Combobox):
            popdown = root.tk.call('ttk::combobox::PopdownWindow', widget)
            root.tk.call(popdown + '.f.l', 'configure', '-background', p['field'],
                         '-foreground', p['text'], '-selectbackground', p['selected'],
                         '-selectforeground', p['text'])
        for child in widget.winfo_children():
            update_dropdowns(child)

    update_dropdowns(root)
    style.configure('.', font=('Segoe UI', 10), background=p['surface'],
                    foreground=p['text'], bordercolor=p['line'], focuscolor=p['accent'],
                    lightcolor=p['surface'], darkcolor=p['surface'], troughcolor=p['bg'])
    style.configure('Shell.TFrame', background=p['bg'])
    style.configure('Shell.TLabel', background=p['bg'], foreground=p['muted'])
    style.configure('Brand.TLabel', background=p['bg'], font=('Segoe UI', 24, 'bold'))
    style.configure('Heading.TLabel', font=('Segoe UI', 17, 'bold'))
    style.configure('Muted.TLabel', foreground=p['muted'])
    style.configure('FieldLabel.TLabel', font=('Segoe UI', 10, 'bold'))
    style.configure('Inset.TFrame', background=p['stripe'])
    style.configure('InsetTitle.TLabel', background=p['stripe'], font=('Segoe UI', 12, 'bold'))
    style.configure('InsetMuted.TLabel', background=p['stripe'], foreground=p['muted'])
    style.configure('Metric.TLabel', background=p['stripe'], foreground=p['accent'], font=('Segoe UI', 28, 'bold'))
    style.configure('TNotebook', background=p['surface'], borderwidth=0)
    style.layout('TNotebook.Tab', [])
    style.configure('TButton', padding=(13, 8), background=p['field'], relief='flat')
    style.map('TButton', background=[('active', p['hover'])], bordercolor=[('focus', p['accent'])])
    style.configure('Nav.TButton', padding=(18, 8), background=p['bg'],
                    foreground=p['muted'], borderwidth=0)
    style.map('Nav.TButton', background=[('selected', p['selected']), ('active', p['hover'])],
              foreground=[('selected', p['accent']), ('active', p['text'])])
    style.configure('Primary.TButton', background=p['accent'], foreground=p['surface'],
                    bordercolor=p['accent'], font=('Segoe UI', 10, 'bold'))
    style.map('Primary.TButton',
              background=[('disabled', p['hover']), ('active', p['active'])],
              foreground=[('disabled', p['muted']), ('!disabled', p['surface'])])
    for control in ('TEntry', 'TCombobox'):
        style.configure(control, padding=(9, 7), fieldbackground=p['field'],
                        background=p['field'], insertcolor=p['text'], arrowcolor=p['text'])
        style.map(control, fieldbackground=[('readonly', p['field'])],
                  bordercolor=[('focus', p['accent'])],
                  selectbackground=[('focus', p['selected'])], selectforeground=[('focus', p['text'])])
    style.configure('Treeview', borderwidth=0, rowheight=36, background=p['surface'], fieldbackground=p['surface'])
    style.configure('Treeview.Heading', background=p['field'], font=('Segoe UI', 9, 'bold'), padding=8)
    style.map('Treeview', background=[('selected', p['selected'])], foreground=[('selected', p['text'])])
    style.configure('Horizontal.TProgressbar', thickness=9, background=p['accent'],
                    troughcolor=p['bg'], bordercolor=p['bg'], lightcolor=p['accent'], darkcolor=p['accent'])
    style.configure('TScrollbar', background=p['field'], arrowcolor=p['muted'])
    style.map('TScrollbar', background=[('active', p['hover'])])

    root.update_idletasks()
    parent = ctypes.windll.user32.GetParent
    parent.argtypes = [wintypes.HWND]
    parent.restype = wintypes.HWND
    hwnd = parent(root.winfo_id())
    dark = wintypes.BOOL(mode == 'Dark')
    set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
    set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    set_attribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
    return p


class Progress:
    def __init__(self, root, parent):
        self.root = root
        self.value = tk.DoubleVar(value=0)
        self.bar = ttk.Progressbar(parent, maximum=100, variable=self.value)
        self.pending = None
        self.busy = False

    def show(self, target):
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None
        animate = motion_enabled()
        if target is None:
            if not self.busy:
                self.busy = True
                self.value.set(0)
                if animate:
                    self.bar.configure(mode='indeterminate')
                    self.bar.start(22)
            return
        if self.busy:
            self.bar.stop()
            self.bar.configure(mode='determinate')
            self.value.set(0)
            self.busy = False
        start = self.value.get()
        if not animate or target <= start:
            self.value.set(target)
            return

        def step(frame):
            self.pending = None
            self.value.set(start + (target - start) * (1 - (1 - frame / 10) ** 3))
            if frame < 10:
                self.pending = self.root.after(16, step, frame + 1)

        step(1)
