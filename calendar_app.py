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
MISSING_VALUE = "missing value"

CALENDAR_DISPLAY_LABELS = {
    "id": "id",
    "summary": "summary",
    "start_date": "start date",
    "end_date": "end date",
    "location": "location",
    "allday": "all-day",
    "url": "url",
    "calendar": "calendar",
    "alarms": "alarms"
}


class CalendarAppError(RuntimeError):
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
        raise CalendarAppError(
            "AppleScript request timed out. Check Calendar automation permissions and retry "
            "with narrower scope (for example --calendar)."
        ) from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"osascript exited with code {result.returncode}"
        raise CalendarAppError(detail)
    return result.stdout.rstrip("\n")


def parse_tsv(output: str, field_names: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not output.strip():
        return rows
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != len(field_names):
            raise CalendarAppError("Unexpected AppleScript output format")
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


def list_calendars() -> list[dict[str, str]]:
    script = (
        script_helpers()
        + """
on run argv
    set outText to ""
    tell application "Calendar"
        set calCount to count of every calendar
        repeat with i from 1 to calCount
            set calRef to calendar i
            set calName to name of calRef
            set outText to my emitRow(outText, calName & tab & my sanitize(calName))
        end repeat
    end tell
    return outText
end run
"""
    )
    output = run_osascript(script, [])
    return parse_tsv(output, ["id", "name"])


def normalize_event_id(event_id: str) -> str:
    # Calendar IDs can be complex, but they often don't have a standard URI prefix like reminders
    # We will assume the ID is used directly.
    return event_id


def list_events(
    calendar_name: str,
    start_after: str,
    start_before: str,
    limit: int | None,
    order: str,
) -> list[dict[str, str]]:
    max_count = "" if limit is None else str(limit)
    script = (
        script_helpers()
        + """
on run argv
    set targetCalName to item 1 of argv
    set startAfterText to item 2 of argv
    set startBeforeText to item 3 of argv
    set maxCountText to item 4 of argv
    set sortOrder to item 5 of argv

    set outText to ""
    set remainingCount to -1
    if maxCountText is not "" then
        set remainingCount to maxCountText as integer
    end if

    set startAfterDate to missing value
    if startAfterText is not "" then
        set startAfterDate to date startAfterText
    end if

    set startBeforeDate to missing value
    if startBeforeText is not "" then
        set startBeforeDate to date startBeforeText
    end if

    if startAfterText is "" and startBeforeText is "" then
        set startAfterDate to current date
    end if

    tell application "Calendar"
        if targetCalName is "" then
            set targetCalendars to every calendar
        else
            set targetCalendars to {calendar targetCalName}
        end if

        repeat with aCal in targetCalendars
            if remainingCount is 0 then
                exit repeat
            end if
            
            tell aCal
                set refEvents to a reference to every event
                
                -- Manual filtering because whose clauses with dates can be flaky in Calendar
                set matchingEvents to {}
                repeat with anEvent in refEvents
                    set ok to true
                    set sd to start date of anEvent
                    if startAfterDate is not missing value and sd < startAfterDate then
                        set ok to false
                    end if
                    if startBeforeDate is not missing value and sd > startBeforeDate then
                        set ok to false
                    end if
                    if ok then
                        copy anEvent to end of matchingEvents
                    end if
                end repeat

                set eventCount to count of matchingEvents
                if eventCount > 0 then
                    set calLabel to my sanitize(name)
                    
                    if sortOrder is "asc" then
                        set startIndex to 1
                        set endIndex to eventCount
                        set stepValue to 1
                    else
                        set startIndex to eventCount
                        set endIndex to 1
                        set stepValue to -1
                    end if

                    repeat with i from startIndex to endIndex by stepValue
                        if remainingCount is 0 then
                            exit repeat
                        end if

                        set anEvent to item i of matchingEvents
                        set sd to start date of anEvent
                        set ed to end date of anEvent
                        set diffSeconds to (ed - sd)
                        set durationText to ""
                        if diffSeconds < 3600 then
                            set durationText to ((diffSeconds / 60) as integer as text) & "m"
                        else if diffSeconds < 86400 then
                            set durationText to ((diffSeconds / 3600) as integer as text) & "h"
                        else
                            set durationText to ((diffSeconds / 86400) as integer as text) & "d"
                        end if
                        
                        set rowText to (id of anEvent as text) & tab & my sanitize(summary of anEvent) & tab & (sd as text) & tab & durationText & tab & my sanitize(location of anEvent) & tab & calLabel
                        set outText to my emitRow(outText, rowText)
                        
                        if remainingCount > 0 then
                            set remainingCount to remainingCount - 1
                        end if
                    end repeat
                end if
            end tell
        end repeat
    end tell

    return outText
end run
"""
    )
    output = run_osascript(
        script,
        [calendar_name, start_after, start_before, max_count, order],
    )
    return parse_tsv(
        output,
        ["id", "summary", "start_date", "duration", "location", "calendar"],
    )


def view_event(event_id: str) -> dict[str, str]:
    script = (
        script_helpers()
        + """
on run argv
    set targetId to item 1 of argv
    tell application "Calendar"
        repeat with aCal in every calendar
            try
                set anEvent to event id targetId of aCal
                set calName to name of aCal
                
                set alarmList to {}
                repeat with anAlarm in every display alarm of anEvent
                    copy (trigger interval of anAlarm as text) to end of alarmList
                end repeat
                set alarmText to ""
                set AppleScript's text item delimiters to ", "
                set alarmText to alarmList as text
                set AppleScript's text item delimiters to ""

                return (id of anEvent as text) & tab & my sanitize(summary of anEvent) & tab & (start date of anEvent as text) & tab & (end date of anEvent as text) & tab & my sanitize(location of anEvent) & tab & my sanitize(description of anEvent) & tab & (allday event of anEvent as text) & tab & my sanitize(url of anEvent) & tab & my sanitize(calName) & tab & alarmText
            end try
        end repeat
        error "No event found with id " & targetId
    end tell
end run
"""
    )
    output = run_osascript(script, [event_id])
    rows = parse_tsv(
        output,
        ["id", "summary", "start_date", "end_date", "location", "description", "allday", "url", "calendar", "alarms"],
    )
    if not rows:
        raise CalendarAppError("Unexpected output while viewing event")
    return rows[0]


def show_event(event_id: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Calendar"
        repeat with aCal in every calendar
            try
                set anEvent to event id targetId of aCal
                show anEvent
                activate
                return
            end try
        end repeat
        error "No event found with id " & targetId
    end tell
end run
"""
    run_osascript(script, [event_id])


def create_calendar(name: str) -> None:
    script = """
on run argv
    set calName to item 1 of argv
    tell application "Calendar"
        make new calendar with properties {name:calName}
    end tell
end run
"""
    run_osascript(script, [name])


def rename_calendar(old_name: str, new_name: str) -> None:
    script = """
on run argv
    set oldName to item 1 of argv
    set newName to item 2 of argv
    tell application "Calendar"
        set name of calendar oldName to newName
    end tell
end run
"""
    run_osascript(script, [old_name, new_name])


def delete_calendar(name: str) -> None:
    script = """
on run argv
    set calName to item 1 of argv
    tell application "Calendar"
        delete calendar calName
    end tell
end run
"""
    run_osascript(script, [name])


def create_event(
    summary: str,
    start_date: str,
    end_date: str,
    duration_str: str,
    location: str,
    description: str,
    allday: bool,
    url: str,
    calendar_name: str,
    alarm_minutes: int | None,
) -> None:
    allday_text = "true" if allday else "false"
    alarm_val = str(alarm_minutes) if alarm_minutes is not None else ""
    script = """
on run argv
    set summaryText to item 1 of argv
    set startText to item 2 of argv
    set endText to item 3 of argv
    set durationText to item 4 of argv
    set locText to item 5 of argv
    set descText to item 6 of argv
    set alldayVal to item 7 of argv is "true"
    set urlText to item 8 of argv
    set calName to item 9 of argv
    set alarmMin to item 10 of argv

    tell application "Calendar"
        if calName is "" then
            set targetCal to first calendar
        else
            set targetCal to calendar calName
        end if
    end tell

    set startDateObj to date startText
    set endDateObj to missing value
    
    if endText is not "" then
        set endDateObj to date endText
    else if durationText is not "" then
        set lastChar to character -1 of durationText
        set numPart to text 1 thru -2 of durationText as integer
        set multiplier to 60
        if lastChar is "m" then
            set multiplier to 60
        else if lastChar is "h" then
            set multiplier to 3600
        else if lastChar is "d" then
            set multiplier to 86400
        end if
        set endDateObj to startDateObj + (numPart * multiplier)
    else
        -- Default to 1 hour if neither specified
        set endDateObj to startDateObj + 3600
    end if

    tell application "Calendar"
        set newEvent to make new event at end of events of targetCal with properties {summary:summaryText, start date:startDateObj, end date:endDateObj, allday event:alldayVal}
        
        if locText is not "" then set location of newEvent to locText
        if descText is not "" then set description of newEvent to descText
        if urlText is not "" then set url of newEvent to urlText
        
        if alarmMin is not "" then
            make new display alarm at end of display alarms of newEvent with properties {trigger interval:-(alarmMin as integer)}
        end if
    end tell
end run
"""
    run_osascript(script, [summary, start_date, end_date, duration_str, location, description, allday_text, url, calendar_name, alarm_val])


def update_event(
    event_id: str,
    summary: str,
    start_date: str,
    end_date: str,
    duration_str: str,
    location: str,
    description: str,
    allday: bool | None,
    url: str,
    calendar_name: str,
) -> None:
    allday_text = ""
    if allday is True:
        allday_text = "true"
    elif allday is False:
        allday_text = "false"

    script = """
on run argv
    set targetId to item 1 of argv
    set summaryText to item 2 of argv
    set startText to item 3 of argv
    set endText to item 4 of argv
    set durationText to item 5 of argv
    set locText to item 6 of argv
    set descText to item 7 of argv
    set alldayVal to item 8 of argv
    set urlText to item 9 of argv
    set targetCalName to item 10 of argv

    set startDateObj to missing value
    
    tell application "Calendar"
        set foundRef to missing value
        repeat with aCal in every calendar
            try
                set foundRef to event id targetId of aCal
                exit repeat
            end try
        end repeat
        if foundRef is missing value then error "No event found with id " & targetId
        
        set startDateObj to start date of foundRef
        set endDateObj to end date of foundRef
    end tell

    if startText is not "" then set startDateObj to date startText
    
    if endText is not "" then
        set endDateObj to date endText
    else if durationText is not "" then
        set lastChar to character -1 of durationText
        set numPart to text 1 thru -2 of durationText as integer
        set multiplier to 60
        if lastChar is "m" then
            set multiplier to 60
        else if lastChar is "h" then
            set multiplier to 3600
        else if lastChar is "d" then
            set multiplier to 86400
        end if
        set endDateObj to startDateObj + (numPart * multiplier)
    end if

    tell application "Calendar"
        -- Re-fetching to be safe after potential date calculations
        set found to false
        repeat with aCal in every calendar
            try
                set anEvent to event id targetId of aCal
                if summaryText is not "" then set summary of anEvent to summaryText
                set start date of anEvent to startDateObj
                set end date of anEvent to endDateObj
                if locText is not "" then set location of anEvent to locText
                if descText is not "" then set description of anEvent to descText
                if alldayVal is "true" then
                    set allday event of anEvent to true
                else if alldayVal is "false" then
                    set allday event of anEvent to false
                end if
                if urlText is not "" then set url of anEvent to urlText
                
                if targetCalName is not "" then
                    move anEvent to end of events of calendar targetCalName
                end if
                set found to true
                exit repeat
            end try
        end repeat
        if not found then error "No event found with id " & targetId
    end tell
end run
"""
    run_osascript(script, [event_id, summary, start_date, end_date, duration_str, location, description, allday_text, url, calendar_name])


def delete_event(event_id: str) -> None:
    script = """
on run argv
    set targetId to item 1 of argv
    tell application "Calendar"
        repeat with aCal in every calendar
            try
                delete event id targetId of aCal
                return
            end try
        end repeat
        error "No event found with id " & targetId
    end tell
end run
"""
    run_osascript(script, [event_id])


def cmd_calendars_list(args: argparse.Namespace) -> None:
    print_rows(list_calendars(), args.json, columns=["name"], print_headers=False)


def cmd_calendars_create(args: argparse.Namespace) -> None:
    create_calendar(args.name)
    print(f"Calendar '{args.name}' created.")


def cmd_calendars_rename(args: argparse.Namespace) -> None:
    rename_calendar(args.calendar, args.new_name)
    print(f"Calendar renamed to '{args.new_name}'.")


def cmd_calendars_delete(args: argparse.Namespace) -> None:
    delete_calendar(args.calendar)
    print(f"Calendar '{args.calendar}' deleted.")


def cmd_events_list(args: argparse.Namespace) -> None:
    rows = list_events(
        calendar_name=args.calendar,
        start_after=args.start_after,
        start_before=args.start_before,
        limit=args.limit,
        order=args.order,
    )
    
    formatted_rows = []
    for row in rows:
        formatted_row = {
            "id": row.get("id", ""),
            "summary": row.get("summary", ""),
            "start date": row.get("start_date", ""),
            "duration": row.get("duration", ""),
            "location": row.get("location", ""),
            "calendar": row.get("calendar", ""),
        }
        formatted_rows.append(formatted_row)

    print_rows(formatted_rows, args.json, columns=["id", "summary", "start date", "duration", "location", "calendar"])


def cmd_events_view(args: argparse.Namespace) -> None:
    row = view_event(args.id)
    if args.json:
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return

    for k in CALENDAR_DISPLAY_LABELS.keys():
        v = row.get(k, "")
        if v and v != MISSING_VALUE:
            label = CALENDAR_DISPLAY_LABELS.get(k, k)
            print(f"{label}: {v}")

    if row.get("description"):
        print("")
        print(row["description"])


def cmd_events_show(args: argparse.Namespace) -> None:
    show_event(args.id)
    print("Event shown in Calendar app.")


def cmd_events_create(args: argparse.Namespace) -> None:
    create_event(
        summary=args.summary,
        start_date=args.start_date,
        end_date=args.end_date or "",
        duration_str=args.duration or "",
        location=args.location,
        description=args.notes,
        allday=args.all_day,
        url=args.url,
        calendar_name=args.calendar,
        alarm_minutes=args.alarm,
    )
    print("Event created.")


def cmd_events_update(args: argparse.Namespace) -> None:
    allday = None
    if args.all_day:
        allday = True
    elif args.no_all_day:
        allday = False

    if not any([args.summary, args.start_date, args.end_date, args.duration, args.location, args.notes, args.url, args.calendar, allday is not None]):
        args.parser_obj.error("Provide at least one field to update")

    update_event(
        event_id=args.id,
        summary=args.summary,
        start_date=args.start_date,
        end_date=args.end_date or "",
        duration_str=args.duration or "",
        location=args.location,
        description=args.notes,
        allday=allday,
        url=args.url,
        calendar_name=args.calendar,
    )
    print("Event updated.")


def cmd_events_delete(args: argparse.Namespace) -> None:
    delete_event(args.id)
    print("Event deleted.")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="calendar-app",
        description="Apple Calendar command-line interface powered by AppleScript.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root_subparsers = parser.add_subparsers(dest="resource", required=True)

    # Calendars
    calendars_parser = root_subparsers.add_parser("calendars", aliases=["cal", "cals"], help="Calendar operations")
    calendars_subparsers = calendars_parser.add_subparsers(dest="calendar_command", required=True)

    cal_list = calendars_subparsers.add_parser("list", aliases=["ls"], help="List calendars")
    cal_list.add_argument("--json", action="store_true", help="JSON output")
    cal_list.set_defaults(func=cmd_calendars_list)

    cal_create = calendars_subparsers.add_parser("create", aliases=["add"], help="Create a calendar")
    cal_create.add_argument("--name", required=True, help="Calendar name")
    cal_create.set_defaults(func=cmd_calendars_create)

    cal_rename = calendars_subparsers.add_parser("rename", help="Rename a calendar")
    cal_rename.add_argument("--calendar", required=True, help="Current name")
    cal_rename.add_argument("--new-name", required=True, help="New name")
    cal_rename.set_defaults(func=cmd_calendars_rename)

    cal_delete = calendars_subparsers.add_parser("delete", aliases=["rm"], help="Delete a calendar")
    cal_delete.add_argument("--calendar", required=True, help="Calendar name")
    cal_delete.set_defaults(func=cmd_calendars_delete)

    # Events
    events_parser = root_subparsers.add_parser("events", aliases=["ev", "evs"], help="Event operations")
    events_subparsers = events_parser.add_subparsers(dest="event_command", required=True)

    ev_list = events_subparsers.add_parser("list", aliases=["ls"], help="List events")
    ev_list.add_argument("--calendar", default="", help="Calendar name")
    ev_list.add_argument("--start-after", default="", help="Start date after")
    ev_list.add_argument("--start-before", default="", help="Start date before")
    ev_list.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT, help="Limit")
    ev_list.add_argument("--order", choices=("desc", "asc"), default="desc", help="Order")
    ev_list.add_argument("--json", action="store_true", help="JSON output")
    ev_list.set_defaults(func=cmd_events_list)

    ev_view = events_subparsers.add_parser("view", aliases=["v"], help="View an event")
    ev_view.add_argument("--id", required=True, help="Event ID")
    ev_view.add_argument("--json", action="store_true", help="JSON output")
    ev_view.set_defaults(func=cmd_events_view)

    ev_show = events_subparsers.add_parser(
        "show",
        aliases=["open"],
        help="Show an event in the Calendar app",
        description="Reveal one event by id in the macOS Calendar application.",
    )
    ev_show.add_argument("--id", required=True, help="Event ID")
    ev_show.set_defaults(func=cmd_events_show)

    ev_create = events_subparsers.add_parser("create", aliases=["add"], help="Create an event")
    ev_create.add_argument("--summary", required=True, help="Summary")
    ev_create.add_argument("--start-date", required=True, help="Start date/time")
    end_group = ev_create.add_mutually_exclusive_group()
    end_group.add_argument("--end-date", help="End date/time")
    end_group.add_argument("--duration", help="Duration (e.g. 15m, 2h, 1d)")
    ev_create.add_argument("--location", default="", help="Location")
    ev_create.add_argument("--notes", default="", help="Description/notes")
    ev_create.add_argument("--all-day", action="store_true", help="All-day event")
    ev_create.add_argument("--url", default="", help="URL")
    ev_create.add_argument("--calendar", default="", help="Calendar name")
    ev_create.add_argument("--alarm", type=int, help="Display alarm (minutes before)")
    ev_create.set_defaults(func=cmd_events_create)

    ev_update = events_subparsers.add_parser("update", aliases=["set"], help="Update an event")
    ev_update.add_argument("--id", required=True, help="Event ID")
    ev_update.add_argument("--summary", default="", help="New summary")
    ev_update.add_argument("--start-date", default="", help="New start date")
    end_group = ev_update.add_mutually_exclusive_group()
    end_group.add_argument("--end-date", help="New end date")
    end_group.add_argument("--duration", help="New duration (e.g. 15m, 2h, 1d)")
    ev_update.add_argument("--location", default="", help="New location")
    ev_update.add_argument("--notes", default="", help="New notes")
    ev_update.add_argument("--url", default="", help="New URL")
    ev_update.add_argument("--calendar", default="", help="Move to calendar")
    ev_all_day_group = ev_update.add_mutually_exclusive_group()
    ev_all_day_group.add_argument("--all-day", action="store_true", help="Set as all-day")
    ev_all_day_group.add_argument("--no-all-day", action="store_true", help="Set as not all-day")
    ev_update.set_defaults(func=cmd_events_update)

    ev_delete = events_subparsers.add_parser("delete", aliases=["rm"], help="Delete an event")
    ev_delete.add_argument("--id", required=True, help="Event ID")
    ev_delete.set_defaults(func=cmd_events_delete)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CalendarAppError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.SubprocessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
