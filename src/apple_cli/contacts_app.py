from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any, Sequence

try:
    from .version import __version__
except ImportError:
    __version__ = "unknown"


DEFAULT_LIST_LIMIT = 100
OSASCRIPT_TIMEOUT_SECONDS = 120
MISSING_VALUE = "missing value"

CONTACT_DISPLAY_LABELS = {
    "id": "id",
    "first_name": "first name",
    "last_name": "last name",
    "organization": "organization",
    "job_title": "job title",
    "nickname": "nickname",
    "birth_date": "birth date",
    "note": "note",
    "emails": "emails",
    "phones": "phones",
    "urls": "urls"
}


class ContactsAppError(RuntimeError):
    pass


class SubcommandHelpFormatter(argparse.HelpFormatter):
    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            parts = []
            for subaction in self._iter_indented_subactions(action):
                parts.append(self._format_action(subaction))
            return "".join(parts)
        return super()._format_action(action)


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
        raise ContactsAppError(
            "AppleScript request timed out. Check Contacts automation permissions and retry."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"osascript exited with code {result.returncode}"
        raise ContactsAppError(detail)
    return result.stdout.rstrip("\n")


def parse_tsv(output: str, field_names: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not output.strip():
        return rows
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != len(field_names):
            raise ContactsAppError("Unexpected AppleScript output format")
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


def list_groups() -> list[dict[str, str]]:
    script = (
        script_helpers()
        + """
on run argv
    set outText to ""
    tell application "Contacts"
        repeat with gRef in every group
            set outText to my emitRow(outText, my sanitize(name of gRef))
        end repeat
    end tell
    return outText
end run
"""
    )
    output = run_osascript(script, [])
    return parse_tsv(output, ["name"])


def list_contacts(search: str, group_name: str, limit: int | None, order: str) -> list[dict[str, str]]:
    max_count = "" if limit is None else str(limit)
    script = (
        script_helpers()
        + """
on run argv
    set searchText to item 1 of argv
    set targetGroupName to item 2 of argv
    set maxCountText to item 3 of argv
    set sortOrder to item 4 of argv

    set outText to ""
    set remainingCount to -1
    if maxCountText is not "" then
        set remainingCount to maxCountText as integer
    end if

    tell application "Contacts"
        if targetGroupName is "" then
            set targetPeople to every person
        else
            set targetPeople to every person of group targetGroupName
        end if

        set matchingPeople to {}
        repeat with p in targetPeople
            set ok to true
            if searchText is not "" then
                set fn to my sanitize(first name of p)
                set ln to my sanitize(last name of p)
                set org to my sanitize(organization of p)
                if (fn does not contain searchText) and (ln does not contain searchText) and (org does not contain searchText) then
                    set ok to false
                end if
            end if
            if ok then
                copy p to end of matchingPeople
            end if
        end repeat

        set pCount to count of matchingPeople
        if pCount > 0 then
            if sortOrder is "asc" then
                set startIndex to 1
                set endIndex to pCount
                set stepValue to 1
            else
                set startIndex to pCount
                set endIndex to 1
                set stepValue to -1
            end if

            repeat with i from startIndex to endIndex by stepValue
                if remainingCount is 0 then
                    exit repeat
                end if

                set p to item i of matchingPeople
                set fullId to id of p as text
                set AppleScript's text item delimiters to ":"
                set idParts to text items of fullId
                set shortId to item 1 of idParts
                set AppleScript's text item delimiters to ""
                
                set rowText to shortId & tab & my sanitize(first name of p) & tab & my sanitize(last name of p) & tab & my sanitize(organization of p)
                set outText to my emitRow(outText, rowText)
                
                if remainingCount > 0 then
                    set remainingCount to remainingCount - 1
                end if
            end repeat
        end if
    end tell

    return outText
end run
"""
    )
    output = run_osascript(script, [search, group_name, max_count, order])
    return parse_tsv(output, ["id", "first_name", "last_name", "organization"])


def view_contact(contact_id: str) -> dict[str, str]:
    script = (
        script_helpers()
        + """
on run argv
    set targetId to item 1 of argv
    tell application "Contacts"
        try
            set p to (first person whose id contains targetId)
            
            set emailList to {}
            repeat with em in every email of p
                copy (value of em as text) to end of emailList
            end repeat
            set AppleScript's text item delimiters to ", "
            set emailText to emailList as text
            
            set phoneList to {}
            repeat with ph in every phone of p
                copy (value of ph as text) to end of phoneList
            end repeat
            set phoneText to phoneList as text
            
            set urlList to {}
            repeat with ur in every url of p
                copy (value of ur as text) to end of urlList
            end repeat
            set urlText to urlList as text

            set AppleScript's text item delimiters to ""

            set bdText to ""
            if birth date of p is not missing value then
                set bdText to birth date of p as text
            end if

            set fullId to id of p as text
            set AppleScript's text item delimiters to ":"
            set idParts to text items of fullId
            set shortId to item 1 of idParts
            set AppleScript's text item delimiters to ""

            return shortId & tab & my sanitize(first name of p) & tab & my sanitize(last name of p) & tab & my sanitize(organization of p) & tab & my sanitize(job title of p) & tab & my sanitize(nickname of p) & tab & my sanitize(bdText) & tab & my sanitize(note of p) & tab & emailText & tab & phoneText & tab & urlText
        on error
            error "No contact found with id " & targetId
        end try
    end tell
end run
"""
    )
    output = run_osascript(script, [contact_id])
    rows = parse_tsv(output, ["id", "first_name", "last_name", "organization", "job_title", "nickname", "birth_date", "note", "emails", "phones", "urls"])
    if not rows:
        raise ContactsAppError("Unexpected output while viewing contact")
    return rows[0]


def show_contact(contact_id: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Contacts"
        activate
        try
            set p to (first person whose id contains targetId)
            show p
        on error
            error "No contact found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [contact_id])


def create_group(name: str) -> None:
    script = """
on run argv
    set groupName to item 1 of argv
    tell application "Contacts"
        make new group with properties {name:groupName}
    end tell
end run
"""
    run_osascript(script, [name])


def delete_group(name: str) -> None:
    script = """
on run argv
    set groupName to item 1 of argv
    tell application "Contacts"
        delete group groupName
    end tell
end run
"""
    run_osascript(script, [name])


def create_contact(first_name: str, last_name: str, org: str, job: str, nickname: str, note: str, email: str, phone: str) -> None:
    script = """
on run argv
    set fn to item 1 of argv
    set ln to item 2 of argv
    set orgText to item 3 of argv
    set jobText to item 4 of argv
    set nick to item 5 of argv
    set noteText to item 6 of argv
    set emailText to item 7 of argv
    set phoneText to item 8 of argv

    tell application "Contacts"
        set p to make new person with properties {first name:fn, last name:ln}
        if orgText is not "" then set organization of p to orgText
        if jobText is not "" then set job title of p to jobText
        if nick is not "" then set nickname of p to nick
        if noteText is not "" then set note of p to noteText
        if emailText is not "" then
            make new email at end of emails of p with properties {label:"work", value:emailText}
        end if
        if phoneText is not "" then
            make new phone at end of phones of p with properties {label:"mobile", value:phoneText}
        end if
        save
    end tell
end run
"""
    run_osascript(script, [first_name, last_name, org, job, nickname, note, email, phone])


def delete_contact(contact_id: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Contacts"
        try
            set p to (first person whose id contains targetId)
            delete p
            save
        on error
            error "No contact found with id " & targetId
        end try
    end tell
end run
"""
    run_osascript(script, [contact_id])


def cmd_groups_list(args: argparse.Namespace) -> None:
    print_rows(list_groups(), args.json, print_headers=False)


def cmd_groups_create(args: argparse.Namespace) -> None:
    create_group(args.name)
    print(f"Group '{args.name}' created.")


def cmd_groups_delete(args: argparse.Namespace) -> None:
    delete_group(args.name)
    print(f"Group '{args.name}' deleted.")


def cmd_contacts_list(args: argparse.Namespace) -> None:
    rows = list_contacts(args.search, args.group, args.limit, args.order)
    
    formatted_rows = []
    for row in rows:
        formatted_row = {
            "id": row.get("id", ""),
            "first name": row.get("first_name", ""),
            "last name": row.get("last_name", ""),
            "organization": row.get("organization", ""),
        }
        formatted_rows.append(formatted_row)
    
    print_rows(formatted_rows, args.json, columns=["id", "first name", "last name", "organization"])


def cmd_contacts_view(args: argparse.Namespace) -> None:
    row = view_contact(args.id)
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return
    
    for k in CONTACT_DISPLAY_LABELS.keys():
        v = row.get(k, "")
        if v and v != MISSING_VALUE:
            label = CONTACT_DISPLAY_LABELS.get(k, k)
            print(f"{label}: {v}")


def cmd_contacts_show(args: argparse.Namespace) -> None:
    show_contact(args.id)
    print("Contact shown in Contacts app.")


def cmd_contacts_create(args: argparse.Namespace) -> None:
    create_contact(
        args.first_name, args.last_name, args.organization, 
        args.job_title, args.nickname, args.note, 
        args.email, args.phone
    )
    print("Contact created.")


def cmd_contacts_delete(args: argparse.Namespace) -> None:
    delete_contact(args.id)
    print("Contact deleted.")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contacts-app",
        description="macOS Contacts command-line interface powered by AppleScript.",
        formatter_class=SubcommandHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root_subparsers = parser.add_subparsers(dest="resource", required=True, title="commands", metavar="COMMAND")

    # Groups
    groups_parser = root_subparsers.add_parser("groups", help="Group operations", formatter_class=SubcommandHelpFormatter)
    groups_subparsers = groups_parser.add_subparsers(dest="group_command", required=True, title="commands", metavar="COMMAND")

    g_list = groups_subparsers.add_parser("list", aliases=["ls"], help="List groups")
    g_list.add_argument("--json", action="store_true", help="JSON output")
    g_list.set_defaults(func=cmd_groups_list)

    g_create = groups_subparsers.add_parser("create", aliases=["add"], help="Create a group")
    g_create.add_argument("--name", required=True, help="Group name")
    g_create.set_defaults(func=cmd_groups_create)

    g_delete = groups_subparsers.add_parser("delete", aliases=["rm"], help="Delete a group")
    g_delete.add_argument("--name", required=True, help="Group name")
    g_delete.set_defaults(func=cmd_groups_delete)

    # Contacts
    contacts_parser = root_subparsers.add_parser("contacts", aliases=["ct", "cts"], help="Contact operations", formatter_class=SubcommandHelpFormatter)
    contacts_subparsers = contacts_parser.add_subparsers(dest="contact_command", required=True, title="commands", metavar="COMMAND")

    ct_list = contacts_subparsers.add_parser("list", aliases=["ls"], help="List contacts")
    ct_list.add_argument("--search", default="", help="Search by name or organization")
    ct_list.add_argument("--group", default="", help="Filter by group name")
    ct_list.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT, help="Limit")
    ct_list.add_argument("--order", choices=("desc", "asc"), default="asc", help="Order by last name")
    ct_list.add_argument("--json", action="store_true", help="JSON output")
    ct_list.set_defaults(func=cmd_contacts_list)

    ct_view = contacts_subparsers.add_parser("view", aliases=["v"], help="View a contact")
    ct_view.add_argument("--id", required=True, help="Contact ID")
    ct_view.add_argument("--json", action="store_true", help="JSON output")
    ct_view.set_defaults(func=cmd_contacts_view)

    ct_show = contacts_subparsers.add_parser("show", aliases=["open"], help="Show a contact in the Contacts app")
    ct_show.add_argument("--id", required=True, help="Contact ID")
    ct_show.set_defaults(func=cmd_contacts_show)

    ct_create = contacts_subparsers.add_parser("create", aliases=["add"], help="Create a contact")
    ct_create.add_argument("--first-name", required=True, help="First name")
    ct_create.add_argument("--last-name", default="", help="Last name")
    ct_create.add_argument("--organization", default="", help="Organization")
    ct_create.add_argument("--job-title", default="", help="Job title")
    ct_create.add_argument("--nickname", default="", help="Nickname")
    ct_create.add_argument("--note", default="", help="Note")
    ct_create.add_argument("--email", default="", help="Email address")
    ct_create.add_argument("--phone", default="", help="Phone number")
    ct_create.set_defaults(func=cmd_contacts_create)

    ct_delete = contacts_subparsers.add_parser("delete", aliases=["rm"], help="Delete a contact")
    ct_delete.add_argument("--id", required=True, help="Contact ID")
    ct_delete.set_defaults(func=cmd_contacts_delete)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help(sys.stderr)
        return 1
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except ContactsAppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.SubprocessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
