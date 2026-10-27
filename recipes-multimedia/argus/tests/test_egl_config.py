#!/usr/bin/env python3
"""Execute the patched EGL selection rules without a GPU or vendor sources."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


LAYER = Path(__file__).resolve().parents[3]
PATCHES = LAYER / "recipes-multimedia/argus/files"
RUNTIME = (LAYER / "recipes-devtools/edge-ai-sdk-manager/files/runtime" /
           "patches/argus")
DEPTH_PATCH = "0005-argus-preview-allow-depthless-egl-config.patch"


def resulting_hunks(name, target):
    """Read the production patch's resulting lines, not a copied predicate."""
    contents = (PATCHES / name).read_text()
    section = contents.split("+++ b/" + target + "\n", 1)[1]
    section = section.split("diff --git ", 1)[0]
    return "\n".join(line[1:] for line in section.splitlines()
                     if line.startswith(("+", " ")))


class EglConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("c++"):
            raise unittest.SkipTest("C++ compiler needed for EGL selection fixture")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        visual = resulting_hunks(
            "0001-argus-match-egl-config-to-x11-window.patch",
            "argus/samples/utils/GLContext.cpp")
        visual = visual.split("                // Depth bits.", 1)[0]
        depth = resulting_hunks(DEPTH_PATCH,
                                "argus/samples/utils/GLContext.cpp")
        depth = depth.split("                // Depth bits.\n", 1)[1]
        depth = depth.split("                // Samples.", 1)[0]
        # The rules under test are extracted from the actual production patches.
        # EGL itself is mocked so failures and visual/depth combinations are
        # deterministic and never open a desktop, camera or GPU.
        source = r'''
#include <cstdlib>
#include <iostream>
using EGLint = int;
using EGLConfig = int;
const int EGL_DONT_CARE = -1;
const int EGL_WINDOW_BIT = 4;
enum { EGL_SURFACE_TYPE, EGL_NATIVE_VISUAL_ID, EGL_BUFFER_SIZE,
       EGL_DEPTH_SIZE, EGL_SAMPLES };
int attributes[5];
int failedAttribute = -1;
bool eglGetConfigAttrib(int, int, int attribute, int* value) {
    if (attribute == failedAttribute) return false;
    *value = attributes[attribute];
    return true;
}
int eglGetError() { return 0; }
#define ORIGINATE_ERROR(...) return false
#define PROPAGATE_ERROR(value) do { if (!(value)) return false; } while (0)
struct Window {
    int visual;
    bool getEGLNativeVisualId(int& result) { result = visual; return true; }
};
struct Context {
    int m_display = 1;
    int m_config = 0;
    Window* m_window;
    bool select(int depthBits) {
        const int numConfigs = 1;
        int configs[] = {1};
''' + visual + depth + r'''
                eglGetConfigAttrib(m_display, configs[config], EGL_SAMPLES,
                                   &attrib);
                if (attrib != 0) continue;
                m_config = configs[config];
                break;
            }
            return m_config != 0;
    }
};
int main(int argc, char** argv) {
    if (argc != 9) return 2;
    Window window{std::atoi(argv[1])};
    Context context;
    context.m_window = &window;
    int depthBits = std::atoi(argv[2]);
    for (int index = 0; index < 5; ++index)
        attributes[index] = std::atoi(argv[index + 3]);
    failedAttribute = std::atoi(argv[8]);
    std::cout << context.select(depthBits) << '\n';
}
'''
        fixture = directory / "egl_selection.cpp"
        fixture.write_text(source)
        cls.executable = directory / "egl_selection"
        result = subprocess.run(
            ["c++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
             str(fixture), "-o", str(cls.executable)],
            capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def selected(self, required=24, visual=0x2b, config_visual=0x2b,
                 depth=0, surface=4, samples=0, color=24, failure=-1):
        result = subprocess.run(
            [str(self.executable), *map(str, (
                visual, required, surface, config_visual, color, depth,
                samples, failure))], capture_output=True, text=True,
            check=True)
        return result.stdout.strip() == "1"

    def test_depthless_native_preview_configuration_is_accepted(self):
        self.assertTrue(self.selected(required=-1))

    def test_existing_depth_tested_default_still_requires_24_bits(self):
        self.assertFalse(self.selected())
        self.assertFalse(self.selected(depth=16))
        self.assertTrue(self.selected(depth=24))

    def test_preview_does_not_require_a_depthless_configuration(self):
        self.assertTrue(self.selected(required=-1, depth=24))

    def test_preview_keeps_exact_native_visual_matching(self):
        self.assertFalse(self.selected(required=-1, config_visual=0x21))

    def test_preview_keeps_window_surface_and_no_multisampling(self):
        self.assertFalse(self.selected(required=-1, surface=1))
        self.assertFalse(self.selected(required=-1, samples=4))

    def test_visual_and_surface_query_failures_are_rejected(self):
        for attribute in (0, 1):
            self.assertFalse(self.selected(required=-1, failure=attribute))

    def test_non_x11_backend_retains_original_color_requirement(self):
        self.assertFalse(self.selected(required=-1, visual=0, color=24))
        self.assertTrue(self.selected(required=-1, visual=0, color=32))

    def test_public_and_internal_defaults_remain_24_and_preview_opts_out(self):
        header = resulting_hunks(DEPTH_PATCH,
                                 "argus/samples/utils/GLContext.h")
        self.assertEqual(header.count("EGLint depthBits = 24"), 2)
        implementation = resulting_hunks(
            DEPTH_PATCH, "argus/samples/utils/GLContext.cpp")
        self.assertIn("initializeInternal(sharingContext, depthBits)",
                      implementation)
        composer = resulting_hunks(
            DEPTH_PATCH, "argus/apps/camera/renderer/Composer.cpp")
        self.assertRegex(composer, re.compile(
            r"m_context.initialize\(&Window::getInstance\(\), NULL,\s*"
            r"EGL_DONT_CARE\)"))

    def test_sdk_and_yocto_use_identical_patches(self):
        for name in (DEPTH_PATCH,
                     "0001-argus-match-egl-config-to-x11-window.patch"):
            self.assertEqual((PATCHES / name).read_bytes(),
                             (RUNTIME / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
