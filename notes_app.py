from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Sequence

try:
    from version import __version__
except ImportError:
    __version__ = "unknown"


DEFAULT_LIST_LIMIT = 100
OSASCRIPT_TIMEOUT_SECONDS = 120


class NotesAppError(RuntimeError):
    pass


def run_osascript(script: str, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-s", "h", "-", *args],
            input=script,
            text=True,
            capture_output=True,
            check=False,
            timeout=OSASCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise NotesAppError(
            "AppleScript request timed out. Check Notes automation permissions and retry "
            "with narrower scope."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"osascript exited with code {result.returncode}"
        raise NotesAppError(detail)
    return result.stdout.rstrip("\n")


def parse_tsv(output: str, field_names: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not output.strip():
        return rows
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != len(field_names):
            raise NotesAppError("Unexpected AppleScript output format")
        rows.append(dict(zip(field_names, parts)))
    return rows


def print_rows(
    rows: Sequence[dict[str, Any]],
    as_json: bool,
    columns: list[str] | None = None,
    print_headers: bool = True,
) -> None:
    if as_json:
        if columns:
            rows = [{k: v for k, v in row.items() if k in columns} for row in rows]
        print(json.dumps(list(rows), ensure_ascii=False, indent=2))
        return
    if not rows:
        return
    
    headers = columns if columns else list(rows[0].keys())
    if print_headers:
        print("\t".join(headers))
    for row in rows:
        print("\t".join(str(row.get(header, "")) for header in headers))


def script_helpers() -> str:
    return """
on sanitize(value)
    if value is missing value then
        return ""
    end if
    set valueText to value as text
    set oldDelims to AppleScript's text item delimiters
    set AppleScript's text item delimiters to return
    set valueParts to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to valueParts as text
    set AppleScript's text item delimiters to linefeed
    set valueParts to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to valueParts as text
    set AppleScript's text item delimiters to tab
    set valueParts to text items of valueText
    set AppleScript's text item delimiters to " "
    set valueText to valueParts as text
    set AppleScript's text item delimiters to oldDelims
    return valueText
end sanitize

on emitRow(existingOutput, rowText)
    if existingOutput is "" then
        return rowText
    end if
    return existingOutput & linefeed & rowText
end emitRow
"""


def list_folders() -> list[dict[str, str]]:
    script = (
        script_helpers()
        + """
on run argv
    set outText to ""
    tell application "Notes"
        repeat with fRef in every folder
            set outText to my emitRow(outText, my sanitize(name of fRef))
        end repeat
    end tell
    return outText
end run
"""
    )
    output = run_osascript(script, [])
    return parse_tsv(output, ["name"])


def normalize_note_id(note_id: str) -> str:
    # If it's just the 'pXXX' suffix, we'll keep it as is and resolve it in AppleScript
    return note_id


def list_notes(folder_name: str, limit: int | None, order: str) -> list[dict[str, str]]:
    max_count = "" if limit is None else str(limit)
    script = (
        script_helpers()
        + """
on run argv
    set targetFolderName to item 1 of argv
    set maxCountText to item 2 of argv
    set sortOrder to item 3 of argv

    set outText to ""
    set remainingCount to -1
    if maxCountText is not "" then
        set remainingCount to maxCountText as integer
    end if

    tell application "Notes"
        if targetFolderName is "" then
            set targetFolders to every folder
        else
            set targetFolders to {folder targetFolderName}
        end if

        repeat with aFolder in targetFolders
            if remainingCount is 0 then
                exit repeat
            end if
            
            set noteCount to count of every note of aFolder
            if noteCount > 0 then
                set folderLabel to my sanitize(name of aFolder)
                
                if sortOrder is "asc" then
                    set startIndex to 1
                    set endIndex to noteCount
                    set stepValue to 1
                else
                    set startIndex to noteCount
                    set endIndex to 1
                    set stepValue to -1
                end if

                repeat with i from startIndex to endIndex by stepValue
                    if remainingCount is 0 then
                        exit repeat
                    end if

                    set aNote to note i of aFolder
                    set fullId to id of aNote as text
                    -- Extract the short ID (pXXX suffix)
                    set AppleScript's text item delimiters to "/"
                    set idParts to text items of fullId
                    set shortId to item 5 of idParts
                    set AppleScript's text item delimiters to ""
                    
                    set rowText to shortId & tab & my sanitize(name of aNote) & tab & folderLabel & tab & (modification date of aNote as text)
                    set outText to my emitRow(outText, rowText)
                    
                    if remainingCount > 0 then
                        set remainingCount to remainingCount - 1
                    end if
                end repeat
            end if
        end repeat
    end tell

    return outText
end run
"""
    )
    output = run_osascript(script, [folder_name, max_count, order])
    return parse_tsv(output, ["id", "name", "folder", "modification_date"])


def view_note(note_id: str) -> dict[str, str]:
    script = (
        script_helpers()
        + """
on run argv
    set targetId to item 1 of argv
    tell application "Notes"
        try
            if targetId starts with "p" then
                set aNote to (first note whose id ends with targetId)
            else
                set aNote to note id targetId
            end if
            set aFolder to container of aNote
            return (id of aNote as text) & tab & my sanitize(name of aNote) & tab & my sanitize(body of aNote) & tab & my sanitize(plaintext of aNote) & tab & (creation date of aNote as text) & tab & (modification date of aNote as text) & tab & my sanitize(name of aFolder)
        on error
            error "No note found with id " & targetId
        end try
    end tell
end run
"""
    )
    output = run_osascript(script, [note_id])
    rows = parse_tsv(output, ["id", "name", "body", "plaintext", "creation_date", "modification_date", "folder"])
    if not rows:
        raise NotesAppError("Unexpected output while viewing note")
    
    row = rows[0]
    row["id"] = row["id"].split("/")[-1]
    return row


def show_note(note_id: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Notes"
        activate
        try
            if targetId starts with "p" then
                set aNote to (first note whose id ends with targetId)
            else
                set aNote to note id targetId
            end if
            show aNote
        on error
            error "No note found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [note_id])


def create_folder(name: str) -> None:
    script = """
on run argv
    set folderName to item 1 of argv
    tell application "Notes"
        make new folder with properties {name:folderName}
    end tell
end run
"""
    run_osascript(script, [name])


def delete_folder(name: str) -> None:
    script = """
on run argv
    set folderName to item 1 of argv
    tell application "Notes"
        delete folder folderName
    end tell
end run
"""
    run_osascript(script, [name])


def create_note(name: str, body: str, folder_name: str) -> None:
    script = """
on run argv
    set noteName to item 1 of argv
    set noteBody to item 2 of argv
    set targetFolderName to item 3 of argv

    tell application "Notes"
        if targetFolderName is "" then
            set targetFolder to default folder
        else
            set targetFolder to folder targetFolderName
        end if
        make new note at targetFolder with properties {name:noteName, body:noteBody}
    end tell
end run
"""
    run_osascript(script, [name, body, folder_name])


def update_note(note_id: str, name: str, body: str, folder_name: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    set newName to item 2 of argv
    set newBody to item 3 of argv
    set targetFolderName to item 4 of argv

    tell application "Notes"
        try
            if targetId starts with "p" then
                set aNote to (first note whose id ends with targetId)
            else
                set aNote to note id targetId
            end if
            if newName is not "" then set name of aNote to newName
            if newBody is not "" then set body of aNote to newBody
            if targetFolderName is not "" then
                move aNote to folder targetFolderName
            end if
        on error
            error "No note found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [note_id, name, body, folder_name])


def delete_note(note_id: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Notes"
        try
            if targetId starts with "p" then
                set aNote to (first note whose id ends with targetId)
            else
                set aNote to note id targetId
            end if
            delete aNote
        on error
            error "No note found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [note_id])


def cmd_folders_list(args: argparse.Namespace) -> None:
    print_rows(list_folders(), args.json, print_headers=False)


def cmd_folders_create(args: argparse.Namespace) -> None:
    create_folder(args.name)
    print(f"Folder '{args.name}' created.")


def cmd_folders_delete(args: argparse.Namespace) -> None:
    delete_folder(args.name)
    print(f"Folder '{args.name}' deleted.")


def cmd_notes_list(args: argparse.Namespace) -> None:
    rows = list_notes(args.folder, args.limit, args.order)
    print_rows(rows, args.json)


def cmd_notes_view(args: argparse.Namespace) -> None:
    row = view_note(args.id)
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return
    for k, v in row.items():
        if k not in ("body", "plaintext"):
            print(f"{k}: {v}")
    print("")
    if args.html:
        print(row["body"])
    else:
        print(row["plaintext"])


def cmd_notes_show(args: argparse.Namespace) -> None:
    show_note(args.id)
    print("Note shown in Notes app.")


def cmd_notes_create(args: argparse.Namespace) -> None:
    create_note(args.name, args.body, args.folder)
    print("Note created.")


def cmd_notes_update(args: argparse.Namespace) -> None:
    if not any([args.name, args.body, args.folder]):
        args.parser_obj.error("Provide at least one field to update")
    update_note(args.id, args.name, args.body, args.folder)
    print("Note updated.")


def cmd_notes_delete(args: argparse.Namespace) -> None:
    delete_note(args.id)
    print("Note deleted.")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notes-app",
        description="Apple Notes command-line interface powered by AppleScript.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root_subparsers = parser.add_subparsers(dest="resource", required=True)

    # Folders
    folders_parser = root_subparsers.add_parser("folders", help="Folder operations")
    folders_subparsers = folders_parser.add_subparsers(dest="folder_command", required=True)

    fold_list = folders_subparsers.add_parser("list", aliases=["ls"], help="List folders")
    fold_list.add_argument("--json", action="store_true", help="JSON output")
    fold_list.set_defaults(func=cmd_folders_list)

    fold_create = folders_subparsers.add_parser("create", aliases=["add"], help="Create a folder")
    fold_create.add_argument("--name", required=True, help="Folder name")
    fold_create.set_defaults(func=cmd_folders_create)

    fold_delete = folders_subparsers.add_parser("delete", aliases=["rm"], help="Delete a folder")
    fold_delete.add_argument("--name", required=True, help="Folder name")
    fold_delete.set_defaults(func=cmd_folders_delete)

    # Notes
    notes_parser = root_subparsers.add_parser("notes", aliases=["nt", "nts"], help="Note operations")
    notes_subparsers = notes_parser.add_subparsers(dest="note_command", required=True)

    nt_list = notes_subparsers.add_parser("list", aliases=["ls"], help="List notes")
    nt_list.add_argument("--folder", default="", help="Folder name")
    nt_list.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT, help="Limit")
    nt_list.add_argument("--order", choices=("desc", "asc"), default="desc", help="Order")
    nt_list.add_argument("--json", action="store_true", help="JSON output")
    nt_list.set_defaults(func=cmd_notes_list)

    nt_view = notes_subparsers.add_parser("view", aliases=["v"], help="View a note")
    nt_view.add_argument("--id", required=True, help="Note ID")
    nt_view.add_argument("--json", action="store_true", help="JSON output")
    nt_view.add_argument("--html", action="store_true", help="Output raw HTML body")
    nt_view.set_defaults(func=cmd_notes_view)

    nt_show = notes_subparsers.add_parser("show", aliases=["open"], help="Show a note in the Notes app")
    nt_show.add_argument("--id", required=True, help="Note ID")
    nt_show.set_defaults(func=cmd_notes_show)

    nt_create = notes_subparsers.add_parser("create", aliases=["add"], help="Create a note")
    nt_create.add_argument("--name", required=True, help="Note name")
    nt_create.add_argument("--body", required=True, help="Note body")
    nt_create.add_argument("--folder", default="", help="Folder name")
    nt_create.set_defaults(func=cmd_notes_create)

    nt_update = notes_subparsers.add_parser("update", aliases=["set"], help="Update a note")
    nt_update.add_argument("--id", required=True, help="Note ID")
    nt_update.add_argument("--name", default="", help="New name")
    nt_update.add_argument("--body", default="", help="New body")
    nt_update.add_argument("--folder", default="", help="Move to folder")
    nt_update.set_defaults(func=cmd_notes_update, parser_obj=nt_update)

    nt_delete = notes_subparsers.add_parser("delete", aliases=["rm"], help="Delete a note")
    nt_delete.add_argument("--id", required=True, help="Note ID")
    nt_delete.set_defaults(func=cmd_notes_delete)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except NotesAppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.SubprocessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
