import logging
import sys
import threading
import types
import unittest
from types import SimpleNamespace


if "colorlog" not in sys.modules:
    class _ColoredFormatter(logging.Formatter):
        def __init__(self, *args, **kwargs):
            kwargs.pop("log_colors", None)
            super().__init__(*args, **kwargs)

        def format(self, record):
            if not hasattr(record, "log_color"):
                record.log_color = ""
            return super().format(record)

    sys.modules["colorlog"] = types.SimpleNamespace(ColoredFormatter=_ColoredFormatter)

if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.SimpleNamespace(
        COLOR_BGR2GRAY=0,
        cvtColor=lambda img, mode: img,
        resize=lambda img, size: img,
        absdiff=lambda a, b: a,
    )


from bot.base.task import TaskStatus
from bot.engine.executor import Executor


class _DummyThread:
    def __init__(self, alive=True):
        self._alive = alive
        self.join_called = False

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        self.join_called = True
        self._alive = False


class ExecutorWatchdogTests(unittest.TestCase):
    def _make_executor(self):
        executor = Executor.__new__(Executor)
        executor.active = True
        executor.watchdog_thread = None
        executor.watchdog_stop_event = None
        executor.watchdog_run_id = 0
        executor.watchdog_lock = threading.Lock()
        return executor

    def test_prepare_watchdog_session_stops_previous_event_and_increments_run_id(self):
        executor = self._make_executor()
        old_event = threading.Event()
        old_thread = _DummyThread()
        executor.watchdog_stop_event = old_event
        executor.watchdog_thread = old_thread
        executor.watchdog_run_id = 4

        run_id, stop_event = executor._prepare_watchdog_session()

        self.assertTrue(old_event.is_set())
        self.assertTrue(old_thread.join_called)
        self.assertEqual(run_id, 5)
        self.assertIs(executor.watchdog_stop_event, stop_event)
        self.assertFalse(stop_event.is_set())

    def test_is_watchdog_session_valid_rejects_stale_run_id(self):
        executor = self._make_executor()
        stop_event = threading.Event()
        executor.watchdog_stop_event = stop_event
        executor.watchdog_run_id = 3
        task = SimpleNamespace(task_status=TaskStatus.TASK_STATUS_RUNNING)

        self.assertTrue(executor._is_watchdog_session_valid(3, stop_event, task))
        self.assertFalse(executor._is_watchdog_session_valid(2, stop_event, task))

    def test_stop_watchdog_clears_state_and_sets_event(self):
        executor = self._make_executor()
        stop_event = threading.Event()
        thread = _DummyThread()
        executor.watchdog_stop_event = stop_event
        executor.watchdog_thread = thread
        executor.watchdog_run_id = 7

        executor._stop_watchdog("test")

        self.assertTrue(stop_event.is_set())
        self.assertTrue(thread.join_called)
        self.assertIsNone(executor.watchdog_thread)
        self.assertIsNone(executor.watchdog_stop_event)


if __name__ == "__main__":
    unittest.main()
