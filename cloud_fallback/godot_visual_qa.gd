extends Node2D
# Generated-only disposable project. No game assets, collision or player scripts.
func _ready() -> void:
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://atlas_data.json"))
	get_window().content_scale_mode = Window.CONTENT_SCALE_MODE_DISABLED
	get_window().size = Vector2i(768,768)
	var texture := load("res://paving_atlas.png") as Texture2D
	var atlas := TileSetAtlasSource.new()
	atlas.texture = texture
	atlas.texture_region_size = Vector2i(32,32)
	for cell in meta.cells:
		atlas.create_tile(Vector2i(cell.atlas_cell[0],cell.atlas_cell[1]))
	var tiles := TileSet.new()
	tiles.tile_size = Vector2i(32,32)
	tiles.add_source(atlas,0)
	var roads := TileMapLayer.new()
	roads.name = "Roads_WorldPaving_NOT_APPROVED"
	roads.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	roads.tile_set = tiles
	add_child(roads)
	for cell in meta.cells:
		roads.set_cell(Vector2i(cell.world_cell[0],cell.world_cell[1]),0,Vector2i(cell.atlas_cell[0],cell.atlas_cell[1]))
	var camera := Camera2D.new()
	camera.position = Vector2(meta.world_pixel_origin[0]+384,meta.world_pixel_origin[1]+384)
	add_child(camera)
	camera.make_current()
	if "--qa" not in OS.get_cmdline_user_args(): return
	var source := Image.load_from_file(ProjectSettings.globalize_path("res://paving_atlas.png"))
	var imported := texture.get_image()
	source.convert(Image.FORMAT_RGBA8)
	imported.convert(Image.FORMAT_RGBA8)
	var checks := {"import_lossless":source.get_data()==imported.get_data(),"mipmaps_disabled":not imported.has_mipmaps(),"filter_nearest":roads.texture_filter==CanvasItem.TEXTURE_FILTER_NEAREST,"atlas_cells":meta.cells.size(),"status":"MATERIAL_VISUAL_APPROVAL_REQUIRED"}
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var one := get_viewport().get_texture().get_image()
	one.convert(Image.FORMAT_RGBA8)
	one.save_png(ProjectSettings.globalize_path("res://godot_nearest_1x.png"))
	checks["one_x_pixels_exact"] = one.get_size()==source.get_size() and one.get_data()==source.get_data()
	camera.zoom = Vector2(2,2)
	await get_tree().process_frame
	await RenderingServer.frame_post_draw
	var two := get_viewport().get_texture().get_image()
	two.convert(Image.FORMAT_RGBA8)
	two.save_png(ProjectSettings.globalize_path("res://godot_nearest_2x.png"))
	var expected := source.get_region(Rect2i(192,192,384,384))
	expected.resize(768,768,Image.INTERPOLATE_NEAREST)
	checks["two_x_pixels_exact"] = two.get_size()==expected.get_size() and two.get_data()==expected.get_data()
	var file := FileAccess.open("res://godot_nearest_checks.json",FileAccess.WRITE)
	file.store_string(JSON.stringify(checks,"  "))
	var passed: bool = checks.import_lossless and checks.mipmaps_disabled and checks.filter_nearest and checks.one_x_pixels_exact and checks.two_x_pixels_exact
	get_tree().quit(0 if passed else 1)
