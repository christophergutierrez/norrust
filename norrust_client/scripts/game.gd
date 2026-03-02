extends Node2D

const BOARD_COLS  = 8
const BOARD_ROWS  = 5

# Circumradius of each drawn hexagon (center to vertex, pixels).
const HEX_RADIUS  = 32.0

# Tile cell size for a regular pointy-top hex with circumradius HEX_RADIUS:
#   width  = R × √3  ≈ 55px  (horizontal center-to-center stride)
#   height = R × 2   = 64px  (vertical bounding box; stride = height × 0.75 = 48 = R×1.5)
# This ensures same-row and diagonal neighbours both share edges with no gaps.
const HEX_CELL_W  = 55   # roundi(HEX_RADIUS * sqrt(3))
const HEX_CELL_H  = 64   # HEX_RADIUS * 2

const COLOR_FLAT = Color(0.29, 0.49, 0.31)  # #4a7c4e — fallback for hexes without color data

# Stride constants for get_reachable_hexes() — returns [col, row, col, row, ...]
const RH_STRIDE = 2
const RH_COL    = 0
const RH_ROW    = 1

var _core: NorRustCore
var _tile_map: TileMap
var _selected_unit_id: int = -1
var _reachable_cells: Array = []   # Array of Vector2i
var _game_over: bool = false

func _ready() -> void:
	_setup_rust_core()
	_setup_tilemap()
	_center_camera()
	queue_redraw()

func _setup_rust_core() -> void:
	_core = NorRustCore.new()
	add_child(_core)

	var project_dir = ProjectSettings.globalize_path("res://")
	var data_path = project_dir + "/../data"
	_core.load_data(data_path)

	_core.create_game(BOARD_COLS, BOARD_ROWS, 42)

	# Generate procedural terrain (seed=42 produces the default map layout)
	_core.generate_map(42)

	# Spawn 5 fighters per faction — stats are copied from the UnitDef registry.
	# 5 enemies per side means a unit can reach 40 XP (5 kills × 9 XP each)
	# and advance during normal play.
	_core.place_unit_at(1, "fighter", 30, 0, 0, 0)
	_core.place_unit_at(2, "fighter", 30, 0, 0, 2)
	_core.place_unit_at(3, "fighter", 30, 0, 0, 4)
	_core.place_unit_at(4, "fighter", 30, 0, 1, 1)
	_core.place_unit_at(5, "fighter", 30, 0, 1, 3)
	_core.place_unit_at(6, "fighter", 30, 1, 7, 0)
	_core.place_unit_at(7, "fighter", 30, 1, 7, 2)
	_core.place_unit_at(8, "fighter", 30, 1, 7, 4)
	_core.place_unit_at(9, "fighter", 30, 1, 6, 1)
	_core.place_unit_at(10, "fighter", 30, 1, 6, 3)

func _setup_tilemap() -> void:
	var tile_set = TileSet.new()
	tile_set.tile_shape       = TileSet.TILE_SHAPE_HEXAGON
	tile_set.tile_layout      = TileSet.TILE_LAYOUT_STACKED
	tile_set.tile_offset_axis = TileSet.TILE_OFFSET_AXIS_HORIZONTAL
	tile_set.tile_size        = Vector2i(HEX_CELL_W, HEX_CELL_H)

	# TileMap is invisible — used only for coordinate math (map_to_local, local_to_map).
	# Hexagons are drawn manually in _draw() below.
	_tile_map = TileMap.new()
	_tile_map.tile_set = tile_set
	_tile_map.visible = false
	add_child(_tile_map)

func _center_camera() -> void:
	var top_left     = _tile_map.map_to_local(Vector2i(0, 0))
	var bot_right    = _tile_map.map_to_local(Vector2i(BOARD_COLS - 1, BOARD_ROWS - 1))
	var board_centre = (top_left + bot_right) / 2.0
	var screen_centre = Vector2(
		ProjectSettings.get_setting("display/window/size/viewport_width"),
		ProjectSettings.get_setting("display/window/size/viewport_height")
	) / 2.0
	_tile_map.position = screen_centre - board_centre

func _parse_state() -> Dictionary:
	var json_str = _core.get_state_json()
	var parsed = JSON.parse_string(json_str)
	return parsed if parsed != null else {}

func _draw() -> void:
	var state = _parse_state()

	# Build per-hex color map from state snapshot (colors defined in terrain TOMLs)
	var tile_colors: Dictionary = {}
	for tile in state.get("terrain", []):
		var c: String = tile.get("color", "")
		tile_colors[Vector2i(int(tile["col"]), int(tile["row"]))] = \
			Color.html(c) if c != "" else COLOR_FLAT

	# 1. Terrain hexes
	for col in range(BOARD_COLS):
		for row in range(BOARD_ROWS):
			var center = _tile_map.map_to_local(Vector2i(col, row)) + _tile_map.position
			var color  = tile_colors.get(Vector2i(col, row), COLOR_FLAT)
			draw_polygon(_hex_polygon(center, HEX_RADIUS), [color])

	# 2. Reachable hex highlights (semi-transparent yellow overlay)
	for cell in _reachable_cells:
		var center = _tile_map.map_to_local(cell) + _tile_map.position
		draw_polygon(_hex_polygon(center, HEX_RADIUS), [Color(1, 1, 0, 0.35)])

	# 3. Selected unit outline (white polyline ring)
	if _selected_unit_id != -1:
		for unit in state.get("units", []):
			if unit["id"] == _selected_unit_id:
				var center = _tile_map.map_to_local(Vector2i(unit["col"], unit["row"])) + _tile_map.position
				var pts = _hex_polygon(center, HEX_RADIUS)
				pts.append(pts[0])   # close the loop
				draw_polyline(pts, Color.WHITE, 2.5)

	# 4. Unit circles + HP text
	_draw_units(state)

	# 5. Win overlay
	if _game_over:
		var winner = _core.get_winner()
		var msg = "Faction %d wins!" % winner
		var screen_w = ProjectSettings.get_setting("display/window/size/viewport_width")
		var screen_h = ProjectSettings.get_setting("display/window/size/viewport_height")
		var center = Vector2(screen_w, screen_h) / 2.0
		draw_string(
			ThemeDB.fallback_font,
			center + Vector2(-80, 0),
			msg,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1, 32, Color.YELLOW
		)

	# 6. HUD: Turn · Time of Day · Active Faction (text color matches unit circle color)
	if not _game_over:
		var faction     = _core.get_active_faction()
		var faction_name  = "Blue" if faction == 0 else "Red"
		var faction_color = Color(0.25, 0.42, 0.88) if faction == 0 else Color(0.80, 0.12, 0.12)
		var tod = _core.get_time_of_day_name()
		var hud_text = "Turn %d  ·  %s  ·  %s's Turn" % [_core.get_turn(), tod, faction_name]
		draw_string(
			ThemeDB.fallback_font,
			Vector2(10, 20),
			hud_text,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1, 14, faction_color
		)

func _draw_units(state: Dictionary) -> void:
	for unit in state.get("units", []):
		var col      = unit["col"]
		var row      = unit["row"]
		var faction  = unit["faction"]
		var hp       = unit["hp"]
		var exhausted = unit["moved"] or unit["attacked"]
		var center   = _tile_map.map_to_local(Vector2i(col, row)) + _tile_map.position
		var alpha    = 0.4 if exhausted else 1.0
		var color    = Color(0.25, 0.42, 0.88, alpha) if faction == 0 else Color(0.80, 0.12, 0.12, alpha)
		draw_circle(center, HEX_RADIUS * 0.45, color)
		draw_string(
			ThemeDB.fallback_font,
			center + Vector2(-8, 5),
			str(hp),
			HORIZONTAL_ALIGNMENT_LEFT,
			-1, 13, Color.WHITE
		)
		if unit["advancement_pending"]:
			draw_arc(center, HEX_RADIUS * 0.52, 0, TAU, 24, Color(1.0, 0.85, 0.0), 2.5)
		if unit["xp_needed"] > 0:
			draw_string(
				ThemeDB.fallback_font,
				center + Vector2(-10, 18),
				str(int(unit["xp"])) + "/" + str(int(unit["xp_needed"])),
				HORIZONTAL_ALIGNMENT_LEFT,
				-1, 10, Color.WHITE
			)

func _build_unit_pos_map(state: Dictionary) -> Dictionary:
	# Returns Dictionary: Vector2i(col, row) -> [unit_id, faction]
	var result: Dictionary = {}
	for unit in state.get("units", []):
		result[Vector2i(unit["col"], unit["row"])] = [int(unit["id"]), int(unit["faction"])]
	return result

func _clear_selection() -> void:
	_selected_unit_id = -1
	_reachable_cells = []

func _hex_polygon(center: Vector2, radius: float) -> PackedVector2Array:
	var pts = PackedVector2Array()
	for i in range(6):
		# Pointy-top hexagon: first vertex at -30° (top-right)
		var angle = deg_to_rad(60.0 * i - 30.0)
		pts.append(center + Vector2(cos(angle), sin(angle)) * radius)
	return pts

func _check_game_over() -> void:
	var winner = _core.get_winner()
	if winner >= 0:
		_game_over = true
		print("Faction %d wins!" % winner)
		queue_redraw()

func _input(event: InputEvent) -> void:
	if _game_over:
		return
	# 'E' key: end turn
	if event is InputEventKey:
		var key_event = event as InputEventKey
		if key_event.pressed and not key_event.echo and key_event.keycode == KEY_E:
			var result = _core.end_turn()
			print("End turn: code %d, faction %d, turn %d" % [result, _core.get_active_faction(), _core.get_turn()])
			_clear_selection()
			# Auto-play AI for faction 1. ai_take_turn() applies EndTurn internally,
			# so active faction returns to 0 after this call.
			if _core.get_active_faction() == 1:
				_core.ai_take_turn(1)
				_check_game_over()
			queue_redraw()
		elif key_event.pressed and not key_event.echo and key_event.keycode == KEY_A:
			if _selected_unit_id != -1:
				var state = _parse_state()
				var active = _core.get_active_faction()
				for unit in state.get("units", []):
					if int(unit["id"]) == _selected_unit_id and int(unit["faction"]) == active \
							and unit["advancement_pending"]:
						var result = _core.apply_advance(_selected_unit_id)
						print("Advance unit %d: code %d" % [_selected_unit_id, result])
						_clear_selection()
						queue_redraw()
						break
		return

	if not event is InputEventMouseButton:
		return
	if not (event as InputEventMouseButton).pressed:
		return
	if (event as InputEventMouseButton).button_index != MOUSE_BUTTON_LEFT:
		return

	var local_pos = _tile_map.to_local(get_global_mouse_position())
	var cell      = _tile_map.local_to_map(local_pos)
	var col       = cell.x
	var row       = cell.y

	if col < 0 or col >= BOARD_COLS or row < 0 or row >= BOARD_ROWS:
		_clear_selection()
		queue_redraw()
		return

	var clicked_cell = Vector2i(col, row)
	var state        = _parse_state()
	var pos_map      = _build_unit_pos_map(state)
	var active       = _core.get_active_faction()

	if _selected_unit_id != -1 and clicked_cell in pos_map and pos_map[clicked_cell][1] != active:
		# Attack enemy unit at clicked hex (check before reachable-move so enemy hexes
		# don't accidentally trigger a move attempt)
		var enemy_id = pos_map[clicked_cell][0]
		var result   = _core.apply_attack(_selected_unit_id, enemy_id)
		print("Attack result: %d" % result)
		_clear_selection()
		queue_redraw()
		_check_game_over()

	elif _selected_unit_id != -1 and clicked_cell in _reachable_cells:
		# Move selected unit to clicked reachable hex
		var result = _core.apply_move(_selected_unit_id, col, row)
		print("Moved unit %d to (%d, %d): code %d" % [_selected_unit_id, col, row, result])
		_clear_selection()
		queue_redraw()

	elif clicked_cell in pos_map and pos_map[clicked_cell][1] == active:
		# Select this friendly unit
		var uid = pos_map[clicked_cell][0]
		_selected_unit_id = uid
		var raw = _core.get_reachable_hexes(uid)
		_reachable_cells = []
		for k in range(0, raw.size(), RH_STRIDE):
			_reachable_cells.append(Vector2i(raw[k + RH_COL], raw[k + RH_ROW]))
		queue_redraw()

	else:
		_clear_selection()
		queue_redraw()
