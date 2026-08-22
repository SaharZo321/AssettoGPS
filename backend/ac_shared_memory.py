"""
Assetto Corsa Shared Memory Interface
Reads memory-mapped files: acpmf_physics, acpmf_graphics, acpmf_static
"""

import ctypes
import mmap
import math
import sys
from typing import Optional, Dict, Any


FILE_MAP_READ = 0x0004
AC_SHARED_MEMORY_NAMES = (
    'acpmf_physics',
    'acpmf_graphics',
    'acpmf_static',
)


def named_mapping_exists(name: str) -> bool:
    """Return True only when an existing Win32 named mapping can be opened."""
    if sys.platform != 'win32':
        return False

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    open_file_mapping = kernel32.OpenFileMappingW
    open_file_mapping.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p)
    open_file_mapping.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool

    handle = open_file_mapping(FILE_MAP_READ, False, name)
    if not handle:
        return False

    close_handle(handle)
    return True


def ac_shared_memory_available() -> bool:
    """Return True only when all AC shared-memory pages already exist."""
    return all(named_mapping_exists(name) for name in AC_SHARED_MEMORY_NAMES)

# AC Flag Enumerations
AC_FLAG_NONE = 0
AC_FLAG_BLUE = 1
AC_FLAG_YELLOW = 2
AC_FLAG_BLACK = 3
AC_FLAG_WHITE = 4
AC_FLAG_CHECKERED = 5
AC_FLAG_PENALTY = 6

# AC Status Enumerations
AC_STATUS_OFF = 0
AC_STATUS_REPLAY = 1
AC_STATUS_LIVE = 2
AC_STATUS_PAUSE = 3

# AC Session Types
AC_SESSION_UNKNOWN = -1
AC_SESSION_PRACTICE = 0
AC_SESSION_QUALIFY = 1
AC_SESSION_RACE = 2
AC_SESSION_HOTLAP = 3
AC_SESSION_TIME_ATTACK = 4
AC_SESSION_DRIFT = 5
AC_SESSION_DRAG = 6


class SPageFilePhysics(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32),
        ("gas", ctypes.c_float),
        ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float),
        ("gear", ctypes.c_int32),
        ("rpms", ctypes.c_int32),
        ("steerAngle", ctypes.c_float),
        ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3),
        ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4),
        ("wheelLoad", ctypes.c_float * 4),
        ("wheelsPressure", ctypes.c_float * 4),
        ("wheelAngularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4),
        ("tyreDirtyLevel", ctypes.c_float * 4),
        ("tyreCoreTemperature", ctypes.c_float * 4),
        ("camberRAD", ctypes.c_float * 4),
        ("suspensionTravel", ctypes.c_float * 4),
        ("drs", ctypes.c_float),
        ("tc", ctypes.c_float),
        ("heading", ctypes.c_float),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("cgHeight", ctypes.c_float),
        ("damage", ctypes.c_float * 5),
        ("numberOfTyresOut", ctypes.c_int32),
        ("pitLimiterOn", ctypes.c_int32),
        ("abs", ctypes.c_float),
        ("kersCharge", ctypes.c_float),
        ("kersInput", ctypes.c_float),
        ("autoShifterOn", ctypes.c_int32),
        ("rideHeight", ctypes.c_float * 2),
        ("turboBoost", ctypes.c_float),
        ("ballast", ctypes.c_float),
        ("airDensity", ctypes.c_float),
        ("airTemp", ctypes.c_float),
        ("roadTemp", ctypes.c_float),
        ("localAngularVel", ctypes.c_float * 3),
        ("finalFF", ctypes.c_float),
        ("performanceMeter", ctypes.c_float),
        ("engineBrake", ctypes.c_int32),
        ("ersRecoveryLevel", ctypes.c_int32),
        ("ersPowerLevel", ctypes.c_int32),
        ("ersHeatCharging", ctypes.c_int32),
        ("ersIsCharging", ctypes.c_int32),
        ("kersCurrentKJ", ctypes.c_float),
        ("drsAvailable", ctypes.c_int32),
        ("drsEnabled", ctypes.c_int32),
        ("brakeTemp", ctypes.c_float * 4),
        ("clutch", ctypes.c_float),
        ("tyreTempI", ctypes.c_float * 4),
        ("tyreTempM", ctypes.c_float * 4),
        ("tyreTempO", ctypes.c_float * 4),
        ("isAIControlled", ctypes.c_int32),
        ("tyreContactPoint", (ctypes.c_float * 3) * 4),
        ("tyreContactNormal", (ctypes.c_float * 3) * 4),
        ("tyreContactHeading", (ctypes.c_float * 3) * 4),
        ("brakeBias", ctypes.c_float),
        ("localVelocity", ctypes.c_float * 3),
    ]


class SPageFileGraphic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", ctypes.c_int32),
        ("status", ctypes.c_int32),
        ("session", ctypes.c_int32),
        ("currentTime", ctypes.c_wchar * 15),
        ("lastTime", ctypes.c_wchar * 15),
        ("bestTime", ctypes.c_wchar * 15),
        ("split", ctypes.c_wchar * 15),
        ("completedLaps", ctypes.c_int32),
        ("position", ctypes.c_int32),
        ("iCurrentTime", ctypes.c_int32),
        ("iLastTime", ctypes.c_int32),
        ("iBestTime", ctypes.c_int32),
        ("sessionTimeLeft", ctypes.c_float),
        ("distanceTraveled", ctypes.c_float),
        ("isInPit", ctypes.c_int32),
        ("currentSectorIndex", ctypes.c_int32),
        ("lastSectorTime", ctypes.c_int32),
        ("numberOfLaps", ctypes.c_int32),
        ("tyreCompound", ctypes.c_wchar * 33),
        ("replayTimeMultiplier", ctypes.c_float),
        ("normalizedCarPosition", ctypes.c_float),
        ("carCoordinates", ctypes.c_float * 3),
        ("penaltyTime", ctypes.c_float),
        ("flag", ctypes.c_int32),
        ("idealLineOn", ctypes.c_int32),
        ("isInPitLane", ctypes.c_int32),
        ("surfaceGrip", ctypes.c_float),
        ("mandatoryPitDone", ctypes.c_int32),
        ("windSpeed", ctypes.c_float),
        ("windDirection", ctypes.c_float),
    ]


class SPageFileStatic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", ctypes.c_wchar * 15),
        ("acVersion", ctypes.c_wchar * 15),
        ("numberOfSessions", ctypes.c_int32),
        ("numCars", ctypes.c_int32),
        ("carModel", ctypes.c_wchar * 33),
        ("track", ctypes.c_wchar * 33),
        ("playerName", ctypes.c_wchar * 33),
        ("playerSurname", ctypes.c_wchar * 33),
        ("playerNick", ctypes.c_wchar * 33),
        ("sectorCount", ctypes.c_int32),
        ("maxTorque", ctypes.c_float),
        ("maxPower", ctypes.c_float),
        ("maxRpm", ctypes.c_int32),
        ("maxFuel", ctypes.c_float),
        ("suspensionMaxTravel", ctypes.c_float * 4),
        ("tyreRadius", ctypes.c_float * 4),
        ("maxTurboBoost", ctypes.c_float),
        ("deprecated_1", ctypes.c_float),
        ("deprecated_2", ctypes.c_float),
        ("penaltiesEnabled", ctypes.c_int32),
        ("aidFuelRate", ctypes.c_float),
        ("aidTireRate", ctypes.c_float),
        ("aidMechanicalDamage", ctypes.c_float),
        ("aidAllowTyreBlankets", ctypes.c_int32),
        ("aidStability", ctypes.c_float),
        ("aidAutoClutch", ctypes.c_int32),
        ("aidAutoBlip", ctypes.c_int32),
        ("hasDRS", ctypes.c_int32),
        ("hasERS", ctypes.c_int32),
        ("hasKERS", ctypes.c_int32),
        ("maxKersChargeKJ", ctypes.c_float),
        ("kersMaxJ", ctypes.c_float),
        ("ersPowerController", ctypes.c_int32),
        ("trackConfiguration", ctypes.c_wchar * 33),
        ("drsMaxDistanceM", ctypes.c_float),
        ("drsMinimumSpeedKMH", ctypes.c_float),
        ("isOnline", ctypes.c_int32),
    ]


class AssettoCorsaSharedMemory:
    """Manages connection and reads from Assetto Corsa Shared Memory"""

    def __init__(self):
        self.phys_mmap: Optional[mmap.mmap] = None
        self.gfx_mmap: Optional[mmap.mmap] = None
        self.stat_mmap: Optional[mmap.mmap] = None
        self.is_connected = False

    def connect(self) -> bool:
        """Attempts to open AC memory maps on Windows"""
        if sys.platform != "win32":
            return False
        if not ac_shared_memory_available():
            return False

        try:
            self.phys_mmap = mmap.mmap(
                0,
                ctypes.sizeof(SPageFilePhysics),
                "acpmf_physics",
                access=mmap.ACCESS_READ,
            )
            self.gfx_mmap = mmap.mmap(
                0,
                ctypes.sizeof(SPageFileGraphic),
                "acpmf_graphics",
                access=mmap.ACCESS_READ,
            )
            self.stat_mmap = mmap.mmap(
                0,
                ctypes.sizeof(SPageFileStatic),
                "acpmf_static",
                access=mmap.ACCESS_READ,
            )
            self.is_connected = True
            return True
        except Exception:
            self.disconnect()
            self.is_connected = False
            return False

    def disconnect(self):
        """Closes memory map handles"""
        for m in [self.phys_mmap, self.gfx_mmap, self.stat_mmap]:
            if m is not None:
                try:
                    m.close()
                except Exception:
                    pass
        self.phys_mmap = None
        self.gfx_mmap = None
        self.stat_mmap = None
        self.is_connected = False

    def read(self) -> Optional[Dict[str, Any]]:
        """Reads current telemetry frame and returns a structured dictionary"""
        if not self.is_connected:
            if not self.connect():
                return None

        try:
            phys = SPageFilePhysics.from_buffer_copy(self.phys_mmap)
            gfx = SPageFileGraphic.from_buffer_copy(self.gfx_mmap)
            stat = SPageFileStatic.from_buffer_copy(self.stat_mmap)

            # Convert gear: AC uses 0=R, 1=N, 2=1st, 3=2nd...
            raw_gear = phys.gear
            if raw_gear == 0:
                gear_display = "R"
            elif raw_gear == 1:
                gear_display = "N"
            else:
                gear_display = str(raw_gear - 1)

            # Heading in degrees (0 = North)
            heading_deg = math.degrees(phys.heading) % 360

            # Avg Tyre Temp
            tyre_temps = list(phys.tyreCoreTemperature)
            avg_tyre_temp = sum(tyre_temps) / 4.0 if tyre_temps else 0.0

            return {
                "connected": True,
                "status": gfx.status,  # 0=off, 1=replay, 2=live, 3=pause
                "session": gfx.session,
                "track": str(stat.track).strip(),
                "trackConfig": str(stat.trackConfiguration).strip(),
                "carModel": str(stat.carModel).strip(),
                "playerName": str(stat.playerName).strip(),
                # Car dynamics
                "speedKmh": round(phys.speedKmh, 1),
                "speedMph": round(phys.speedKmh * 0.621371, 1),
                "gear": gear_display,
                "rawGear": raw_gear,
                "rpms": int(phys.rpms),
                "maxRpm": int(stat.maxRpm) if stat.maxRpm > 0 else 8500,
                "gas": round(phys.gas, 2),
                "brake": round(phys.brake, 2),
                "clutch": round(phys.clutch, 2),
                "steerAngle": round(phys.steerAngle, 1),
                "headingRad": phys.heading,
                "headingDeg": round(heading_deg, 1),
                "pitch": round(phys.pitch, 3),
                "roll": round(phys.roll, 3),
                "velocity": [round(v, 2) for v in phys.velocity],
                # World coordinates
                "carPosition": [
                    round(gfx.carCoordinates[0], 2),
                    round(gfx.carCoordinates[1], 2),
                    round(gfx.carCoordinates[2], 2),
                ],
                # Session & Race Info
                "completedLaps": gfx.completedLaps,
                "position": gfx.position,
                "currentTime": str(gfx.currentTime).strip(),
                "bestTime": str(gfx.bestTime).strip(),
                "lastTime": str(gfx.lastTime).strip(),
                "split": str(gfx.split).strip(),
                "distanceTraveled": round(gfx.distanceTraveled, 1),
                "normalizedPosition": round(gfx.normalizedCarPosition, 4),
                "sessionTimeLeft": round(gfx.sessionTimeLeft, 1),
                # Flags & Pit
                "flag": gfx.flag,
                "isInPit": bool(gfx.isInPit),
                "isInPitLane": bool(gfx.isInPitLane),
                "pitLimiterOn": bool(phys.pitLimiterOn),
                # Vehicle Health & Fuel
                "fuel": round(phys.fuel, 1),
                "maxFuel": round(stat.maxFuel, 1) if stat.maxFuel > 0 else 100.0,
                "fuelPercent": round((phys.fuel / stat.maxFuel * 100.0), 1) if stat.maxFuel > 0 else 100.0,
                "tyreWear": [round(w, 1) for w in phys.tyreWear],
                "tyreTemps": [round(t, 1) for t in tyre_temps],
                "avgTyreTemp": round(avg_tyre_temp, 1),
                "turboBoost": round(phys.turboBoost, 2),
                "drsAvailable": bool(phys.drsAvailable),
                "drsEnabled": bool(phys.drsEnabled),
            }
        except Exception:
            self.disconnect()
            return None
