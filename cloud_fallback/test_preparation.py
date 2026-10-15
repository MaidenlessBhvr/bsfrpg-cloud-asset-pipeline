"""Bounded local math/validator tests. No scene construction or artwork rendering."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import unittest
from PIL import Image
import blender_seamless_experiment as g
import qa_cloud_paving as qa

class PreparationTests(unittest.TestCase):
    def setUp(self):self.c=g.load_config()

    def test_layout_and_negative_neighbor_requests(self):
        result=qa.layout_qa(self.c)
        self.assertEqual(result['unique_chunk_geometry_signatures'],9)
        self.assertTrue(result['negative_coordinates_checked'])

    def test_query_order_does_not_change_shared_polygons(self):
        a={tuple(s['id']):s for s in g.stones_in_bounds(self.c,(-258,-258,2,2))}
        b={tuple(s['id']):s for s in g.stones_in_bounds(self.c,(-2,-258,258,2))}
        shared=set(a)&set(b)
        self.assertGreater(len(shared),0)
        self.assertTrue(all(a[key]==b[key] for key in shared))

    def test_seed_changes_layout_and_color(self):
        other=copy.deepcopy(self.c);other['seed']+=1
        self.assertNotEqual(g.stones_in_bounds(self.c,(-256,-256,256,256)),g.stones_in_bounds(other,(-256,-256,256,256)))

    def test_renewal_intervals_cover_both_sides_without_gaps(self):
        intervals=g.intervals(-80,90,lambda i:17+(i*i)%13,anchor=-9)
        intervals=sorted(intervals,key=lambda v:v[1])
        self.assertLessEqual(intervals[0][1],-80)
        self.assertGreaterEqual(intervals[-1][2],90)
        self.assertTrue(all(a[2]==b[1] for a,b in zip(intervals,intervals[1:])))

    def test_joint_width_is_shared_between_unsplit_neighbor_blocks(self):
        stones=g.stones_in_bounds(self.c,(-256,-256,512,512))
        for a in stones:
            for b in stones:
                if a['bounds_px'][2]==b['bounds_px'][0] and a['bounds_px'][1:4:2]==b['bounds_px'][1:4:2]:
                    self.assertEqual(a['joint_insets_px'][2],b['joint_insets_px'][0])

    def test_overlap_validator_rejects_cracks_and_wrong_axis(self):
        # Synthetic buffers only, never exported as art or used as a render stand-in.
        field=Image.new('RGBA',(20,20));field.putdata([(x*9,y*9,0,255) for y in range(20) for x in range(20)])
        a=field.crop((0,0,12,12));b=field.crop((8,0,20,12))
        self.assertTrue(qa.compare_overlap(a,b,'east',2))
        b.putpixel((1,4),(255,0,0,255))
        self.assertFalse(qa.compare_overlap(a,b,'east',2))
        c=field.crop((0,8,12,20))
        self.assertTrue(qa.compare_overlap(a,c,'south',2))
        c.putpixel((4,1),(255,0,0,255))
        self.assertFalse(qa.compare_overlap(a,c,'south',2))
        with self.assertRaises(ValueError):qa.compare_overlap(a,a,'west',2)

    def test_period_screen_detects_deliberate_repeated_fixture(self):
        image=Image.new('RGB',(64,64))
        image.putdata([(205,198,183) if x%16<2 or y%16<2 else (239,229,209) for y in range(64) for x in range(64)])
        result=qa.period_screen(image,self.c['grout_rgb'])
        self.assertTrue(any(r['lag_px']==16 and r['warning'] for r in result))

    def test_pixel_centers_have_fixed_half_open_coverage(self):
        polygon=[[-1.5,-1.5],[2.5,-1.5],[2.5,2.5],[-1.5,2.5]]
        self.assertTrue(qa.point_inside(-1.5,-1.5,polygon))
        self.assertFalse(qa.point_inside(2.5,0.5,polygon))
        self.assertFalse(qa.point_inside(0.5,2.5,polygon))
        clipped=[[-1,-2],[1,-2],[2,-1],[2,1],[1,2],[-1,2],[-2,1],[-2,-1]]
        self.assertTrue(qa.point_inside(0.5,0.5,clipped))
        self.assertFalse(qa.point_inside(1.5,1.75,clipped))

    def test_independent_pixel_export_uses_global_centers(self):
        fixture={'id':[0,0,0],'bounds_px':[-4,-4,8,8],
                 'polygon_world_px':[[-3.5,-3.5],[7.5,-3.5],[7.5,7.5],[-3.5,7.5]],'palette_index':2}
        # Only a 12px synthetic rectangle is rasterized; no candidate art/files.
        with patch.object(g,'stones_in_bounds',return_value=[fixture]):
            whole=qa.pixel_center_export(self.c,(-4,-4,8,8))
            a=qa.pixel_center_export(self.c,(-4,-4,4,4))
            b=qa.pixel_center_export(self.c,(0,-4,8,4))
            self.assertEqual(a.tobytes(),whole.crop((0,0,8,8)).tobytes())
            self.assertTrue(qa.compare_overlap(a,b,'east',2))

    def test_remote_gate_precedes_bpy_import(self):
        env=os.environ.copy();env.pop('GITHUB_ACTIONS',None);env.pop('AURELIA_REMOTE_EXPERIMENT',None)
        result=subprocess.run([sys.executable,str(g.ROOT/'blender_seamless_experiment.py')],env=env,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Remote-only draft',result.stderr)
        self.assertNotIn('No module named',result.stderr)

    def test_unsupported_large_run_configuration_rejected(self):
        bad=copy.deepcopy(self.c);bad['chunk_grid']=[30,30]
        with patch.object(Path,'read_text',return_value=json.dumps(bad)):
            with self.assertRaises(AssertionError):g.load_config()

if __name__=='__main__':unittest.main(verbosity=2)
