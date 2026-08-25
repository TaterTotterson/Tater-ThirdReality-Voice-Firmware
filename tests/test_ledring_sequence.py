import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HEADER_DIR = ROOT / "buildroot/package/thirdreality/tr-ledring/src"


class LedRingSequenceTests(unittest.TestCase):
    def test_looped_animation_advances_every_frame_and_wraps(self) -> None:
        compiler = shutil.which("c++")
        if compiler is None:
            self.skipTest("A C++ compiler is required for the LED service host test")

        source = r'''
#include <cassert>
#include <cstddef>
#include <vector>

#include "led_animation_sequence.h"

struct Frame {
    bool loop;
};

int main()
{
    const std::vector<Frame> sequence = {{true}, {true}, {true}};
    assert(tater_led_loops_entire_sequence(sequence));
    std::size_t index = 0;
    index = tater_led_next_sequence_frame(index, sequence.size());
    assert(index == 1);
    index = tater_led_next_sequence_frame(index, sequence.size());
    assert(index == 2);
    index = tater_led_next_sequence_frame(index, sequence.size());
    assert(index == 0);

    const std::vector<Frame> hold_last = {{false}, {false}, {true}};
    assert(!tater_led_loops_entire_sequence(hold_last));
    const std::vector<Frame> hold_only = {{true}};
    assert(!tater_led_loops_entire_sequence(hold_only));
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            test_source = directory / "led_sequence_test.cpp"
            executable = directory / "led_sequence_test"
            test_source.write_text(source, encoding="utf-8")
            subprocess.run(
                [
                    compiler,
                    "-std=c++11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(HEADER_DIR),
                    str(test_source),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
