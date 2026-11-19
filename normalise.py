"""One time pass that turns hand written rules into the shapes the app owns, without changing what is backed up.

The input file is never written. Run: python normalise.py INPUT.xml --out FOLDER [--filelists FOLDER]
"""
import argparse
import difflib
import os
import stat
import sys
from pathlib import Path

from rules import Matcher, apply_edits, file_rule_text, folder_rule_text, parse, set_attr


def list_folder(path):
    """(name, is_dir, is_link) for each entry, or None when the folder cannot be read."""
    try:
        with os.scandir(path + "\\") as it:
            out = []
            for entry in it:
                flags = entry.stat(follow_symlinks=False).st_file_attributes
                out.append((entry.name, bool(flags & stat.FILE_ATTRIBUTE_DIRECTORY), bool(flags & stat.FILE_ATTRIBUTE_REPARSE_POINT)))
            return out
    except OSError:
        return None


def _split(path):
    cut = path.rfind("\\")
    return path[:cut], path[cut + 1:]


def normalise(text, listdir=list_folder):
    """Returns (new text, report). The report lists what was fixed, added and left alone, and why."""
    newline = "\r\n" if "\r\n" in text else "\n"
    report = {"fixed": [], "converted_files": [], "added": [], "already_covered": [], "left": [], "parents": set()}
    edits, caught = [], []
    for rule in parse(text):
        if rule.kind == "legacy_folder":
            parent, name = _split(rule.target)
            entries = listdir(parent)
            if entries is None:
                report["left"].append((rule.target, "parent folder cannot be listed"))
                continue
            same = [e for e in entries if e[0].lower() == name.lower()]
            if not same:
                report["left"].append((rule.target, "target not on disk"))
                continue
            if not same[0][1]:
                report["left"].append((rule.target, "target is a file, the rule may be a deliberate name prefix"))
                continue
            edits.append((rule.start, len(rule.raw), set_attr(rule.raw, "contains_1", rule.target + "\\")))
            report["fixed"].append(rule.target)
            report["parents"].add(parent)
            siblings = [e for e in entries if e[0].lower().startswith(name.lower()) and e[0].lower() != name.lower()]
            caught.append((rule, parent, siblings))
        elif rule.kind == "legacy_file":
            parent, name = _split(rule.target)
            entries = listdir(parent)
            same = [e for e in entries or [] if e[0].lower() == name.lower()]
            if not same or same[0][1]:
                report["left"].append((rule.target, "file rule from version 1.1 whose target is not a file on disk"))
                continue
            raw = set_attr(set_attr(rule.raw, "contains_1", "*"), "endsWith", rule.target)
            edits.append((rule.start, len(rule.raw), raw))
            report["converted_files"].append(rule.target)
            report["parents"].add(parent)

    fixed = Matcher(parse(apply_edits(text, edits)))
    seen = set()
    for rule, parent, siblings in caught:
        lines = []
        alone = Matcher([rule])
        for name, is_dir, is_link in siblings:
            path = parent + "\\" + name
            # a name that starts the same way is only caught when this rule really matched it, its prefix criterion can rule that out
            if path.lower() in seen or not (alone.folder_rule(path) if is_dir else alone.file_rule(path)):
                continue
            seen.add(path.lower())
            cover = fixed.folder_rule(path) if is_dir else fixed.file_rule(path)
            if cover:
                report["already_covered"].append((path, rule.target, cover.target or cover.attrs.get("contains_1", "")))
                continue
            lines.append(folder_rule_text(path) if is_dir else file_rule_text(path))
            report["added"].append((path, rule.target, "junction" if is_link else "folder" if is_dir else "file"))
        if lines:
            line_end = text.find("\n", rule.end)
            line_end = len(text) if line_end < 0 else line_end + 1
            edits.append((line_end, 0, "".join(line + newline for line in lines)))
    return apply_edits(text, edits), report


def compare_folders(old_text, new_text, parents, listdir=list_folder):
    """Every entry of the given folders whose state differs between the two rule texts. Empty means nothing changes."""
    old, new = Matcher(parse(old_text)), Matcher(parse(new_text))
    differences = []
    for parent in sorted(parents, key=str.lower):
        for name, is_dir, _link in listdir(parent) or []:
            path = parent + "\\" + name
            before = bool(old.folder_rule(path) if is_dir else old.file_rule(path))
            after = bool(new.folder_rule(path) if is_dir else new.file_rule(path))
            if before != after:
                differences.append((path, "excluded" if before else "backed up", "excluded" if after else "backed up"))
    return differences


def compare_filelists(old_text, new_text, folder, skip_under=()):
    """Runs every path Backblaze listed for backup through both rule texts. Returns (paths checked, paths the old rules
    would drop, paths the new rules would drop). Both lists should be empty: the first checks this matcher against
    Backblaze itself, the second checks that nothing currently backed up gets lost."""
    old, new = Matcher(parse(old_text)), Matcher(parse(new_text))
    checked, old_drops, new_drops = 0, [], []
    for listing in sorted(Path(folder).glob("*____filelist.dat")):
        with open(listing, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith("f\t"):
                    continue
                path = line.rstrip("\r\n").split("\t", 3)[3]
                if path.lower().startswith(skip_under):
                    continue
                checked += 1
                if old.file_rule(path):
                    old_drops.append(path)
                if new.file_rule(path):
                    new_drops.append(path)
    return checked, old_drops, new_drops


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input")
    ap.add_argument("--out", required=True, help="folder for the normalised file, the diff and the report")
    ap.add_argument("--filelists", help="Backblaze bzfilelists folder, to check the result against what is backed up now")
    args = ap.parse_args()

    source = Path(args.input)
    old_text = source.read_bytes().decode("utf-8")
    new_text, report = normalise(old_text)
    differences = compare_folders(old_text, new_text, report["parents"])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if out.resolve() == source.parent.resolve():
        sys.exit("the output folder must not be the folder of the input file")
    (out / source.name).write_bytes(new_text.encode("utf-8"))
    diff = difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), "before", "after", lineterm="", n=0)
    (out / "normalise.diff").write_text("\n".join(diff) + "\n", encoding="utf-8")

    lines = [f"input: {source}", f"rules before: {len(parse(old_text))}, after: {len(parse(new_text))}", ""]
    lines.append(f"folder rules given a trailing backslash: {len(report['fixed'])}")
    lines.append(f"version 1.1 file rules converted: {len(report['converted_files'])}")
    lines.append(f"rules added for entries the old prefix form was catching: {len(report['added'])}")
    lines += [f"    {path}  ({what}, was caught by the rule for {by})" for path, by, what in report["added"]]
    lines.append(f"entries the prefix form was catching that another rule still covers: {len(report['already_covered'])}")
    lines += [f"    {path}  (was caught by {by}, covered by {cover})" for path, by, cover in report["already_covered"]]
    lines.append(f"legacy rules left exactly as they were: {len(report['left'])}")
    lines += [f"    {path}  ({why})" for path, why in report["left"]]
    lines.append("")
    lines.append(f"folders compared entry by entry: {len(report['parents'])}, entries whose state changes: {len(differences)}")
    lines += [f"    CHANGE {path}: {before} before, {after} after" for path, before, after in differences]
    if args.filelists:
        checked, old_drops, new_drops = compare_filelists(old_text, new_text, args.filelists, ("d:\\terminal_temp\\bz_rule_test\\",))
        lines.append(f"paths in the Backblaze file lists checked: {checked}")
        lines.append(f"    listed by Backblaze but dropped by this matcher with the OLD rules: {len(old_drops)}")
        lines += [f"        {p}" for p in old_drops[:40]]
        lines.append(f"    listed by Backblaze but dropped with the NEW rules: {len(new_drops)}")
        lines += [f"        {p}" for p in new_drops[:40]]
    (out / "normalise_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
