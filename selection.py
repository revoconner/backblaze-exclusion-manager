"""What is ticked for backup, held as the exclusions this app owns, and the rule text that follows from it.

A folder that is partly backed up works in one of two ways. Open: single items in it are left out by their own rule, and anything new that appears there is backed up. Keep list: one rule leaves out everything in it except the named items, so anything new stays out.
Paths have no trailing backslash and a drive root is written "C:".
"""
import xml.etree.ElementTree as ET

from normalise import list_folder
from rules import apply_edits, file_rule_text, folder_rule_text, keeplist_rule_text, parse

INCLUDED, PARTIAL, EXCLUDED = "included", "partial", "excluded"
MARKER = "<!-- Rules below this line were added by Backblaze Exclusion Manager -->"
CLOSING = "</bzexclusions>"


def split(path):
    cut = path.rfind("\\")
    return (path[:cut], path[cut + 1:]) if cut >= 0 else ("", path)


def owned(rules):
    """(rule, key) for the rules this app manages. A second keep list for the same folder is left alone as a foreign rule."""
    out, listed = [], set()
    for rule in rules:
        low = rule.target.lower()
        if rule.kind in ("folder", "file"):
            out.append((rule, (rule.kind, low)))
        elif rule.kind == "keeplist" and low not in listed:
            listed.add(low)
            out.append((rule, ("keeplist", low)))
    return out


class Selection:
    def __init__(self, text, listdir=list_folder, locked=None):
        self.listdir = listdir
        self.locked = locked or (lambda path, is_dir: None)
        self.load(text)

    def load(self, text):
        """Takes every state from the rule text. Nothing is remembered from before."""
        self.excluded, self.keep = {}, {}
        self.rebase(text, adopt=True)

    def rebase(self, text, adopt=False):
        """Puts a new text underneath. Without adopt the ticks made so far stay and only the foreign rules are read again."""
        self.text = text
        rules = parse(text)
        mine = owned(rules)
        if adopt:
            for rule, key in mine:
                if key[0] == "keeplist":
                    self.keep[key[1]] = (rule.target, {name.lower(): name for name in rule.extra["names"]})
                else:
                    self.excluded[key[1]] = (rule.target, key[0] == "folder")
        ids = {id(rule) for rule, _key in mine}
        self.foreign = [rule for rule in rules if id(rule) not in ids]
        self._reindex()

    def _reindex(self):
        below = set()
        for low in self.excluded:
            below.update(self._above(low))
        for low in self.keep:
            below.add(low)
            below.update(self._above(low))
        self._below = below

    @staticmethod
    def _above(low):
        cut = low.rfind("\\")
        while cut >= 0:
            low = low[:cut]
            yield low
            cut = low.rfind("\\")

    def cause(self, path):
        """The topmost folder or file on the way to this path that is left out, in lower case, or None when the path is backed up."""
        low = path.lower()
        cut = low.find("\\")
        while True:
            node = low if cut < 0 else low[:cut]
            if node in self.excluded:
                return node
            slash = node.rfind("\\")
            if slash >= 0:
                kept = self.keep.get(node[:slash])
                if kept is not None and node[slash + 1:] not in kept[1]:
                    return node
            if cut < 0:
                return None
            cut = low.find("\\", cut + 1)

    def state(self, path):
        if self.cause(path):
            return EXCLUDED
        return PARTIAL if path.lower() in self._below else INCLUDED

    def mode(self, folder):
        return "keep" if folder.lower() in self.keep else "open"

    def discards(self, path):
        """How many exclusions and keep lists inside this folder a tick or untick on it would throw away."""
        prefix = path.lower() + "\\"
        return sum(k.startswith(prefix) for k in self.excluded) + sum(k == prefix[:-1] or k.startswith(prefix) for k in self.keep)

    def _drop_below(self, low):
        prefix = low + "\\"
        for key in [k for k in self.excluded if k.startswith(prefix)]:
            del self.excluded[key]
        for key in [k for k in self.keep if k == low or k.startswith(prefix)]:
            del self.keep[key]

    def toggle(self, path, is_dir):
        """A click on the box: an unticked item gets ticked, a ticked one unticked, a partly ticked folder becomes fully ticked."""
        if self.state(path) == INCLUDED:
            self.untick(path, is_dir)
        else:
            self.tick(path)

    def untick(self, path, is_dir):
        if self.cause(path):
            return
        self._untick(path, is_dir)
        self._reindex()

    def _untick(self, path, is_dir):
        low = path.lower()
        self._drop_below(low)
        self.excluded.pop(low, None)
        parent, name = split(path)
        kept = self.keep.get(parent.lower())
        if kept is None:
            self.excluded[low] = (path, is_dir)
            return
        kept[1].pop(name.lower(), None)
        if not kept[1]:
            # nothing in the parent is kept any more, so the parent as a whole is out
            self._untick(parent, True)

    def tick(self, path):
        """Backs the item up in full. Inside a folder that is left out, only the way down to the item is opened, as keep lists."""
        low = path.lower()
        hit = self.cause(path)
        if hit:
            node = path[:len(hit)]
            while True:
                self.excluded.pop(node.lower(), None)
                parent, name = split(node)
                kept = self.keep.get(parent.lower())
                if kept is not None:
                    kept[1][name.lower()] = name
                if len(node) == len(path):
                    break
                # this folder was out as a whole, now it keeps only the next step on the way down
                self.keep[node.lower()] = (node, {})
                cut = path.find("\\", len(node) + 1)
                node = path if cut < 0 else path[:cut]
        self._drop_below(low)
        self._reindex()

    def set_keep_mode(self, folder, on):
        """Switches a folder between keep list and open without changing what is backed up right now. False when the folder cannot be listed."""
        low = folder.lower()
        entries = self.listdir(folder)
        if entries is None or self.cause(folder):
            return False
        # a linked folder is skipped both ways: Backblaze does not go into it, so naming it would only add noise
        entries = [e for e in entries if not (e[1] and e[2])]
        if on and low not in self.keep:
            names = {}
            for name, is_dir, _link in entries:
                child = folder + "\\" + name
                if child.lower() not in self.excluded and not self.locked(child, is_dir):
                    names[name.lower()] = name
            for key in [k for k in self.excluded if k.startswith(low + "\\") and "\\" not in k[len(low) + 1:]]:
                self._drop_below(key)
                del self.excluded[key]
            if names:
                self.keep[low] = (folder, names)
            else:
                self._untick(folder, True)
        elif not on and low in self.keep:
            names = self.keep.pop(low)[1]
            for name, is_dir, _link in entries:
                child = folder + "\\" + name
                if name.lower() not in names and not self.locked(child, is_dir):
                    self.excluded[child.lower()] = (child, is_dir)
        self._reindex()
        return True

    def desired(self):
        """key -> (rule text, path, kept names) for every rule the current ticks call for."""
        out = {}
        for low, (path, is_dir) in self.excluded.items():
            out[("folder" if is_dir else "file", low)] = (folder_rule_text(path) if is_dir else file_rule_text(path), path, None)
        for low, (folder, names) in self.keep.items():
            if not names:
                continue
            out[("keeplist", low)] = (keeplist_rule_text(folder, names.values()), folder, frozenset(names))
            # a kept name also keeps whatever starts with the same letters, so such neighbours get a rule of their own
            for name, is_dir, _link in self.listdir(folder) or []:
                n = name.lower()
                if n not in names and any(n.startswith(k) for k in names):
                    child = folder + "\\" + name
                    out.setdefault(("folder" if is_dir else "file", child.lower()), (folder_rule_text(child) if is_dir else file_rule_text(child), child, None))
        return out

    def _plan(self):
        """(lines to remove, rules to replace in place, new rules) that turn the base text into the desired rules."""
        want = self.desired()
        seen, remove, replace = set(), [], []
        for rule, key in owned(parse(self.text)):
            if key not in want:
                remove.append(rule)
                continue
            seen.add(key)
            if key[0] == "keeplist" and frozenset(n.lower() for n in rule.extra["names"]) != want[key][2]:
                replace.append((rule, want[key]))
        new = sorted((v for k, v in want.items() if k not in seen), key=lambda v: v[1].lower())
        return remove, replace, new

    def changes(self):
        """Plain sentences for what saving would do."""
        remove, replace, new = self._plan()
        lines = []
        for text, path, names in new:
            lines.append(f"Back up only the ticked items in {path} ({len(names)} kept), new items stay out" if names else f"Stop backing up {path}")
        for _rule, (_text, path, names) in replace:
            lines.append(f"Change which items are kept in {path} ({len(names)} kept)")
        for rule in remove:
            lines.append(f"New items in {rule.target} are backed up again" if rule.kind == "keeplist" else f"Remove the exclusion of {rule.target}")
        return lines

    def build_text(self):
        """The base text with the owned rules brought in line with the ticks. Every other character stays where it is."""
        remove, replace, new = self._plan()
        text = self.text
        edits = []
        for rule in remove:
            start = text.rfind("\n", 0, rule.start) + 1
            end = text.find("\n", rule.end)
            end = len(text) if end < 0 else end + 1
            if text[start:rule.start].strip() or text[rule.end:end].strip():
                edits.append((rule.start, rule.end - rule.start, ""))
            else:
                edits.append((start, end - start, ""))
        for rule, (wanted, _path, _names) in replace:
            edits.append((rule.start, rule.end - rule.start, wanted))
        if new:
            newline = "\r\n" if "\r\n" in text else "\n"
            at = text.rfind(CLOSING)
            if at < 0:
                raise ValueError("the rules file has no closing </bzexclusions> tag")
            lines = [] if MARKER in text else [MARKER]
            lines += [wanted for wanted, _path, _names in new]
            lead = "" if at == 0 or text[at - 1] == "\n" else newline
            edits.append((at, 0, lead + "".join(line + newline for line in lines)))
        return apply_edits(text, edits)

    def check(self, new_text):
        """None when the text is safe to write, else what is wrong with it. Nothing gets saved without passing this."""
        try:
            ET.fromstring(new_text.encode("utf-8"))
        except ET.ParseError as error:
            return f"the result is not valid XML ({error})"
        if not new_text.rstrip().endswith(CLOSING):
            return "the result does not end with the closing tag"
        if "\r\n" in self.text and new_text.count("\n") != new_text.count("\r\n"):
            return "the result mixes line endings"
        again = Selection(new_text, self.listdir, self.locked)
        if [r.raw for r in again.foreign] != [r.raw for r in self.foreign]:
            return "rules that do not belong to this app would be changed"
        if any(r.kind == "invalid" for r in parse(new_text)) and not any(r.kind == "invalid" for r in parse(self.text)):
            return "a rule in the result is missing a required attribute"
        mine, theirs = self.desired(), again.desired()
        if {k: v[2] for k, v in mine.items()} != {k: v[2] for k, v in theirs.items()}:
            return "reading the result back does not give the same ticks"
        return None
