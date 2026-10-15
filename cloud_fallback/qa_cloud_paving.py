"""V4 layout-math checks plus future rendered export/QA. No renderer is run here."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zlib
from PIL import __version__ as pillow_version
from PIL import Image
import blender_seamless_experiment as generator

ROOT = Path(__file__).resolve().parent


def intersects(a,b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def coordinates(config):
    ox,oy=config["first_chunk"]
    nx,ny=config["chunk_grid"]
    return [(x,y) for y in range(oy,oy+ny) for x in range(ox,ox+nx)]


def chunk_bounds(config,coordinate,halo=0):
    x,y=coordinate;size=config["chunk_px"]
    return x*size-halo,y*size-halo,(x+1)*size+halo,(y+1)*size+halo


def layout_qa(config):
    bounds=generator.bounds_for_pilot(config,config["halo_px"])
    stones=generator.stones_in_bounds(config,bounds)
    canonical={tuple(s["id"]):s for s in stones}
    assert len(canonical)==len(stones)
    assert stones==generator.stones_in_bounds(config,bounds)
    signatures=[]
    for coord in reversed(coordinates(config)):
        query=chunk_bounds(config,coord,config["halo_px"])
        independent={tuple(s["id"]):s for s in generator.stones_in_bounds(config,query)}
        expected={key:s for key,s in canonical.items() if intersects(s["bounds_px"],query)}
        assert independent==expected,('Chunk-dependent layout',coord)
        core=chunk_bounds(config,coord)
        shape=[[[x-core[0],y-core[1]] for x,y in s["polygon_world_px"]] for s in independent.values()]
        signatures.append(hashlib.sha256(json.dumps(shape).encode()).hexdigest())
    assert len(set(signatures))==9,'Repeated chunk geometry'
    heights=set();widths=set();rectangular=polygonal=0
    for s in stones:
        x0,y0,x1,y1=s["bounds_px"]
        heights.add(y1-y0);widths.add(x1-x0)
        assert 14 <= x1-x0 <= 46 and 18 <= y1-y0 <= 30
        assert all(0.5 <= v <= 1 for v in s["joint_insets_px"])
        assert all(x0 <= x <= x1 and y0 <= y <= y1 for x,y in s["polygon_world_px"])
        assert all(v*2==int(v*2) for point in s["polygon_world_px"] for v in point)
        if len(s["polygon_world_px"])==4:rectangular+=1
        else:polygonal+=1
    assert len(heights)>=6 and len(widths)>=12 and rectangular and polygonal
    # Clipping a road does not resize/reseed the stones. No navigation claim.
    strips=[]
    for width in [1,3,4,6]:
        query=(-256,0,512,width*32)
        field={tuple(s["id"]):s for s in generator.stones_in_bounds(config,query)}
        expected={key:s for key,s in canonical.items() if intersects(s["bounds_px"],query)}
        assert field==expected,('Road width changed stone scale',width)
        strips.append({'width_cells':width,'same_world_stones':True})
    return {'status':'LAYOUT_MATH_PASS_RENDER_PENDING','stone_count':len(stones),
            'independent_chunk_queries':9,'negative_coordinates_checked':True,
            'unique_chunk_geometry_signatures':9,'course_heights_px':sorted(heights),
            'block_widths_px':sorted(widths),'rectangular_stones':rectangular,
            'polygonal_stones':polygonal,'road_widths':strips,
            'guarantee':'Same global stone ID has exact same polygon/color across requests.',
            'limitations':'No rendered seam, pixel-art quality or Godot runtime result.'}


def compare_overlap(a,b,direction,halo):
    assert a.size==b.size
    w,h=a.size;span=halo*2
    if direction=='east':
        aa=a.crop((w-span,0,w,h));bb=b.crop((0,0,span,h))
    elif direction=='south':
        aa=a.crop((0,h-span,w,h));bb=b.crop((0,0,w,span))
    else:raise ValueError(direction)
    return aa.tobytes()==bb.tobytes()


def period_screen(image,grout):
    """Joint-mask F1 and exact color equality at plausible suspicious periods.
    A warning screen, not proof of non-repetition or an art approval gate.
    """
    image=image.convert('RGB');pixels=image.load();w,h=image.size
    result=[]
    for axis in ['x','y']:
        for lag in [16,32,64,128,256]:
            hits=first=second=equal=total=0
            for y in range(0,h-(lag if axis=='y' else 0),3):
                for x in range(0,w-(lag if axis=='x' else 0),3):
                    a=pixels[x,y];b=pixels[x+(lag if axis=='x' else 0),y+(lag if axis=='y' else 0)]
                    ga,gb=a==tuple(grout),b==tuple(grout)
                    first+=ga;second+=gb;hits+=ga and gb;equal+=a==b;total+=1
            f1=2*hits/max(1,first+second)
            result.append({'axis':axis,'lag_px':lag,'joint_mask_f1':round(f1,5),
                           'exact_rgb_fraction':round(equal/max(1,total),5),
                           'warning':f1>0.85 or equal/max(1,total)>0.98})
    return result


def point_inside(px,py,polygon):
    # Half-open ray crossing: explicit pixel-center coverage, no AA or resizing.
    inside=False
    last=polygon[-1]
    for current in polygon:
        x0,y0=last;x1,y1=current
        if (y0>py)!=(y1>py) and px < x0+(py-y0)*(x1-x0)/(y1-y0):
            inside=not inside
        last=current
    return inside


def pixel_center_export(config,bounds):
    """Native crisp projection of the same emitted planar Blender polygons.
    Uses global centers even for negative chunk coordinates. Executes on cloud
    during actual export; local tests use only tiny synthetic coverage fixtures.
    """
    xmin,ymin,xmax,ymax=bounds
    image=Image.new('RGBA',(xmax-xmin,ymax-ymin),tuple(config['grout_rgb'])+(255,))
    pixels=image.load()
    for stone in generator.stones_in_bounds(config,bounds):
        a,b,c,d=stone['bounds_px']
        color=tuple(config['palette_rgb'][stone['palette_index']])+(255,)
        for y in range(max(ymin,b),min(ymax,d)):
            for x in range(max(xmin,a),min(xmax,c)):
                if point_inside(x+0.5,y+0.5,stone['polygon_world_px']):
                    pixels[x-xmin,y-ymin]=color
    return image


def export_render(output):
    config=generator.load_config(output/'paving_config.json')
    assert json.loads((output/'generation_metadata.json').read_text())['config']==config
    layout=layout_qa(config)
    raw=Image.open(output/'raw_world_render.png').convert('RGBA')
    halo=config['halo_px'];size=config['chunk_px'];nx,ny=config['chunk_grid']
    expected=(size*nx+2*halo,size*ny+2*halo)
    assert raw.size==expected,'Native render dimensions changed'
    assert raw.getchannel('A').getextrema()==(255,255),'Surface has holes/transparency'
    # The same flat projected geometry is sampled at fixed GLOBAL pixel centers.
    # Cycles subpixel jitter must not make independently requested chunks diverge.
    render_bounds=generator.bounds_for_pilot(config,halo)
    field=pixel_center_export(config,render_bounds)
    delta=max_delta=0
    for rendered,crisp in zip(raw.getdata(),field.getdata()):
        differences=[abs(rendered[i]-crisp[i]) for i in range(3)]
        delta+=sum(differences);max_delta=max(max_delta,*differences)
    field.save(output/'world_field_with_halo.png')
    assembled=field.crop((halo,halo,halo+size*nx,halo+size*ny))
    assembled.save(output/'assembled_preview.png')
    chunks_dir=output/'chunks';guards_dir=output/'qa_halos'
    chunks_dir.mkdir(exist_ok=True);guards_dir.mkdir(exist_ok=True)
    ox,oy=config['first_chunk'];chunks=[];guards={};core_images={}
    for x,y in coordinates(config):
        lx,ly=(x-ox)*size,(y-oy)*size
        stem=f'chunk_{x}_{y}'
        core=field.crop((lx+halo,ly+halo,lx+halo+size,ly+halo+size))
        guard=field.crop((lx,ly,lx+size+halo*2,ly+size+halo*2))
        core.save(chunks_dir/(stem+'.png'));guard.save(guards_dir/(stem+'.png'))
        independent=pixel_center_export(config,chunk_bounds(config,(x,y),halo))
        assert guard.tobytes()==independent.tobytes(),('Independent world-pixel coverage differs',(x,y))
        guards[(x,y)]=guard;core_images[(x,y)]=core
        chunks.append({'chunk_coordinate':[x,y],'world_origin_px':[x*size,y*size],
                       'world_cell_origin':[x*size//32,y*size//32],'size_px':[size,size],
                       'png':'chunks/'+stem+'.png','halo_png':'qa_halos/'+stem+'.png',
                       'assembled_crop_px':[lx,ly,lx+size,ly+size]})
    seam_checks=[]
    for (x,y),guard in guards.items():
        for direction,next_coord in [('east',(x+1,y)),('south',(x,y+1))]:
            if next_coord in guards:
                passed=compare_overlap(guard,guards[next_coord],direction,halo)
                seam_checks.append({'from':[x,y],'to':list(next_coord),'direction':direction,
                                    'shared_world_pixel_overlap_px':halo*2,'exact_match':passed})
                assert passed,'Exported neighbor shared-coordinate seam differs'
    assert len(seam_checks)==12
    for entry in chunks:
        core=core_images[tuple(entry['chunk_coordinate'])]
        assert core.tobytes()==assembled.crop(tuple(entry['assembled_crop_px'])).tobytes()
    godot=output/'godot';godot.mkdir(exist_ok=True)
    shutil.copy2(output/'assembled_preview.png',godot/'paving_atlas.png')
    cells=[]
    for y in range(ny*size//32):
        for x in range(nx*size//32):
            cells.append({'world_cell':[ox*size//32+x,oy*size//32+y],
                          'source_id':0,'atlas_cell':[x,y]})
    atlas={'status':'UNREVIEWED_NOT_APPROVED','cell_size_px':[32,32],
           'atlas_grid_cells':[nx*size//32,ny*size//32],
           'texture':'paving_atlas.png','texture_size_px':list(assembled.size),
           'world_pixel_origin':[ox*size,oy*size],'cells':cells,
           'sampling':'nearest; lossless; no mipmaps/resize; no wrapping to a repeated master'}
    (godot/'atlas_data.json').write_text(json.dumps(atlas,indent=2)+'\n')
    shutil.copy2(ROOT/'godot_visual_qa.gd',godot/'PavingPilot.gd')
    (godot/'PavingPilot.tscn').write_text('[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://PavingPilot.gd" id="1"]\n[node name="PavingPilot" type="Node2D"]\nscript = ExtResource("1")\n')
    (godot/'project.godot').write_text('config_version=5\n[application]\nconfig/name="Aurelia V4 disposable visual QA"\nrun/main_scene="res://PavingPilot.tscn"\n[display]\nwindow/size/viewport_width=768\nwindow/size/viewport_height=768\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n')
    for width in [1,3,4,6]:
        # All strips show the same world origin/stone scale, not re-tiled samples.
        assembled.crop((0,256,assembled.width,256+width*32)).save(output/f'road_{width}_cells.png')
    (output/'chunk_coordinates.json').write_text(json.dumps({'seed':config['seed'],
         'algorithm':config['algorithm'],'chunks':chunks},indent=2)+'\n')
    screen=period_screen(assembled,config['grout_rgb'])
    result={'status':'EXPORT_CHECKS_PASS_VISUAL_QA_PENDING','layout_math':layout,
            'native_render_px':list(raw.size),'chunk_count':9,'chunk_core_px':256,
            'assembled_px':list(assembled.size),'shared_world_overlap_checks':seam_checks,
            'chunk_core_matches_reference':True,'atlas_cells':len(cells),'cell_alignment_px':32,
            'raw_vs_pixel_center_mean_abs_rgb':round(delta/(raw.width*raw.height*3),6),
            'raw_vs_pixel_center_max_channel_delta':max_delta,'palette_colors_used':len(set(field.getdata())),
            'periodicity_screen':screen,'periodicity_warning':any(r['warning'] for r in screen),
            'independent_chunk_pixel_coverage_checks':9,'seam_scope':'Independent global geometry and pixel-center raster requests match. Cycles raw field retained for projection/art QA; independent Cycles cameras not tested.',
            'python_version':sys.version,'pillow_version':pillow_version,'zlib_version':zlib.ZLIB_VERSION,
            'projection_warning':delta/(raw.width*raw.height*3)>3.0,
            'manual_visual_qa':'REQUIRED: joints, repeated course bands, stone scale, crisp pixels, 1x/2x architecture match.',
            'godot_runtime':'NOT_RUN; supplied disposable project captures/checks exact 1x/2x nearest pixels.'}
    (output/'rendered_qa.json').write_text(json.dumps(result,indent=2)+'\n')
    hashes={str(f.relative_to(output)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest()
            for f in output.rglob('*') if f.is_file() and f.name!='output_hashes.json'}
    (output/'output_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--layout-only',action='store_true')
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    if args.layout_only:
        print(json.dumps(layout_qa(generator.load_config()),indent=2))
    elif args.output_dir:
        print(json.dumps(export_render(args.output_dir),indent=2))
    else:parser.error('Choose --layout-only or --output-dir (future render required).')


if __name__=='__main__':main()
