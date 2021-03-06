import tkanvas
import argparse
from tkanvas import TKanvas
import numpy as np
import numpy.ma as ma
import time
import slider_filter
import sys
import os
import csv


class Gilbert(object):
    """implementS a Gilbert Markov chain, which can switch between two states. Simulates
    bursty behaviour."""

    def __init__(self, p1, p2):
        self.p1 = p1
        self.p2 = p2
        self.state = 0

    def update(self, dt):
        # account for sampling rate
        p1 = 1 - ((1 - self.p1) ** (dt))
        p2 = 1 - ((1 - self.p2) ** (dt))

        if self.state == 0:
            if np.random.random() < p1:
                self.state = 1
        if self.state == 1:
            if np.random.random() < p2:
                self.state = 0
        return self.state


class Box:
    def __init__(self, name, left, right, prior, color):
        self.name = name
        self.left = left
        self.right = right
        self.prior = prior
        self.color = color


def clamp(val, minimum=0, maximum=255):
    if val < minimum:
        return minimum
    if val > maximum:
        return maximum
    return val


def colorscale(hexstr, scalefactor):
    """
    Scales a hex string by ``scalefactor``. Returns scaled hex string.

    To darken the color, use a float value between 0 and 1.
    To brighten the color, use a float value greater than 1.

    >>> colorscale("#DF3C3C", .5)
    #6F1E1E
    >>> colorscale("#52D24F", 1.6)
    #83FF7E
    >>> colorscale("#4F75D2", 1)
    #4F75D2
    """

    hexstr = hexstr.strip("#")

    if scalefactor < 0 or len(hexstr) != 6:
        return hexstr

    r, g, b = int(hexstr[:2], 16), int(hexstr[2:4], 16), int(hexstr[4:], 16)

    r = clamp(r * scalefactor)
    g = clamp(g * scalefactor)
    b = clamp(b * scalefactor)

    return "#%02x%02x%02x" % (int(r), int(g), int(b))


def box_probability(particles, weights, boxes):
    xs = particles[:, 0]
    probs = []
    for box in boxes:
        # compute weight in each box
        posterior = np.sum(
            weights[np.logical_and(xs > box.left, xs < box.right)] * box.prior
        )
        probs.append(posterior)
    probs = np.array(probs) + 1e-6

    # normalise probabilities and return
    return probs / np.sum(probs)


class SliderLogger:
    def __init__(self, fields):
        time_name = "slider_{time}.csv".format(
            time=time.asctime().replace(" ", "_").replace(":", "_")
        )
        fname = os.path.join("..", "captured_data", time_name)
        self.log_file = open(fname, "w")        
        self.writer = csv.DictWriter(self.log_file, fieldnames=fields)
        self.writer.writeheader()


    def log(self, **fields):
        self.writer.writerow(fields)

    def close(self):
        self.log_file.close()


class SliderDemo(object):
    def __init__(self, boxes, args):
        self.boxes = boxes
        self.screen_size = 1000
        self.slider_height = 150
        self.canvas = TKanvas(
            draw_fn=self.draw,
            event_fn=self.event,
            quit_fn=self.quit,
            w=self.screen_size,
            h=self.slider_height,
        )

        self.logger = SliderLogger(
            fields=[
                "t",
                "true_x",
                "true_dx",
                "obs_x",
                "obs_speed",
                "est_x",
                "est_dx",
                "std_x",
                "std_dx",
                "mode",
            ]
        )
        self.gilbert = Gilbert(0.5, 0.3)
        self.n_particles = 200
        self.particles = slider_filter.prior(self.n_particles)
        # self.canvas.root.config(cursor='none')
        self.show_particles = args.particles
        self.show_block = args.block
        self.sampling_intermittency = args.sampling
        self.last_x = None
        self.last_t = time.time()
        self.start_time = time.time()
        self.dx = 0
        self.x = 0
        self.position_noise = 0.03

    def quit(self, src):
        self.logger.close()
        return

    def event(self, src, event_type, event):

        pass

    def update_filter(self):
        observation = [self.observed_x if self.observed else np.nan, np.abs(self.dx)]

        self.particles, self.weights = slider_filter.filter_step(
            self.particles, observed=observation, dt=self.dt, prior_rate=0.00005
        )

    def update_state(self, screen_x):
        t = time.time()
        self.x = screen_x / self.screen_size

        if self.last_x != None:
            dx = self.x - self.last_x
            dt = t - self.last_t
            self.dx = dx / dt
        else:
            dt = 1 / 60.0

        self.gilbert.update(dt)
        self.t = t
        self.last_x = self.x
        self.last_t = t
        self.dt = dt
        self.observed_x = self.x + np.random.normal(0, self.position_noise)

        if self.gilbert.state == 0:
            self.observed = np.random.uniform(0, 1) < 0.9
        else:
            self.observed = np.random.uniform(0, 1) < self.sampling_intermittency

    def draw(self, src):
        screen_x = src.mouse_x
        self.update_state(screen_x)
        self.update_filter()
        src.clear()

        box_weights = box_probability(self.particles, self.weights, self.boxes)

        for box, box_w in zip(self.boxes, box_weights):
            screen_left = box.left * self.screen_size
            screen_right = box.right * self.screen_size
            # show fading boxes if in particle mode
            if self.show_particles or self.show_block:
                scaled_color = colorscale(box.color, box_w)
                src.rectangle(
                    screen_left,
                    0,
                    screen_right,
                    self.slider_height,
                    fill=scaled_color,
                    outline=box.color,
                )
            else:
                src.rectangle(
                    screen_left,
                    0,
                    screen_right,
                    self.slider_height,
                    fill=box.color,
                    outline=box.color,
                )

        expected_pos = slider_filter.expected_position(self.particles, self.weights)
        expected_var = slider_filter.variance_position(self.particles, self.weights)
        screen_expected = expected_pos[0] * self.screen_size

        # log one row
        self.logger.log(
            t=time.time()-self.start_time,
            true_x=self.x,
            true_dx=self.dx,
            obs_x=np.nan if not self.observed else self.observed_x,
            obs_speed=np.abs(self.dx),
            est_x=expected_pos[0],
            est_dx=expected_pos[1],
            std_x=np.sqrt(expected_var[0]),
            std_dx=np.sqrt(expected_var[1]),
            mode=self.gilbert.state,
        )

        screen_left_var = (
            expected_pos[0] - np.sqrt(expected_var[0])
        ) * self.screen_size
        screen_right_var = (
            expected_pos[0] + np.sqrt(expected_var[0])
        ) * self.screen_size

        if self.show_block:

            for std, height, stipple in [
                (0.5, 0.75, "gray50"),
                (1, 0.5, "gray25"),
                (2, 0.25, "gray25"),
            ]:
                left = (
                    expected_pos[0] - np.sqrt(expected_var[0]) * std
                ) * self.screen_size
                right = (
                    expected_pos[0] + np.sqrt(expected_var[0]) * std
                ) * self.screen_size
                top = (0.5 - 0.5 * height) * self.slider_height
                bottom = (0.5 + 0.5 * height) * self.slider_height

                src.rectangle(
                    left, top, right, bottom, fill="blue", stipple=stipple, width=0
                )

        if self.show_particles:
            for particle, w in zip(self.particles, self.weights):
                x = particle[0] * self.screen_size
                x = x if np.isfinite(x) else 0
                w = w if np.isfinite(w) else 0
                src.circle(x, self.slider_height // 2, np.sqrt(w) * 20 + 1, fill="grey")

            src.circle(screen_expected, self.slider_height // 2, 5, fill="blue")
            src.line(
                screen_expected,
                0,
                screen_expected,
                self.slider_height,
                fill="cyan",
                width=2,
            )

            src.line(
                screen_left_var,
                0.25 * self.slider_height,
                screen_left_var,
                0.75 * self.slider_height,
                fill="blue",
            )
            src.line(
                screen_right_var,
                0.25 * self.slider_height,
                screen_right_var,
                0.75 * self.slider_height,
                fill="blue",
            )

        if self.observed:
            observed = self.observed_x * self.screen_size
            src.line(observed, 0, observed, self.slider_height, fill="white", width=5)


def create_slider():
    boxes = [
        Box("A", 0.0, 0.1, prior=0.25, color="#ff7200"),
        Box("X", 0.1, 0.9, prior=0.25, color="#3e3e3f"),
        Box("B", 0.9, 1.0, prior=0.5, color="#086375"),
    ]

    parser = argparse.ArgumentParser(description="Slider demo")
    parser.add_argument("--particles", action="store_true")
    parser.add_argument("--block", action="store_true")
    parser.add_argument("--sampling", type=float, default=0.1)

    args = parser.parse_args()
    print(args)

    slider = SliderDemo(boxes, args)
    return slider


if __name__ == "__main__":

    slider = create_slider()
    slider.canvas.root.mainloop()

