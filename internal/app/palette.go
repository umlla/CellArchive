package app

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// 细胞株配色：同一标签用相近色系，不同标签明显区分，且每次加载颜色一致。
//
// 配色规则（不预设任何标签含义）：
//  1. 标签完全由使用者自由填写；系统只按「标签」分配色相区间，
//     与标签的具体内容无关，所以新增标签不需要改代码。
//  2. 色相区间按标签稳定哈希均匀铺满色环，相邻区间之间留有间隙，
//     保证不同标签颜色一定不同；同一标签内的细胞株在区间内取不同色相，
//     并搭配 3 档饱和度/亮度，做到「同标签相近、同标签内仍可区分」。
//  3. 未填标签的细胞株统一用中性灰蓝，不会抢占有标签细胞株的颜色。
//  4. 同一细胞株不同批次共用该细胞株的颜色，只靠深浅区分。
//
// 颜色完全由 (标签, 细胞株 id) 决定，不依赖列表顺序、不随机，
// 所以在看板、组内曲线、生长曲线对比、增殖速率柱状图里同一个细胞株永远是同一个颜色。
//
// 注意：这里的哈希与色相计算必须与 Python 版 backend/services/palette.py 完全一致，
// 否则同一个数据库在两个版本下颜色会不同。

// 一个标签占用的色相区间宽度（度）。
// 不能用等分色环：蓝色区（约 200-280°）人眼分辨力强、占视觉面积大，
// 而绿-黄区（约 70-140°）很窄，等分会让多个标签挤在蓝紫区难以区分。
// 下面这组「非等宽」边界让每个标签分到的色相块在视觉上大小接近。
var hueBoundaries = []float64{0, 26, 52, 78, 104, 140, 176, 212, 248, 284, 316, 344}

// 区间内只用中间 70%，两侧留白，避免相邻标签在边界处撞色
const innerRatio = 0.7

var saturationBands = []float64{0.70, 0.60, 0.78}
var lightnessBands = []float64{0.42, 0.50, 0.35}

const (
	fallbackColor   = "#64748b"
	noSpeciesColor  = "#94a3b8"
	slotCountForHue = 12
)

// stableHash 复刻 Python 的 int(md5(...).hexdigest()[:8], 16)。
func stableHash(parts ...string) int64 {
	joined := strings.Join(parts, "|")
	sum := md5.Sum([]byte(joined))
	head := hex.EncodeToString(sum[:])[:8]
	value, err := strconv.ParseInt(head, 16, 64)
	if err != nil {
		return 0
	}
	return value
}

func hslToHex(hue, saturation, lightness float64) string {
	hue = math.Mod(hue, 360)
	if hue < 0 {
		hue += 360
	}
	chroma := (1 - math.Abs(2*lightness-1)) * saturation
	x := chroma * (1 - math.Abs(math.Mod(hue/60, 2)-1))
	m := lightness - chroma/2

	var r, g, b float64
	switch {
	case hue < 60:
		r, g, b = chroma, x, 0
	case hue < 120:
		r, g, b = x, chroma, 0
	case hue < 180:
		r, g, b = 0, chroma, x
	case hue < 240:
		r, g, b = 0, x, chroma
	case hue < 300:
		r, g, b = x, 0, chroma
	default:
		r, g, b = chroma, 0, x
	}
	return fmt.Sprintf("#%02x%02x%02x",
		roundHalfUp((r+m)*255), roundHalfUp((g+m)*255), roundHalfUp((b+m)*255))
}

// roundHalfUp 复刻 Python 的 round()（四舍六入五成双不适用于此处的浮点范围，
// 用 +0.5 取整即可与 Python 结果一致）。
func roundHalfUp(value float64) int {
	return int(math.Floor(value + 0.5))
}

func slotRange(slot, slotCount int) (float64, float64) {
	if slotCount == len(hueBoundaries) {
		low := hueBoundaries[slot]
		high := hueBoundaries[(slot+1)%len(hueBoundaries)]
		if high == 0 {
			high = 360
		}
		return low, high
	}
	width := 360.0 / math.Max(1, float64(slotCount))
	return float64(slot) * width, float64(slot+1) * width
}

// assignSlots 给标签分配色相槽位，保证互不重叠。
//
// 核心原则：一个标签的颜色只由它自己的名字决定，不受其它标签影响。
//  1. 每个标签先用 hash(名字) % 槽位数 算出自己的首选槽位；
//  2. 万一两个标签撞到同一槽位（概率很低），按标签排序做线性探测，
//     让排在后面的那个顺延到下一个空槽。
//
// 这样新增/改名一个标签时，已有标签的颜色不会变（除非撞位且排序在前）。
func assignSlots(names []string) map[string]int {
	unique := map[string]struct{}{}
	for _, name := range names {
		trimmed := strings.TrimSpace(name)
		if trimmed != "" {
			unique[trimmed] = struct{}{}
		}
	}
	sorted := make([]string, 0, len(unique))
	for name := range unique {
		sorted = append(sorted, name)
	}
	sort.Strings(sorted)

	result := make(map[string]int, len(sorted))
	if len(sorted) == 0 {
		return result
	}

	total := len(hueBoundaries)
	// 探测步长与槽位数互质，才能遍历所有槽位
	step := 1
	for _, candidate := range []int{5, 4, 3} {
		if gcd(candidate, total) == 1 {
			step = candidate
			break
		}
	}

	taken := map[int]struct{}{}
	for _, name := range sorted {
		preferred := int(stableHash("species-slot", name) % int64(total))
		slot := preferred
		for probe := 0; probe < total; probe++ {
			candidate := (preferred + probe*step) % total
			if _, used := taken[candidate]; !used {
				slot = candidate
				break
			}
		}
		taken[slot] = struct{}{}
		result[name] = slot
	}
	return result
}

func gcd(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	if a < 0 {
		return -a
	}
	return a
}

// colorFor 返回某细胞株的固定颜色。slot 由 assignSlots() 给出。
func colorFor(species string, lineID int64, slot int) string {
	name := strings.TrimSpace(species)
	if name == "" {
		return noSpeciesColor
	}
	low, high := slotRange(((slot%len(hueBoundaries))+len(hueBoundaries))%len(hueBoundaries), len(hueBoundaries))
	if high <= low {
		high += 360
	}
	span := (high - low) * innerRatio
	seed := stableHash(name, strconv.FormatInt(lineID, 10))
	hue := low + span*(float64(seed%1000)/1000.0)
	saturation := saturationBands[(seed/1000)%int64(len(saturationBands))]
	lightness := lightnessBands[(seed/10000)%int64(len(lightnessBands))]
	return hslToHex(hue, saturation, lightness)
}

// lighten 把颜色调浅，用于同细胞株不同批次的次要曲线。
func lighten(hexColor string, amount float64) string {
	value := strings.TrimPrefix(hexColor, "#")
	if len(value) != 6 {
		return hexColor
	}
	channels := make([]int, 3)
	for i := 0; i < 3; i++ {
		parsed, err := strconv.ParseInt(value[i*2:i*2+2], 16, 64)
		if err != nil {
			return hexColor
		}
		channels[i] = int(parsed)
	}
	for i, channel := range channels {
		channels[i] = roundHalfUp(float64(channel) + (255-float64(channel))*amount)
	}
	return fmt.Sprintf("#%02x%02x%02x", channels[0], channels[1], channels[2])
}

// lineColorInfo 是某个细胞株的配色信息。
type lineColorInfo struct {
	Species string `json:"species"`
	Color   string `json:"color"`
}

// lineColors 返回所有细胞株的配色表：{cell_line_id: {species, color}}。
func lineColors(ctx context.Context, q Querier) (map[int64]lineColorInfo, error) {
	rows, err := queryMaps(ctx, q, `SELECT id, species FROM cell_lines ORDER BY id`)
	if err != nil {
		// 旧库可能还没有 species 列，此时不给颜色，前端用兜底色
		return map[int64]lineColorInfo{}, nil
	}
	names := make([]string, 0, len(rows))
	for _, row := range rows {
		names = append(names, rowString(row, "species"))
	}
	slots := assignSlots(names)

	result := make(map[int64]lineColorInfo, len(rows))
	for _, row := range rows {
		lineID := rowInt(row, "id")
		species := rowString(row, "species")
		result[lineID] = lineColorInfo{
			Species: species,
			Color:   colorFor(species, lineID, slots[strings.TrimSpace(species)]),
		}
	}
	return result, nil
}

// colorResolver 返回一个 (species, line_id) -> 颜色 的函数，供各处图表复用同一套分配。
// 已知细胞株直接取预计算好的颜色，保证与前端配色表完全一致。
func colorResolver(ctx context.Context, q Querier) func(species string, lineID int64) string {
	colors, _ := lineColors(ctx, q)
	names := make([]string, 0, len(colors))
	for _, info := range colors {
		names = append(names, info.Species)
	}
	slots := assignSlots(names)

	return func(species string, lineID int64) string {
		if info, ok := colors[lineID]; ok {
			return info.Color
		}
		name := strings.TrimSpace(species)
		return colorFor(name, lineID, slots[name])
	}
}

// speciesPalette 汇总给前端的配色表。
type speciesPalette struct {
	Species []speciesColorEntry `json:"species"`
	Lines   []lineColorEntry    `json:"lines"`
}

type speciesColorEntry struct {
	Species string `json:"species"`
	Color   string `json:"color"`
}

type lineColorEntry struct {
	CellLineID int64  `json:"cell_line_id"`
	Species    string `json:"species"`
	Color      string `json:"color"`
}

// buildSpeciesPalette 生成 /api/meta 里的 species_colors 字段。
func buildSpeciesPalette(ctx context.Context, q Querier) speciesPalette {
	colors, _ := lineColors(ctx, q)
	lines := make([]lineColorEntry, 0, len(colors))
	bySpecies := map[string]string{}
	for lineID, info := range colors {
		lines = append(lines, lineColorEntry{
			CellLineID: lineID,
			Species:    info.Species,
			Color:      info.Color,
		})
		name := strings.TrimSpace(info.Species)
		if name != "" {
			if _, seen := bySpecies[name]; !seen {
				bySpecies[name] = info.Color
			}
		}
	}
	sort.Slice(lines, func(i, j int) bool { return lines[i].CellLineID < lines[j].CellLineID })

	names := make([]string, 0, len(bySpecies))
	for name := range bySpecies {
		names = append(names, name)
	}
	sort.Strings(names)
	species := make([]speciesColorEntry, 0, len(names))
	for _, name := range names {
		species = append(species, speciesColorEntry{Species: name, Color: bySpecies[name]})
	}
	return speciesPalette{Species: species, Lines: lines}
}
