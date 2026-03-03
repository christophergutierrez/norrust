extends Node2D

enum GameMode { PICK_FACTION_BLUE, PICK_FACTION_RED, SETUP_BLUE, SETUP_RED, PLAYING }

const BOARD_COLS  = 8
const BOARD_ROWS  = 5

# Circumradius of each drawn hexagon (center to vertex, pixels).
const HEX_RADIUS  = 64.0

# Tile cell size for a regular pointy-top hex with circumradius HEX_RADIUS:
#   width  = R × √3  ≈ 111px  (horizontal center-to-center stride)
#   height = R × 2   = 128px  (vertical bounding box; stride = height × 0.75 = 96 = R×1.5)
# This ensures same-row and diagonal neighbours both share edges with no gaps.
const HEX_CELL_W  = 111   # roundi(HEX_RADIUS * sqrt(3))
const HEX_CELL_H  = 128   # HEX_RADIUS * 2

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

var _game_mode: int = GameMode.PICK_FACTION_BLUE
var _factions: Array = []                  # [{id, name}, ...]
var _sel_faction_idx: int = 0              # highlighted row in faction picker
var _faction_id: Array = ["", ""]          # [blue_faction_id, red_faction_id]
var _leader_placed: Array = [false, false]
var _leader_level: Array = [1, 1]
var _palette: Array = []                   # list of def_id strings for current setup phase
var _selected_palette_idx: int = 0
var _next_unit_id: int = 1
var _recruit_mode: bool = false
var _recruit_palette: Array = []
var _selected_recruit_idx: int = 0
var _recruit_error: String = ""

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

	# Load board from scenario file; units are placed interactively in setup mode.
	# scenarios/ lives at the repo root, one level up from the Redot project.
	var scenarios_dir = project_dir + "/../scenarios"
	_core.load_board(scenarios_dir + "/contested.toml", 42)
	_core.load_factions(data_path)
	var raw = _core.get_faction_ids_json()
	_factions = JSON.parse_string(raw) if raw != "" else []

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

	# 2. Reachable hex highlights — skip in setup mode
	if _game_mode == GameMode.PLAYING:
		for cell in _reachable_cells:
			var center = _tile_map.map_to_local(cell) + _tile_map.position
			draw_polygon(_hex_polygon(center, HEX_RADIUS), [Color(1, 1, 0, 0.35)])

	# 3. Selected unit outline — skip in setup mode
	if _game_mode == GameMode.PLAYING and _selected_unit_id != -1:
		for unit in state.get("units", []):
			if unit["id"] == _selected_unit_id:
				var center = _tile_map.map_to_local(Vector2i(unit["col"], unit["row"])) + _tile_map.position
				var pts = _hex_polygon(center, HEX_RADIUS)
				pts.append(pts[0])   # close the loop
				draw_polyline(pts, Color.WHITE, 2.5)

	# 4. Unit circles + HP text (always drawn so placed units show up in setup)
	_draw_units(state)

	# 5. Setup HUD or game HUD
	if _game_mode != GameMode.PLAYING:
		_draw_setup_hud()
	else:
		# Win overlay
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

		# HUD: Turn · Time of Day · Active Faction (text color matches unit circle color)
		if not _game_over:
			var faction     = _core.get_active_faction()
			var faction_name  = "Blue" if faction == 0 else "Red"
			var faction_color = Color(0.25, 0.42, 0.88) if faction == 0 else Color(0.80, 0.12, 0.12)
			var tod = _core.get_time_of_day_name()
			var gold_arr = state.get("gold", [0, 0])
			var gold = int(gold_arr[faction])
			var hud_text = "Turn %d  ·  %s  ·  %s's Turn  ·  %dg" % [_core.get_turn(), tod, faction_name, gold]
			draw_string(
				ThemeDB.fallback_font,
				Vector2(10, 20),
				hud_text,
				HORIZONTAL_ALIGNMENT_LEFT,
				-1, 14, faction_color
			)

		if _recruit_mode:
			_draw_recruit_panel(state)

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

func _draw_setup_hud() -> void:
	var is_blue = (_game_mode == GameMode.PICK_FACTION_BLUE or _game_mode == GameMode.SETUP_BLUE)
	var faction_name  = "Blue" if is_blue else "Red"
	var faction_color = Color(0.25, 0.42, 0.88) if is_blue else Color(0.80, 0.12, 0.12)
	var screen_w = ProjectSettings.get_setting("display/window/size/viewport_width")
	var screen_h = ProjectSettings.get_setting("display/window/size/viewport_height")

	draw_rect(Rect2(screen_w - 200, 0, 200, screen_h), Color(0, 0, 0, 0.6))

	if _game_mode == GameMode.PICK_FACTION_BLUE or _game_mode == GameMode.PICK_FACTION_RED:
		draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 24),
			"FACTION — %s" % faction_name,
			HORIZONTAL_ALIGNMENT_LEFT, -1, 15, faction_color)
		draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 44),
			"Press 1-%d to pick" % _factions.size(),
			HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.LIGHT_GRAY)
		for i in range(_factions.size()):
			var y = 70 + i * 22
			var label = "[%d] %s" % [i + 1, _factions[i]["name"]]
			var col = Color.YELLOW if i == _sel_faction_idx else Color.WHITE
			draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, y),
				label, HORIZONTAL_ALIGNMENT_LEFT, -1, 13, col)
	else:
		draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 24),
			"SETUP — %s" % faction_name,
			HORIZONTAL_ALIGNMENT_LEFT, -1, 15, faction_color)
		var fi = _faction_index_for_mode()
		if not _leader_placed[fi]:
			var leader_def = _core.get_faction_leader(_faction_id[fi])
			# Sidebar: just show the unit name
			draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 44),
				"Place leader:", HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.LIGHT_GRAY)
			draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 62),
				leader_def, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color.YELLOW)
			# Draw prompt ON the board so the user clicks the board, not the sidebar
			var board_mid = _tile_map.map_to_local(Vector2i(BOARD_COLS / 2, BOARD_ROWS / 2)) + _tile_map.position
			var prompt = "Click a hex on the board to place %s" % leader_def
			draw_rect(Rect2(board_mid.x - 200, board_mid.y - 14, 400, 24), Color(0, 0, 0, 0.75))
			draw_string(ThemeDB.fallback_font, board_mid + Vector2(-196, 8),
				prompt, HORIZONTAL_ALIGNMENT_LEFT, -1, 13, Color.YELLOW)
		else:
			draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 44),
				"Leader placed.",
				HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.LIGHT_GRAY)
			draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 58),
				"[Enter] Continue",
				HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.YELLOW)

func _draw_recruit_panel(state: Dictionary) -> void:
	var faction = _core.get_active_faction()
	var screen_w = ProjectSettings.get_setting("display/window/size/viewport_width")
	var screen_h = ProjectSettings.get_setting("display/window/size/viewport_height")

	# Highlight keep hexes (gold) and castle hexes (bright cyan) in recruit mode
	for tile in state.get("terrain", []):
		var tid = tile.get("terrain_id", "")
		var center = _tile_map.map_to_local(Vector2i(int(tile["col"]), int(tile["row"]))) \
					 + _tile_map.position
		if tid == "keep":
			var pts = _hex_polygon(center, HEX_RADIUS)
			draw_polygon(pts, [Color(1.0, 0.75, 0.0, 0.7)])
			var border = pts
			border.append(border[0])
			draw_polyline(border, Color.YELLOW, 3.0)
		elif tid == "castle":
			var pts = _hex_polygon(center, HEX_RADIUS)
			draw_polygon(pts, [Color(0.0, 0.9, 0.9, 0.65)])
			var border = pts
			border.append(border[0])
			draw_polyline(border, Color.WHITE, 2.5)

	# Sidebar panel
	draw_rect(Rect2(screen_w - 200, 0, 200, screen_h), Color(0, 0, 0, 0.6))
	var faction_color = Color(0.25, 0.42, 0.88) if faction == 0 else Color(0.80, 0.12, 0.12)
	var gold_arr = state.get("gold", [0, 0])
	var gold = int(gold_arr[faction])
	draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 24),
		"RECRUIT — %dg" % gold, HORIZONTAL_ALIGNMENT_LEFT, -1, 15, faction_color)
	draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 44),
		"Leader must be on gold hex", HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.YELLOW)
	draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 58),
		"Click adjacent blue hex", HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.LIGHT_GRAY)
	draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 72),
		"[R] Cancel", HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.LIGHT_GRAY)
	if _recruit_error != "":
		draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, 86),
			_recruit_error, HORIZONTAL_ALIGNMENT_LEFT, -1, 11, Color.RED)
	for i in range(_recruit_palette.size()):
		var def_id = _recruit_palette[i]
		var cost = _core.get_unit_cost(def_id)
		var y = 108 + i * 20
		var label = "[%d] %s (%dg)" % [i + 1, def_id, cost]
		var col = Color.YELLOW if i == _selected_recruit_idx else Color.WHITE
		draw_string(ThemeDB.fallback_font, Vector2(screen_w - 190, y),
			label, HORIZONTAL_ALIGNMENT_LEFT, -1, 11, col)

func _build_unit_pos_map(state: Dictionary) -> Dictionary:
	# Returns Dictionary: Vector2i(col, row) -> [unit_id, faction]
	var result: Dictionary = {}
	for unit in state.get("units", []):
		result[Vector2i(unit["col"], unit["row"])] = [int(unit["id"]), int(unit["faction"])]
	return result

func _faction_index_for_mode() -> int:
	return 0 if _game_mode == GameMode.SETUP_BLUE else 1

func _reload_palette() -> void:
	var fi = _faction_index_for_mode()
	var raw = _core.get_faction_recruits_json(_faction_id[fi], _leader_level[fi])
	_palette = JSON.parse_string(raw) if raw != "" else []
	_selected_palette_idx = 0

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
	if _game_mode != GameMode.PLAYING:
		_handle_setup_input(event)
		return
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
				var n = _core.ai_recruit(_faction_id[1], _next_unit_id)
				_next_unit_id += n
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
		elif key_event.pressed and not key_event.echo and key_event.keycode == KEY_R:
			if not _recruit_mode:
				var faction = _core.get_active_faction()
				var raw = _core.get_faction_recruits_json(_faction_id[faction], 0)
				_recruit_palette = JSON.parse_string(raw) if raw != "" else []
				_selected_recruit_idx = 0
				_recruit_error = ""
				_recruit_mode = true
				_clear_selection()
			else:
				_recruit_mode = false
			queue_redraw()
		elif key_event.pressed and not key_event.echo \
				and key_event.keycode >= KEY_1 and key_event.keycode <= KEY_9:
			if _recruit_mode and _recruit_palette.size() > 0:
				_selected_recruit_idx = min(key_event.keycode - KEY_1, _recruit_palette.size() - 1)
				queue_redraw()
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

	if _recruit_mode:
		var def_id = _recruit_palette[_selected_recruit_idx] if _recruit_palette.size() > 0 else ""
		if def_id != "":
			var result = _core.recruit_unit_at(_next_unit_id, def_id, col, row)
			if result == 0:
				_next_unit_id += 1
				_recruit_error = ""
				_recruit_mode = false
				print("Recruited %s at (%d,%d)" % [def_id, col, row])
			else:
				# Keep recruit mode open so the player can try a different hex
				var err_map = {-4: "Hex is occupied", -8: "Not enough gold",
					-9: "Must click a castle hex", -10: "Move leader to the keep first"}
				_recruit_error = err_map.get(result, "Recruit failed (code %d)" % result)
				print("Recruit failed: code %d — %s" % [result, _recruit_error])
		queue_redraw()
		return

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

func _handle_setup_input(event: InputEvent) -> void:
	if event is InputEventKey and (event as InputEventKey).pressed \
			and not (event as InputEventKey).echo:
		var key = (event as InputEventKey).keycode

		if _game_mode == GameMode.PICK_FACTION_BLUE or _game_mode == GameMode.PICK_FACTION_RED:
			if key >= KEY_1 and key <= KEY_9:
				var idx = key - KEY_1
				if idx < _factions.size():
					var fi = 0 if _game_mode == GameMode.PICK_FACTION_BLUE else 1
					_faction_id[fi] = _factions[idx]["id"]
					_sel_faction_idx = 0
					_game_mode = GameMode.SETUP_BLUE if _game_mode == GameMode.PICK_FACTION_BLUE \
								 else GameMode.SETUP_RED
					queue_redraw()
				return

		# SETUP modes — key input
		if key == KEY_ENTER or key == KEY_KP_ENTER:
			if _game_mode == GameMode.SETUP_BLUE:
				_game_mode = GameMode.PICK_FACTION_RED
			else:
				# Both factions chosen — wire starting gold before game begins
				_core.apply_starting_gold(_faction_id[0], _faction_id[1])
				_game_mode = GameMode.PLAYING
			queue_redraw()
			return

	if not event is InputEventMouseButton:
		return
	if not (event as InputEventMouseButton).pressed:
		return
	if (event as InputEventMouseButton).button_index != MOUSE_BUTTON_LEFT:
		return
	if _game_mode == GameMode.PICK_FACTION_BLUE or _game_mode == GameMode.PICK_FACTION_RED:
		return

	var local_pos = _tile_map.to_local(get_global_mouse_position())
	var cell      = _tile_map.local_to_map(local_pos)
	var col = cell.x
	var row = cell.y
	if col < 0 or col >= BOARD_COLS or row < 0 or row >= BOARD_ROWS:
		return

	var state   = _parse_state()
	var pos_map = _build_unit_pos_map(state)
	var clicked = Vector2i(col, row)
	var fi      = _faction_index_for_mode()
	var faction = fi

	if not _leader_placed[fi]:
		# Place the leader — the only free unit in setup
		if clicked not in pos_map:
			var leader_def = _core.get_faction_leader(_faction_id[fi])
			_core.place_unit_at(_next_unit_id, leader_def, 0, faction, col, row)
			_next_unit_id += 1
			_leader_placed[fi] = true
		queue_redraw()
		return

	# Leader already placed — clicks do nothing in setup (recruit in battle with R)
	queue_redraw()
