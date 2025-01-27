# SPDX-License-Identifier: BSD-3-Clause

import datetime
import time
from typing import List, Optional

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore

try:
    from PyQt5.QtWidgets import (
        QCheckBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QSizePolicy,
        QSlider,
        QVBoxLayout,
        QWidget,
    )
    from PyQt5.QtCore import Qt
except ImportError:
    from PySide2.QtWidgets import (
        QMainWindow,
        QWidget,
        QLabel,
        QHBoxLayout,
        QVBoxLayout,
        QCheckBox,
        QSizePolicy,
        QSlider,
        QFrame,
    )
    from PySide2.QtCore import Qt

from . import config
from .core import Checkpoint, Location
from .graphics import Graphics
from .map import Map
from .player import Player
from .scores import (
    finalize_scores,
    get_player_points,
    read_fastest_times,
    read_scores,
    write_fastest_times,
)
from .utils import distance_on_surface, pre_compile
from .weather import Weather


class Engine:
    def __init__(
        self,
        bots: dict,
        test: bool = True,
        time_limit: float = 8 * 60,
        seed: int = None,
        start: Optional[Location] = None,
        speedup: Optional[float] = None,
        course_preview: Optional[List[Checkpoint]] = None,
        high_contrast: bool = False,
    ):
        pre_compile()

        self.time_limit = time_limit
        self.start_time = None
        self.safe = not test
        self.test = test
        self.speedup = speedup
        self.high_contrast = high_contrast

        t0 = time.time()
        print("Generating players...", end=" ", flush=True)
        self.bots = {bot.team: bot for bot in bots}
        self.players = {}
        for name in self.bots:
            self.players[name] = Player(team=name, start=start)
        print(f"done [{time.time() - t0:.2f} s]")

        self.map = Map()
        self.weather = Weather(seed=seed, time_limit=self.time_limit)
        self.graphics = Graphics(
            game_map=self.map,
            weather=self.weather,
            players=self.players,
            course_preview=course_preview,
        )
        self.players_not_arrived = list(self.players.keys())
        self.forecast = self.weather.get_forecast(0)
        self.fastest_times = read_fastest_times(self.players)

    def initialize_time(self):
        self.start_time = time.time()
        self.last_player_update = self.start_time
        self.last_graphics_update = self.start_time
        self.last_time_update = self.start_time
        self.last_forecast_update = self.start_time
        self.previous_clock_time = self.start_time
        self.current_time = 0.0

    def execute_player_bot(self, player, t: float, dt: float):
        instructions = None
        args = {
            "t": t,
            "dt": dt,
            "longitude": player.longitude,
            "latitude": player.latitude,
            "heading": player.heading,
            "speed": player.speed,
            "vector": player.get_vector(),
            "forecast": self.forecast.get_uv,
            "world_map": self.map.get_terrain,
        }
        if self.safe:
            try:
                instructions = self.bots[player.team].run(**args)
            except:  # noqa
                pass
        else:
            instructions = self.bots[player.team].run(**args)
        return instructions

    def call_player_bots(self, t: float, dt: float):
        for player in self.players.values():
            if self.safe:
                try:
                    player.execute_bot_instructions(
                        self.execute_player_bot(player=player, t=t, dt=dt)
                    )
                except:  # noqa
                    pass
            else:
                player.execute_bot_instructions(
                    self.execute_player_bot(player=player, t=t, dt=dt)
                )

    def move_players(self, weather: Weather, t: float, dt: float):
        latitudes = np.array([player.latitude for player in self.players.values()])
        longitudes = np.array([player.longitude for player in self.players.values()])
        u, v = weather.get_uv(latitudes, longitudes, np.array([t]))
        for i, player in enumerate([p for p in self.players.values() if not p.arrived]):
            lat, lon = player.get_path(dt, u[i], v[i])
            terrain = self.map.get_terrain(longitudes=lon, latitudes=lat)
            w = np.where(terrain == 0)[0]
            if len(w) > 0:
                ind = max(w[0] - 1, 0)
            else:
                ind = len(terrain) - 1
            if ind > 0:
                next_lat = lat[ind]
                next_lon = lon[ind]
                player.distance_travelled += distance_on_surface(
                    longitude1=player.longitude,
                    latitude1=player.latitude,
                    longitude2=next_lon,
                    latitude2=next_lat,
                )
                player.latitude = next_lat
                player.longitude = next_lon
            else:
                player.dlat = 0
                player.dlon = 0

            for checkpoint in player.checkpoints:
                if not checkpoint.reached:
                    d = distance_on_surface(
                        longitude1=player.longitude,
                        latitude1=player.latitude,
                        longitude2=checkpoint.longitude,
                        latitude2=checkpoint.latitude,
                    )
                    if d < checkpoint.radius:
                        checkpoint.reached = True
                        print(f"{player.team} reached {checkpoint}")
            dist_to_finish = distance_on_surface(
                longitude1=player.longitude,
                latitude1=player.latitude,
                longitude2=config.start.longitude,
                latitude2=config.start.latitude,
            )
            if dist_to_finish < config.start.radius and all(
                ch.reached for ch in player.checkpoints
            ):
                player.arrived = True
                player.bonus = config.score_step * len(self.players_not_arrived)
                n_not_arrived = len(self.players_not_arrived)
                n_players = len(self.players)
                if n_not_arrived == n_players:
                    pos_str = "st"
                elif n_not_arrived == n_players - 1:
                    pos_str = "nd"
                elif n_not_arrived == n_players - 2:
                    pos_str = "rd"
                else:
                    pos_str = "th"
                print(
                    f"{player.team} finished in {n_players - n_not_arrived + 1}"
                    f"{pos_str} position!"
                )
                self.players_not_arrived.remove(player.team)
                self.fastest_times[player.team] = min(
                    t, self.fastest_times[player.team]
                )

    def shutdown(self):
        final_scores = finalize_scores(players=self.players, test=self.test)
        write_fastest_times(self.fastest_times)
        self.update_leaderboard(final_scores, self.fastest_times)
        self.timer.stop()

    def update(self):
        clock_time = time.time()
        dt_raw = clock_time - self.previous_clock_time
        if self.speedup is not None:
            dt_raw *= self.speedup
            self.current_time += dt_raw
        else:
            self.current_time = clock_time - self.start_time
        dt = dt_raw * config.seconds_to_hours
        if self.current_time > self.time_limit:
            self.shutdown()

        if (clock_time - self.last_time_update) > config.time_update_interval:
            self.update_scoreboard(self.time_limit - self.current_time)
            self.last_time_update = clock_time

        if (clock_time - self.last_forecast_update) > config.weather_update_interval:
            self.forecast = self.weather.get_forecast(self.current_time)
            self.last_forecast_update = clock_time

        self.call_player_bots(t=self.current_time * config.seconds_to_hours, dt=dt)
        self.move_players(self.weather, t=self.current_time, dt=dt)
        if self.tracer_checkbox.isChecked():
            self.weather.update_wind_tracers(
                t=np.array([self.current_time]), dt=dt, speedup=self.speedup
            )
            self.graphics.update_wind_tracers(
                self.weather.tracer_lat, self.weather.tracer_lon
            )
        self.graphics.update_player_positions(self.players)

        if len(self.players_not_arrived) == 0:
            self.shutdown()

        self.previous_clock_time = clock_time

    def update_scoreboard(self, t: float):
        time = str(datetime.timedelta(seconds=int(t)))[2:]
        self.time_label.setText(f"Time left: {time} s")
        status = [
            (
                get_player_points(player),
                player.distance_travelled,
                player.team,
                player.speed,
                player.color,
                len([ch for ch in player.checkpoints if ch.reached]),
            )
            for player in self.players.values()
        ]
        for i, (_, dist, team, speed, col, nch) in enumerate(
            sorted(status, reverse=True)
        ):
            self.player_boxes[i].setText(
                f'<div style="color:{col}">&#9632;</div> {i+1}. '
                f"{team[:config.max_name_length]}: {int(dist)} km, "
                f"{int(speed)} km/h [{nch}]"
            )

    def update_leaderboard(self, scores, fastest_times):
        sorted_scores = dict(
            sorted(scores.items(), key=lambda item: item[1], reverse=True)
        )
        for i, (name, score) in enumerate(sorted_scores.items()):
            self.score_boxes[i].setText(
                f'<div style="color:{self.players[name].color}">&#9632;</div> '
                f"{i+1}. {name[:config.max_name_length]}: {score:.2f}"
            )

        sorted_times = dict(sorted(fastest_times.items(), key=lambda item: item[1]))
        time_list = list(enumerate(sorted_times.items()))
        for i, (name, t) in time_list[:3]:
            try:
                time = str(datetime.timedelta(seconds=int(t)))[2:]
            except OverflowError:
                time = "None"
            self.fastest_boxes[i].setText(
                f'<div style="color:{self.players[name].color}">&#9632;</div> '
                f"{i+1}. {name[:config.max_name_length]}: {time}"
            )

    def run(self):
        window = QMainWindow()
        window.setWindowTitle("Vendée Globe")
        window.setGeometry(100, 100, 1280, 720)

        # Create a central widget to hold the two widgets
        central_widget = QWidget()
        window.setCentralWidget(central_widget)

        # Create a layout for the central widget
        layout = QHBoxLayout(central_widget)

        # Create the first widget with vertical checkboxes
        widget1 = QWidget()
        layout.addWidget(widget1)
        widget1_layout = QVBoxLayout(widget1)
        widget1.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        widget1.setMinimumWidth(int(window.width() * 0.2))

        self.time_label = QLabel("Time left:")
        widget1_layout.addWidget(self.time_label)
        self.tracer_checkbox = QCheckBox("Wind tracers", checked=True)
        self.tracer_checkbox.stateChanged.connect(self.graphics.toggle_wind_tracers)
        widget1_layout.addWidget(self.tracer_checkbox)

        thickness_slider = QSlider(Qt.Horizontal)
        thickness_slider.setMinimum(1)
        thickness_slider.setMaximum(10)
        thickness_slider.setSingleStep(1)
        thickness_slider.setTickInterval(1)
        thickness_slider.setTickPosition(QSlider.TicksBelow)
        thickness_slider.setValue(int(self.graphics.tracers.size))
        thickness_slider.valueChanged.connect(self.graphics.set_tracer_thickness)
        widget1_layout.addWidget(thickness_slider)

        texture_checkbox = QCheckBox("High contrast", checked=False)
        widget1_layout.addWidget(texture_checkbox)
        texture_checkbox.stateChanged.connect(self.graphics.toggle_texture)
        texture_checkbox.setChecked(self.high_contrast)

        stars_checkbox = QCheckBox("Background stars", checked=True)
        widget1_layout.addWidget(stars_checkbox)
        stars_checkbox.stateChanged.connect(self.graphics.toggle_stars)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setLineWidth(1)
        widget1_layout.addWidget(separator)

        self.player_boxes = {}
        for i, p in enumerate(self.players.values()):
            self.player_boxes[i] = QLabel("")
            widget1_layout.addWidget(self.player_boxes[i])
        widget1_layout.addStretch()

        layout.addWidget(self.graphics.window)
        self.graphics.window.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        widget2 = QWidget()
        layout.addWidget(widget2)
        widget2_layout = QVBoxLayout(widget2)
        widget2.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        widget2.setMinimumWidth(int(window.width() * 0.08))
        widget2_layout.addWidget(QLabel("Leader board"))
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setLineWidth(1)
        widget2_layout.addWidget(separator)
        widget2_layout.addWidget(QLabel("Scores:"))
        self.score_boxes = {}
        for i, p in enumerate(self.players.values()):
            self.score_boxes[i] = QLabel(p.team)
            widget2_layout.addWidget(self.score_boxes[i])
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setLineWidth(1)
        widget2_layout.addWidget(separator)
        widget2_layout.addWidget(QLabel("Fastest finish:"))
        self.fastest_boxes = {}
        for i in range(3):
            self.fastest_boxes[i] = QLabel(str(i + 1))
            widget2_layout.addWidget(self.fastest_boxes[i])
        widget2_layout.addStretch()
        self.update_leaderboard(
            read_scores(self.players.keys(), test=self.test), self.fastest_times
        )

        window.show()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.initialize_time()
        self.timer.start(0)
        pg.exec()
