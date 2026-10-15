"""V4 world-coordinate masonry and remote-only Blender rendering.
Import is safe for local layout-math tests; bpy is gated. V3 is in history/v3.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
ALGORITHM = "aurelia_coursed_ashlar_v4_1"


def load_config(path=None):
    config = json.loads(Path(path or ROOT / "paving_config.json").read_text())
    assert config["algorithm"] == ALGORITHM
    assert config["cell_px"] == 32 and config["chunk_px"] == 256
    assert config["chunk_grid"] == [3, 3] and config["halo_px"] == 2
    assert len(config["palette_rgb"]) == 8
    return config


def value(config, domain, *coordinates):
    # No Python hash(), traversal-dependent PRNG or chunk-local random state.
    key = "|".join(map(str, [ALGORITHM, config["seed"], domain, *coordinates]))
    return int.from_bytes(hashlib.blake2b(key.encode("ascii"), digest_size=8).digest(), "big")


def choose(config, domain, coordinates, low, high):
    return low + value(config, domain, *coordinates) % (high - low + 1)


def intervals(low, high, length, anchor=0):
    """Signed renewal intervals anchored globally, never a modulo lattice.
    Origin scanning is sufficient for this pilot; city indexing is out of scope.
    """
    assert low < high and max(abs(low), abs(high), abs(anchor)) <= 8192
    result = []
    position, index = anchor, -1
    while position > low:
        start = position - length(index)
        if start < high and position > low:
            result.append((index, start, position))
        position, index = start, index - 1
    position, index = anchor, 0
    while position < high:
        end = position + length(index)
        if end > low:
            result.append((index, position, end))
        position, index = end, index + 1
    return sorted(result)


def bounds_for_pilot(config, halo=0):
    size = config["chunk_px"]
    x, y = config["first_chunk"]
    nx, ny = config["chunk_grid"]
    return (x*size-halo, y*size-halo, (x+nx)*size+halo, (y+ny)*size+halo)


def stones_in_bounds(config, bounds):
    """Whole globally identified stones intersecting the requested rectangle.
    Variable courses, staggered lengths, occasional split blocks and clipped
    polygonal corners remain coplanar. No walkability/collision is generated.
    """
    xmin, ymin, xmax, ymax = bounds
    rows = intervals(ymin, ymax, lambda r: choose(config, "course_height", (r,), *config["course_height_px"]))
    result = []
    for row, y0, y1 in rows:
        phase = choose(config, "course_phase", (row,), -18, 18)
        columns = intervals(xmin, xmax, lambda c: choose(config, "block_length", (row,c), *config["block_length_px"]), phase)
        for col, x0, x1 in columns:
            left = choose(config, "vertical_joint", (row,col), *config["joint_px"])/2
            right = choose(config, "vertical_joint", (row,col+1), *config["joint_px"])/2
            top = choose(config, "horizontal_joint", (row,), *config["joint_px"])/2
            bottom = choose(config, "horizontal_joint", (row+1,), *config["joint_px"])/2
            divisions = [(x0,x1,left,right)]
            if x1-x0 >= 36 and value(config, "split", row,col)%5 == 0:
                split = x0 + choose(config, "split_position", (row,col), 14, x1-x0-14)
                joint = choose(config, "split_joint", (row,col), *config["joint_px"])/2
                divisions = [(x0,split,left,joint),(split,x1,joint,right)]
            for child, (a,b,inset_a,inset_b) in enumerate(divisions):
                if b <= xmin or a >= xmax:
                    continue
                lx,rx,ty,by = a+inset_a,b-inset_b,y0+top,y1-bottom
                bevel = choose(config,"corner_clip",(row,col,child),1,2) if value(config,"polygonal",row,col,child)%3 == 0 else 0
                if bevel:
                    polygon = [(lx+bevel,ty),(rx-bevel,ty),(rx,ty+bevel),(rx,by-bevel),
                               (rx-bevel,by),(lx+bevel,by),(lx,by-bevel),(lx,ty+bevel)]
                else:
                    polygon = [(lx,ty),(rx,ty),(rx,by),(lx,by)]
                result.append({"id":[row,col,child],"bounds_px":[a,y0,b,y1],
                               "polygon_world_px":polygon,"palette_index":value(config,"color",row,col,child)%8,
                               "joint_insets_px":[inset_a,top,inset_b,bottom]})
    return sorted(result,key=lambda stone:stone["id"])


def linear_channel(v):
    v /= 255.0
    return v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4


def emission_material(bpy,name,rgb):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*[linear_channel(v) for v in rgb],1.0)
    emission.inputs["Strength"].default_value = 1.0
    material.node_tree.links.new(emission.outputs[0],output.inputs["Surface"])
    return material


def build_scene(bpy,config,stones,bounds):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.cycles.seed = config["seed"]
    scene.cycles.use_animated_seed = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.use_denoising = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.resolution_percentage = 100
    scene.render.filter_size = 0.01
    scene.render.dither_intensity = 0.0
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.use_nodes = False
    materials = [emission_material(bpy,"Ivory_%d"%i,rgb) for i,rgb in enumerate(config["palette_rgb"])]
    materials.append(emission_material(bpy,"WarmGrayJoint",config["grout_rgb"]))
    vertices,faces,material_ids = [],[],[]
    for stone in stones:
        offset = len(vertices)
        vertices.extend((x,-y,0.0) for x,y in stone["polygon_world_px"])
        faces.append(tuple(reversed(range(offset,len(vertices)))))
        material_ids.append(stone["palette_index"])
    xmin,ymin,xmax,ymax = bounds
    offset = len(vertices)
    vertices.extend([(xmin-1,-ymin+1,-0.01),(xmax+1,-ymin+1,-0.01),
                     (xmax+1,-ymax-1,-0.01),(xmin-1,-ymax-1,-0.01)])
    faces.append(tuple(reversed(range(offset,offset+4))))
    material_ids.append(len(materials)-1)
    mesh = bpy.data.meshes.new("WorldCoordinatePaving")
    mesh.from_pydata(vertices,[],faces)
    mesh.update()
    for material in materials:
        mesh.materials.append(material)
    for polygon,material_id in zip(mesh.polygons,material_ids):
        polygon.material_index = material_id
        polygon.use_smooth = False
    scene.collection.objects.link(bpy.data.objects.new("FlatVisualPaving_NoCollision",mesh))
    camera_data = bpy.data.cameras.new("NativePixelOrthographic")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = ymax-ymin
    camera_data.clip_start,camera_data.clip_end = 0.1,2000
    camera = bpy.data.objects.new("NativePixelOrthographic",camera_data)
    scene.collection.objects.link(camera)
    camera.location = ((xmin+xmax)/2,-(ymin+ymax)/2,1000)
    camera.rotation_euler = (0,0,0)
    scene.camera = camera
    scene.render.resolution_x,scene.render.resolution_y = xmax-xmin,ymax-ymin
    return scene


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("AURELIA_REMOTE_EXPERIMENT") != "approved_v4_pilot":
        raise RuntimeError("Remote-only draft: local Blender construction/render is not authorized.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,default=ROOT/"paving_config.json")
    parser.add_argument("--output-dir",type=Path,required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    config = load_config(args.config)
    output = args.output_dir
    output.mkdir(parents=True,exist_ok=True)
    bounds = bounds_for_pilot(config,config["halo_px"])
    stones = stones_in_bounds(config,bounds)
    import bpy  # Remote-only; never imported by layout/static tests.
    scene = build_scene(bpy,config,stones,bounds)
    for path in [Path(__file__),args.config,ROOT/"qa_cloud_paving.py",ROOT/"godot_visual_qa.gd"]:
        text = bpy.data.texts.new(path.name)
        text.write(path.read_text())
        (output/path.name).write_text(path.read_text())
    scene.render.filepath = str(output/"raw_world_render.png")
    scene["algorithm"],scene["seed"] = ALGORITHM,config["seed"]
    bpy.ops.wm.save_as_mainfile(filepath=str(output/"aurelia_world_paving.blend"))
    bpy.ops.render.render(write_still=True)
    metadata = {"status":"RENDERED_UNREVIEWED_NOT_APPROVED","algorithm":ALGORITHM,
                "blender_version":bpy.app.version_string,"seed":config["seed"],"config":config,
                "render_world_bounds_px":list(bounds),"render_size_px":[bounds[2]-bounds[0],bounds[3]-bounds[1]],
                "stone_count":len(stones),"stones":stones,
                "render_model":"one world field, flat emission, native orthographic CPU",
                "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "config_sha256":hashlib.sha256(args.config.read_bytes()).hexdigest()}
    (output/"generation_metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")


if __name__ == "__main__":
    main()
