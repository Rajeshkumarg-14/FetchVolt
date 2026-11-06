"""Install wizard shown by `FetchVolt.exe --install`: welcome, license, folder and options, progress, finish.

All work is done by installer.py; this module only collects choices and shows messages.
"""
import os
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import installer
from version import VERSION

BG, PANEL, FG, MUTED, ACCENT, ERROR = '#0b0b0c', '#151517', '#f2f2f2', '#9a9aa2', '#c8f65d', '#ff8a8a'
FONT = 'Segoe UI'
CUSTOM_FOLDER_NOTE = ('Custom folder: in-app updates (fetchvolt update) are not available for it. '
                      'To update, run the new FetchVolt.exe with --install again.')


class Wizard:
    pages = ('welcome', 'license', 'folder', 'installing', 'finish')

    def __init__(self, layout=None, source=None, headless=False):
        self.layout = layout or installer.Layout()
        self.source = source
        self.installed_to = None
        self.page = 'welcome'
        self.root = tk.Tk()
        if headless:
            self.root.withdraw()
        self.root.title('FetchVolt Setup')
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        width, height = 640, 470
        self.root.geometry(f'{width}x{height}+{(self.root.winfo_screenwidth() - width) // 2}+{(self.root.winfo_screenheight() - height) // 3}')
        self.accepted = tk.BooleanVar(value=False)
        self.folder = tk.StringVar(value=str(self.layout.install))
        self.shortcut = tk.BooleanVar(value=True)
        self.add_path = tk.BooleanVar(value=True)
        self.launch = tk.BooleanVar(value=True)
        self.message = tk.StringVar()
        self._style()
        self._build()
        self.accepted.trace_add('write', lambda *_: self._buttons())
        self.folder.trace_add('write', lambda *_: self._folder_note())
        self.show('welcome')

    # layout -------------------------------------------------------------------------------------------------
    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=FG, font=(FONT, 10), borderwidth=0)
        style.configure('TFrame', background=BG)
        style.configure('Panel.TFrame', background=PANEL)
        style.configure('TLabel', background=BG, foreground=FG)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Title.TLabel', font=(FONT, 20, 'bold'))
        style.configure('Error.TLabel', foreground=ERROR)
        style.configure('TCheckbutton', background=BG, foreground=FG, focuscolor=BG)
        style.map('TCheckbutton', background=[('active', BG)], foreground=[('disabled', MUTED)])
        style.configure('TButton', background=PANEL, foreground=FG, padding=(18, 7), focuscolor=PANEL)
        style.map('TButton', background=[('active', '#222226')], foreground=[('disabled', '#55555c')])
        style.configure('Accent.TButton', background=ACCENT, foreground='#0b0b0c', font=(FONT, 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#d9ff7a'), ('disabled', '#3c4a1e')], foreground=[('disabled', '#7d8a5a')])
        style.configure('TEntry', fieldbackground=PANEL, foreground=FG, insertcolor=FG, padding=6)
        style.configure('Horizontal.TProgressbar', background=ACCENT, troughcolor=PANEL)

    def _build(self):
        outer = ttk.Frame(self.root, padding=(32, 28, 32, 18))
        outer.pack(fill='both', expand=True)
        self.body = ttk.Frame(outer)
        self.body.pack(fill='both', expand=True)
        self.frames = {name: ttk.Frame(self.body) for name in self.pages}
        self._welcome(self.frames['welcome'])
        self._license(self.frames['license'])
        self._folder(self.frames['folder'])
        self._installing(self.frames['installing'])
        self._finish(self.frames['finish'])
        ttk.Label(outer, textvariable=self.message, style='Error.TLabel', wraplength=570, justify='left').pack(fill='x', pady=(6, 0))
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=(10, 0))
        self.cancel_button = ttk.Button(bar, text='Cancel', command=self.cancel)
        self.cancel_button.pack(side='left')
        self.next_button = ttk.Button(bar, text='Next', style='Accent.TButton', command=self.next)
        self.next_button.pack(side='right')
        self.back_button = ttk.Button(bar, text='Back', command=self.back)
        self.back_button.pack(side='right', padx=(0, 10))

    def _heading(self, frame, title, subtitle=None):
        ttk.Label(frame, text=title, style='Title.TLabel').pack(anchor='w')
        if subtitle:
            ttk.Label(frame, text=subtitle, style='Muted.TLabel', wraplength=570, justify='left').pack(anchor='w', pady=(6, 14))

    def _welcome(self, frame):
        self._heading(frame, 'Install FetchVolt', f'Version {VERSION}')
        for line in ('Splits one HTTPS download across your Wi-Fi, Ethernet and tethered connections.',
                     'Installs for your Windows account only. No administrator rights are needed.',
                     'Click Next to read the license and choose where FetchVolt goes.'):
            ttk.Label(frame, text=line, wraplength=570, justify='left').pack(anchor='w', pady=4)

    def _license(self, frame):
        self._heading(frame, 'License agreement', 'FetchVolt is source-available under the PolyForm Noncommercial License. Read it before accepting.')
        holder = ttk.Frame(frame, style='Panel.TFrame', padding=2)
        holder.pack(fill='both', expand=True)
        scroll = ttk.Scrollbar(holder)
        scroll.pack(side='right', fill='y')
        self.license_box = tk.Text(holder, wrap='word', height=10, bg=PANEL, fg=FG, relief='flat', padx=10, pady=8,
                                   font=(FONT, 9), yscrollcommand=scroll.set, insertbackground=PANEL)
        scroll.config(command=self.license_box.yview)
        self.license_box.pack(side='left', fill='both', expand=True)
        try:
            self.license_box.insert('1.0', installer.license_text())
        except OSError:
            self.license_box.insert('1.0', 'The license text could not be loaded. Read LICENSE in the FetchVolt repository before installing.')
        self.license_box.config(state='disabled')
        ttk.Checkbutton(frame, text='I have read and accept the license terms', variable=self.accepted).pack(anchor='w', pady=(10, 0))

    def _folder(self, frame):
        self._heading(frame, 'Choose how to install', 'FetchVolt needs about 40 MB.')
        row = ttk.Frame(frame)
        row.pack(fill='x')
        self.folder_entry = ttk.Entry(row, textvariable=self.folder)
        self.folder_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=self.browse).pack(side='left', padx=(8, 0))
        self.folder_note = ttk.Label(frame, text='', style='Muted.TLabel', wraplength=570, justify='left')
        self.folder_note.pack(anchor='w', pady=(8, 14))
        ttk.Checkbutton(frame, text='Add a Start menu shortcut', variable=self.shortcut).pack(anchor='w', pady=3)
        ttk.Checkbutton(frame, text='Add the fetchvolt command to my PATH (new terminals)', variable=self.add_path).pack(anchor='w', pady=3)
        self._folder_note()

    def _installing(self, frame):
        self._heading(frame, 'Installing…', 'Copying FetchVolt and registering it for your account.')
        self.progress = ttk.Progressbar(frame, mode='indeterminate', length=570)
        self.progress.pack(anchor='w', pady=20)

    def _finish(self, frame):
        self._heading(frame, 'FetchVolt is installed')
        self.finish_text = ttk.Label(frame, text='', style='Muted.TLabel', wraplength=570, justify='left')
        self.finish_text.pack(anchor='w', pady=(0, 14))
        ttk.Checkbutton(frame, text='Start FetchVolt now', variable=self.launch).pack(anchor='w')

    # behavior -----------------------------------------------------------------------------------------------
    def show(self, name):
        self.page = name
        self.message.set('')
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[name].pack(fill='both', expand=True)
        self._buttons()

    def _buttons(self):
        page = self.page
        working = page == 'installing'
        self.back_button.state(['!disabled'] if page in ('license', 'folder') else ['disabled'])
        self.cancel_button.state(['disabled'] if working or page == 'finish' else ['!disabled'])
        label = {'folder': 'Install', 'finish': 'Close'}.get(page, 'Next')
        self.next_button.config(text=label)
        blocked = working or page == 'license' and not self.accepted.get()
        self.next_button.state(['disabled'] if blocked else ['!disabled'])

    def _folder_note(self):
        try:
            custom = not self.layout.at(self.folder.get()).is_default
        except (OSError, ValueError):
            custom = False
        self.folder_note.config(text=CUSTOM_FOLDER_NOTE if custom else 'This is the default folder, so in-app updates keep working.')

    def browse(self):
        chosen = filedialog.askdirectory(parent=self.root, initialdir=self.folder.get() if os.path.isdir(self.folder.get()) else None,
                                         title='Choose the FetchVolt install folder', mustexist=False)
        if chosen:
            self.folder.set(os.path.normpath(chosen))

    def back(self):
        if self.page in ('license', 'folder'):
            self.show(self.pages[self.pages.index(self.page) - 1])

    def next(self):
        if self.page == 'welcome':
            self.show('license')
        elif self.page == 'license':
            if not self.accepted.get():
                self.message.set('Accept the license terms to continue.')
                return
            self.show('folder')
        elif self.page == 'folder':
            self.begin_install()
        elif self.page == 'finish':
            self.finish()

    def begin_install(self):
        try:
            chosen = installer.validate_directory(self.folder.get())
            layout = self.layout.at(chosen)
            if installer.running_copies(layout):
                raise installer.InstallerError('Close the installed copy of FetchVolt before updating it.')
        except installer.InstallerError as error:
            self.message.set(str(error))
            return
        self.layout = layout
        self.show('installing')
        self.progress.start(12)
        self.outcome = {}
        # Tk variables must only be read on the main thread, so snapshot the choices first.
        choices = dict(accept_license=self.accepted.get(), shortcut=self.shortcut.get(), add_path=self.add_path.get())
        threading.Thread(target=self._work, args=(self.layout, choices), daemon=True).start()
        self.root.after(100, self._poll)

    def _work(self, layout, choices):
        try:
            self.outcome['path'] = installer.install(layout, self.source, **choices)
        except installer.InstallerError as error:
            self.outcome['error'] = str(error)
        except OSError:
            self.outcome['error'] = 'Windows refused the change. Pick a folder you can write to, or check your security software.'
        except Exception:
            self.outcome['error'] = 'The installation failed. Nothing was registered; try again or use a different folder.'

    def _poll(self):
        if not self.outcome:
            self.root.after(100, self._poll)
            return
        self.progress.stop()
        if 'error' in self.outcome:
            self.show('folder')
            self.message.set(self.outcome['error'])
            return
        self.installed_to = self.outcome['path']
        text = f'Installed in {self.installed_to}. Open a new terminal to use the fetchvolt command.'
        if not self.layout.is_default:
            text += ' ' + CUSTOM_FOLDER_NOTE
        self.finish_text.config(text=text)
        self.show('finish')

    def finish(self):
        if self.launch.get() and self.installed_to:
            subprocess.Popen([str(self.layout.exe)], cwd=str(self.layout.install), close_fds=True, creationflags=0x00000008)
        self.root.destroy()

    def cancel(self):
        if self.page != 'installing':
            self.root.destroy()


def run(layout=None, source=None):
    """Show the wizard. Returns 0 after a completed install, 1 if the user cancelled."""
    wizard = Wizard(layout, source)
    wizard.root.mainloop()
    return 0 if wizard.installed_to else 1
