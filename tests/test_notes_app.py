import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from apple_cli import notes_app


class NotesAppTests(unittest.TestCase):
    def test_main_no_args_shows_help(self) -> None:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            exit_code = notes_app.main([])
        self.assertEqual(1, exit_code)
        output = buffer.getvalue()
        self.assertIn("usage:", output)
        self.assertIn("notes-app", output)

    def test_run_osascript_success(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        with patch("apple_cli.notes_app.subprocess.run", return_value=completed) as run_mock:
            output = notes_app.run_osascript("script", ["arg1"])
        self.assertEqual("ok", output)
        self.assertEqual(["osascript", "-s", "h", "-", "arg1"], run_mock.call_args.args[0])

    def test_run_osascript_error(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="script failed")
        with patch("apple_cli.notes_app.subprocess.run", return_value=completed):
            with self.assertRaises(notes_app.NotesAppError):
                notes_app.run_osascript("script", [])

    def test_run_osascript_timeout(self) -> None:
        with patch(
            "apple_cli.notes_app.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=30),
        ):
            with self.assertRaises(notes_app.NotesAppError):
                notes_app.run_osascript("script", [])

    def test_notes_list_defaults(self) -> None:
        with patch("apple_cli.notes_app.list_notes", return_value=[]) as list_mock:
            exit_code = notes_app.main(["notes", "list"])
        self.assertEqual(0, exit_code)
        # Positional arguments: folder_name, limit, order
        self.assertEqual("", list_mock.call_args.args[0])
        self.assertEqual(notes_app.DEFAULT_LIST_LIMIT, list_mock.call_args.args[1])
        self.assertEqual("desc", list_mock.call_args.args[2])

    def test_view_note(self) -> None:
        buffer = io.StringIO()
        # id, name, body, plaintext, creation_date, modification_date, folder
        mock_output = "1\tName\tBody\tPlaintext\t2026-01-01\t2026-01-02\tFolder"
        with patch(
            "apple_cli.notes_app.run_osascript",
            return_value=mock_output,
        ), redirect_stdout(buffer):
            exit_code = notes_app.main(["notes", "view", "--id", "1"])
        self.assertEqual(0, exit_code)
        output = buffer.getvalue()
        self.assertIn("id: 1", output)
        self.assertIn("name: Name", output)
        self.assertIn("creation date: 2026-01-01", output)
        self.assertIn("Plaintext", output)
        self.assertNotIn("Body", output)

    def test_show_note(self) -> None:
        with patch("apple_cli.notes_app.run_osascript") as script_mock:
            exit_code = notes_app.main(["notes", "show", "--id", "123"])
        self.assertEqual(0, exit_code)
        script_mock.assert_called_once()
        self.assertIn("show aNote", script_mock.call_args[0][0])
        self.assertIn("activate", script_mock.call_args[0][0])

    def test_delete_folder(self) -> None:
        with patch("apple_cli.notes_app.run_osascript") as script_mock:
            exit_code = notes_app.main(["folders", "delete", "--name", "Old Folder"])
        self.assertEqual(0, exit_code)
        script_mock.assert_called_once()
        self.assertIn("delete folder folderName", script_mock.call_args[0][0])
        self.assertEqual("Old Folder", script_mock.call_args[0][1][0])

    def test_subprocess_failure_returns_nonzero(self) -> None:
        with patch("apple_cli.notes_app.run_osascript", side_effect=subprocess.SubprocessError("spawn failed")):
            code = notes_app.main(["notes", "list"])
        self.assertEqual(1, code)


if __name__ == "__main__":
    unittest.main()
