#ifndef TATER_LED_ANIMATION_SEQUENCE_H
#define TATER_LED_ANIMATION_SEQUENCE_H

#include <cstddef>

template <typename Frames>
bool tater_led_loops_entire_sequence(const Frames &frames)
{
	if (frames.size() <= 1) {
		return false;
	}
	for (const auto &frame : frames) {
		if (!frame.loop) {
			return false;
		}
	}
	return true;
}

inline std::size_t tater_led_next_sequence_frame(
	std::size_t current,
	std::size_t frame_count
)
{
	return frame_count == 0 ? 0 : (current + 1) % frame_count;
}

#endif
