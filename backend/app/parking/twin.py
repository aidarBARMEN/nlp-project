"""Цифровой двойник парковки КБТУ: состояние мест, симуляция датчиков, прогноз и подбор места.

Режимы:
    simulation — датчики симулируются по профилю спроса (расписание занятий, сценарий дня);
    live       — состояние приходит от реальных датчиков/камер через POST /api/parking/events.

Время двойника идёт с ускорением `speed` относительно реального (1 — реальное время).
"""

from __future__ import annotations

import json
import math
import random
import threading
from collections import deque
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

ALMATY = timezone(timedelta(hours=5))
LAYOUT_PATH = Path(__file__).parent / "data" / "layout.json"

# Доля занятых мест по часам (0–23) для разных сценариев
PROFILES = {
    "weekday": [.05, .04, .04, .04, .04, .05, .08, .25, .65, .88, .93, .94, .92, .85, .90, .92,
                .88, .75, .55, .38, .25, .15, .09, .06],
    "exam": [.05, .04, .04, .04, .04, .06, .15, .55, .95, .98, .98, .97, .95, .92, .95, .95,
             .90, .70, .45, .28, .18, .12, .08, .06],
    "weekend": [.04, .04, .03, .03, .03, .04, .05, .08, .15, .25, .35, .40, .42, .40, .38, .35,
                .30, .25, .20, .15, .10, .08, .05, .04],
}
SCENARIOS = {"weekday": "Учебный день", "exam": "Сессия / мероприятие", "weekend": "Выходной"}
# средняя продолжительность стоянки, мин: уличная — короче, дворовые — весь учебный день
DWELL = {"A": 100, "B": 260, "C": 240}
# уличная парковка — общественная: днём её занимают и не студенты
ZONE_DEMAND = {"A": 1.04, "B": 0.97, "C": 1.0}
TYPE_NAMES = {"regular": "Обычное", "disabled": "Для людей с инвалидностью", "ev": "Зарядка электромобиля",
              "staff": "Для сотрудников"}
LETTERS = "ABCDEHKMOPTXYZ"


def _now_local() -> datetime:
    return datetime.now(ALMATY).replace(tzinfo=None)


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class ParkingTwin:
    def __init__(self, layout_path: Path = LAYOUT_PATH, seed: int = 7):
        self.layout = json.loads(layout_path.read_text(encoding="utf-8"))
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.stalls = {s["id"]: s for s in self.layout["stalls"]}
        self.state = {sid: {"occupied": False, "plate": None, "since": None, "permit": False, "violation": None}
                      for sid in self.stalls}
        self.zones = {z["id"]: z for z in self.layout["zones"]}
        self.entrances = [p["at"] for p in self.layout["points"] if p["kind"].startswith("entrance")]
        self.events: deque = deque(maxlen=80)
        self.history: deque = deque(maxlen=24 * 12)  # срез каждые 5 минут за сутки
        self.mode = "simulation"
        self.scenario = "weekday"
        self.speed = 30.0
        self.paused = False
        self.clock = _now_local()
        self._real = datetime.now(UTC)
        self._last_sample = None
        self._warm_start()

    # ------------------------------------------------------------ симуляция
    def _profile(self, t: datetime) -> float:
        scenario = "weekend" if self.scenario == "weekday" and t.weekday() >= 5 else self.scenario
        prof = PROFILES[scenario]
        h = t.hour + t.minute / 60
        a, b = prof[int(h) % 24], prof[(int(h) + 1) % 24]
        return a + (b - a) * (h - int(h))

    def _plate(self) -> str:
        region = self.rng.choice(["02"] * 8 + ["01", "05", "13", "17"])
        return f"{self.rng.randint(100, 999)} {''.join(self.rng.choice(LETTERS) for _ in range(3))} {region}"

    def _zone_stalls(self, zid):
        return [sid for sid, s in self.stalls.items() if s["zone"] == zid]

    def _warm_start(self):
        """Прогоняет симуляцию с 5:00 до текущего времени: к открытию страницы у двойника
        уже есть реалистичное состояние и история загрузки за сегодняшнее утро."""
        now = self.clock
        start = now.replace(hour=5, minute=0, second=0, microsecond=0)
        if start > now:
            start -= timedelta(days=1)
        self.clock = start
        self._sample()
        while self.clock < now:
            self.clock += timedelta(minutes=1)
            self._tick(self.clock)
            if self.clock - self._last_sample >= timedelta(minutes=5):
                self._sample()

    def _park(self, sid, at, permit=False, log=True):
        st = self.state[sid]
        kind = self.stalls[sid]["type"]
        violation = None
        if kind == "disabled" and not permit:
            violation = "Место для людей с инвалидностью занято без разрешения"
        st.update(occupied=True, plate=self._plate(), since=at, permit=permit, violation=violation)
        if log:
            zone = self.stalls[sid]["zone"]
            source = "Камера въезда" if self.zones[zone].get("camera") else "Датчик места"
            self._event(at, "arrival", sid, f"{source}: {self._mask(st['plate'])} → место {sid}")
            if violation:
                self._event(at, "violation", sid, f"Нарушение: {violation.lower()} ({sid})")

    def _leave(self, sid, at):
        st = self.state[sid]
        minutes = int((at - st["since"]).total_seconds() // 60) if st["since"] else 0
        zone = self.stalls[sid]["zone"]
        source = "Камера выезда" if self.zones[zone].get("camera") else "Датчик места"
        self._event(at, "departure", sid, f"{source}: место {sid} освободилось ({minutes // 60} ч {minutes % 60} мин)")
        st.update(occupied=False, plate=None, since=None, permit=False, violation=None)

    def _event(self, at, kind, sid, text):
        self.events.appendleft({"at": at.isoformat(timespec="seconds"), "kind": kind, "stall": sid, "text": text})

    def _tick(self, t: datetime):
        """Одна минута симуляции."""
        target = self._profile(t)
        for zid in self.zones:
            ids = self._zone_stalls(zid)
            occ = [sid for sid in ids if self.state[sid]["occupied"]]
            goal = min(len(ids) * target * ZONE_DEMAND[zid], len(ids))
            # уход: базовая вероятность по средней стоянке + разгрузка, если машин больше цели
            p_leave = 1 / DWELL[zid] + max(0.0, len(occ) - goal) / max(len(occ), 1) * 0.08
            for sid in occ:
                if self.rng.random() < p_leave:
                    self._leave(sid, t)
            # приезд: стремимся к цели
            free = [sid for sid in ids if not self.state[sid]["occupied"]]
            lam = max(0.0, goal - (len(ids) - len(free))) * 0.12 + 0.01
            for _ in range(self._poisson(lam)):
                if not free:
                    break
                sid = self._choose(free, zid)
                free.remove(sid)
                kind = self.stalls[sid]["type"]
                permit = kind == "disabled" and self.rng.random() < 0.85
                self._park(sid, t, permit=permit)

    def _choose(self, free, zid):
        """Водители выбирают места ближе к въезду; спецместа — реже (обычно своими машинами)."""
        order = {sid: i for i, sid in enumerate(self._zone_stalls(zid))}
        weights = []
        for sid in free:
            w = math.exp(-order[sid] / 25)
            if self.stalls[sid]["type"] in ("disabled", "ev"):
                w *= 0.08
            weights.append(w)
        return self.rng.choices(free, weights=weights)[0]

    def _poisson(self, lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.rng.random()
            if p <= L:
                return k
            k += 1

    def _sample(self):
        occ = sum(s["occupied"] for s in self.state.values())
        self.history.append({"at": self.clock.isoformat(timespec="minutes"), "occupied": occ,
                             "rate": round(occ / len(self.state), 3)})
        self._last_sample = self.clock

    def advance(self):
        with self.lock:
            now = datetime.now(UTC)
            real = (now - self._real).total_seconds()
            self._real = now
            if self.paused or self.mode == "live":
                if self.mode == "live":
                    self.clock = _now_local()
                return
            minutes = real * self.speed / 60
            # большие разрывы (сервер «спал») не прогоняем поминутно
            if minutes > 720:
                self.clock += timedelta(minutes=minutes - 720)
                minutes = 720
            steps = int(minutes)
            self._carry = getattr(self, "_carry", 0.0) + minutes - steps
            if self._carry >= 1:
                steps += 1
                self._carry -= 1
            for _ in range(steps):
                self.clock += timedelta(minutes=1)
                self._tick(self.clock)
                if self._last_sample is None or self.clock - self._last_sample >= timedelta(minutes=5):
                    self._sample()

    # ------------------------------------------------------------ управление
    def control(self, speed=None, paused=None, scenario=None, jump_to=None, mode=None):
        with self.lock:
            self.advance()
            if speed is not None:
                self.speed = max(1.0, min(float(speed), 600.0))
            if paused is not None:
                self.paused = bool(paused)
            if scenario is not None:
                if scenario not in SCENARIOS:
                    raise ValueError("Неизвестный сценарий")
                self.scenario = scenario
            if mode is not None:
                if mode not in ("simulation", "live"):
                    raise ValueError("Режим: simulation или live")
                self.mode = mode
            if jump_to:
                h, m = (int(x) for x in jump_to.split(":"))
                target = self.clock.replace(hour=h, minute=m, second=0)
                if target <= self.clock:
                    target += timedelta(days=1)
                for _ in range(int((target - self.clock).total_seconds() // 60)):
                    self.clock += timedelta(minutes=1)
                    self._tick(self.clock)
                    if self.clock - self._last_sample >= timedelta(minutes=5):
                        self._sample()

    def sensor_event(self, stall_id: str, occupied: bool, plate: str | None = None):
        """Событие от реального датчика или камеры. Переводит двойник в режим live."""
        with self.lock:
            if stall_id not in self.state:
                raise KeyError(stall_id)
            self.mode = "live"
            self.clock = _now_local()
            st = self.state[stall_id]
            if occupied and not st["occupied"]:
                self._park(stall_id, self.clock, permit=False)
                if plate:
                    st["plate"] = plate
            elif not occupied and st["occupied"]:
                self._leave(stall_id, self.clock)
            self._sample()

    # ------------------------------------------------------------ выдача
    @staticmethod
    def _mask(plate: str | None) -> str | None:
        """Номер показывается частично: буквы и регион, цифры скрыты."""
        if not plate:
            return None
        num, letters, region = plate.split()
        return f"•••{letters} {region}"

    def snapshot(self) -> dict:
        with self.lock:
            self.advance()
            stalls = []
            for sid, st in self.state.items():
                stalls.append({
                    "id": sid,
                    "occupied": st["occupied"],
                    "plate": self._mask(st["plate"]),
                    "since": st["since"].isoformat(timespec="minutes") if st["since"] else None,
                    "minutes": int((self.clock - st["since"]).total_seconds() // 60) if st["since"] else None,
                    "violation": st["violation"],
                })
            zones = []
            for zid, z in self.zones.items():
                ids = self._zone_stalls(zid)
                free_by_type = {}
                for sid in ids:
                    if not self.state[sid]["occupied"]:
                        t = self.stalls[sid]["type"]
                        free_by_type[t] = free_by_type.get(t, 0) + 1
                zones.append({"id": zid, "name": z["name"], "total": len(ids),
                              "free": sum(free_by_type.values()), "free_by_type": free_by_type})
            total = len(self.state)
            occupied = sum(s["occupied"] for s in self.state.values())
            violations = [s["id"] for s in stalls if s["violation"]]
            return {
                "clock": self.clock.isoformat(timespec="seconds"),
                "mode": self.mode,
                "scenario": self.scenario,
                "scenarios": SCENARIOS,
                "speed": self.speed,
                "paused": self.paused,
                "totals": {"total": total, "occupied": occupied, "free": total - occupied,
                           "rate": round(occupied / total, 3), "violations": len(violations)},
                "zones": zones,
                "stalls": stalls,
                "events": list(self.events)[:30],
                "history": list(self.history),
                "forecast": self.forecast(),
            }

    def forecast(self) -> list[dict]:
        """Ожидаемая загрузка на сегодня по часам (профиль сценария + зональные коэффициенты)."""
        day = self.clock.replace(minute=0, second=0, microsecond=0)
        weight = {z: len(self._zone_stalls(z)) for z in self.zones}
        total = sum(weight.values())
        out = []
        for h in range(24):
            t = day.replace(hour=h)
            base = self._profile(t)
            rate = sum(min(base * ZONE_DEMAND[z], 1.0) * weight[z] for z in self.zones) / total
            out.append({"hour": h, "rate": round(rate, 3)})
        return out

    def recommend(self, need: str = "regular") -> dict | None:
        """Свободное место с кратчайшим путём пешком до входа в здание + маршрут машины к нему."""
        with self.lock:
            self.advance()
            allowed = {"regular": {"regular"}, "disabled": {"disabled", "regular"}, "ev": {"ev"},
                       "staff": {"staff", "regular"}}.get(need, {"regular"})
            best = None
            for sid, s in self.stalls.items():
                if self.state[sid]["occupied"] or s["type"] not in allowed:
                    continue
                walk = min(_dist(s["center"], e) for e in self.entrances)
                # нужный тип места важнее расстояния
                score = walk - (40 if s["type"] == need and need != "regular" else 0)
                if best is None or score < best[0]:
                    best = (score, sid, walk)
            if not best:
                return None
            sid, walk = best[1], best[2]
            stall = self.stalls[sid]
            entrance = min(self.entrances, key=lambda e: _dist(stall["center"], e))
            return {"stall": sid, "zone": stall["zone"], "type": stall["type"],
                    "walk_m": round(walk), "drive": self._route(stall), "walk": [stall["center"], entrance]}

    def _route(self, stall) -> list:
        zone = self.zones[stall["zone"]]
        if zone["kind"] == "street":
            return [stall["center"]]
        aisle = next(a["line"] for a in self.layout["aisles"] if a["zone"] == stall["zone"])
        if _dist(aisle[0], zone["entry"]) > _dist(aisle[-1], zone["entry"]):
            aisle = aisle[::-1]
        # едем по проезду до проекции места на ближайший отрезок проезда
        best = None
        for i, (p, q) in enumerate(zip(aisle, aisle[1:], strict=False)):
            dx, dy = q[0] - p[0], q[1] - p[1]
            seg2 = dx * dx + dy * dy or 1e-9
            t = max(0.0, min(1.0, ((stall["center"][0] - p[0]) * dx + (stall["center"][1] - p[1]) * dy) / seg2))
            proj = [round(p[0] + t * dx, 1), round(p[1] + t * dy, 1)]
            d = _dist(proj, stall["center"])
            if best is None or d < best[0]:
                best = (d, i, proj)
        _, i, proj = best
        return [*aisle[: i + 1], proj, stall["center"]]


_twin: ParkingTwin | None = None
_twin_lock = threading.Lock()


def get_twin() -> ParkingTwin:
    global _twin
    with _twin_lock:
        if _twin is None:
            _twin = ParkingTwin()
        return _twin
