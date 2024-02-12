# SPDX-License-Identifier: BSD-3-Clause

import datetime
import os
import time
from multiprocessing import Lock, Process
from multiprocessing.managers import SharedMemoryManager
from multiprocessing.shared_memory import SharedMemory
from typing import List, Optional, Tuple


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
from .core import Location
from .engine import Engine
from .graphics import Graphics
from .map import MapData, MapProxy, MapTextures
from .player import Player
from .scores import (
    finalize_scores,
    get_player_points,
    read_fastest_times,
    read_scores,
    write_fastest_times,
)
from .utils import (
    array_from_shared_mem,
    distance_on_surface,
    longitude_difference,
    pre_compile,
    string_to_color,
)
from .weather import Weather, WeatherData


class Controller:
    def __init__(
        self,
        # lock: Lock,
        player_names,
        buffers,
        # tracer_shared_mem: SharedMemory,
        # tracer_shared_data_dtype: np.dtype,
        # tracer_shared_data_shape: Tuple[int, ...],
        # player_positions_shared_mem: SharedMemory,
        # player_positions_data_dtype: np.dtype,
        # player_positions_data_shape: Tuple[int, ...],
        # u_shared_mem: SharedMemory,
        # u_shared_data_dtype: np.dtype,
        # u_shared_data_shape: Tuple[int, ...],
        # v_shared_mem: SharedMemory,
        # v_shared_data_dtype: np.dtype,
        # v_shared_data_shape: Tuple[int, ...],
        # forecast_u_shared_mem: SharedMemory,
        # forecast_u_shared_data_dtype: np.dtype,
        # forecast_u_shared_data_shape: Tuple[int, ...],
        # forecast_v_shared_mem: SharedMemory,
        # forecast_v_shared_data_dtype: np.dtype,
        # forecast_v_shared_data_shape: Tuple[int, ...],
        # default_texture_shared_mem: SharedMemory,
        # default_texture_shared_data_dtype: np.dtype,
        # default_texture_shared_data_shape: Tuple[int, ...],
        # high_contrast_texture_shared_mem: SharedMemory,
        # high_contrast_texture_shared_data_dtype: np.dtype,
        # high_contrast_texture_shared_data_shape: Tuple[int, ...],
        # bots: dict,
        # test: bool = True,
        # time_limit: float = 8 * 60,
        # seed: int = None,
        # start: Optional[Location] = None,
    ):
        # self.n_sub_processes = 2
        # n = config.ntracers // self.n_sub_processes
        # self.ntracers_per_sub_process = [n for _ in range(self.n_sub_processes)]
        # for i in range(config.ntracers - sum(self.ntracers_per_sub_process)):
        #     self.ntracers_per_sub_process[i] += 1

        # self.lock = lock

        self.buffers = {
            key: array_from_shared_mem(*value) for key, value in buffers.items()
        }

        # self.tracer_positions = array_from_shared_mem(
        #     tracer_shared_mem, tracer_shared_data_dtype, tracer_shared_data_shape
        # )

        # self.player_positions = array_from_shared_mem(
        #     player_positions_shared_mem,
        #     player_positions_data_dtype,
        #     player_positions_data_shape,
        # )

        # self.default_texture = array_from_shared_mem(
        #     default_texture_shared_mem,
        #     default_texture_shared_data_dtype,
        #     default_texture_shared_data_shape,
        # )

        # self.high_contrast_texture = array_from_shared_mem(
        #     high_contrast_texture_shared_mem,
        #     high_contrast_texture_shared_data_dtype,
        #     high_contrast_texture_shared_data_shape,
        # )

        # SHARED_DATA_DTYPE = self.tracer_positions_array.dtype
        # SHARED_DATA_SHAPE = self.tracer_positions_array.shape
        # SHARED_DATA_NBYTES = self.tracer_positions_array.nbytes

        # pre_compile()

        self.player_colors = [string_to_color(name) for name in player_names]

        self.time_limit = 8 * 60  # time_limit
        self.start_time = None
        self.safe = False  # not test
        self.test = True  # test

        # t0 = time.time()
        # print("Generating players...", end=" ", flush=True)
        # self.bots = {bot.team: bot for bot in bots}
        # self.players = {}
        # for name, bot in self.bots.items():
        #     self.players[name] = Player(
        #         team=name, avatar=getattr(bot, 'avatar', 1), start=start
        #     )
        # print(f"done [{time.time() - t0:.2f} s]")

        # self.map = Map()
        # self.map_proxy = MapProxy(self.map.array, self.map.dlat, self.map.dlon)

        # self.map_textures = MapTextures()

        self.graphics = Graphics(
            # game_map=self.map, weather=self.weather, players=self.players
            player_colors=self.player_colors,
            tracer_positions=self.buffers['tracer_positions'],
            player_positions=self.buffers['player_positions'],
            # default_texture=self.map_textures.default_texture,
        )

        # self.weather = WeatherData(seed=seed, time_limit=self.time_limit)

        # self.players_not_arrived = list(self.players.keys())
        # self.forecast = self.weather.get_forecast(0)

        # self.set_schedule()
        # self.group_counter = 0
        # self.fastest_times = read_fastest_times(self.players)

    def initialize_time(self):
        self.start_time = time.time()
        self.last_player_update = self.start_time
        self.last_graphics_update = self.start_time
        self.last_time_update = self.start_time
        self.last_forecast_update = self.start_time
        self.previous_clock_time = self.start_time
        self.update_interval = 1 / config.fps

    def set_schedule(self):
        times = []
        for player in self.players.values():
            t0 = time.time()
            self.execute_player_bot(player=player, t=0, dt=0)
            times.append(((time.time() - t0), player))
        ng = 3
        time_groups = {i: [] for i in range(ng)}
        self.player_groups = {i: [] for i in range(ng)}
        for t in sorted(times, key=lambda tup: tup[0], reverse=True):
            ind = np.argmin([sum(g) for g in time_groups.values()])
            time_groups[ind].append(t[0])
            self.player_groups[ind].append(t[1])
        empty_groups = [i for i, g in time_groups.items() if len(g) == 0]
        for i in empty_groups:
            del self.player_groups[i]

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
            "forecast": self.forecast,
            "map": self.map_proxy,
        }
        if self.safe:
            try:
                instructions = self.bots[player.team].run(**args)
            except:  # noqa
                pass
        else:
            instructions = self.bots[player.team].run(**args)
        return instructions

    def call_player_bots(self, t: float, dt: float, players: List[Player]):
        for player in players:
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
                player.dlat = next_lat - player.latitude
                player.dlon = longitude_difference(next_lon, player.longitude)
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
        t = clock_time - self.start_time
        # dt = (clock_time - self.previous_clock_time) * config.seconds_to_hours
        dt = clock_time - self.previous_clock_time
        if dt > self.update_interval:
            dt = dt * config.seconds_to_hours
            # if t > self.time_limit:
            #     self.shutdown()

            # if (clock_time - self.last_time_update) > config.time_update_interval:
            #     self.update_scoreboard(self.time_limit - t)
            #     self.last_time_update = clock_time

            # if (clock_time - self.last_forecast_update) > config.weather_update_interval:
            #     self.forecast = self.weather.get_forecast(t)
            #     self.last_forecast_update = clock_time

            # self.call_player_bots(
            #     t=t * config.seconds_to_hours,
            #     dt=dt,
            #     players=self.player_groups[self.group_counter % len(self.player_groups)],
            # )
            # self.move_players(self.weather, t=t, dt=dt)
            # if self.tracer_checkbox.isChecked():
            # self.weather.update_wind_tracers(t=np.array([t]), dt=dt)
            # self.lock.acquire()
            self.graphics.update_wind_tracers(
                # self.weather.tracer_lat, self.weather.tracer_lon
            )
            # time.sleep(0.1)
            # self.lock.release()
            self.graphics.update_player_positions()
            # self.group_counter += 1

            # if len(self.players_not_arrived) == 0:
            #     self.shutdown()

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
                f'{team[:config.max_name_length]}: {int(dist)} km, '
                f'{int(speed)} km/h [{nch}]'
            )

    def update_leaderboard(self, scores, fastest_times):
        sorted_scores = dict(
            sorted(scores.items(), key=lambda item: item[1], reverse=True)
        )
        for i, (name, score) in enumerate(sorted_scores.items()):
            self.score_boxes[i].setText(
                f'<div style="color:{self.players[name].color}">&#9632;</div> '
                f'{i+1}. {name[:config.max_name_length]}: {score}'
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
                f'{i+1}. {name[:config.max_name_length]}: {time}'
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
        # self.tracer_checkbox.stateChanged.connect(self.graphics.toggle_wind_tracers)
        widget1_layout.addWidget(self.tracer_checkbox)

        thickness_slider = QSlider(Qt.Horizontal)
        thickness_slider.setMinimum(1)
        thickness_slider.setMaximum(10)
        thickness_slider.setSingleStep(1)
        thickness_slider.setTickInterval(1)
        thickness_slider.setTickPosition(QSlider.TicksBelow)
        # thickness_slider.setValue(int(self.graphics.tracers.size))
        # thickness_slider.valueChanged.connect(self.graphics.set_tracer_thickness)
        widget1_layout.addWidget(thickness_slider)

        texture_checkbox = QCheckBox("High contrast", checked=False)
        widget1_layout.addWidget(texture_checkbox)
        # texture_checkbox.stateChanged.connect(self.graphics.toggle_texture)

        stars_checkbox = QCheckBox("Background stars", checked=True)
        widget1_layout.addWidget(stars_checkbox)
        # stars_checkbox.stateChanged.connect(self.graphics.toggle_stars)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setLineWidth(1)
        widget1_layout.addWidget(separator)

        # self.player_boxes = {}
        # for i, p in enumerate(self.players.values()):
        #     self.player_boxes[i] = QLabel("")
        #     widget1_layout.addWidget(self.player_boxes[i])
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
        # self.score_boxes = {}
        # for i, p in enumerate(self.players.values()):
        #     self.score_boxes[i] = QLabel(p.team)
        #     widget2_layout.addWidget(self.score_boxes[i])
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setLineWidth(1)
        widget2_layout.addWidget(separator)
        widget2_layout.addWidget(QLabel("Fastest finish:"))
        # self.fastest_boxes = {}
        # for i in range(3):
        #     self.fastest_boxes[i] = QLabel(str(i + 1))
        #     widget2_layout.addWidget(self.fastest_boxes[i])
        widget2_layout.addStretch()
        # self.update_leaderboard(
        #     read_scores(self.players.keys(), test=self.test), self.fastest_times
        # )

        window.show()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.initialize_time()
        self.timer.start(0)
        pg.exec()


def spawn_graphics(*args):
    graphics = Graphics(*args)
    graphics.run()


def spawn_engine(*args):
    engine = Engine(*args)
    engine.run()


def play(bots, seed=None, time_limit=8 * 60, start=None, test=True):
    n_sub_processes = 2
    # n = config.ntracers // self.n_sub_processes
    # self.ntracers_per_sub_process = [n for _ in range(self.n_sub_processes)]
    # for i in range(config.ntracers - sum(self.ntracers_per_sub_process)):
    #     self.ntracers_per_sub_process[i] += 1

    bots = {bot.team: bot for bot in bots}
    players = {}
    for name, bot in bots.items():
        players[name] = Player(team=name, avatar=getattr(bot, 'avatar', 1), start=start)

    groups = np.array_split(list(bots.keys()), n_sub_processes)
    print('groups', groups)
    bot_groups = []
    for group in groups:
        bot_groups.append({name: bots[name] for name in group})
    print(len(bot_groups))
    print('keys', [it.keys() for it in bot_groups])

    ntracers = config.ntracers // n_sub_processes
    tracer_positions = np.empty((n_sub_processes, config.tracer_lifetime, ntracers, 3))
    player_positions = np.empty((len(bots), config.max_track_length, 3))
    # tracer_positions = 6000 * (
    #     np.random.random((n_sub_processes, config.tracer_lifetime, config.ntracers, 3))
    #     - 0.5
    # )

    weather = WeatherData(seed=seed, time_limit=time_limit)

    # map_terrain = MapData()

    map_terrain = np.load(os.path.join(config.resourcedir, 'mapdata.npz'))['sea_array']
    # # self.array = mapdata['array']
    # self.sea_array = mapdata

    # SHARED_DATA_DTYPE = tracer_positions_array.dtype
    # SHARED_DATA_SHAPE = tracer_positions_array.shape
    # SHARED_DATA_NBYTES = tracer_positions_array.nbytes

    # lock = Lock()
    game_flow = np.empty(2, dtype=int)  # pause, exit

    # pre_compile()

    # self.time_limit = time_limit
    # self.start_time = None
    # self.safe = not test
    # self.test = test
    with SharedMemoryManager() as smm:
        tracer_positions_mem = smm.SharedMemory(size=tracer_positions.nbytes)
        weather_u_mem = smm.SharedMemory(size=weather.u.nbytes)
        weather_v_mem = smm.SharedMemory(size=weather.v.nbytes)
        forecast_u_mem = smm.SharedMemory(size=weather.forecast_u.nbytes)
        forecast_v_mem = smm.SharedMemory(size=weather.forecast_v.nbytes)
        # default_texture_shared_mem = smm.SharedMemory(size=game_map.array.nbytes)
        terrain_mem = smm.SharedMemory(size=map_terrain.nbytes)

        player_positions_mem = smm.SharedMemory(size=player_positions.nbytes)
        game_flow_mem = smm.SharedMemory(size=game_flow.nbytes)

        # high_contrast_texture_shared_mem = smm.SharedMemory(
        #     size=game_map.high_contrast_texture.nbytes
        # )

        # Populate map terrain
        terrain_arr = array_from_shared_mem(
            terrain_mem, map_terrain.dtype, map_terrain.shape
        )
        terrain_arr[...] = map_terrain

        # Populate weather arrays
        weather_u_arr = array_from_shared_mem(
            weather_u_mem, weather.u.dtype, weather.u.shape
        )
        weather_u_arr[...] = weather.u
        weather_v_arr = array_from_shared_mem(
            weather_v_mem, weather.v.dtype, weather.v.shape
        )
        weather_v_arr[...] = weather.v
        forecast_u_arr = array_from_shared_mem(
            forecast_u_mem, weather.forecast_u.dtype, weather.forecast_u.shape
        )
        forecast_u_arr[...] = weather.forecast_u
        forecast_v_arr = array_from_shared_mem(
            forecast_v_mem, weather.forecast_v.dtype, weather.forecast_v.shape
        )
        forecast_v_arr[...] = weather.forecast_v

        game_flow_arr = array_from_shared_mem(
            game_flow_mem, game_flow.dtype, game_flow.shape
        )
        game_flow_arr[...] = 0

        # Fill in map data

        buffers = {
            'tracer_positions': (
                tracer_positions_mem,
                tracer_positions.dtype,
                tracer_positions.shape,
            ),
            'player_positions': (
                player_positions_mem,
                player_positions.dtype,
                player_positions.shape,
            ),
            'weather_u': (weather_u_mem, weather.u.dtype, weather.u.shape),
            'weather_v': (weather_v_mem, weather.v.dtype, weather.v.shape),
            'forecast_u': (
                forecast_u_mem,
                weather.forecast_u.dtype,
                weather.forecast_u.shape,
            ),
            'forecast_v': (
                forecast_v_mem,
                weather.forecast_v.dtype,
                weather.forecast_v.shape,
            ),
            'game_flow': (game_flow_mem, game_flow.dtype, game_flow.shape),
        }

        graphics = Process(
            target=spawn_graphics,
            args=(
                # lock,
                # bots,
                list(bots.keys()),
                {
                    key: buffers[key]
                    for key in ('tracer_positions', 'player_positions', 'game_flow')
                },
                # tracer_shared_mem,
                # tracer_positions.dtype,
                # tracer_positions.shape,
                # player_positions_shared_mem,
                # player_positions.dtype,
                # player_positions.shape,
                # u_shared_mem,
                # weather.u.dtype,
                # weather.u.shape,
                # v_shared_mem,
                # weather.v.dtype,
                # weather.v.shape,
                # forecast_u_shared_mem,
                # weather.forecast_u.dtype,
                # weather.forecast_u.shape,
                # forecast_v_shared_mem,
                # weather.forecast_v.dtype,
                # weather.forecast_v.shape,
                # default_texture_shared_mem,
                # game_map.array.dtype,
                # game_map.array.shape,
                # high_contrast_texture_shared_mem,
                # game_map.high_contrast_texture.dtype,
                # game_map.high_contrast_texture.shape,
            ),
        )

        engines = []
        bot_index_begin = 0
        for i in range(n_sub_processes):
            engines.append(
                Process(
                    target=spawn_engine,
                    args=(
                        # lock,
                        i,
                        seed,
                        bot_groups[i],
                        bot_index_begin,
                        buffers,
                    ),
                )
            )
            bot_index_begin += len(bot_groups[i])

        graphics.start()
        for engine in engines:
            engine.start()
        graphics.join()
        for engine in engines:
            engine.join()

        del (
            terrain_arr,
            weather_u_arr,
            weather_v_arr,
            forecast_u_arr,
            forecast_v_arr,
            game_flow_arr,
        )