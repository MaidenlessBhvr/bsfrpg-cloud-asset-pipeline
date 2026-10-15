"""Future remote runtime API probe; no rendering, file saving or local bpy import."""
import json
import os
from pathlib import Path
import sys

def main():
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('AURELIA_REMOTE_EXPERIMENT')!='approved_v4_pilot':
        raise RuntimeError('Remote-only Blender API preflight.')
    import bpy
    assert bpy.app.version==(4,0,2),bpy.app.version_string
    assert bpy.app.build_options.cycles,'Ubuntu build lacks Cycles'
    scene=bpy.context.scene
    scene.render.engine='CYCLES';scene.cycles.device='CPU'
    for name in ['samples','seed','use_animated_seed','use_adaptive_sampling','use_denoising']:
        assert hasattr(scene.cycles,name),name
    material=bpy.data.materials.new('ApiProbe');material.use_nodes=True
    emission=material.node_tree.nodes.new('ShaderNodeEmission')
    output=material.node_tree.nodes.new('ShaderNodeOutputMaterial')
    assert emission.inputs.get('Color') and emission.inputs.get('Strength')
    assert output.inputs.get('Surface')
    material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    mesh=bpy.data.meshes.new('ApiProbe');mesh.from_pydata([(0,0,0),(1,0,0),(0,1,0)],[],[(0,1,2)])
    mesh.update();assert len(mesh.polygons)==1
    camera=bpy.data.cameras.new('ApiProbe');camera.type='ORTHO';camera.ortho_scale=772
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGBA';scene.render.image_settings.color_depth='8'
    scene.render.filter_size=0.01;scene.render.dither_intensity=0
    scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
    assert 'write_still' in bpy.ops.render.render.get_rna_type().properties
    assert 'filepath' in bpy.ops.wm.save_as_mainfile.get_rna_type().properties
    args=sys.argv[sys.argv.index('--')+1:]
    Path(args[0]).write_text(json.dumps({'status':'RUNTIME_API_PROBE_PASS_NOT_RENDER_QA',
        'blender_version':bpy.app.version_string,'cycles_cpu':True,'emission':True,'mesh':True,
        'orthographic_camera':True,'png_export_settings':True,'blend_save_operator':True,
        'render_executed':False},indent=2)+'\n')

if __name__=='__main__':main()
