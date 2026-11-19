"""Read only view of what the Backblaze client itself decides, apart from the editable rules: selected drives, folders excluded in its settings, built in rules."""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from rules import Matcher, parse

BZDATA = Path(r"C:\ProgramData\Backblaze\bzdata")
RULES_NAME = "bzexcluderules_editable.xml"


def default_xml():
    return BZDATA / RULES_NAME


def os_name():
    """The osVers word Backblaze uses for this Windows version."""
    build = sys.getwindowsversion().build if hasattr(sys, "getwindowsversion") else 22000
    return "eleven" if build >= 22000 else "ten"


class BzState:
    """bzinfo.xml and the mandatory rules. Looked up next to the rule file first, then in the Backblaze data folder. Never written."""

    def __init__(self, xml_path):
        self.drives = None
        self.filtered = set()
        self.mandatory = []
        folder = Path(xml_path).parent
        info = self._find(folder, "bzinfo.xml")
        if info:
            try:
                root = ET.parse(info).getroot()
                chosen = root.find("hard_drives_to_backup")
                if chosen is not None:
                    self.drives = {v.get("mountPointPath", "")[:2].lower() for v in chosen.iter("bzvolume")}
                for entry in root.iter("bzdirfilter"):
                    if entry.get("whichfiles") == "none":
                        self.filtered.add(entry.get("dir", "").lower().rstrip("\\"))
            except (ET.ParseError, OSError):
                pass
        builtin = self._find(folder, "bzexcluderules_mandatory.xml")
        if builtin:
            try:
                self.mandatory = parse(builtin.read_bytes().decode("utf-8", errors="replace"))
            except OSError:
                pass

    @staticmethod
    def _find(folder, name):
        for place in (folder, BZDATA):
            if (place / name).is_file():
                return place / name
        return None


class Locks:
    """Why an item is left out for a reason this app does not control, so its box cannot be ticked here."""

    def __init__(self, bz, foreign_rules):
        self.bz = bz
        name = os_name()
        self.builtin = Matcher(bz.mandatory, name)
        self.custom = Matcher(foreign_rules, name)

    def reason(self, path, is_dir):
        low = path.lower()
        if self.bz.drives is not None and low[:2] not in self.bz.drives:
            return "drive is not selected in Backblaze"
        node = low
        while len(node) > 2:
            if node in self.bz.filtered:
                return "excluded in the Backblaze settings"
            node = node[:node.rfind("\\")]
        if len(low) <= 2:
            return None
        if self.builtin.folder_rule(path) if is_dir else self.builtin.file_rule(path):
            return "always excluded by Backblaze"
        if self.custom.folder_rule(path) if is_dir else self.custom.file_rule(path):
            return "excluded by another rule in the rules file"
        return None
