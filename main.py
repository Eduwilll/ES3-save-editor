#!/usr/bin/env python3
"""
ES3 Save Editor
A desktop editor for Easy Save 3 (ES3) Unity save files.
Supports AES-128-CBC + optional GZip compression.
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
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
#  ES3 type system
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
    """
    Returns (kind, safety_key, display_type)
    kind is one of: number, bool, string, list_simple, list_complex,
                    dict, datetime, custom_obj, raw
    """
    t = type_str.strip()
    tl = t.lower()

    if tl in SIMPLE_NUM_TYPES:
        return 'number', 'safe', t
    if tl in BOOL_TYPES:
        return 'bool', 'safe', t
    if tl in STR_TYPES:
        return 'string', 'safe', t

    if 'list' in tl:
        m = re.search(r'\[\[?(?:[^\]]*\.)*(\w+),', t)
        inner = m.group(1) if m else '?'
        safe_inners = {'Int32', 'Int64', 'Single', 'Double', 'Boolean', 'String'}
        if inner in safe_inners:
            return 'list_simple', 'safe', f'List<{inner}>'
        return 'list_complex', 'caution', f'List<{inner}>'

    if 'dictionary' in tl:
        return 'dict', 'caution', 'Dictionary'

    if 'datetime' in tl:
        return 'datetime', 'caution', 'DateTime'

    if t.startswith('System.'):
        short = t.split('.')[-1].split(',')[0].split('`')[0]
        return 'system', 'caution', short

    if ',' in t:                             # Unity/Hotfix custom type
        short = t.split(',')[0].split('.')[-1]
        return 'custom_obj', 'advanced', short

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
#  ES3 file parser (bracket-counting, handles non-standard JSON keys)
# ─────────────────────────────────────────────────────────────────────────────

def _read_quoted_string(text, i):
    """Read past the closing quote (i points to the opening quote). Returns (string, new_i)."""
    i += 1  # skip opening "
    start = i
    while i < len(text) and text[i] != '"':
        if text[i] == '\\':
            i += 1
        i += 1
    return text[start:i], i + 1   # skip closing "


def _skip_balanced(text, i):
    """i points to '{' or '['. Returns index just after the matching closer."""
    opener = text[i]
    closer = '}' if opener == '{' else ']'
    depth = 0
    in_str = False
    while i < len(text):
        c = text[i]
        if in_str:
            if c == '\\':
                i += 1
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return i


def extract_entries(text: str) -> list:
    """
    Parse the outer ES3 object into a list of entry dicts:
      {key, raw_block, parsed, type_str, display_type, kind, safety, value}
    """
    entries = []
    i = text.index('{') + 1   # skip the outermost '{'
    n = len(text)

    while i < n:
        # skip whitespace and commas
        while i < n and text[i] in ' \t\r\n,':
            i += 1
        if i >= n or text[i] == '}':
            break

        if text[i] != '"':
            i += 1
            continue

        key, i = _read_quoted_string(text, i)

        # skip whitespace + ':'
        while i < n and text[i] in ' \t\r\n:':
            i += 1

        if i >= n or text[i] != '{':
            continue

        block_start = i
        i = _skip_balanced(text, i)
        raw_block = text[block_start:i]

        entry = _annotate_entry(key, raw_block)
        entries.append(entry)

    return entries


def _try_parse_block(raw_block: str):
    """Try json.loads after quoting bare-integer keys. Returns dict or None."""
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
    """Build a full entry dict from key + raw_block."""
    parsed = _try_parse_block(raw_block)
    entry = {'key': key, 'raw_block': raw_block, 'parsed': parsed}

    if parsed and isinstance(parsed, dict) and '__type' in parsed:
        type_str = parsed['__type']
        kind, safety, display_type = classify(type_str)
        entry.update(
            type_str=type_str,
            display_type=display_type,
            kind=kind,
            safety=safety,
            value=parsed.get('value'),
        )
    else:
        entry.update(
            type_str='?',
            display_type='Unknown',
            kind='raw',
            safety='advanced',
            value=None,
        )
    return entry


# ─────────────────────────────────────────────────────────────────────────────
#  ES3 file serialiser
# ─────────────────────────────────────────────────────────────────────────────

def rebuild_file(entries: list) -> str:
    """Reconstruct the complete ES3 file text from a list of entry dicts."""
    parts = ['{\n']
    for idx, e in enumerate(entries):
        comma = ',' if idx < len(entries) - 1 else ''
        parts.append(f'\t"{e["key"]}" : {e["raw_block"]}{comma}\n')
    parts.append('}')
    return ''.join(parts)


def rebuild_raw_block(entry: dict) -> str:
    """Regenerate the raw_block text for a modified simple entry."""
    kind     = entry['kind']
    type_str = entry['type_str']
    val      = entry['value']

    t_json = json.dumps(type_str)

    if kind in ('number', 'bool', 'string'):
        v_json = json.dumps(val)
        return f'{{\n\t\t"__type" : {t_json},\n\t\t"value" : {v_json}\n\t}}'

    if kind == 'list_simple':
        # Write as compact single-line array (matches original style)
        items = ', '.join(
            ('true' if v else 'false') if isinstance(v, bool) else str(v)
            for v in val
        )
        return f'{{\n\t\t"__type" : {t_json},\n\t\t"value" : [{items}]\n\t}}'

    # Fallback: let json handle it (may not be perfectly round-trippable for
    # dict/object entries, but those use the raw editor anyway)
    return json.dumps({'__type': type_str, 'value': val}, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers for .NET DateTime
# ─────────────────────────────────────────────────────────────────────────────

_EPOCH_TICKS = 621_355_968_000_000_000   # ticks between 0001-01-01 and 1970-01-01

def ticks_to_datetime(ticks: int) -> str:
    try:
        secs = (ticks - _EPOCH_TICKS) / 10_000_000
        dt = datetime.utcfromtimestamp(secs)
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
        self._password: str | None  = None
        self._salt: bytes | None    = None
        self._is_gzipped: bool      = False
        self._entries: list         = []
        self._modified: set         = set()
        self._all_entries: list     = []   # unfiltered reference

        self._build_ui()
        self._apply_theme()

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
        s.configure('Sub.TLabel', font=('Segoe UI', 8), foreground='#666')
        s.configure('Orig.TLabel', font=('Consolas', 9), foreground='#888')
        s.configure('Warn.TLabel', font=('Segoe UI', 8), foreground='#c0392b')
        s.configure('Hint.TLabel', font=('Segoe UI', 8), foreground='#666',
                    wraplength=420)
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
        fm.add_command(label='Open…',        accelerator='Ctrl+O', command=self._open_file)
        fm.add_command(label='Save',          accelerator='Ctrl+S', command=self._save_file)
        fm.add_command(label='Save As…',      command=self._save_as)
        fm.add_separator()
        fm.add_command(label='Restore Backup…', command=self._restore_backup)
        fm.add_separator()
        fm.add_command(label='Exit', command=self.quit)

        self.bind('<Control-o>', lambda _: self._open_file())
        self.bind('<Control-s>', lambda _: self._save_file())

    def _build_toolbar(self):
        bar = ttk.Frame(self, style='Toolbar.TFrame')
        bar.pack(fill=tk.X)

        ttk.Button(bar, text='📂 Open',  command=self._open_file).pack(side=tk.LEFT, padx=6, pady=4)
        ttk.Button(bar, text='💾 Save',  command=self._save_file).pack(side=tk.LEFT, padx=(0, 6), pady=4)
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

    # ── Left: field list ───────────────────────────────────────────────────
    def _build_field_list(self, parent):
        # Search + filter row
        top = ttk.Frame(parent)
        top.pack(fill=tk.X, padx=4, pady=(4, 2))

        ttk.Label(top, text='🔍').pack(side=tk.LEFT)
        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', lambda *_: self._refresh_tree())
        ttk.Entry(top, textvariable=self._search_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # Safety filter
        self._safety_filter = tk.StringVar(value='all')
        sf = ttk.Combobox(top, textvariable=self._safety_filter,
                          values=['all', '🟢 safe', '🟡 caution', '🔴 advanced'],
                          state='readonly', width=12)
        sf.pack(side=tk.LEFT)
        sf.bind('<<ComboboxSelected>>', lambda _: self._refresh_tree())

        # Treeview
        cols = ('type', 'value', 's')
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

        self._tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0), pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)

        self._tree.bind('<<TreeviewSelect>>', self._on_select)

        # Tag colours for safety levels
        for sk, (icon, fg, bg, _) in SAFETY.items():
            self._tree.tag_configure(sk, background=bg)
        self._tree.tag_configure('modified', font=('Segoe UI', 9, 'bold'))

    # ── Right: editor panel ────────────────────────────────────────────────
    def _build_editor_panel(self, parent):
        # ── Info header ──────────────────────────────
        info = ttk.LabelFrame(parent, text='Field Info')
        info.pack(fill=tk.X, padx=4, pady=(4, 2))
        info.columnconfigure(1, weight=1)

        ttk.Label(info, text='Name:').grid(row=0, column=0, sticky='w', pady=1)
        self._i_name = ttk.Label(info, text='—', style='FieldName.TLabel')
        self._i_name.grid(row=0, column=1, sticky='w', padx=8)

        self._i_badge = ttk.Label(info, text='', font=('Segoe UI', 9, 'bold'))
        self._i_badge.grid(row=0, column=2, sticky='e', padx=8)

        ttk.Label(info, text='Type:').grid(row=1, column=0, sticky='w', pady=1)
        self._i_type = ttk.Label(info, text='—', style='Sub.TLabel')
        self._i_type.grid(row=1, column=1, sticky='w', padx=8, columnspan=2)

        ttk.Label(info, text='Note:').grid(row=2, column=0, sticky='nw', pady=(4, 1))
        self._i_hint = ttk.Label(info, text='Open a file and select a field.',
                                  style='Hint.TLabel')
        self._i_hint.grid(row=2, column=1, sticky='w', padx=8, columnspan=2, pady=(4, 1))

        # ── Dynamic editor area ───────────────────────
        self._ed_frame = ttk.LabelFrame(parent, text='Edit Value')
        self._ed_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))

        ttk.Label(self._ed_frame, text='Select a field on the left to edit it.',
                  foreground='#aaa').pack(expand=True)

    # ── Status bar ─────────────────────────────────────────────────────────
    def _build_status(self):
        self._status_var = tk.StringVar(value='Ready — open a .es3 file to begin.')
        ttk.Label(self, textvariable=self._status_var,
                  relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)).pack(
            fill=tk.X, side=tk.BOTTOM)

    # ── File operations ────────────────────────────────────────────────────
    def _open_file(self):
        path = filedialog.askopenfilename(
            title='Open ES3 Save File',
            filetypes=[('ES3 Files', '*.es3'), ('All Files', '*.*')],
        )
        if not path:
            return

        password = simpledialog.askstring(
            'Decryption Password',
            'Enter the file encryption password.\n'
            'Leave blank if the file is NOT encrypted.',
            show='*',
        )
        if password is None:
            return

        try:
            with open(path, 'rb') as f:
                raw = f.read()

            self._salt     = raw[:16]
            self._password = password
            payload        = decrypt_aes_128_cbc(raw, password) if password else raw

            self._is_gzipped = payload[:2] == b'\x1f\x8b'
            if self._is_gzipped:
                payload = gzip.decompress(payload)

            text           = payload.decode('utf-8')
            self._entries  = extract_entries(text)
            self._all_entries = self._entries   # keep reference for filtering

            self._file_path = path
            self._modified.clear()
            self._search_var.set('')
            self._safety_filter.set('all')
            self._refresh_tree()
            self._clear_editor()

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

    def _do_save(self, path):
        # Auto-backup on FIRST save (once per file session)
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
            # Refresh badges in tree (no longer bold)
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
                f'This will overwrite:\n  {self._file_path}\nwith:\n  {bak}\n\nProceed?'):
            try:
                shutil.copy2(bak, self._file_path)
                messagebox.showinfo('Restored', 'Backup restored. Re-open the file to reload it.')
            except Exception as exc:
                messagebox.showerror('Error', str(exc))

    # ── Tree helpers ───────────────────────────────────────────────────────
    def _refresh_tree(self):
        for iid in self._tree.get_children():
            self._tree.delete(iid)

        ft = self._search_var.get().lower()
        sf = self._safety_filter.get()
        if sf.startswith('🟢'):
            sf = 'safe'
        elif sf.startswith('🟡'):
            sf = 'caution'
        elif sf.startswith('🔴'):
            sf = 'advanced'
        else:
            sf = 'all'

        for e in self._all_entries:
            key    = e['key']
            safety = e.get('safety', 'advanced')

            if sf != 'all' and safety != sf:
                continue
            if ft and ft not in key.lower() and ft not in e.get('display_type', '').lower():
                continue

            icon   = SAFETY[safety][0]
            prev   = value_preview(e.get('value'), e.get('kind', ''))
            tags   = [safety]
            if key in self._modified:
                tags.append('modified')

            self._tree.insert('', 'end', iid=key, text=key,
                               values=(e.get('display_type', '?'), prev, icon),
                               tags=tuple(tags))

    def _update_tree_row(self, entry):
        key = entry['key']
        if not self._tree.exists(key):
            return
        prev = value_preview(entry.get('value'), entry.get('kind', ''))
        self._tree.set(key, 'value', prev)
        safety = entry.get('safety', 'advanced')
        tags = [safety, 'modified']
        self._tree.item(key, tags=tuple(tags))

    # ── Editor panel ───────────────────────────────────────────────────────
    def _on_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        key   = sel[0]
        entry = next((e for e in self._all_entries if e['key'] == key), None)
        if entry:
            self._show_entry(entry)

    def _clear_editor(self):
        for w in self._ed_frame.winfo_children():
            w.destroy()
        ttk.Label(self._ed_frame,
                  text='Select a field on the left to edit it.',
                  foreground='#aaa').pack(expand=True)
        self._i_name.config(text='—')
        self._i_type.config(text='—')
        self._i_badge.config(text='')
        self._i_hint.config(text='Open a file and select a field.')

    def _show_entry(self, entry):
        key    = entry['key']
        kind   = entry.get('kind', 'raw')
        safety = entry.get('safety', 'advanced')
        icon, fg, bg, desc = SAFETY[safety]

        # Info header
        self._i_name.config(text=key)
        self._i_type.config(text=entry.get('type_str', '?'))
        self._i_badge.config(text=f'{icon} {safety.capitalize()}', foreground=fg)
        self._i_hint.config(text=desc)

        # Clear editor
        for w in self._ed_frame.winfo_children():
            w.destroy()

        val = entry.get('value')

        # Pick the right editor widget
        if kind == 'number' and val is not None:
            self._ed_number(entry)
        elif kind == 'bool' and val is not None:
            self._ed_bool(entry)
        elif kind == 'string':
            self._ed_string(entry)
        elif kind == 'list_simple' and isinstance(val, list):
            self._ed_list(entry)
        elif kind == 'datetime':
            self._ed_datetime(entry)
        elif kind == 'custom_obj' and entry.get('parsed') and isinstance(entry['parsed'].get('value'), dict):
            self._ed_object(entry)
        else:
            self._ed_raw(entry)

    # ── Number editor ──────────────────────────────────────────────────────
    def _ed_number(self, entry):
        f   = self._ed_frame
        val = entry['value']
        is_float = isinstance(val, float)

        orig_lbl = ttk.Label(f, text=f'Original value:  {val}', style='Orig.TLabel')
        orig_lbl.pack(anchor='w', padx=8, pady=(8, 2))

        row = ttk.Frame(f)
        row.pack(pady=8)

        var = tk.StringVar(value=str(val))
        entry_w = ttk.Entry(row, textvariable=var, width=18,
                             justify='center', font=('Consolas', 14))

        def step(delta):
            try:
                cur = float(var.get()) if is_float else int(var.get())
                var.set(str(round(cur + delta, 6) if is_float else cur + int(delta)))
            except ValueError:
                pass

        ttk.Button(row, text='－', width=3, command=lambda: step(-1 if not is_float else -0.1)).pack(side=tk.LEFT, padx=2)
        entry_w.pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text='＋', width=3, command=lambda: step(1 if not is_float else 0.1)).pack(side=tk.LEFT, padx=2)

        type_hint = 'float' if is_float else 'integer'
        ttk.Label(f, text=f'Enter a {type_hint} value, then click Apply.',
                  style='Hint.TLabel').pack(anchor='w', padx=8)

        def apply():
            try:
                new = float(var.get()) if is_float else int(var.get())
                entry['value'] = new
                entry['raw_block'] = rebuild_raw_block(entry)
                self._commit(entry)
            except ValueError as exc:
                messagebox.showerror('Invalid value', str(exc))

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton',
                   command=apply).pack(pady=12)

    # ── Bool editor ────────────────────────────────────────────────────────
    def _ed_bool(self, entry):
        f   = self._ed_frame
        val = entry['value']

        ttk.Label(f, text=f'Original value:  {val}', style='Orig.TLabel').pack(
            anchor='w', padx=8, pady=(8, 2))

        var = tk.BooleanVar(value=bool(val))
        rf  = ttk.Frame(f)
        rf.pack(pady=10, padx=20, anchor='w')
        ttk.Radiobutton(rf, text='✓  True',  variable=var, value=True ).pack(anchor='w', pady=3)
        ttk.Radiobutton(rf, text='✗  False', variable=var, value=False).pack(anchor='w', pady=3)

        def apply():
            entry['value'] = var.get()
            entry['raw_block'] = rebuild_raw_block(entry)
            self._commit(entry)

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton',
                   command=apply).pack(pady=12)

    # ── String editor ──────────────────────────────────────────────────────
    def _ed_string(self, entry):
        f   = self._ed_frame
        val = str(entry['value']) if entry['value'] is not None else ''

        ttk.Label(f, text=f'Original value:  {repr(val)}', style='Orig.TLabel').pack(
            anchor='w', padx=8, pady=(8, 2))

        var = tk.StringVar(value=val)
        ttk.Entry(f, textvariable=var, font=('Consolas', 11)).pack(
            fill=tk.X, padx=8, pady=4)

        def apply():
            entry['value'] = var.get()
            entry['raw_block'] = rebuild_raw_block(entry)
            self._commit(entry)

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton',
                   command=apply).pack(pady=12)

    # ── List editor ────────────────────────────────────────────────────────
    def _ed_list(self, entry):
        f    = self._ed_frame
        val  = list(entry['value'])
        kind = entry.get('kind', 'list_simple')

        sample = val[0] if val else 0
        is_bool  = isinstance(sample, bool)
        is_float = isinstance(sample, float)

        ttk.Label(f, text=f'{len(val)} item(s)  ·  {entry.get("display_type", "")}',
                  style='Sub.TLabel').pack(anchor='w', padx=8, pady=(8, 0))
        ttk.Label(f, text='Edit as comma-separated values:', style='Hint.TLabel').pack(
            anchor='w', padx=8, pady=(2, 4))

        var = tk.StringVar(value=', '.join(
            ('true' if v else 'false') if isinstance(v, bool) else str(v)
            for v in val
        ))
        ttk.Entry(f, textvariable=var, font=('Consolas', 10)).pack(
            fill=tk.X, padx=8, pady=2)

        ttk.Label(f, text='Tip: add or remove items by editing the list above.',
                  style='Hint.TLabel').pack(anchor='w', padx=8)

        def apply():
            try:
                raw = [x.strip() for x in var.get().split(',') if x.strip()]
                if is_bool:
                    new_val = [v.lower() in ('true', '1', 'yes') for v in raw]
                elif is_float:
                    new_val = [float(v) for v in raw]
                else:
                    try:
                        new_val = [int(v) for v in raw]
                    except ValueError:
                        new_val = raw
                entry['value'] = new_val
                entry['raw_block'] = rebuild_raw_block(entry)
                self._commit(entry)
            except Exception as exc:
                messagebox.showerror('Invalid value', str(exc))

        ttk.Button(f, text='✔  Apply Change', style='Apply.TButton',
                   command=apply).pack(pady=12)

    # ── DateTime viewer ────────────────────────────────────────────────────
    def _ed_datetime(self, entry):
        f   = self._ed_frame
        val = entry.get('value')

        display = '—'
        if isinstance(val, dict) and 'ticks' in val:
            display = ticks_to_datetime(val['ticks'])
        elif val is not None:
            display = str(val)

        ttk.Label(f, text='DateTime (read-only)', style='Sub.TLabel').pack(
            anchor='w', padx=8, pady=(12, 4))
        ttk.Label(f, text=display, font=('Consolas', 11)).pack(anchor='w', padx=12)
        ttk.Label(f, text='⚠  Editing DateTime values manually may corrupt the save.',
                  style='Warn.TLabel').pack(anchor='w', padx=8, pady=8)

    # ── Object inspector (nested key-value) ────────────────────────────────
    def _ed_object(self, entry):
        """Show nested fields of a custom object as a compact key=value table."""
        f       = self._ed_frame
        val_obj = entry['parsed']['value']   # dict

        ttk.Label(f, text='Object fields (edit directly in the table):',
                  style='Hint.TLabel').pack(anchor='w', padx=8, pady=(8, 4))

        # Scrollable canvas for the table
        canvas = tk.Canvas(f, highlightthickness=0)
        vsb    = ttk.Scrollbar(f, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4))
        canvas.pack(fill=tk.BOTH, expand=True, padx=(8, 0))

        table = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=table, anchor='nw')
        table.bind('<Configure>', lambda e: canvas.configure(
            scrollregion=canvas.bbox('all')))

        vars_map = {}   # field_name -> tkVar

        for row_idx, (k, v) in enumerate(val_obj.items()):
            if k == '__type':
                continue
            is_safe = isinstance(v, (int, float, bool)) and not isinstance(v, str)
            # Allow editing simple scalar values inside objects too
            ttk.Label(table, text=k, width=22, anchor='w',
                      font=('Consolas', 9)).grid(row=row_idx, column=0, sticky='w', padx=4, pady=1)

            if isinstance(v, bool):
                var = tk.BooleanVar(value=v)
                cb  = ttk.Checkbutton(table, variable=var)
                cb.grid(row=row_idx, column=1, sticky='w')
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
            new_val = dict(val_obj)  # copy
            try:
                for fname, info in vars_map.items():
                    if info[0] == 'bool':
                        new_val[fname] = info[1].get()
                    elif info[0] == 'num':
                        raw = info[1].get()
                        new_val[fname] = float(raw) if info[2] else int(raw)
                # Rebuild raw block via the outer parsed structure
                entry['parsed']['value'] = new_val
                entry['value'] = new_val
                # Rebuild using json (the value dict is standard JSON here)
                type_str = entry['type_str']
                inner_json = json.dumps(new_val, indent=3, ensure_ascii=False)
                entry['raw_block'] = (
                    f'{{\n\t\t"__type" : {json.dumps(type_str)},'
                    f'\n\t\t"value" : {inner_json}\n\t}}'
                )
                self._commit(entry)
            except Exception as exc:
                messagebox.showerror('Invalid value', str(exc))

        ttk.Button(f, text='✔  Apply All Changes', style='Apply.TButton',
                   command=apply).pack(pady=8)

    # ── Raw text editor ────────────────────────────────────────────────────
    def _ed_raw(self, entry):
        f = self._ed_frame

        ttk.Label(f, text='Raw ES3 block  (advanced editing):',
                  style='Sub.TLabel').pack(anchor='w', padx=8, pady=(8, 2))
        ttk.Label(f,
                  text='⚠  This field uses non-standard types. Edit the raw text carefully.',
                  style='Warn.TLabel').pack(anchor='w', padx=8, pady=(0, 4))

        txt_frame = ttk.Frame(f)
        txt_frame.pack(fill=tk.BOTH, expand=True, padx=8)

        txt = tk.Text(txt_frame, wrap=tk.NONE, font=('Consolas', 9), undo=True)
        vsb = ttk.Scrollbar(txt_frame, orient=tk.VERTICAL, command=txt.yview)
        hsb = ttk.Scrollbar(f, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(fill=tk.BOTH, expand=True)
        hsb.pack(fill=tk.X, padx=8)

        txt.insert('1.0', entry['raw_block'])

        def apply():
            new_block = txt.get('1.0', tk.END).rstrip('\n')
            entry['raw_block'] = new_block
            # Try to re-annotate value/preview
            re_annotated = _annotate_entry(entry['key'], new_block)
            entry.update(
                parsed      = re_annotated['parsed'],
                value       = re_annotated['value'],
                display_type= re_annotated['display_type'],
                kind        = re_annotated['kind'],
                safety      = re_annotated['safety'],
            )
            self._commit(entry)

        ttk.Button(f, text='✔  Apply Raw Edit', style='Apply.TButton',
                   command=apply).pack(pady=6)

    # ── Commit a change ────────────────────────────────────────────────────
    def _commit(self, entry):
        key = entry['key']
        self._modified.add(key)
        self._unsaved_lbl.config(text='● Unsaved changes')
        self._update_tree_row(entry)
        self._set_status(
            f'Changed: {key}  →  {value_preview(entry.get("value"), entry.get("kind", ""))}'
        )

    # ── Misc helpers ───────────────────────────────────────────────────────
    def _update_backup_label(self):
        if self._file_path:
            bak = self._file_path + '.bak'
            if os.path.exists(bak):
                mtime = datetime.fromtimestamp(os.path.getmtime(bak))
                self._backup_lbl.config(
                    text=f'💾 Backup: {mtime.strftime("%H:%M:%S")}')
            else:
                self._backup_lbl.config(text='No backup yet')

    def _set_status(self, msg: str):
        self._status_var.set(msg)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app = ES3Editor()
    app.mainloop()
