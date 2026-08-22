#!/usr/bin/env python3
"""
ES3 Save Editor
A desktop editor for Easy Save 3 (ES3) Unity save files.
Supports AES-128-CBC + optional GZip compression.
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import gzip
import re
import json
import shutil
from datetime import datetime

try:
    from es3_modifier.main import decrypt_aes_128_cbc, encrypt_aes_128_cbc
except ImportError:
    tk.Tk().withdraw()
    messagebox.showerror(
        "Missing dependency",
        "es3-modifier is not installed.\nRun: pip install es3-modifier"
    )
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
#  Config (remembers last file + passwords)
# ─────────────────────────────────────────────────────────────────────────────

_APP_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_APP_DIR, 'config.json')
__version__ = "1.0.0"

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'files': {}, 'last_file': None}


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  Custom password dialog (with show/hide + remember)
# ─────────────────────────────────────────────────────────────────────────────

class PasswordDialog(tk.Toplevel):
    """
    Modal dialog asking for the decryption password.
    Returns (password: str, remember: bool) or None if cancelled.
    """
    def __init__(self, parent, filename: str, saved_password: str | None = None):
        super().__init__(parent)
        self.result = None

        self.title('Open ES3 File')
        self.resizable(False, False)
        self.transient(parent)

        # ── Body ──────────────────────────────────────────────
        pad = dict(padx=16, pady=6)

        ttk.Label(self, text='File:', font=('Segoe UI', 9, 'bold')).grid(
            row=0, column=0, sticky='w', **pad)
        ttk.Label(self, text=os.path.basename(filename), foreground='#444').grid(
            row=0, column=1, sticky='w', padx=(0, 16), pady=6)

        ttk.Separator(self, orient=tk.HORIZONTAL).grid(
            row=1, column=0, columnspan=2, sticky='ew', padx=16, pady=4)

        ttk.Label(self, text='Password:').grid(row=2, column=0, sticky='w', **pad)

        pw_row = ttk.Frame(self)
        pw_row.grid(row=2, column=1, sticky='ew', padx=(0, 16), pady=6)

        self._pw_var = tk.StringVar(value=saved_password or '')
        self._show_var = tk.BooleanVar(value=False)

        self._pw_entry = ttk.Entry(pw_row, textvariable=self._pw_var,
                                   show='●', width=26, font=('Consolas', 10))
        self._pw_entry.pack(side=tk.LEFT)

        self._eye_btn = ttk.Checkbutton(
            pw_row, text='👁', variable=self._show_var,
            command=self._toggle_show, width=3)
        self._eye_btn.pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(self, text='Leave blank if file is not encrypted.',
                  font=('Segoe UI', 8), foreground='#888').grid(
            row=3, column=1, sticky='w', padx=(0, 16))

        ttk.Separator(self, orient=tk.HORIZONTAL).grid(
            row=4, column=0, columnspan=2, sticky='ew', padx=16, pady=8)

        self._remember_var = tk.BooleanVar(value=bool(saved_password))
        ttk.Checkbutton(
            self,
            text='Remember password for this file',
            variable=self._remember_var,
        ).grid(row=5, column=0, columnspan=2, sticky='w', padx=16, pady=(0, 6))

        # ── Buttons ───────────────────────────────────────────
        btn_row = ttk.Frame(self)
        btn_row.grid(row=6, column=0, columnspan=2,
                     sticky='e', padx=16, pady=(4, 14))

        ttk.Button(btn_row, text='Cancel', command=self._cancel).pack(
            side=tk.RIGHT, padx=(4, 0))
        ttk.Button(btn_row, text='Open  ▶', command=self._ok).pack(side=tk.RIGHT)

        # ── Focus + bindings ──────────────────────────────────
        self._pw_entry.focus_set()
        # Select all pre-filled text so user can instantly overtype
        if saved_password:
            self._pw_entry.select_range(0, tk.END)
        self.bind('<Return>', lambda _: self._ok())
        self.bind('<Escape>', lambda _: self._cancel())

        # Center over parent
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{px}+{py}')

        self.grab_set()
        parent.wait_window(self)

    def _toggle_show(self):
        self._pw_entry.config(show='' if self._show_var.get() else '●')

    def _ok(self):
        self.result = (self._pw_var.get(), self._remember_var.get())
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
#  Welcome / Recent Files dialog
# ─────────────────────────────────────────────────────────────────────────────

class WelcomeDialog(tk.Toplevel):
    """
    Shown on startup when saved files exist.
    result is one of:
      ('open',   path)  — open a specific remembered file
      ('browse', None)  — user wants to browse for a file
      None              — start fresh / dismissed
    """
    def _load_icon(self):
        png = os.path.join(_APP_DIR, 'icon.png')

        if hasattr(self, '_load_icon'):
            icon = self._load_icon()
            if icon:
                self.iconphoto(True, icon)  
    def __init__(self, parent, cfg: dict):
        super().__init__(parent)
        self.result = None
        self.title('ES3 Save Editor — Open File')
        self.resizable(True, True)
        self.minsize(560, 300)
        self.transient(parent)

        # Inherit the same icon as the main window
        try:
            ico = os.path.join(_APP_DIR, 'icon.ico')
            png = os.path.join(_APP_DIR, 'icon.png')
            if os.path.exists(ico):
                self.wm_iconbitmap(ico)
            elif os.path.exists(png):
                img = tk.PhotoImage(file=png)
                self.iconphoto(True, img)
                self._icon_ref = img
        except Exception:
            pass

        files = cfg.get('files', {})   # {path: {password: ...}}

        # ── Header ────────────────────────────────────────────
        hdr = tk.Frame(self, bg='#1a2a5e')
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text='🛡  ES3 Save Editor', bg='#1a2a5e', fg='white',
                 font=('Segoe UI', 13, 'bold'), padx=16, pady=10).pack(side=tk.LEFT)
        tk.Label(hdr, text='Choose a file to open', bg='#1a2a5e', fg='#aabbdd',
                 font=('Segoe UI', 9), padx=8).pack(side=tk.LEFT)

        # ── File list ──────────────────────────────────────────
        list_frame = ttk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 4))

        ttk.Label(list_frame, text='Recent Files', font=('Segoe UI', 9, 'bold')).pack(
            anchor='w', pady=(0, 4))

        cols = ('pw', 'name', 'path', 'status')
        tv = ttk.Treeview(list_frame, columns=cols, show='headings',
                          selectmode='browse', height=8)
        tv.heading('pw',     text='')
        tv.heading('name',   text='File')
        tv.heading('path',   text='Folder')
        tv.heading('status', text='Status')
        tv.column('pw',     width=28,  minwidth=28,  stretch=False, anchor='center')
        tv.column('name',   width=160, minwidth=100)
        tv.column('path',   width=260, minwidth=120)
        tv.column('status', width=70,  minwidth=60,  anchor='center')

        vsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        tv.pack(fill=tk.BOTH, expand=True)

        # Populate rows
        tv.tag_configure('missing',  foreground='#aaa')
        tv.tag_configure('ok',       foreground='#222')
        tv.tag_configure('nopw',     foreground='#555')

        self._path_map = {}   # iid -> path

        for path, meta in files.items():
            exists  = os.path.exists(path)
            has_pw  = 'password' in meta
            pw_icon = '🔑' if has_pw else '🔓'
            name    = os.path.basename(path)
            folder  = os.path.dirname(path)
            status  = '✔ Found' if exists else '✖ Missing'
            tag     = 'ok' if exists else 'missing'
            iid = tv.insert('', 'end',
                             values=(pw_icon, name, folder, status),
                             tags=(tag,))
            self._path_map[iid] = path

        self._tv = tv
        tv.bind('<Double-1>', lambda _: self._open_selected())

        # Select first valid row
        for iid in tv.get_children():
            if os.path.exists(self._path_map[iid]):
                tv.selection_set(iid)
                tv.focus(iid)
                break

        # ── Hint ──────────────────────────────────────────────
        ttk.Label(self, text='🔑 = password remembered   🔓 = password not saved',
                  font=('Segoe UI', 8), foreground='#777').pack(anchor='w', padx=14)

        # ── Buttons ───────────────────────────────────────────
        btn_bar = ttk.Frame(self)
        btn_bar.pack(fill=tk.X, padx=12, pady=(6, 14))

        ttk.Button(btn_bar, text='✔  Open Selected',
                   command=self._open_selected).pack(side=tk.LEFT)
        ttk.Button(btn_bar, text='📂  Browse for file…',
                   command=self._browse).pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_bar, text='Start Fresh',
                   command=self._fresh).pack(side=tk.RIGHT)

        # ── Center + grab ──────────────────────────────────────
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{max(0,px)}+{max(0,py)}')

        self.bind('<Return>', lambda _: self._open_selected())
        self.bind('<Escape>', lambda _: self._fresh())
        self.grab_set()
        parent.wait_window(self)

    def _open_selected(self):
        sel = self._tv.selection()
        if not sel:
            messagebox.showwarning('No selection', 'Select a file first.',
                                   parent=self)
            return
        path = self._path_map[sel[0]]
        if not os.path.exists(path):
            messagebox.showwarning('File missing',
                f'The file no longer exists:\n{path}', parent=self)
            return
        self.result = ('open', path)
        self.destroy()

    def _browse(self):
        self.result = ('browse', None)
        self.destroy()

    def _fresh(self):
        self.result = None
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────

SIMPLE_NUM_TYPES = {
    'int', 'float', 'double', 'long', 'uint', 'ulong',
    'short', 'ushort', 'byte', 'sbyte', 'decimal', 'single',
}
BOOL_TYPES  = {'bool', 'boolean'}
STR_TYPES   = {'string', 'char'}

SAFETY = {
    'safe':     ('🟢', '#2d8a4e', '#eafaf1', 'Common numeric/bool/string — safe to edit freely.'),
    'caution':  ('🟡', '#9a7d0a', '#fef9e7', 'Structured collection — edit values carefully.'),
    'advanced': ('🔴', '#c0392b', '#fdecea', 'Complex game object — incorrect edits may break the save.'),
}


def classify(type_str: str):
    t  = type_str.strip()
    tl = t.lower()
    if tl in SIMPLE_NUM_TYPES:
        return 'number', 'safe', t
    if tl in BOOL_TYPES:
        return 'bool', 'safe', t
    if tl in STR_TYPES:
        return 'string', 'safe', t
    if 'list' in tl:
        m     = re.search(r'\[\[?(?:[^\]]*\.)*(\w+),', t)
        inner = m.group(1) if m else '?'
        return ('list_simple', 'safe', f'List<{inner}>') \
            if inner in {'Int32','Int64','Single','Double','Boolean','String'} \
            else ('list_complex', 'caution', f'List<{inner}>')
    if 'dictionary' in tl:
        return 'dict', 'caution', 'Dictionary'
    if 'datetime' in tl:
        return 'datetime', 'caution', 'DateTime'
    if t.startswith('System.'):
        return 'system', 'caution', t.split('.')[-1].split(',')[0].split('`')[0]
    if ',' in t:
        return 'custom_obj', 'advanced', t.split(',')[0].split('.')[-1]
    return 'raw', 'advanced', t


def value_preview(value, kind: str, max_ch=28) -> str:
    if value is None:
        return '—'
    if kind == 'bool':
        return '✓ true' if value else '✗ false'
    if kind == 'number':
        return str(value)
    if kind == 'string':
        s = str(value)
        return (s[:max_ch] + '…') if len(s) > max_ch else s
    if isinstance(value, list):
        return f'[{len(value)} items]'
    if isinstance(value, dict):
        return f'{{{len(value)} keys}}'
    return str(value)[:max_ch]


# ─────────────────────────────────────────────────────────────────────────────
#  ES3 file parser
# ─────────────────────────────────────────────────────────────────────────────

def _read_quoted_string(text, i):
    i += 1
    start = i
    while i < len(text) and text[i] != '"':
        if text[i] == '\\':
            i += 1
        i += 1
    return text[start:i], i + 1


def _skip_balanced(text, i):
    opener = text[i]
    closer = '}' if opener == '{' else ']'
    depth, in_str = 0, False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == '\\': i += 1
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c == opener: depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0: return i + 1
        i += 1
    return i


def _try_parse_block(raw_block: str):
    fixed = re.sub(
        r'(?<=[{,])\s*(-?\d+)\s*:',
        lambda m: ' "' + m.group(1).strip() + '":',
        raw_block,
    )
    try:
        return json.loads(fixed)
    except Exception:
        return None


def _annotate_entry(key: str, raw_block: str) -> dict:
    parsed = _try_parse_block(raw_block)
    entry  = {'key': key, 'raw_block': raw_block, 'parsed': parsed}
    if parsed and isinstance(parsed, dict) and '__type' in parsed:
        ts   = parsed['__type']
        kind, safety, dt = classify(ts)
        entry.update(type_str=ts, display_type=dt, kind=kind,
                     safety=safety, value=parsed.get('value'))
    else:
        entry.update(type_str='?', display_type='Unknown',
                     kind='raw', safety='advanced', value=None)
    return entry


def extract_entries(text: str) -> list:
    entries, i, n = [], text.index('{') + 1, len(text)
    while i < n:
        while i < n and text[i] in ' \t\r\n,': i += 1
        if i >= n or text[i] == '}': break
        if text[i] != '"': i += 1; continue
        key, i = _read_quoted_string(text, i)
        while i < n and text[i] in ' \t\r\n:': i += 1
        if i >= n or text[i] != '{': continue
        bs = i
        i  = _skip_balanced(text, i)
        entries.append(_annotate_entry(key, text[bs:i]))
    return entries


# ─────────────────────────────────────────────────────────────────────────────
#  ES3 file serialiser
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_file(entries: list) -> str:
    parts = ['{\n']
    for idx, e in enumerate(entries):
        comma = ',' if idx < len(entries) - 1 else ''
        parts.append(f'\t"{e["key"]}" : {e["raw_block"]}{comma}\n')
    parts.append('}')
    return ''.join(parts)


def rebuild_raw_block(entry: dict) -> str:
    kind, ts, val = entry['kind'], entry['type_str'], entry['value']
    t_json = json.dumps(ts)
    if kind in ('number', 'bool', 'string'):
        return f'{{\n\t\t"__type" : {t_json},\n\t\t"value" : {json.dumps(val)}\n\t}}'
    if kind == 'list_simple':
        items = ', '.join(
            ('true' if v else 'false') if isinstance(v, bool) else str(v)
            for v in val
        )
        return f'{{\n\t\t"__type" : {t_json},\n\t\t"value" : [{items}]\n\t}}'
    return json.dumps({'__type': ts, 'value': val}, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  .NET DateTime helper
# ─────────────────────────────────────────────────────────────────────────────

_EPOCH_TICKS = 621_355_968_000_000_000

def ticks_to_str(ticks: int) -> str:
    try:
        dt = datetime.utcfromtimestamp((ticks - _EPOCH_TICKS) / 10_000_000)
        return dt.strftime('%Y-%m-%d  %H:%M:%S  UTC')
    except Exception:
        return f'{ticks} ticks'


# ─────────────────────────────────────────────────────────────────────────────
#  Application
# ─────────────────────────────────────────────────────────────────────────────

class ES3Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('ES3 Save Editor')
        self.geometry('1100x680')
        self.minsize(800, 500)

        # State
        self._file_path: str | None = None
        self._password:  str | None = None
        self._salt: bytes | None    = None
        self._is_gzipped: bool      = False
        self._entries: list         = []
        self._all_entries: list     = []
        self._modified: set         = set()
        self._cfg: dict             = load_config()

        self._build_ui()
        self._apply_theme()
        self._load_icon()

        # Set Windows taskbar app ID so icon appears there correctly
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'ES3SaveEditor.App.1')
        except Exception:
            pass

        # Show welcome dialog instead of silently auto-reopening
        self.after(100, self._show_welcome)

    # ── Icon ───────────────────────────────────────────────────────────────
    def _load_icon(self):
        ico = os.path.join(_APP_DIR, 'icon.ico')
        png = os.path.join(_APP_DIR, 'icon.png')
        try:
            if os.path.exists(ico):
                self.wm_iconbitmap(ico)
            elif os.path.exists(png):
                img = tk.PhotoImage(file=png)
                self.iconphoto(True, img)
                self._icon_ref = img   # keep reference
        except Exception:
            pass   # silently ignore missing icon

    # ── Theme ──────────────────────────────────────────────────────────────
    def _apply_theme(self):
        s = ttk.Style(self)
        s.theme_use('clam')
        bg = '#f5f5f5'
        self.configure(bg=bg)
        s.configure('.', background=bg, font=('Segoe UI', 9))
        s.configure('Treeview', rowheight=26, font=('Segoe UI', 9))
        s.configure('Treeview.Heading', font=('Segoe UI', 9, 'bold'))
        s.configure('TLabelframe', padding=6)
        s.configure('TLabelframe.Label', font=('Segoe UI', 9, 'bold'))
        s.configure('FieldName.TLabel', font=('Segoe UI', 11, 'bold'))
        s.configure('Sub.TLabel',  font=('Segoe UI', 8),    foreground='#666')
        s.configure('Orig.TLabel', font=('Consolas', 9),    foreground='#888')
        s.configure('Warn.TLabel', font=('Segoe UI', 8),    foreground='#c0392b')
        s.configure('Hint.TLabel', font=('Segoe UI', 8),    foreground='#666', wraplength=420)
        s.configure('Apply.TButton', font=('Segoe UI', 9, 'bold'))
        s.configure('Toolbar.TFrame', background='#e8e8e8', relief='flat')

    # ── UI construction ────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_menu()
        self._build_toolbar()
        self._build_panes()
        self._build_status()

    def _build_menu(self):
        mb = tk.Menu(self)
        self.config(menu=mb)
        fm = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label='File', menu=fm)
        fm.add_command(label='Open…',         accelerator='Ctrl+O', command=self._open_file)
        fm.add_command(label='Save',           accelerator='Ctrl+S', command=self._save_file)
        fm.add_command(label='Save As…',       command=self._save_as)
        fm.add_separator()
        fm.add_command(label='Restore Backup…', command=self._restore_backup)
        fm.add_separator()
        fm.add_command(label='Clear saved passwords', command=self._clear_passwords)
        fm.add_separator()
        fm.add_command(label='Exit', command=self.quit)
        self.bind('<Control-o>', lambda _: self._open_file())
        self.bind('<Control-s>', lambda _: self._save_file())

        # About
        hm = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label='Help', menu=hm)
        hm.add_command(label='About', command=self._show_about)

    

    def _build_toolbar(self):
        bar = ttk.Frame(self, style='Toolbar.TFrame')
        bar.pack(fill=tk.X)
        ttk.Button(bar, text='📂 Open',  command=self._open_file).pack(side=tk.LEFT, padx=6, pady=4)
        ttk.Button(bar, text='💾 Save',  command=self._save_file).pack(side=tk.LEFT, padx=(0,6), pady=4)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        self._file_lbl = ttk.Label(bar, text='No file open', foreground='#888')
        self._file_lbl.pack(side=tk.LEFT, padx=4)
        self._unsaved_lbl = ttk.Label(bar, text='', foreground='#e67e22',
                                       font=('Segoe UI', 9, 'bold'))
        self._unsaved_lbl.pack(side=tk.LEFT, padx=4)
        self._backup_lbl = ttk.Label(bar, text='', foreground='#2d8a4e',
                                      font=('Segoe UI', 8))
        self._backup_lbl.pack(side=tk.RIGHT, padx=8)

    def _build_panes(self):
        pw = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pw.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        left = ttk.Frame(pw)
        pw.add(left, weight=1)
        self._build_field_list(left)
        right = ttk.Frame(pw)
        pw.add(right, weight=2)
        self._build_editor_panel(right)

    def _build_field_list(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=4, pady=(4,2))
        ttk.Label(top, text='🔍').pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', lambda *_: self._refresh_tree())
        ttk.Entry(top, textvariable=self._search_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._safety_filter = tk.StringVar(value='all')
        sf = ttk.Combobox(top, textvariable=self._safety_filter,
                          values=['all','🟢 safe','🟡 caution','🔴 advanced'],
                          state='readonly', width=12)
        sf.pack(side=tk.LEFT)
        sf.bind('<<ComboboxSelected>>', lambda _: self._refresh_tree())

        # ── Color legend ──────────────────────────────────────
        legend_frame = tk.Frame(parent, bg='#e8e8e8', pady=2)
        legend_frame.pack(fill=tk.X, padx=4, pady=(0, 2))

        legend_data = [
            ('safe',     '🟢 Safe',     '#eafaf1', '#2d8a4e', 'int · float · bool · string'),
            ('caution',  '🟡 Caution',  '#fef9e7', '#9a7d0a', 'Dictionary · Collections'),
            ('advanced', '🔴 Advanced', '#fdecea', '#c0392b', 'Complex game objects'),
        ]
        for _, label, bg, fg, desc in legend_data:
            pill = tk.Frame(legend_frame, bg=bg, padx=5, pady=1,
                            relief='flat', bd=0)
            pill.pack(side=tk.LEFT, padx=(4, 0))
            tk.Label(pill, text=label, bg=bg, fg=fg,
                     font=('Segoe UI', 7, 'bold')).pack(side=tk.LEFT)
            tk.Label(pill, text=f'  {desc}', bg=bg, fg='#555',
                     font=('Segoe UI', 7)).pack(side=tk.LEFT)

        cols = ('type','value','s')
        self._tree = ttk.Treeview(parent, columns=cols, show='tree headings',
                                  selectmode='browse')
        self._tree.heading('#0',    text='Field')
        self._tree.heading('type',  text='Type')
        self._tree.heading('value', text='Value')
        self._tree.heading('s',     text='')
        self._tree.column('#0',    width=165, minwidth=100)
        self._tree.column('type',  width=100, minwidth=70)
        self._tree.column('value', width=90,  minwidth=60)
        self._tree.column('s',     width=26,  minwidth=26, stretch=False, anchor='center')
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4,0), pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        for sk, (_, _, bg, _) in SAFETY.items():
            self._tree.tag_configure(sk, background=bg)
        self._tree.tag_configure('modified', font=('Segoe UI', 9, 'bold'))

    def _build_editor_panel(self, parent):
        info = ttk.LabelFrame(parent, text='Field Info')
        info.pack(fill=tk.X, padx=4, pady=(4,2))
        info.columnconfigure(1, weight=1)
        ttk.Label(info, text='Name:').grid(row=0, column=0, sticky='w', pady=1)
        self._i_name = ttk.Label(info, text='—', style='FieldName.TLabel')
        self._i_name.grid(row=0, column=1, sticky='w', padx=8)
        self._i_badge = ttk.Label(info, text='', font=('Segoe UI', 9, 'bold'))
        self._i_badge.grid(row=0, column=2, sticky='e', padx=8)
        ttk.Label(info, text='Type:').grid(row=1, column=0, sticky='w', pady=1)
        self._i_type = ttk.Label(info, text='—', style='Sub.TLabel')
        self._i_type.grid(row=1, column=1, sticky='w', padx=8, columnspan=2)
        ttk.Label(info, text='Note:').grid(row=2, column=0, sticky='nw', pady=(4,1))
        self._i_hint = ttk.Label(info, text='Open a file and select a field.',
                                  style='Hint.TLabel')
        self._i_hint.grid(row=2, column=1, sticky='w', padx=8, columnspan=2, pady=(4,1))

        self._ed_frame = ttk.LabelFrame(parent, text='Edit Value')
        self._ed_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2,4))
        ttk.Label(self._ed_frame, text='Select a field on the left to edit it.',
                  foreground='#aaa').pack(expand=True)

    def _build_status(self):
        self._status_var = tk.StringVar(value='Ready — open a .es3 file to begin.')
        ttk.Label(self, textvariable=self._status_var,
                  relief=tk.SUNKEN, anchor=tk.W, padding=(6,2)).pack(
            fill=tk.X, side=tk.BOTTOM)

    # ── Config helpers ─────────────────────────────────────────────────────
    def _saved_password(self, path: str) -> str | None:
        return self._cfg.get('files', {}).get(path, {}).get('password')

    def _remember_password(self, path: str, password: str):
        self._cfg.setdefault('files', {}).setdefault(path, {})['password'] = password
        self._cfg['last_file'] = path
        save_config(self._cfg)

    def _forget_password(self, path: str):
        self._cfg.get('files', {}).pop(path, None)
        save_config(self._cfg)

    def _clear_passwords(self):
        self._cfg['files'] = {}
        save_config(self._cfg)
        messagebox.showinfo('Cleared', 'All saved passwords have been removed.')

    # ── Welcome / startup ──────────────────────────────────────────────────
    def _show_welcome(self):
        """Show the recent-files dialog if any files are remembered."""
        files = self._cfg.get('files', {})
        if not files:
            return   # no saved files → clean state, do nothing

        dlg = WelcomeDialog(self, self._cfg)
        if dlg.result is None:
            return   # Start Fresh: nothing opened

        action, path = dlg.result
        if action == 'browse':
            self._open_file()
            return

        # action == 'open'
        saved_pw = self._saved_password(path)
        if saved_pw is not None:
            # Password remembered — open directly
            self._do_open(path, saved_pw, remember=True)
        else:
            # No saved password — ask for it
            dlg2 = PasswordDialog(self, path, saved_password=None)
            if dlg2.result is None:
                return
            pw, remember = dlg2.result
            self._do_open(path, pw, remember)

    # ── File operations ────────────────────────────────────────────────────
    def _open_file(self):
        path = filedialog.askopenfilename(
            title='Open ES3 Save File',
            filetypes=[('ES3 Files', '*.es3'), ('All Files', '*.*')],
        )
        if not path:
            return
        saved = self._saved_password(path)
        dlg   = PasswordDialog(self, path, saved_password=saved)
        if dlg.result is None:
            return
        password, remember = dlg.result
        self._do_open(path, password, remember)

    def _do_open(self, path: str, password: str, remember: bool):
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            self._salt     = raw[:16]
            self._password = password
            payload        = decrypt_aes_128_cbc(raw, password) if password else raw
            self._is_gzipped = payload[:2] == b'\x1f\x8b'
            if self._is_gzipped:
                payload = gzip.decompress(payload)
            text              = payload.decode('utf-8')
            self._entries     = extract_entries(text)
            self._all_entries = self._entries
            self._file_path   = path
            self._modified.clear()
            self._search_var.set('')
            self._safety_filter.set('all')
            self._refresh_tree()
            self._clear_editor()

            # Update config
            self._cfg['last_file'] = path
            if remember:
                self._remember_password(path, password)
            else:
                # Update last_file only, keep or remove password
                if not remember and self._saved_password(path):
                    self._forget_password(path)
                save_config(self._cfg)

            gz  = 'GZip + ' if self._is_gzipped else ''
            enc = 'AES-128' if password else 'unencrypted'
            n   = len(self._entries)
            self._file_lbl.config(text=os.path.basename(path), foreground='#222')
            self._unsaved_lbl.config(text='')
            self._set_status(f'Loaded {n} fields  ·  {gz}{enc}  ·  {path}')
            self._update_backup_label()

        except Exception as exc:
            messagebox.showerror('Open Error',
                f'Could not open or decrypt the file.\n'
                f'Double-check the password.\n\nDetail: {exc}')

    def _save_file(self):
        if not self._file_path or self._password is None:
            messagebox.showwarning('Nothing to save', 'Open a file first.')
            return
        self._do_save(self._file_path)

    def _save_as(self):
        if self._password is None:
            messagebox.showwarning('Nothing to save', 'Open a file first.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.es3',
            filetypes=[('ES3 Files', '*.es3'), ('All Files', '*.*')],
        )
        if path:
            self._do_save(path)

    def _do_save(self, path: str):
        bak = path + '.bak'
        if not os.path.exists(bak):
            try:
                shutil.copy2(path, bak)
                self._update_backup_label()
            except Exception as exc:
                if not messagebox.askyesno('Backup failed',
                        f'Could not create backup:\n{exc}\n\nSave anyway?'):
                    return
        try:
            text    = rebuild_file(self._all_entries)
            payload = text.encode('utf-8')
            if self._is_gzipped:
                payload = gzip.compress(payload)
            out = encrypt_aes_128_cbc(payload, self._password, self._salt) \
                  if self._password else payload
            with open(path, 'wb') as f:
                f.write(out)
            self._file_path = path
            self._modified.clear()
            self._unsaved_lbl.config(text='')
            self._refresh_tree()
            self._set_status(f'Saved  ·  {path}')
            messagebox.showinfo('Saved', 'File saved successfully!')
        except Exception as exc:
            messagebox.showerror('Save Error', f'Could not save file.\n\nDetail: {exc}')

    def _restore_backup(self):
        if not self._file_path:
            messagebox.showwarning('No file open', 'Open a file first.')
            return
        bak = self._file_path + '.bak'
        if not os.path.exists(bak):
            messagebox.showinfo('No backup', f'No backup found at:\n{bak}')
            return
        if messagebox.askyesno('Restore backup',
                f'Overwrite:\n  {self._file_path}\nwith backup:\n  {bak}\n\nProceed?'):
            try:
                shutil.copy2(bak, self._file_path)
                messagebox.showinfo('Restored', 'Backup restored. Re-open the file to reload it.')
            except Exception as exc:
                messagebox.showerror('Error', str(exc))
    # ── About ─────────────────────────────────────────────────────────────
    def _show_about(self):
            messagebox.showinfo(
                'About ES3 Editor',
                'ES3 Save Editor\n'
                f'Version {__version__}\n'
                'Author: Eduwilll100\n'
            )
        
    # ── Tree ───────────────────────────────────────────────────────────────
    def _refresh_tree(self):
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        ft  = self._search_var.get().lower()
        sf  = self._safety_filter.get()
        sf  = {'🟢 safe':'safe','🟡 caution':'caution','🔴 advanced':'advanced'}.get(sf, 'all')
        for e in self._all_entries:
            key    = e['key']
            safety = e.get('safety', 'advanced')
            if sf != 'all' and safety != sf: continue
            if ft and ft not in key.lower() and ft not in e.get('display_type','').lower():
                continue
            tags = [safety]
            if key in self._modified: tags.append('modified')
            self._tree.insert('', 'end', iid=key, text=key,
                               values=(e.get('display_type','?'),
                                       value_preview(e.get('value'), e.get('kind','')),
                                       SAFETY[safety][0]),
                               tags=tuple(tags))

    def _update_tree_row(self, entry):
        key = entry['key']
        if not self._tree.exists(key): return
        self._tree.set(key, 'value', value_preview(entry.get('value'), entry.get('kind','')))
        safety = entry.get('safety', 'advanced')
        self._tree.item(key, tags=(safety, 'modified'))

    # ── Editor ─────────────────────────────────────────────────────────────
    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel: return
        entry = next((e for e in self._all_entries if e['key'] == sel[0]), None)
        if entry: self._show_entry(entry)

    def _clear_editor(self):
        for w in self._ed_frame.winfo_children(): w.destroy()
        ttk.Label(self._ed_frame, text='Select a field on the left to edit it.',
                  foreground='#aaa').pack(expand=True)
        self._i_name.config(text='—'); self._i_type.config(text='—')
        self._i_badge.config(text='')
        self._i_hint.config(text='Open a file and select a field.')

    def _show_entry(self, entry):
        safety = entry.get('safety', 'advanced')
        icon, fg, _, desc = SAFETY[safety]
        self._i_name.config(text=entry['key'])
        self._i_type.config(text=entry.get('type_str', '?'))
        self._i_badge.config(text=f'{icon} {safety.capitalize()}', foreground=fg)
        self._i_hint.config(text=desc)
        for w in self._ed_frame.winfo_children(): w.destroy()
        kind, val = entry.get('kind','raw'), entry.get('value')
        if   kind == 'number'     and val is not None:             self._ed_number(entry)
        elif kind == 'bool'       and val is not None:             self._ed_bool(entry)
        elif kind == 'string':                                     self._ed_string(entry)
        elif kind == 'list_simple' and isinstance(val, list):     self._ed_list(entry)
        elif kind == 'datetime':                                   self._ed_datetime(entry)
        elif kind == 'custom_obj' and isinstance(
                (entry.get('parsed') or {}).get('value'), dict):  self._ed_object(entry)
        else:                                                      self._ed_raw(entry)

    # ── Number editor ──────────────────────────────────────────────────────
    def _ed_number(self, entry):
        f, val = self._ed_frame, entry['value']
        is_float = isinstance(val, float)
        ttk.Label(f, text=f'Original value:  {val}', style='Orig.TLabel').pack(
            anchor='w', padx=8, pady=(8,2))
        row = ttk.Frame(f); row.pack(pady=8)
        var = tk.StringVar(value=str(val))

        def step(d):
            try:
                cur = float(var.get()) if is_float else int(var.get())
                var.set(str(round(cur + d, 6) if is_float else cur + int(d)))
            except ValueError: pass

        ttk.Button(row, text='－', width=3, command=lambda: step(-0.1 if is_float else -1)).pack(side=tk.LEFT, padx=2)
        ttk.Entry(row, textvariable=var, width=18, justify='center',
                  font=('Consolas', 14)).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text='＋', width=3, command=lambda: step(0.1 if is_float else 1)).pack(side=tk.LEFT, padx=2)
        ttk.Label(f, text=f'Enter a {"float" if is_float else "integer"} value.',
                  style='Hint.TLabel').pack(anchor='w', padx=8)

        def apply():
            try:
                entry['value'] = float(var.get()) if is_float else int(var.get())
                entry['raw_block'] = rebuild_raw_block(entry)
                self._commit(entry)
            except ValueError as exc: messagebox.showerror('Invalid value', str(exc))

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton', command=apply).pack(pady=12)

    # ── Bool editor ────────────────────────────────────────────────────────
    def _ed_bool(self, entry):
        f, val = self._ed_frame, entry['value']
        ttk.Label(f, text=f'Original value:  {val}', style='Orig.TLabel').pack(
            anchor='w', padx=8, pady=(8,2))
        var = tk.BooleanVar(value=bool(val))
        rf  = ttk.Frame(f); rf.pack(pady=10, padx=20, anchor='w')
        ttk.Radiobutton(rf, text='✓  True',  variable=var, value=True ).pack(anchor='w', pady=3)
        ttk.Radiobutton(rf, text='✗  False', variable=var, value=False).pack(anchor='w', pady=3)

        def apply():
            entry['value'] = var.get(); entry['raw_block'] = rebuild_raw_block(entry)
            self._commit(entry)

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton', command=apply).pack(pady=12)

    # ── String editor ──────────────────────────────────────────────────────
    def _ed_string(self, entry):
        f, val = self._ed_frame, str(entry['value'] or '')
        ttk.Label(f, text=f'Original value:  {repr(val)}', style='Orig.TLabel').pack(
            anchor='w', padx=8, pady=(8,2))
        var = tk.StringVar(value=val)
        ttk.Entry(f, textvariable=var, font=('Consolas', 11)).pack(fill=tk.X, padx=8, pady=4)

        def apply():
            entry['value'] = var.get(); entry['raw_block'] = rebuild_raw_block(entry)
            self._commit(entry)

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton', command=apply).pack(pady=12)

    # ── List editor ────────────────────────────────────────────────────────
    def _ed_list(self, entry):
        f, val = self._ed_frame, list(entry['value'])
        sample   = val[0] if val else 0
        is_bool  = isinstance(sample, bool)
        is_float = isinstance(sample, float)
        ttk.Label(f, text=f'{len(val)} item(s)  ·  {entry.get("display_type","")}',
                  style='Sub.TLabel').pack(anchor='w', padx=8, pady=(8,0))
        ttk.Label(f, text='Edit as comma-separated values:', style='Hint.TLabel').pack(
            anchor='w', padx=8, pady=(2,4))
        var = tk.StringVar(value=', '.join(
            ('true' if v else 'false') if isinstance(v, bool) else str(v) for v in val))
        ttk.Entry(f, textvariable=var, font=('Consolas', 10)).pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(f, text='Tip: add or remove items by editing the list above.',
                  style='Hint.TLabel').pack(anchor='w', padx=8)

        def apply():
            try:
                raw = [x.strip() for x in var.get().split(',') if x.strip()]
                if is_bool:        nv = [v.lower() in ('true','1','yes') for v in raw]
                elif is_float:     nv = [float(v) for v in raw]
                else:
                    try:           nv = [int(v) for v in raw]
                    except ValueError: nv = raw
                entry['value'] = nv; entry['raw_block'] = rebuild_raw_block(entry)
                self._commit(entry)
            except Exception as exc: messagebox.showerror('Invalid value', str(exc))

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton', command=apply).pack(pady=12)

    # ── DateTime view ──────────────────────────────────────────────────────
    def _ed_datetime(self, entry):
        f, val = self._ed_frame, entry.get('value')
        ttk.Label(f, text='DateTime (read-only)', style='Sub.TLabel').pack(
            anchor='w', padx=8, pady=(12,4))
        disp = ticks_to_str(val['ticks']) if isinstance(val, dict) and 'ticks' in val else str(val)
        ttk.Label(f, text=disp, font=('Consolas', 11)).pack(anchor='w', padx=12)
        ttk.Label(f, text='⚠  Editing DateTime values manually may corrupt the save.',
                  style='Warn.TLabel').pack(anchor='w', padx=8, pady=8)

    # ── Object inspector ───────────────────────────────────────────────────
    def _ed_object(self, entry):
        f       = self._ed_frame
        val_obj = entry['parsed']['value']
        ttk.Label(f, text='Object fields:', style='Hint.TLabel').pack(
            anchor='w', padx=8, pady=(8,4))
        canvas = tk.Canvas(f, highlightthickness=0)
        vsb    = ttk.Scrollbar(f, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,4))
        canvas.pack(fill=tk.BOTH, expand=True, padx=(8,0))
        table = ttk.Frame(canvas)
        canvas.create_window((0,0), window=table, anchor='nw')
        table.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        vars_map = {}
        for row_idx, (k, v) in enumerate(val_obj.items()):
            if k == '__type': continue
            ttk.Label(table, text=k, width=24, anchor='w',
                      font=('Consolas', 9)).grid(row=row_idx, column=0, sticky='w', padx=4, pady=1)
            if isinstance(v, bool):
                var = tk.BooleanVar(value=v)
                ttk.Checkbutton(table, variable=var).grid(row=row_idx, column=1, sticky='w')
                vars_map[k] = ('bool', var)
            elif isinstance(v, (int, float)):
                var = tk.StringVar(value=str(v))
                ttk.Entry(table, textvariable=var, width=16,
                          font=('Consolas', 9)).grid(row=row_idx, column=1, sticky='w', padx=4, pady=1)
                vars_map[k] = ('num', var, isinstance(v, float))
            else:
                lbl = json.dumps(v) if not isinstance(v, str) else repr(v)
                ttk.Label(table, text=lbl[:48], foreground='#888',
                          font=('Consolas', 8)).grid(row=row_idx, column=1, sticky='w', padx=4)

        def apply():
            nv = dict(val_obj)
            try:
                for fname, info in vars_map.items():
                    if   info[0] == 'bool': nv[fname] = info[1].get()
                    elif info[0] == 'num':  nv[fname] = float(info[1].get()) if info[2] else int(info[1].get())
                entry['parsed']['value'] = nv; entry['value'] = nv
                ts = entry['type_str']
                inner = json.dumps(nv, indent=3, ensure_ascii=False)
                entry['raw_block'] = (f'{{\n\t\t"__type" : {json.dumps(ts)},'
                                      f'\n\t\t"value" : {inner}\n\t}}')
                self._commit(entry)
            except Exception as exc: messagebox.showerror('Invalid value', str(exc))

        ttk.Button(f, text='✔  Apply All Changes', style='Apply.TButton', command=apply).pack(pady=8)

    # ── Raw editor ─────────────────────────────────────────────────────────
    def _ed_raw(self, entry):
        f = self._ed_frame
        ttk.Label(f, text='Raw ES3 block (advanced):', style='Sub.TLabel').pack(
            anchor='w', padx=8, pady=(8,2))
        ttk.Label(f, text='⚠  Non-standard types — edit carefully.',
                  style='Warn.TLabel').pack(anchor='w', padx=8, pady=(0,4))
        tf  = ttk.Frame(f); tf.pack(fill=tk.BOTH, expand=True, padx=8)
        txt = tk.Text(tf, wrap=tk.NONE, font=('Consolas', 9), undo=True)
        vsb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=txt.yview)
        hsb = ttk.Scrollbar(f, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y); txt.pack(fill=tk.BOTH, expand=True)
        hsb.pack(fill=tk.X, padx=8)
        txt.insert('1.0', entry['raw_block'])

        def apply():
            nb = txt.get('1.0', tk.END).rstrip('\n')
            entry['raw_block'] = nb
            re_a = _annotate_entry(entry['key'], nb)
            entry.update(parsed=re_a['parsed'], value=re_a['value'],
                         display_type=re_a['display_type'], kind=re_a['kind'],
                         safety=re_a['safety'])
            self._commit(entry)

        ttk.Button(f, text='✔  Apply Raw Edit', style='Apply.TButton', command=apply).pack(pady=6)

    # ── Commit ──────────────────────────────────────────────────────────────
    def _commit(self, entry):
        key = entry['key']
        self._modified.add(key)
        self._unsaved_lbl.config(text='● Unsaved changes')
        self._update_tree_row(entry)
        self._set_status(
            f'Changed: {key}  →  {value_preview(entry.get("value"), entry.get("kind",""))}')

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _update_backup_label(self):
        if self._file_path:
            bak = self._file_path + '.bak'
            if os.path.exists(bak):
                mt = datetime.fromtimestamp(os.path.getmtime(bak))
                self._backup_lbl.config(text=f'💾 Backup: {mt.strftime("%H:%M:%S")}')
            else:
                self._backup_lbl.config(text='No backup yet')

    def _set_status(self, msg: str):
        self._status_var.set(msg)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = ES3Editor()
    app.mainloop()
