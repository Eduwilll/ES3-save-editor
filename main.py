import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import os
import sys
import gzip

try:
    from es3_modifier.main import decrypt_aes_128_cbc, encrypt_aes_128_cbc
except ImportError:
    messagebox.showerror("Error", "es3-modifier library not found. Please install it using 'pip install es3-modifier'")
    sys.exit(1)


class ES3EditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Easy Save 3 (ES3) Save Editor")
        self.root.geometry("900x650")

        self.current_file_path = None
        self.current_password = None
        self.current_salt = None
        self.is_gzipped = False

        self._setup_ui()

    def _setup_ui(self):
        # Menu Bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As...", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-s>", lambda e: self.save_file())

        # Main Frame
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Text Editor with line numbers using a frame
        editor_frame = tk.Frame(main_frame)
        editor_frame.pack(fill=tk.BOTH, expand=True)

        self.line_numbers = tk.Text(
            editor_frame,
            width=5,
            padx=4,
            state=tk.DISABLED,
            bg="#f0f0f0",
            fg="#888888",
            font=("Consolas", 10),
            wrap=tk.NONE,
            relief=tk.FLAT,
            takefocus=0,
        )
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        self.text_editor = tk.Text(
            editor_frame,
            wrap=tk.NONE,
            font=("Consolas", 10),
            undo=True,
            autoseparators=True,
        )

        v_scroll = tk.Scrollbar(editor_frame, orient=tk.VERTICAL)
        h_scroll = tk.Scrollbar(main_frame, orient=tk.HORIZONTAL, command=self.text_editor.xview)

        v_scroll.config(command=self._on_vscroll)
        self.text_editor.config(
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
        )
        self.line_numbers.config(yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.text_editor.bind("<KeyRelease>", self._update_line_numbers)
        self.text_editor.bind("<MouseWheel>", self._update_line_numbers)

        # Status Bar
        self.status_var = tk.StringVar(value="Ready. Use File → Open to load an .es3 file.")
        status_bar = tk.Label(
            self.root, textvariable=self.status_var,
            bd=1, relief=tk.SUNKEN, anchor=tk.W, padx=4
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _on_vscroll(self, *args):
        self.text_editor.yview(*args)
        self.line_numbers.yview(*args)

    def _update_line_numbers(self, event=None):
        self.line_numbers.config(state=tk.NORMAL)
        self.line_numbers.delete(1.0, tk.END)
        lines = self.text_editor.get(1.0, tk.END).count("\n")
        self.line_numbers.insert(tk.END, "\n".join(str(i) for i in range(1, lines + 1)))
        self.line_numbers.config(state=tk.DISABLED)

    def open_file(self):
        file_path = filedialog.askopenfilename(
            title="Open ES3 Save File",
            filetypes=[("ES3 Files", "*.es3"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        password = simpledialog.askstring(
            "Decryption Password",
            "Enter the decryption password.\n(Leave blank if the file is not encrypted.)",
            show='*'
        )
        if password is None:  # user hit Cancel
            return

        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()

            self.current_salt = raw_data[:16]
            self.current_password = password

            if password:
                payload = decrypt_aes_128_cbc(raw_data, password)
            else:
                payload = raw_data

            # Detect and remove GZip compression
            self.is_gzipped = payload[:2] == b'\x1f\x8b'
            if self.is_gzipped:
                payload = gzip.decompress(payload)

            text = payload.decode('utf-8')

            self.text_editor.delete(1.0, tk.END)
            self.text_editor.insert(tk.END, text)
            self.text_editor.edit_reset()   # clear undo history for the new file
            self._update_line_numbers()

            self.current_file_path = file_path
            gz = "GZip + " if self.is_gzipped else ""
            enc = "AES encrypted" if password else "unencrypted"
            self.status_var.set(f"Loaded: {os.path.basename(file_path)}  [{gz}{enc}]")

        except Exception as e:
            messagebox.showerror(
                "Open Error",
                f"Could not open or decrypt the file.\n"
                f"Check that the password is correct.\n\nDetail: {e}"
            )

    def save_file(self):
        if not self.current_file_path or self.current_password is None:
            self.save_file_as()
            return
        self._perform_save(self.current_file_path)

    def save_file_as(self):
        if self.current_password is None:
            messagebox.showwarning("Nothing to save", "Open a file first.")
            return
        file_path = filedialog.asksaveasfilename(
            defaultextension=".es3",
            filetypes=[("ES3 Files", "*.es3"), ("All Files", "*.*")]
        )
        if file_path:
            self._perform_save(file_path)

    def _perform_save(self, save_path):
        try:
            text = self.text_editor.get(1.0, tk.END)
            # Strip the trailing newline tkinter always adds
            if text.endswith("\n"):
                text = text[:-1]

            payload = text.encode('utf-8')

            if self.is_gzipped:
                payload = gzip.compress(payload)

            if self.current_password:
                out = encrypt_aes_128_cbc(payload, self.current_password, self.current_salt)
            else:
                out = payload

            with open(save_path, 'wb') as f:
                f.write(out)

            self.current_file_path = save_path
            self.status_var.set(f"Saved: {os.path.basename(save_path)}")
            messagebox.showinfo("Saved", f"File saved successfully!\n{save_path}")

        except Exception as e:
            messagebox.showerror("Save Error", f"Could not save file.\n\nDetail: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ES3EditorApp(root)
    root.mainloop()
