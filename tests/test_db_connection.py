import unittest
from unittest.mock import Mock, patch

from apps.db.connection import get_db_cursor


class DatabaseCursorTransactionTests(unittest.TestCase):
    def test_read_only_cursor_rolls_back_before_releasing_connection(self):
        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor

        with patch("apps.db.connection.get_db_connection", return_value=connection), patch(
            "apps.db.connection.release_db_connection"
        ) as release:
            with get_db_cursor(commit=False) as received_cursor:
                self.assertIs(received_cursor, cursor)

        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        cursor.close.assert_called_once_with()
        release.assert_called_once_with(connection)

    def test_write_cursor_commits_before_releasing_connection(self):
        connection = Mock()
        cursor = Mock()
        connection.cursor.return_value = cursor

        with patch("apps.db.connection.get_db_connection", return_value=connection), patch(
            "apps.db.connection.release_db_connection"
        ) as release:
            with get_db_cursor(commit=True):
                pass

        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        cursor.close.assert_called_once_with()
        release.assert_called_once_with(connection)


if __name__ == "__main__":
    unittest.main()
