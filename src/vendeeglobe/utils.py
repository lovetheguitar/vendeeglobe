# SPDX-License-Identifier: BSD-3-Clause

import hashlib
import time
from multiprocessing.shared_memory import SharedMemory
from typing import Tuple, Union

import numba
import numpy as np

from . import config

RADIUS = float(config.map_radius)


def array_from_shared_mem(
    shared_mem: SharedMemory,
    shared_data_dtype: np.dtype,
    shared_data_shape: Tuple[int, ...],
) -> np.ndarray:
    arr = np.frombuffer(shared_mem.buf, dtype=shared_data_dtype)
    arr = arr.reshape(shared_data_shape)
    return arr


def string_to_color(input_string: str) -> str:
    hash_object = hashlib.md5(input_string.encode())
    hex_hash = hash_object.hexdigest()
    return "#" + hex_hash[:6]


@numba.njit(cache=True)
def to_xyz(
    phi: Union[float, np.ndarray],
    theta: Union[float, np.ndarray],
    gl: bool = False,
) -> Tuple[
    Union[float, np.ndarray], Union[float, np.ndarray], Union[float, np.ndarray]
]:
    if gl:
        # theta = np.pi - theta
        theta -= np.pi
        theta *= -1.0
    sin_theta = np.sin(theta) * RADIUS
    xpos = sin_theta * np.cos(phi)
    ypos = sin_theta * np.sin(phi)
    zpos = np.cos(theta) * RADIUS
    return xpos, ypos, zpos


@numba.njit(cache=True)
def lat_to_theta(lat: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    return np.radians(90.0 - lat)


@numba.njit(cache=True)
def lon_to_phi(lon: Union[float, np.ndarray]) -> Union[float, np.ndarray]:
    out = lon % 360.0
    out += 180.0
    return np.radians(out)


@numba.njit(cache=True)
def wrap(
    lat: Union[float, np.ndarray], lon: Union[float, np.ndarray]
) -> Tuple[Union[float, np.ndarray], Union[float, np.ndarray]]:
    out_lat = np.maximum(np.minimum(lat, 180.0 - lat), -180.0 - lat)
    out_lon = lon + 180.0
    out_lon = np.where((lat > 90.0) | (lat < -90.0), out_lon + 180.0, out_lon)
    out_lon %= 360.0
    out_lon -= 180.0
    return out_lat, out_lon


@numba.njit(cache=True)
def wind_force(ship_vector: np.ndarray, wind: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(wind)
    vsum = ship_vector + wind / norm
    vsum /= np.linalg.norm(vsum)
    mag = np.abs(np.dot(ship_vector, vsum))
    return (mag * norm) * ship_vector


@numba.njit(cache=True)
def lon_degs_from_length(length: np.ndarray, lat: np.ndarray) -> np.ndarray:
    """
    Given a length, compute how many degrees of longitude it represents at a given
    latitude.
    """
    return length / ((np.pi * RADIUS * np.cos(np.radians(lat))) / 180.0)


@numba.njit(cache=True)
def lat_degs_from_length(length: np.ndarray) -> np.ndarray:
    """
    Given a length, compute how many degrees of latitude it represents.
    """
    return length / (2.0 * np.pi * RADIUS) * 360.0


@numba.njit(cache=True)
def distance_on_surface(
    longitude1: float, latitude1: float, longitude2: float, latitude2: float
) -> float:
    """
    Use the Haversine formula to calculate the distance on the surface of the globe
    between two points given by their longitude and latitude.
    """
    lon1 = np.radians(longitude1)
    lat1 = np.radians(latitude1)
    lon2 = np.radians(longitude2)
    lat2 = np.radians(latitude2)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return RADIUS * c


@numba.njit(cache=True)
def longitude_difference(lon1: float, lon2: float) -> float:
    # Calculate the standard difference in longitudes
    lon_diff = lon1 - lon2
    # Check if the crossing of the +/- 180 degrees line is shorter
    crossing_diff = 360.0 - abs(lon_diff)
    # Return the signed difference
    if lon_diff >= 0:
        return min(lon_diff, crossing_diff)
    else:
        return -min(-lon_diff, crossing_diff)


# def gkern(sigma=1):
#     """
#     Creates gaussian kernel
#     """
#     ax = np.linspace(-(sigma - 1) / 2.0, (sigma - 1) / 2.0, sigma)
#     gauss = np.exp(-0.5 * np.square(ax) / np.square(sigma))
#     kernel = np.outer(gauss, gauss)
#     return kernel / np.sum(kernel)


# @numba.njit(cache=True)
# def blur_weather(u: np.ndarray, v: np.ndarray, n: int) -> Tuple[np.ndarray, np.ndarray]:
#     u_out = np.zeros((n,) + u.shape)
#     v_out = np.zeros_like(u_out)
#     nt, ny, nx = u.shape
#     for k in range(n):
#         sigma = 2 * k + 1
#         ax = np.linspace(-(sigma - 1) / 2.0, (sigma - 1) / 2.0, sigma)
#         gauss = np.exp(-0.5 * np.square(ax) / np.square(sigma))
#         kernel = np.outer(gauss, gauss)
#         kernel /= np.sum(kernel)

#         for t in range(nt):
#             for j in range(ny):
#                 for i in range(nx):
#                     for jj in range(-k, k + 1):
#                         for ii in range(-k, k + 1):
#                             u_out[k, t, j, i] += (
#                                 kernel[jj, ii] * u[t, (j + jj) % ny, (i + ii) % nx]
#                             )
#                             v_out[k, t, j, i] += (
#                                 kernel[jj, ii] * v[t, (j + jj) % ny, (i + ii) % nx]
#                             )
#     # u_out[0] = u
#     # v_out[0] = v
#     # for i in range(1, n):
#     #     u_out[i] = uniform_filter(u, size=i * 2, mode="wrap")
#     #     v_out[i] = uniform_filter(v, size=i * 2, mode="wrap")
#     return u_out, v_out


def pre_compile():
    t0 = time.time()
    print('Precompiling utils...', end=' ', flush=True)
    a = np.zeros(2)
    b = 0.0
    for ab in (a, b):
        to_xyz(ab, ab)
        lat_to_theta(ab)
        lon_to_phi(ab)
        wrap(ab, ab)
        lon_degs_from_length(ab, ab)
        lat_degs_from_length(ab)
        distance_on_surface(ab, ab, ab, ab)
    wind_force(a, a)
    longitude_difference(b, b)
    print(f'done [{time.time() - t0:.2f} s]')
