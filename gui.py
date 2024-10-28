import customtkinter as ctk
from tkinter import messagebox
import platform
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
import shutil


class ExclusionManagerGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Backblaze Exclusion Manager")
        self.root.geometry("1200x800")

        # Set default color theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # XML file path
        platform_ = platform.system()
        if platform_ == 'Windows':
            self.xml_path = "C:/ProgramData/Backblaze/bzdata/bzexcluderules_editable.xml"
            self.plat = 'win'
        elif platform_ == 'Darwin':
            self.xml_path = "/Library/Backblaze.bzpkg/bzdata/bzexcluderules_editable.xml"
            self.plat = 'mac'
        else:
            print(f'This app is designed for Windows and Mac platforms only. {platform_} is not supported.')
            exit(1)

        # Create main frame
        self.main_frame = ctk.CTkFrame(self.root)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Create button frame
        self.button_frame = ctk.CTkFrame(self.main_frame)
        self.button_frame.pack(fill="x", padx=5, pady=5)

        # Create buttons
        ctk.CTkButton(self.button_frame,
                      text="Select File",
                      command=self.select_file).pack(side="left", padx=5, pady=5, expand=True)

        ctk.CTkButton(self.button_frame,
                      text="Select Folder",
                      command=self.select_folder).pack(side="left", padx=5, pady=5, expand=True)

        ctk.CTkButton(self.button_frame,
                      text="Remove Selected",
                      command=self.remove_selected).pack(side="left", padx=5, pady=5, expand=True)

        ctk.CTkButton(self.button_frame,
                      text="Backup This List",
                      command=self.create_backup).pack(side="left", padx=5, pady=5, expand=True)

        # Create scrollable frame for list
        self.list_frame = ctk.CTkScrollableFrame(self.main_frame)
        self.list_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Store labels and selected label
        self.labels = []
        self.selected_label = None

        # Load existing entries
        self.refresh_listbox()

    def handle_label_click(self, label):
        if self.selected_label:
            self.selected_label.configure(fg_color="transparent")
        label.configure(fg_color="green")
        self.selected_label = label

    def refresh_listbox(self):
        # Clear existing labels
        for label in self.labels:
            label.destroy()
        self.labels.clear()
        self.selected_label = None

        try:
            tree = ET.parse(self.xml_path)
            root = tree.getroot()

            entries = []
            for rule in root.findall(".//excludefname_rule"):
                # Get all relevant attributes
                start_with = rule.get('skipFirstCharThenStartsWith')
                contains_1 = rule.get('contains_1')
                contains_2 = rule.get('contains_2')
                file_ext = rule.get('hasFileExtension')
                ends_with = rule.get('endsWith')
                plat = rule.get('plat')

                # Skip if all values are "*"
                if all(x == "*" for x in [start_with, contains_1, contains_2, file_ext, ends_with]):
                    continue

                # Skip if the rule is not for the current platform
                if plat != self.plat:
                    continue

                # Create display string
                display_parts = []
                if start_with != "*":
                    display_parts.append(f"Starts With: {start_with}")
                if contains_1 != "*":
                    display_parts.append(f"Path:  {contains_1}")
                if contains_2 != "*":
                    display_parts.append(f"Contains:  {contains_2}")
                if ends_with != "*":
                    display_parts.append(f"Ends With:  {ends_with}")
                if file_ext != "*":
                    display_parts.append(f"File Extension:  {file_ext}")

                if display_parts:  # Only add if there's something to display
                    entries.append("  |  ".join(display_parts))

            # Add all entries as labels
            for i, entry in enumerate(entries, 1):
                text = f"{i}. {entry}"
                label = ctk.CTkLabel(
                    self.list_frame,
                    text=text,
                    anchor="w",
                    padx=5,
                    pady=5,
                    corner_radius=6,
                    cursor="hand2"
                )
                label.pack(fill="x", padx=5, pady=2)
                label.bind("<Button-1>", lambda event, widget=label: self.handle_label_click(widget))
                self.labels.append(label)

        except Exception as e:
            messagebox.showerror("Error", f"Error loading existing entries: {str(e)}")

    def get_selected_text(self):
        if not self.selected_label:
            messagebox.showinfo("Info", "Please select an item first")
            return None

        text = self.selected_label.cget("text")
        # Remove the number prefix
        return '.'.join(text.split('.')[1:]).strip()

    def create_exclusion_rule(self, path, is_file=False):
        base_rule = {
            'plat': self.plat,
            'osVers': '*',
            'ruleIsOptional': 't',
            'skipFirstCharThenStartsWith': '*',
            'contains_1': path,
            'contains_2': '*',
            'doesNotContain': '*',
            'endsWith': '*'
        }

        if is_file:
            file_path = Path(path)
            ext = file_path.suffix
            stem = file_path.stem
            if ext:
                base_rule['hasFileExtension'] = ext[1:]  # Remove the dot
                base_rule['endsWith'] = stem + ext
            else:
                base_rule['hasFileExtension'] = '*'
                base_rule['endsWith'] = stem
        else:
            base_rule['hasFileExtension'] = '*'

        return base_rule

    def add_exclusion_to_xml(self, rule_attrs):
        try:
            # Read the file content
            with open(self.xml_path, 'r', encoding='utf-8') as file:
                content = file.read()

            # Create the new rule XML string
            new_rule = '<excludefname_rule'
            for key, value in rule_attrs.items():
                new_rule += f' {key}="{value}"'
            new_rule += ' />\n'

            # Find the position of the closing tag
            closing_pos = content.rfind('</bzexclusions>')

            if closing_pos != -1:
                # Insert the new rule before the closing tag
                new_content = content[:closing_pos] + new_rule + content[closing_pos:]

                # Write the modified content back to the file
                with open(self.xml_path, 'w', encoding='utf-8') as file:
                    file.write(new_content)

                # Refresh the listbox
                self.refresh_listbox()
            else:
                messagebox.showerror("Error", "Could not find closing tag in XML file")

        except Exception as e:
            messagebox.showerror("Error", f"Error updating XML: {str(e)}")

    def select_file(self):
        file_path = ctk.filedialog.askopenfilename()
        if file_path:
            if self.plat == 'win':
                file_path = file_path.replace('/', '\\')  # Convert to Windows path format
            rule = self.create_exclusion_rule(file_path, is_file=True)
            self.add_exclusion_to_xml(rule)

    def select_folder(self):
        folder_path = ctk.filedialog.askdirectory()
        if folder_path:
            if self.plat == 'win':
                folder_path = folder_path.replace('/', '\\')  # Convert to Windows path format
            rule = self.create_exclusion_rule(folder_path, is_file=False)
            self.add_exclusion_to_xml(rule)

    def remove_selected(self):
        selected_text = self.get_selected_text()
        if not selected_text:
            return

        try:
            # Read the entire file content
            with open(self.xml_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()

            # Find and remove the matching line
            for i, line in enumerate(lines):
                if 'excludefname_rule' in line:
                    # Extract attributes using string operations
                    attributes = {}
                    parts = line.split('" ')
                    for part in parts:
                        if '=' in part:
                            key, value = part.split('=', 1)
                            key = key.strip().split()[-1]  # Get the last word before =
                            value = value.strip('"').strip("'").strip()  # Remove quotes
                            attributes[key] = value

                    # Build rule text parts
                    rule_text_parts = []
                    if attributes.get('skipFirstCharThenStartsWith', '*') != '*':
                        rule_text_parts.append(f"Start With: {attributes['skipFirstCharThenStartsWith']}")
                    if attributes.get('contains_1', '*') != '*':
                        rule_text_parts.append(f"Path:  {attributes['contains_1']}")
                    if attributes.get('contains_2', '*') != '*':
                        rule_text_parts.append(f"Contains:  {attributes['contains_2']}")
                    if attributes.get('endsWith', '*') != '*':
                        rule_text_parts.append(f"Ends With:  {attributes['endsWith']}")
                    if attributes.get('hasFileExtension', '*') != '*':
                        rule_text_parts.append(f"File Extension:  {attributes['hasFileExtension']}")

                    rule_text = "  |  ".join(rule_text_parts)

                    if rule_text == selected_text:
                        response = messagebox.askyesno("Confirm", "Are you sure you want to remove this item?")
                        if response:
                            lines.pop(i)
                            # Write back the modified content
                            with open(self.xml_path, 'w', encoding='utf-8') as file:
                                file.writelines(lines)
                            self.refresh_listbox()
                        break

        except Exception as e:
            messagebox.showerror("Error", f"Error removing entry: {str(e)}")

    def create_backup(self):
        try:
            # Generate timestamp in ddmmyyhhmmss format
            timestamp = datetime.now().strftime("%d%m%y%H%M%S")
            backup_path = f"{self.xml_path}_bak{timestamp}"

            # Create backup
            shutil.copy2(self.xml_path, backup_path)
            messagebox.showinfo("Success", f"Backup created successfully at:\n{backup_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Error creating backup: {str(e)}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = ExclusionManagerGUI()
    app.run()
