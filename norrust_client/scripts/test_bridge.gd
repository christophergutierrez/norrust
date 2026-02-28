extends Node

func _ready():
	var core = NorRustCore.new()
	add_child(core)

	print("Core version: ", core.get_core_version())

	# Build absolute path to the data directory.
	# ProjectSettings.globalize_path("res://") returns the absolute path to
	# the norrust_client/ project root. The data directory is one level up.
	var project_dir = ProjectSettings.globalize_path("res://")
	var data_path = project_dir + "/../data"

	if core.load_data(data_path):
		print("Fighter HP: ", core.get_unit_max_hp("fighter"))
		print("Archer HP: ", core.get_unit_max_hp("archer"))
		print("Dragon HP: ", core.get_unit_max_hp("dragon"))
	else:
		push_error("Failed to load data from: " + data_path)

	core.queue_free()
