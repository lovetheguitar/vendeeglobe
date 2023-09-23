# SPDX-License-Identifier: BSD-3-Clause

import importlib
import os
import time
from typing import Dict

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore


from . import config
from .graphics import Graphics
from .map import Map
from .player import Player
from .weather import Weather


class Engine:
    def __init__(
        self,
        players: dict,
        safe=False,
        width=1200,
        height=900,
        test=True,
        fps=1,
        time_limit=300,
        seed=None,
        current_round=0,
    ):
        np.random.seed(seed)
        config.setup(players=players)

        self.time_limit = time_limit
        self.start_time = None

        self.players = {
            name: Player(team=name, score=0, number=i)
            for i, (name, ai) in enumerate(players.items())
        }

        self.app = pg.mkQApp("GLImageItem Example")
        self.map = Map(width=width, height=height)
        self.weather = Weather(self.map)
        self.graphics = Graphics(
            game_map=self.map, weather=self.weather, players=self.players
        )
        self.start_time = time.time()

    def move_players(self, weather, t, dt):
        # return
        latitudes = np.array([player.latitude for player in self.players.values()])
        longitudes = np.array([player.longitude for player in self.players.values()])
        u, v, n = weather.get_uv(latitudes, longitudes, t)
        for i, player in enumerate(self.players.values()):
            lat, lon = player.get_path(t, dt, u[i], v[i], n[i])
            terrain = self.map.get_terrain(longitudes=lon, latitudes=lat)
            sea_inds = np.where(terrain == 1)[0]
            if len(sea_inds) > 0:
                player.latitude = lat[sea_inds[-1]]
                player.longitude = lon[sea_inds[-1]]

    def update(self):
        t = time.time() - self.start_time
        self.weather.update_wind_tracers(t=t, dt=0.1)
        self.move_players(self.weather, t=t, dt=0.1)
        # for team, player in self.players.items():
        #     player.move()
        self.graphics.update_wind_tracers(
            self.weather.tracer_lat, self.weather.tracer_lon
        )
        self.graphics.update_player_positions(self.players)

    def run(self, N=10000):
        self.graphics.window.show()

        t = QtCore.QTimer()
        t.timeout.connect(self.update)
        t.start(50)

        pg.exec()
