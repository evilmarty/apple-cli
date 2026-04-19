import io
import subprocess
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from apple_cli import calendar_app


class CalendarAppTests(unittest.TestCase):
    def test_run_osascript_success(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        with patch("apple_cli.calendar_app.subprocess.run", return_value=completed) as run_mock:
            output = calendar_app.run_osascript("script", ["arg1"])
        self.assertEqual("ok", output)
        self.assertEqual(["osascript", "-s", "h", "-", "arg1"], run_mock.call_args.args[0])

    def test_run_osascript_error(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="script failed")
        with patch("apple_cli.calendar_app.subprocess.run", return_value=completed):
            with self.assertRaises(calendar_app.CalendarAppError):
                calendar_app.run_osascript("script", [])

    def test_run_osascript_timeout(self) -> None:
        with patch(
            "apple_cli.calendar_app.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30),
        ):
            with self.assertRaises(calendar_app.CalendarAppError):
                calendar_app.run_osascript("script", [])

    def test_events_list_defaults(self) -> None:
        with patch("apple_cli.calendar_app.list_events", return_value=[]) as list_mock:
            exit_code = calendar_app.main(["events", "list"])
        self.assertEqual(0, exit_code)
        self.assertEqual("", list_mock.call_args.kwargs["calendar_name"])
        self.assertEqual("", list_mock.call_args.kwargs["start_after"])
        self.assertEqual("", list_mock.call_args.kwargs["start_before"])
        self.assertEqual(calendar_app.DEFAULT_LIST_LIMIT, list_mock.call_args.kwargs["limit"])
        self.assertEqual("desc", list_mock.call_args.kwargs["order"])

    def test_events_list_filters(self) -> None:
        with patch("apple_cli.calendar_app.list_events", return_value=[]) as list_mock:
            exit_code = calendar_app.main(["events", "list", "--calendar", "Work", "--start-after", "2026-01-01"])
        self.assertEqual(0, exit_code)
        self.assertEqual("Work", list_mock.call_args.kwargs["calendar_name"])
        self.assertEqual("2026-01-01", list_mock.call_args.kwargs["start_after"])

    def test_view_event(self) -> None:
        buffer = io.StringIO()
        # Updated mock to match the 10 columns: id, summary, start_date, end_date, location, description, allday, url, calendar, alarms
        mock_output = "1\tSummary\t2026-04-18\t2026-04-18\tLocation\tNotes\tfalse\thttp://example.com\tCalendar\t-15"
        with patch(
            "apple_cli.calendar_app.run_osascript",
            return_value=mock_output,
        ), redirect_stdout(buffer):
            exit_code = calendar_app.main(["events", "view", "--id", "1"])
        self.assertEqual(0, exit_code)
        output = buffer.getvalue()
        self.assertIn("id: 1", output)
        self.assertIn("summary: Summary", output)
        self.assertIn("Notes", output)

    def test_events_create_duration(self) -> None:
        with patch("apple_cli.calendar_app.create_event") as create_mock:
            exit_code = calendar_app.main([
                "events", "create", 
                "--summary", "Meeting", 
                "--start-date", "2026-05-01 10:00", 
                "--duration", "1h"
            ])
        self.assertEqual(0, exit_code)
        create_mock.assert_called_once()
        self.assertEqual("1h", create_mock.call_args.kwargs["duration_str"])
        self.assertEqual("", create_mock.call_args.kwargs["end_date"])

    def test_show_event(self) -> None:
        with patch("apple_cli.calendar_app.run_osascript") as script_mock:
            exit_code = calendar_app.main(["events", "show", "--id", "123"])
        self.assertEqual(0, exit_code)
        script_mock.assert_called_once()
        self.assertIn("show anEvent", script_mock.call_args[0][0])
        self.assertIn("activate", script_mock.call_args[0][0])

    def test_subprocess_failure_returns_nonzero(self) -> None:
        with patch("apple_cli.calendar_app.run_osascript", side_effect=subprocess.SubprocessError("spawn failed")):
            code = calendar_app.main(["events", "list"])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
