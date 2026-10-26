#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Hardware-free argument and lifecycle tests for the X11 preview host."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import types
import unittest
from unittest import mock


HELPER = (Path(__file__).resolve().parents[1] /
          "files/edge-ai-gst-x11-preview")
LOADER = importlib.machinery.SourceFileLoader("x11_preview", str(HELPER))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
PREVIEW = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(PREVIEW)


class X11PreviewTests(unittest.TestCase):
    def test_help_does_not_need_gi_or_display(self):
        result = subprocess.run(
            [sys.executable, "-B", str(HELPER), "--help"],
            env={"PATH": os.environ["PATH"]}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--fullscreen", result.stdout)

    def test_missing_pipeline_fails_without_starting_runtime(self):
        with mock.patch.object(PREVIEW, "run_pipeline") as run:
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    PREVIEW.main([])
        self.assertEqual(error.exception.code, 2)
        run.assert_not_called()

    def test_tokens_are_forwarded_literally_with_fullscreen(self):
        tokens = ["videotestsrc", "!", "nv3dsink", "name=edge_ai_preview",
                  "literal=$(touch SHOULD_NOT_EXIST); quoted 'text'"]
        with mock.patch.object(PREVIEW, "run_pipeline", return_value=0) as run:
            self.assertEqual(PREVIEW.main(["--fullscreen", "--", *tokens]), 0)
        run.assert_called_once_with(tokens, True)

    def test_runtime_error_is_reported_as_failure(self):
        with mock.patch.object(PREVIEW, "run_pipeline",
                               side_effect=RuntimeError("display unavailable")):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(PREVIEW.main(["videotestsrc"]), 1)
        self.assertIn("display unavailable", stderr.getvalue())

    def bindings(self, event="eos", overlay=True, start_failure=False):
        state = types.SimpleNamespace(handler=None, signals={}, lifecycle=[])

        class Display:
            @staticmethod
            def get_default():
                return Display()

        class NativeWindow:
            @staticmethod
            def get_xid(window):
                self.assertIsInstance(window, NativeWindow)
                return 321

        class Overlay:
            @staticmethod
            def set_window_handle(sink, xid):
                state.lifecycle.append(("handle", xid))

            @staticmethod
            def expose(sink):
                pass

        sink = Overlay() if overlay else object()
        bus = mock.Mock()

        def connect_bus(name, callback):
            self.assertEqual(name, "message")
            state.handler = callback
            return 7

        bus.connect.side_effect = connect_bus
        pipeline = mock.Mock()
        pipeline.get_by_name.return_value = sink
        pipeline.get_bus.return_value = bus

        def set_state(value):
            state.lifecycle.append(("state", value))
            return "failure" if start_failure and value == "playing" else "ok"

        pipeline.set_state.side_effect = set_state
        gst = types.SimpleNamespace(
            init=mock.Mock(), parse_launchv=mock.Mock(return_value=pipeline),
            State=types.SimpleNamespace(PLAYING="playing", NULL="null"),
            StateChangeReturn=types.SimpleNamespace(FAILURE="failure"),
            MessageType=types.SimpleNamespace(ERROR="error", EOS="eos"))
        window = mock.Mock()
        drawing = mock.Mock()
        drawing.get_window.return_value = NativeWindow()

        def main():
            if event == "signal":
                state.signals[signal.SIGTERM]()
            else:
                message = types.SimpleNamespace(type=event)
                message.parse_error = lambda: ("camera failure", "details")
                state.handler(bus, message)

        gtk = types.SimpleNamespace(
            init_check=lambda: (True, []),
            Window=mock.Mock(return_value=window),
            DrawingArea=mock.Mock(return_value=drawing), main=main,
            main_quit=mock.Mock())

        def unix_signal_add(_priority, signum, callback):
            state.signals[signum] = callback
            return len(state.signals)

        context = types.SimpleNamespace(
            find_source_by_id=lambda _source: object())
        glib = types.SimpleNamespace(
            SOURCE_REMOVE=False, PRIORITY_DEFAULT=0,
            unix_signal_add=unix_signal_add, source_remove=mock.Mock(),
            MainContext=types.SimpleNamespace(default=lambda: context))
        repository = types.ModuleType("gi.repository")
        repository.Gdk = types.SimpleNamespace(Display=Display,
                                              KEY_Escape=65307)
        repository.GdkX11 = types.SimpleNamespace(X11Display=Display,
                                                X11Window=NativeWindow)
        repository.GLib = glib
        repository.Gst = gst
        repository.GstVideo = types.SimpleNamespace(VideoOverlay=Overlay)
        repository.Gtk = gtk
        gi = types.ModuleType("gi")
        gi.require_version = mock.Mock()
        return ({"gi": gi, "gi.repository": repository}, state, pipeline,
                bus, window, gst, gtk, glib)

    def test_overlay_is_bound_before_playing_and_eos_cleans_up(self):
        modules, state, pipeline, bus, window, gst, gtk, glib = self.bindings()
        tokens = ["videotestsrc", "!", "nv3dsink", "name=edge_ai_preview"]
        with mock.patch.dict(sys.modules, modules):
            with mock.patch.dict(os.environ, {"DISPLAY": ":fixture"}):
                self.assertEqual(PREVIEW.run_pipeline(tokens, True), 0)
        gst.parse_launchv.assert_called_once_with(tokens)
        self.assertEqual(
            modules["gi"].require_version.call_args_list,
            [mock.call("Gtk", "3.0"), mock.call("Gdk", "3.0"),
             mock.call("GdkX11", "3.0"), mock.call("Gst", "1.0"),
             mock.call("GstVideo", "1.0")])
        self.assertEqual(state.lifecycle,
                         [("handle", 321), ("state", "playing"),
                          ("state", "null")])
        window.fullscreen.assert_called_once_with()
        window.destroy.assert_called_once_with()
        bus.disconnect.assert_called_once_with(7)
        bus.remove_signal_watch.assert_called_once_with()
        gtk.main_quit.assert_called_once_with()
        self.assertEqual(glib.source_remove.call_count, 2)

    def test_bus_error_is_nonzero_and_stops_pipeline(self):
        modules, state, pipeline, bus, window, gst, gtk, glib = self.bindings(
            event="error")
        with mock.patch.dict(sys.modules, modules):
            with mock.patch.dict(os.environ, {"DISPLAY": ":fixture"}):
                with contextlib.redirect_stderr(io.StringIO()) as stderr:
                    self.assertEqual(PREVIEW.run_pipeline(["fixture"]), 1)
        self.assertIn("camera failure", stderr.getvalue())
        self.assertEqual(state.lifecycle[-1], ("state", "null"))
        window.destroy.assert_called_once_with()

    def test_signal_stops_without_claiming_camera_failure(self):
        modules, state, pipeline, bus, window, gst, gtk, glib = self.bindings(
            event="signal")
        with mock.patch.dict(sys.modules, modules):
            with mock.patch.dict(os.environ, {"DISPLAY": ":fixture"}):
                self.assertEqual(PREVIEW.run_pipeline(["fixture"]), 0)
        self.assertEqual(state.lifecycle[-1], ("state", "null"))

    def test_invalid_sink_and_start_failure_still_stop_pipeline(self):
        for options in ({"overlay": False}, {"start_failure": True}):
            with self.subTest(options=options):
                result = self.bindings(**options)
                modules, state, pipeline, bus, window, gst, gtk, glib = result
                with mock.patch.dict(sys.modules, modules):
                    with mock.patch.dict(os.environ, {"DISPLAY": ":fixture"}):
                        with self.assertRaises(RuntimeError):
                            PREVIEW.run_pipeline(["fixture"])
                self.assertEqual(state.lifecycle[-1], ("state", "null"))


if __name__ == "__main__":
    unittest.main()
