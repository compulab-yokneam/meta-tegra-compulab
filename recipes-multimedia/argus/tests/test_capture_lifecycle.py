#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compile real patched Argus capture code against host-only GUI/camera mocks.

Set ARGUS_CAPTURE_SOURCE to an unpacked R39.2.1 jetson_multimedia_api source
directory. The current workspace's standard recipe source is used if present.
Sources are copied and patched in a temporary directory; no camera, display,
root privileges, target build, or NVIDIA runtime is used. Missing source or
host C++ compiler is reported as a skip, never a camera validation success.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


DIRECTORY = Path(__file__).resolve().parents[1]
PATCH = DIRECTORY / "files/0006-argus-camera-clean-up-partial-capture-start.patch"
WORKSPACE = DIRECTORY.parents[3]
DEFAULT_SOURCE = (
    WORKSPACE / "build-edge-ai-nx-16g/tmp/work/aarch64_tegra234-oe4t-linux"
    / "argus-samples/39.2.1-20260806224157/sources/tegra-mmapi"
    / "usr/src/jetson_multimedia_api"
)

MOCKS = r'''
#ifndef CAPTURE_LIFECYCLE_MOCKS_H
#define CAPTURE_LIFECYCLE_MOCKS_H
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace ArgusSamples {
bool failStart = false, failStop = false, failAction = false;
bool failAdd = false, failRegister = false, failDetach = false;
int gridsCreated = 0, gridsDeleted = 0, capturesStarted = 0;
int capturesStopped = 0, observerAdds = 0, observerRemoves = 0;
std::vector<void*> attached;

template<typename T> class UniquePointer {
    T *pointer;
public:
    explicit UniquePointer(T *value = NULL) : pointer(value) {}
    ~UniquePointer() { delete pointer; }
    T *get() const { return pointer; }
    T **operator&() { assert(pointer == NULL); return &pointer; }
    T *release() { T *value = pointer; pointer = NULL; return value; }
    void reset(T *value = NULL) { delete pointer; pointer = value; }
    explicit operator bool() const { return pointer != NULL; }
};
template<typename T> class Value {};
enum StillFileType { JPEG };

class Window {
public:
    struct IKeyObserver {
        struct Key {
            std::string text;
            explicit Key(const char *value) : text(value) {}
            bool operator==(const Key &other) const { return text == other.text; }
        };
        virtual ~IKeyObserver() {}
        virtual bool onKey(const Key &) = 0;
    };
    struct IGuiElement {
        enum ValueTypeEnum { VALUE_ZERO };
        enum { FLAG_NONE, ICON_NONE };
        virtual ~IGuiElement() {}
        template<typename T>
        static bool createValue(Value<T> *, IGuiElement **element) {
            *element = new IGuiElement(); return true;
        }
        static bool createAction(const char *, bool (*)(void *, const char *),
                                 void *, int, int, IGuiElement **element) {
            if (failAction) return false;
            *element = new IGuiElement(); return true;
        }
    };
    struct IGuiMenuBar {};
    struct IGuiContainer : IGuiElement {
        virtual bool add(IGuiElement *) = 0;
        virtual bool remove(IGuiElement *) = 0;
    };
    struct IGuiContainerGrid : IGuiContainer {
        static bool create(IGuiContainerGrid **grid);
        struct BuildHelper {
            IGuiContainerGrid *grid;
            explicit BuildHelper(IGuiContainerGrid *value) : grid(value) {}
            bool append(const char *, IGuiElement *element) {
                return grid->add(element);
            }
            bool append(IGuiElement *element, int) { return grid->add(element); }
        };
    };
    std::vector<IKeyObserver*> observers;
    static Window &getInstance() { static Window window; return window; }
    bool registerObserver(IKeyObserver *observer) {
        ++observerAdds;
        if (failRegister) return false;
        assert(std::find(observers.begin(), observers.end(), observer) == observers.end());
        observers.push_back(observer); return true;
    }
    bool unregisterObserver(IKeyObserver *observer) {
        ++observerRemoves;
        auto found = std::find(observers.begin(), observers.end(), observer);
        assert(found != observers.end());
        observers.erase(found); return true;
    }
    bool pollEvents() { return true; }
};

struct Grid : Window::IGuiContainerGrid {
    std::vector<Window::IGuiElement*> children;
    Grid() { ++gridsCreated; }
    ~Grid() {
        // Deterministically detect deleting a child still owned by its parent.
        assert(std::find(attached.begin(), attached.end(), this) == attached.end());
        for (auto child : children) delete child;
        ++gridsDeleted;
    }
    bool add(Window::IGuiElement *element) {
        children.push_back(element); return true;
    }
    bool remove(Window::IGuiElement *) { std::abort(); }
};
bool Window::IGuiContainerGrid::create(IGuiContainerGrid **grid) {
    *grid = new Grid(); return true;
}

struct Parent : Window::IGuiContainer {
    std::vector<Window::IGuiElement*> children;
    int removes = 0;
    ~Parent() {
        while (!children.empty()) {
            auto child = children.back(); children.pop_back();
            auto found = std::find(attached.begin(), attached.end(), child);
            assert(found != attached.end()); attached.erase(found);
            delete child;
        }
    }
    bool add(Window::IGuiElement *element) {
        if (failAdd) return false;
        assert(std::find(children.begin(), children.end(), element) == children.end());
        children.push_back(element); attached.push_back(element); return true;
    }
    bool remove(Window::IGuiElement *element) {
        ++removes;
        if (failDetach) return false;
        auto child = std::find(children.begin(), children.end(), element);
        assert(child != children.end()); children.erase(child);
        auto found = std::find(attached.begin(), attached.end(), element);
        assert(found != attached.end()); attached.erase(found); return true;
    }
};

struct Options {
    struct Option {
        enum { TYPE_ACTION };
        template<typename... Args> explicit Option(Args...) {}
    };
    template<typename T> bool addOption(T) { return true; }
};
template<typename T> int createValueOption(const char *, int, const char *,
                                           const char *, T &) { return 0; }
class IAppModule {
public:
    virtual ~IAppModule() {}
    virtual bool initialize(Options &) = 0;
    virtual bool shutdown() = 0;
    virtual bool start(Window::IGuiMenuBar *, Window::IGuiContainer *) = 0;
    virtual bool stop() = 0;
};
struct Dispatcher {
    Value<StillFileType> m_stillFileType;
    static Dispatcher &getInstance() { static Dispatcher instance; return instance; }
};
struct TaskStillCapture {
    bool initialize() { return true; }
    bool start() { ++capturesStarted; return !failStart; }
    bool stop() { ++capturesStopped; return !failStop; }
    bool shutdown() { return true; }
    bool execute() { return true; }
};
} // namespace ArgusSamples
#endif
'''

HARNESS = r'''
#include "argus/apps/camera/ui/capture/AppModuleCapture.cpp"
using namespace ArgusSamples;

int main(int argc, char **argv) {
    assert(argc == 2);
    const std::string scenario(argv[1]);
    {
        Parent parent;
        AppModuleCapture module;
        Options options;
        assert(module.initialize(options));
        if (scenario == "capture-start-failure") {
            failStart = true;
            assert(!module.start(NULL, &parent));
            assert(parent.children.empty());
            assert(Window::getInstance().observers.empty());
            assert(parent.removes == 1);
            assert(module.shutdown());
            assert(gridsDeleted == 1);
        } else if (scenario == "capture-start-retry") {
            failStart = true;
            assert(!module.start(NULL, &parent));
            failStart = false;
            assert(module.start(NULL, &parent));
            assert(parent.children.size() == 1);
            assert(Window::getInstance().observers.size() == 1);
            assert(gridsCreated == 1);
            assert(module.stop());
            assert(module.stop());
            assert(parent.removes == 2);
            assert(module.shutdown());
        } else if (scenario == "capture-stop-failure") {
            assert(module.start(NULL, &parent));
            failStop = true;
            assert(!module.stop());
            assert(parent.children.empty());
            assert(Window::getInstance().observers.empty());
            assert(parent.removes == 1);
            assert(module.shutdown());
            assert(gridsDeleted == 1);
        } else if (scenario == "gui-construction-failure") {
            failAction = true;
            assert(!module.start(NULL, &parent));
            assert(gridsDeleted == 1);
            assert(parent.children.empty());
            assert(Window::getInstance().observers.empty());
            failAction = false;
            assert(module.start(NULL, &parent));
            assert(module.shutdown());
            assert(gridsCreated == 2 && gridsDeleted == 2);
        } else if (scenario == "parent-add-failure") {
            failAdd = true;
            assert(!module.start(NULL, &parent));
            assert(parent.children.empty());
            assert(Window::getInstance().observers.empty());
            assert(parent.removes == 0);
            failAdd = false;
            assert(module.start(NULL, &parent));
            assert(module.shutdown());
        } else if (scenario == "observer-registration-failure") {
            failRegister = true;
            assert(!module.start(NULL, &parent));
            assert(Window::getInstance().observers.empty());
            assert(gridsCreated == 0);
            assert(observerRemoves == 0);
            assert(module.shutdown());
        } else if (scenario == "idempotent-success") {
            assert(module.start(NULL, &parent));
            assert(module.start(NULL, &parent));
            assert(capturesStarted == 1 && observerAdds == 1);
            assert(module.stop());
            assert(module.stop());
            assert(capturesStopped == 1 && observerRemoves == 1);
            assert(module.shutdown());
            assert(module.shutdown());
        } else if (scenario == "failed-detach-retains-parent-ownership") {
            assert(module.start(NULL, &parent));
            failDetach = true;
            assert(module.shutdown());
            assert(gridsDeleted == 0);
            assert(parent.children.size() == 1);
            assert(Window::getInstance().observers.empty());
            failDetach = false;
        } else {
            std::abort();
        }
        assert(Window::getInstance().observers.empty());
    }
    assert(attached.empty());
    assert(gridsCreated == gridsDeleted);
}
'''


class CaptureLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ.get("ARGUS_CAPTURE_SOURCE", DEFAULT_SOURCE))
        if not (source / "argus/apps/camera/ui/capture/AppModuleCapture.cpp").is_file():
            raise unittest.SkipTest("set ARGUS_CAPTURE_SOURCE to unpacked MMAPI source")
        compiler = shutil.which("g++")
        if not compiler or not shutil.which("patch"):
            raise unittest.SkipTest("host g++ and patch are required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="argus-capture-lifecycle-")
        cls.addClassCleanup(cls.temporary.cleanup)
        base = Path(cls.temporary.name)
        capture = Path("argus/apps/camera/ui/capture")
        for name in ("AppModuleCapture.cpp", "AppModuleCapture.h"):
            target = base / capture / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / capture / name, target)
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p1", "-i", str(PATCH)],
                       cwd=base, check=True, capture_output=True, text=True)
        (base / "mocks.h").write_text(MOCKS)
        for name in ("Dispatcher.h", "Options.h", "tasks/StillCapture.h",
                     "argus/apps/camera/ui/common/IAppModule.h"):
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('#include "mocks.h"\n')
        shutil.copyfile(source / "argus/samples/utils/Error.h", base / "Error.h")
        shutil.copyfile(source / "argus/apps/camera/common/ScopedGuard.h",
                        base / "ScopedGuard.h")
        (base / "harness.cpp").write_text(HARNESS)
        cls.binary = base / "capture-lifecycle"
        result = subprocess.run(
            [compiler, "-std=c++11", "-g", "-O0", "-I", str(base),
             str(base / "harness.cpp"), "-o", str(cls.binary)],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_scenario(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_capture_start_failure_detaches_before_shutdown_deletes(self):
        self.run_scenario("capture-start-failure")

    def test_capture_start_failure_can_retry_without_duplicate_resources(self):
        self.run_scenario("capture-start-retry")

    def test_capture_stop_error_still_cleans_controls_and_is_reported(self):
        self.run_scenario("capture-stop-failure")

    def test_partial_gui_construction_is_transactional(self):
        self.run_scenario("gui-construction-failure")

    def test_failed_parent_add_does_not_try_to_detach_unattached_controls(self):
        self.run_scenario("parent-add-failure")

    def test_observer_registration_failure_leaves_no_resources(self):
        self.run_scenario("observer-registration-failure")

    def test_success_and_repeated_stop_shutdown_are_idempotent(self):
        self.run_scenario("idempotent-success")

    def test_failed_detach_does_not_delete_a_parent_owned_child(self):
        self.run_scenario("failed-detach-retains-parent-ownership")


if __name__ == "__main__":
    unittest.main()
