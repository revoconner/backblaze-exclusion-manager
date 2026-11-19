"""Backblaze exclusion rules: parsing that keeps the file text intact, classification by shape, and matching the way the client does it.

The matching here follows what the Backblaze client was observed to do in a live test on 2026-11-19 (tests/fixtures/live_rule_test.json).
"""
import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, unescape

CRITERIA = ("skipFirstCharThenStartsWith", "contains_1", "contains_2", "doesNotContain", "endsWith", "hasFileExtension")
REQUIRED = ("plat", "osVers") + CRITERIA
QUOTES = {'"': "&quot;"}
UNQUOTES = {"&quot;": '"', "&apos;": "'"}

_TOKEN = re.compile(r"<!--.*?-->|<excludefname_rule\b[^>]*>", re.S)
_ATTR = re.compile(r'([\w.-]+)\s*=\s*"([^"]*)"')
_ANCHOR = re.compile(r"^[A-Za-z]:\\.")


@dataclass
class Rule:
    start: int
    end: int
    raw: str
    attrs: dict
    kind: str = "foreign"
    target: str = ""
    extra: dict = field(default_factory=dict)


def parse(text):
    """Every excludefname_rule outside a comment, with its position in the text. Each rule is classified."""
    rules = []
    for m in _TOKEN.finditer(text):
        raw = m.group()
        if raw.startswith("<!--"):
            continue
        attrs = {k: unescape(v, UNQUOTES) for k, v in _ATTR.findall(raw)}
        rule = Rule(m.start(), m.end(), raw, attrs)
        classify(rule)
        rules.append(rule)
    return rules


def anchored(value):
    return bool(_ANCHOR.match(value))


def _prefix_fits(prefix, path):
    return prefix == "*" or (path + "\\")[1:].lower().startswith(prefix.lower())


def classify(rule):
    """Sets rule.kind to folder, legacy_folder, file, legacy_file, keeplist, foreign or invalid, and rule.target to the path it is about."""
    a = rule.attrs
    rule.kind, rule.target = "foreign", ""
    if any(name not in a for name in REQUIRED):
        rule.kind = "invalid"
        return
    if a["plat"] != "win" or a["osVers"] != "*" or "bzmergeblock" in a:
        return
    sw, c1, c2, dnc, ew, ext = (a[name] for name in CRITERIA)
    if anchored(c1) and c2 == "*" and ew == "*" and ext == "*" and _prefix_fits(sw, c1.rstrip("\\")):
        if dnc == "*":
            rule.kind = "folder" if c1.endswith("\\") else "legacy_folder"
            rule.target = c1.rstrip("\\")
        elif c1.endswith("\\") and all(part.lower().startswith(c1.lower()) for part in dnc.split("|")):
            rule.kind, rule.target = "keeplist", c1.rstrip("\\")
    elif anchored(ew) and c1 == "*" and c2 == "*" and dnc == "*" and _prefix_fits(sw, ew):
        rule.kind, rule.target = "file", ew
    elif anchored(c1) and c2 == "*" and dnc == "*" and "\\" not in ew and c1.lower().endswith("\\" + ew.lower()):
        # the shape version 1.1 wrote for a file: full path in contains_1, bare name in endsWith
        rule.kind, rule.target = "legacy_file", c1


def extension(low_path):
    """The file extension as Backblaze defines it: text after the last period, no space, no slash, plain ASCII. Empty when there is none."""
    dot = low_path.rfind(".")
    rest = low_path[dot + 1:] if dot >= 0 else ""
    if not rest or not rest.isascii() or any(ch in rest for ch in "\\/ "):
        return ""
    return rest


class Matcher:
    """Answers whether Backblaze would leave a path out, for one set of rules.

    A folder is tested as its path without a trailing backslash, and when a rule matches it nothing below is looked at.
    That only happens from the third level below a drive root. The first two levels are top folders that Backblaze always walks, testing their files one by one.
    A file is left out when a folder above it was cut off or when a rule matches the file path itself.
    """

    def __init__(self, rules, os_name="eleven"):
        self._entries = []
        for rule in rules:
            a = rule.attrs
            if any(name not in a for name in REQUIRED) or a["plat"] != "win" or a["osVers"] not in ("*", os_name):
                continue
            sw, c1, c2, dnc, ew, ext = (a[name].lower() for name in CRITERIA)
            if sw != "*" and len(sw) < 4:
                continue
            parts = () if dnc == "*" else tuple(p for p in dnc.split("|") if p)
            self._entries.append((sw, c1, c2, parts, ew, ext, rule))
        # rules that can take out a whole folder: no file name criteria, and any keep entries are full paths
        self._whole = [e for e in self._entries if e[4] == "*" and e[5] == "*" and all(_ANCHOR.match(part) for part in e[3])]
        self._by_parent = {}
        self._cut = {}

    @staticmethod
    def _test(entry, low):
        sw, c1, c2, parts, ew, _ext, _rule = entry
        if sw != "*" and not low.startswith(sw, 1):
            return False
        if c1 != "*" and c1 not in low:
            return False
        if c2 != "*" and c2 not in low:
            return False
        if ew != "*" and not low.endswith(ew):
            return False
        return not any(part in low for part in parts)

    def _candidates(self, parent):
        hit = self._by_parent.get(parent)
        if hit is None:
            tail = parent[1:]
            plain, by_ext = [], {}
            for entry in self._entries:
                sw = entry[0]
                if sw != "*" and not tail.startswith(sw) and not sw.startswith(tail):
                    continue
                if entry[5] == "*":
                    plain.append(entry)
                else:
                    by_ext.setdefault(entry[5], []).append(entry)
            hit = self._by_parent[parent] = (plain, by_ext)
        return hit

    def match(self, path):
        """The first rule whose criteria all match this exact path string, or None."""
        low = path.lower()
        plain, by_ext = self._candidates(low[:low.rfind("\\") + 1])
        for entry in plain:
            if self._test(entry, low):
                return entry[6]
        for entry in by_ext.get(extension(low), ()):
            if self._test(entry, low):
                return entry[6]
        return None

    def cut_off(self, folder):
        """The rule that stops Backblaze from walking into this folder (it or a folder above it matches), or None."""
        low = folder.lower().rstrip("\\")
        if len(low) <= 2:
            return None
        if low not in self._cut:
            own = self.match(low) if low.count("\\") > 2 else None
            self._cut[low] = self.cut_off(low[:low.rfind("\\")]) or own
        return self._cut[low]

    def file_rule(self, path):
        """The rule that keeps this file out of the backup, or None when it is backed up."""
        return self.cut_off(path[:path.rfind("\\")]) or self.match(path)

    def folder_rule(self, path):
        """The rule that keeps this whole folder out, or None. Nothing is said about single items inside it."""
        path = path.rstrip("\\")
        hit = self.cut_off(path)
        if hit:
            return hit
        low = path.lower() + "\\"
        for entry in self._whole:
            if self._test(entry, low) and not any(part.startswith(low) for part in entry[3]):
                return entry[6]
        return None


def prefix_for(path, is_dir):
    """skipFirstCharThenStartsWith for an item: its parent folder, or the item itself when it sits in a drive root."""
    rest = path[2:]
    parent = rest[:rest.rfind("\\") + 1]
    if parent != "\\":
        return ":" + parent
    prefix = ":" + rest + ("\\" if is_dir else "")
    return prefix if len(prefix) >= 4 else "*"


def format_rule(prefix="*", contains_1="*", does_not_contain="*", ends_with="*", ext="*"):
    values = (prefix, contains_1, "*", does_not_contain, ends_with, ext)
    body = " ".join(f'{name}="{escape(value, QUOTES)}"' for name, value in zip(CRITERIA, values))
    return f'<excludefname_rule plat="win" osVers="*" ruleIsOptional="t" {body} />'


def folder_rule_text(path):
    path = path.rstrip("\\")
    return format_rule(prefix_for(path, True), contains_1=path + "\\")


def file_rule_text(path):
    name = path[path.rfind("\\") + 1:]
    dot = name.rfind(".")
    ext = name[dot + 1:] if dot > 0 else ""
    return format_rule(prefix_for(path, False), ends_with=path, ext=ext if ext.isascii() and ext.isalnum() else "*")


def set_attr(raw, name, value):
    """The rule text with one attribute value replaced and everything else left as it was."""
    return re.sub(rf'(\b{name}\s*=\s*")[^"]*(")', lambda m: m.group(1) + escape(value, QUOTES) + m.group(2), raw, count=1)


def apply_edits(text, edits):
    """edits are (offset, length to remove, text to insert). Applied back to front so offsets stay valid."""
    for offset, length, insert in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:offset] + insert + text[offset + length:]
    return text
