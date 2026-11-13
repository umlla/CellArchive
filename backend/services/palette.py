"""细胞株配色：同一物种用相近色系，不同物种明显区分，且每次加载颜色一致。

配色规则（不预设任何物种）：
1. 物种标签完全由使用者自由填写；系统只按「标签」分配色相区间，
   与标签的具体内容无关，所以新增物种不需要改代码。
2. 色相区间按标签稳定哈希均匀铺满色环，相邻区间之间留有间隙，
   保证不同物种颜色一定不同；同一物种内的细胞株在区间内取不同色相，
   并搭配 3 档饱和度/亮度，做到「同物种相近、同物种内仍可区分」。
3. 未填物种的细胞株统一用中性灰蓝，不会抢占有物种细胞株的颜色。
4. 同一细胞株不同批次共用该细胞株的颜色，只靠深浅区分。

颜色完全由 (物种标签, 细胞株 id) 决定，不依赖列表顺序、不随机，
所以在看板、组内曲线、生长曲线对比、增殖速率柱状图里同一个细胞株永远是同一个颜色。
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from typing import Any

# 一个物种占用的色相区间宽度（度）。
# 注意不能用等分色环：蓝色区（约 200-280°）人眼分辨力强、占视觉面积大，
# 而绿-黄区（约 70-140°）很窄，等分会让多个物种挤在蓝紫区难以区分。
# 下面这组「非等宽」边界让每个物种分到的色相块在视觉上大小接近。
_HUE_BOUNDARIES = (0.0, 26.0, 52.0, 78.0, 104.0, 140.0, 176.0, 212.0, 248.0, 284.0, 316.0, 344.0)
# 区间内只用中间 70%，两侧留白，避免相邻物种在边界处撞色
_INNER_RATIO = 0.7

_SATURATION_BANDS = (0.70, 0.60, 0.78)
_LIGHTNESS_BANDS = (0.42, 0.50, 0.35)

FALLBACK_COLOR = "#64748b"
_NO_SPECIES_COLOR = "#94a3b8"


def _stable_hash(*parts: Any) -> int:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.md5(raw).hexdigest()[:8], 16)


def _hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    hue = hue % 360.0
    chroma = (1 - abs(2 * lightness - 1)) * saturation
    x = chroma * (1 - abs((hue / 60.0) % 2 - 1))
    m = lightness - chroma / 2
    if hue < 60:
        rgb = (chroma, x, 0.0)
    elif hue < 120:
        rgb = (x, chroma, 0.0)
    elif hue < 180:
        rgb = (0.0, chroma, x)
    elif hue < 240:
        rgb = (0.0, x, chroma)
    elif hue < 300:
        rgb = (x, 0.0, chroma)
    else:
        rgb = (chroma, 0.0, x)
    return "#" + "".join(f"{round((value + m) * 255):02x}" for value in rgb)


def _slot_range(slot: int, slot_count: int) -> tuple[float, float]:
    """取第 slot 个色相区间 [low, high]。槽位数超过预设边界时退回等分。"""
    if slot_count == len(_HUE_BOUNDARIES):
        low = _HUE_BOUNDARIES[slot]
        high = _HUE_BOUNDARIES[(slot + 1) % len(_HUE_BOUNDARIES)] or 360.0
        return low, high
    width = 360.0 / max(1, slot_count)
    return slot * width, (slot + 1) * width


def assign_slots(species_names: list[str]) -> dict[str, int]:
    """给物种分配色相槽位，保证互不重叠。

    核心原则：**一个物种的颜色只由它自己的名字决定**，不受其它物种影响。
    所以这里不再按「集合整体」排布，而是：

    1. 每个物种先用 `hash(名字) % 槽位数` 算出自己的首选槽位；
    2. 万一两个物种撞到同一槽位（概率很低），按标签排序做线性探测，
       让排在后面的那个顺延到下一个空槽。

    这样新增/改名一个物种时，**已有物种的颜色不会变**
    （除非新物种恰好撞到它的槽位且排序在前），不会出现整体重排。
    """
    names = sorted({name.strip() for name in species_names if name and name.strip()})
    total = len(_HUE_BOUNDARIES)
    if not names:
        return {}
    # 探测步长与槽位数互质，才能遍历所有槽位
    step = 1
    for candidate in (5, 4, 3):
        if math.gcd(candidate, total) == 1:
            step = candidate
            break

    used: dict[str, int] = {}
    taken: set[int] = set()
    for name in names:
        preferred = _stable_hash("species-slot", name) % total
        slot = preferred
        for probe in range(total):
            candidate = (preferred + probe * step) % total
            if candidate not in taken:
                slot = candidate
                break
        taken.add(slot)
        used[name] = slot
    return used


def color_for(species: str | None, line_id: int | None, slot: int = 0) -> str:
    """返回某细胞株的固定颜色。slot 由 assign_slots() 给出。"""
    line_id = int(line_id or 0)
    name = (species or "").strip()
    if not name:
        return _NO_SPECIES_COLOR
    low, high = _slot_range(slot % len(_HUE_BOUNDARIES), len(_HUE_BOUNDARIES))
    if high <= low:
        high += 360.0
    span = (high - low) * _INNER_RATIO
    seed = _stable_hash(name, line_id)
    hue = low + span * ((seed % 1000) / 1000.0)
    saturation = _SATURATION_BANDS[(seed // 1000) % len(_SATURATION_BANDS)]
    lightness = _LIGHTNESS_BANDS[(seed // 10000) % len(_LIGHTNESS_BANDS)]
    return _hsl_to_hex(hue, saturation, lightness)


def lighten(hex_color: str, amount: float = 0.35) -> str:
    """把颜色调浅，用于同细胞株不同批次的次要曲线。"""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    channels = [int(value[index:index + 2], 16) for index in (0, 2, 4)]
    mixed = [round(channel + (255 - channel) * amount) for channel in channels]
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def _slot_count(species_names: list[str]) -> int:
    """槽位数固定为预设的视觉等宽区间数量，保证同一物种的色系不随物种数量变化。"""
    return len(_HUE_BOUNDARIES)


def line_colors(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """所有细胞株的配色表：{cell_line_id: {species, color}}。"""
    try:
        rows = conn.execute("SELECT id, species FROM cell_lines ORDER BY id").fetchall()
    except sqlite3.OperationalError:
        return {}
    slots = assign_slots([row["species"] or "" for row in rows])
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        line_id = int(row["id"])
        species = (row["species"] or "").strip()
        result[line_id] = {
            "species": row["species"],
            "color": color_for(species, line_id, slots.get(species, 0)),
        }
    return result


def color_map(conn: sqlite3.Connection) -> dict[int, str]:
    return {line_id: info["color"] for line_id, info in line_colors(conn).items()}


def resolver(conn: sqlite3.Connection):
    """返回一个 (species, line_id) -> 颜色 的函数，供各处图表复用同一套分配。"""
    colors = line_colors(conn)
    slots = assign_slots([info["species"] or "" for info in colors.values()])

    def resolve(species: str | None, line_id: int | None) -> str:
        name = (species or "").strip()
        # 已知细胞株直接取预计算好的颜色，保证与前端配色表完全一致
        if line_id is not None and int(line_id) in colors:
            return colors[int(line_id)]["color"]
        return color_for(name, line_id, slots.get(name, 0))

    return resolve
