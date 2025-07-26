# ============================================================
#  Advanced Decimate for Blender
#  Author: Slategray
#  Version: 1.1 | Release Date: 2025-07-26
# ------------------------------------------------------------
#  Description:
#      A one-click Blender script for mesh decimation
#      that preserves shape keys, UVs, vertex groups,
#      materials, and other essential mesh data.
#
#  Repository & Documentation:
#      https://github.com/slategraydev/Advanced_Decimate
# ============================================================

# ============================================================
#  IMPORTS
# ============================================================
import bpy
import numpy as np
import time
import mathutils
import bmesh

# ============================================================
#  REGISTRATION
# ============================================================
bl_info = {
    "name": "Advanced Decimate",
    "author": "Slategray",
    "version": (1, 1),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Tool",
    "description": "Decimates a mesh while preserving shape keys, UVs, vertex groups, and other data.",
    "warning": "",
    "doc_url": "",
    "category": "Object",
}

# ============================================================
#  CORE FUNCTIONS
# ============================================================
def manage_uv_seams(obj, mark_seams=True):
    """
    Identifies and marks UV seams on a given object.
    """
    bpy.context.view_layer.objects.active = obj

    if bpy.context.object.mode == 'EDIT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # The operator works on the active UV map, so exit if it doesn't exist.
    if not obj.data.uv_layers.active:
        return

    # Mark the edges on the UV island borders to outline the seams.
    if mark_seams:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.seams_from_islands()
        bpy.ops.object.mode_set(mode='OBJECT')

def get_decimation_mapping_kdtree(source_obj_to_decimate, decimate_ratio, use_iterative=False):
    """
    Get a precise vertex mapping using a KDTree and decimate the provided object.
    If iterative decimation is enabled, the object will be decimated gradually.
    """
    # Build a KDTree from the object's vertex positions before it gets decimated.
    # This allows us to map the new vertices back to the original vertex indices.
    source_vertex_count = len(source_obj_to_decimate.data.vertices)
    kdtree = mathutils.kdtree.KDTree(source_vertex_count)
    for i, v in enumerate(source_obj_to_decimate.data.vertices):
        kdtree.insert(v.co, i)
    kdtree.balance()

    # Need to clear the shape keys from the temporary object.
    if source_obj_to_decimate.data.shape_keys:
        source_obj_to_decimate.shape_key_clear()

    if use_iterative:
        # For iterative decimation, create a reference object to snap the vertices back to.
        # This prevents the vertices from drifting away from the original surface over all the iterations.
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = source_obj_to_decimate
        source_obj_to_decimate.select_set(True)
        bpy.ops.object.duplicate(linked=False)
        reference_obj = bpy.context.active_object
        reference_obj.name = source_obj_to_decimate.name + "_reference"
        reference_obj.hide_set(True)
        
        # Ensure we are operating on the correct object after duplication.
        bpy.context.view_layer.objects.active = source_obj_to_decimate

        # Get the initial polygon count to use as a baseline for gradual decimation.
        initial_poly_count = len(source_obj_to_decimate.data.polygons)
        if initial_poly_count == 0:
            bpy.data.objects.remove(reference_obj, do_unlink=True)
            return {}, source_obj_to_decimate

        # Gradually decimate the object in small steps for higher quality results.
        target_poly_count = int(initial_poly_count * decimate_ratio)
        current_poly_count = initial_poly_count
        step = 0.01 

        while current_poly_count > target_poly_count:
            # Calculate the number of polygons to aim for in the next step.
            polys_to_remove = int(initial_poly_count * step)
            next_target_poly_count = current_poly_count - polys_to_remove

            # Ensure we don't go below the final target.
            if next_target_poly_count < target_poly_count:
                next_target_poly_count = target_poly_count
            
            # The modifier's ratio is relative to the current mesh state.
            if current_poly_count > 0:
                modifier_ratio = next_target_poly_count / current_poly_count
            else:
                modifier_ratio = 0

            # Apply the decimation modifier.
            bpy.context.view_layer.objects.active = source_obj_to_decimate
            mod = source_obj_to_decimate.modifiers.new(name="Decimate", type='DECIMATE')
            mod.ratio = modifier_ratio
            mod.delimit = {'SEAM'}
            bpy.ops.object.modifier_apply(modifier=mod.name)

            # After each decimation step, snap the vertices back to the original surface.
            shrinkwrap_mod = source_obj_to_decimate.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
            shrinkwrap_mod.target = reference_obj
            shrinkwrap_mod.wrap_method = 'NEAREST_SURFACEPOINT'
            bpy.ops.object.modifier_apply(modifier=shrinkwrap_mod.name)

            # Update the current polygon count for the next iteration.
            current_poly_count = len(source_obj_to_decimate.data.polygons)
        
        # Clean up the reference object, we don't need it anymore.
        bpy.data.objects.remove(reference_obj, do_unlink=True)
    else:
        # Perform a single, direct decimation.
        bpy.context.view_layer.objects.active = source_obj_to_decimate
        mod = source_obj_to_decimate.modifiers.new(name="Decimate", type='DECIMATE')
        mod.ratio = decimate_ratio
        mod.delimit = {'SEAM'}
        bpy.ops.object.modifier_apply(modifier=mod.name)

    # Map each new vertex to its closest original vertex using the KDTree.
    vertex_mapping = {}
    for i, v_dec in enumerate(source_obj_to_decimate.data.vertices):
        co, index, dist = kdtree.find(v_dec.co)
        vertex_mapping[i] = index

    return vertex_mapping, source_obj_to_decimate

def apply_decimation_mapping_to_shape_key(shape_key_verts, vertex_mapping):
    """
    Apply the decimation mapping to a single shape key's vertex data.
    """
    if not vertex_mapping:
        return np.array([])
        
    decimated_verts_count = max(vertex_mapping.keys()) + 1
    decimated_verts = np.zeros((decimated_verts_count, 3), dtype=np.float32)
    
    # Map the decimated vertices to the original vertices.
    for decimated_idx, original_idx in vertex_mapping.items():
        if original_idx < len(shape_key_verts):
            decimated_verts[decimated_idx] = shape_key_verts[original_idx]
    
    return decimated_verts

def rebuild_data_on_decimated_object(source_obj, final_obj, shape_key_geometry, key_names, vertex_mapping, shape_key_values):
    """
    Rebuilds all the data (shape keys, materials, etc.) onto the final object
    using the decimation mapping and data from the source object.
    TODO:
    - Add adjustable user settings for the data transfer modifiers.
    """
    # Rename the decimated object to be more descriptive.
    final_obj.name = source_obj.name + "_Decimated"
    
    # Ran into some projection issues, need to align the new object to the source object.
    final_obj.matrix_world = source_obj.matrix_world

    # Recreate shape keys using the precise mapping.
    if key_names:
        for i, name in enumerate(key_names):
            shape_key_verts = shape_key_geometry[name]
            new_key = final_obj.shape_key_add(name=name, from_mix=(i == 0)) 
            
            decimated_verts = apply_decimation_mapping_to_shape_key(shape_key_verts, vertex_mapping)
            
            if decimated_verts.size > 0:
                new_key.data.foreach_set('co', decimated_verts.ravel())
                
        # Restore the original shape key values.
        if final_obj.data.shape_keys:
            final_keys = final_obj.data.shape_keys.key_blocks
            for name, value in shape_key_values.items():
                if name in final_keys:
                    final_keys[name].value = value
    
    # Start the data transfer process.
    # I think the Data Transfer modifier needs the source object to be visible.
    source_obj.hide_set(False)
    bpy.context.view_layer.objects.active = final_obj
    final_obj.select_set(True)

    # Transfer the vertex groups.
    vg_data_transfer_mod = final_obj.modifiers.new(name="VGroupTransfer", type='DATA_TRANSFER')
    vg_data_transfer_mod.object = source_obj
    vg_data_transfer_mod.use_vert_data = True
    vg_data_transfer_mod.data_types_verts = {'VGROUP_WEIGHTS'}
    vg_data_transfer_mod.vert_mapping = 'POLYINTERP_NEAREST'
    vg_data_transfer_mod.layers_vgroup_select_src = 'ALL'
    vg_data_transfer_mod.layers_vgroup_select_dst = 'NAME'
    bpy.ops.object.datalayout_transfer(modifier=vg_data_transfer_mod.name)
    bpy.ops.object.modifier_apply(modifier=vg_data_transfer_mod.name)
  
    # Clear all seams from the final mesh as they will not line up with the new topology.
    bpy.context.view_layer.objects.active = final_obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.mark_seam(clear=True)
    bpy.ops.object.mode_set(mode='OBJECT')
  
    # Transfer the custom normals.
    cn_data_transfer_mod = final_obj.modifiers.new(name="NormalTransfer", type='DATA_TRANSFER')
    cn_data_transfer_mod.object = source_obj
    cn_data_transfer_mod.use_loop_data = True
    cn_data_transfer_mod.data_types_loops = {'CUSTOM_NORMAL'}
    cn_data_transfer_mod.loop_mapping = 'NEAREST_POLYNOR'
    bpy.ops.object.datalayout_transfer(modifier=cn_data_transfer_mod.name)
    bpy.ops.object.modifier_apply(modifier=cn_data_transfer_mod.name)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Link the materials from the source object.
    bpy.context.view_layer.objects.active = source_obj
    bpy.ops.object.make_links_data(type='MATERIAL')
    bpy.context.view_layer.objects.active = final_obj

    # Transfer the material assignments.
    source_bm = bmesh.new()
    source_bm.from_mesh(source_obj.data)
    source_bm.transform(source_obj.matrix_world) 

    # Iterate through the source object's faces and build a KDTree of their centers.
    poly_count = len(source_bm.faces)
    kd = mathutils.kdtree.KDTree(poly_count)
    for i, face in enumerate(source_bm.faces):
        kd.insert(face.calc_center_median(), i)
    kd.balance()

    # Get the target BMesh.
    target_bm = bmesh.new()
    target_bm.from_mesh(final_obj.data)
    target_bm.transform(final_obj.matrix_world)
    target_bm.faces.ensure_lookup_table()
    source_bm.faces.ensure_lookup_table()

    # For each target face, find the closest source face and copy its material index and smooth flag.
    for face in target_bm.faces:
        co, index, dist = kd.find(face.calc_center_median())
        if index is not None:
            source_face = source_bm.faces[index]
            face.material_index = source_face.material_index
            face.smooth = source_face.smooth

    # Write the changes back to the mesh and clean up BMesh data.
    target_bm.to_mesh(final_obj.data)
    source_bm.free()
    target_bm.free()

    # Set the parent and transforms.
    if source_obj.parent:
        final_obj.parent = source_obj.parent
        final_obj.parent_type = source_obj.parent_type
    final_obj.matrix_world = source_obj.matrix_world

    # Recreate the armature modifier if it exists.
    for mod in source_obj.modifiers:
        if mod.type == 'ARMATURE' and mod.object:
            armature_mod = final_obj.modifiers.new(name=mod.name, type='ARMATURE')
            armature_mod.object = mod.object

    # Finalize the shading settings from the source object.
    if hasattr(source_obj.data, 'use_auto_smooth'):
        final_obj.data.use_auto_smooth = source_obj.data.use_auto_smooth
        final_obj.data.auto_smooth_angle = source_obj.data.auto_smooth_angle
    
    final_obj.data.update()
    return final_obj

# ============================================================
#  OPERATOR
# ============================================================
class OBJECT_OT_advanced_decimate(bpy.types.Operator):
    """
    The main operator to perform the advanced decimation.
    """
    bl_idname = "object.advanced_decimate"
    bl_label = "Advanced Decimate"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        start_time = time.time()

        if context.object and context.object.mode == 'EDIT':
            bpy.ops.object.mode_set(mode='OBJECT')
        
        decimate_ratio = context.scene.adv_decimate_ratio
        use_iterative = context.scene.adv_decimate_iterative
        
        source_obj = bpy.context.active_object
        if source_obj is None or source_obj.type != 'MESH':
            self.report({'ERROR'}, "Please select a valid mesh object.")
            return {'CANCELLED'}

        # Ensure the original object is the only one selected to avoid duplicating others.
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = source_obj
        source_obj.select_set(True)

        # Create a full, unlinked duplicate of the source object to work on.
        bpy.ops.object.duplicate(linked=False)
        source_copy_obj = context.active_object
        source_copy_obj.name = source_obj.name + "_temp_copy"
        source_copy_obj.modifiers.clear()
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        
        # Mark the seams on the duplicated object so they can be preserved during decimation.
        manage_uv_seams(source_copy_obj, mark_seams=True)
        
        shape_keys = source_obj.data.shape_keys
        shape_key_geometry = {}
        key_names = []
        shape_key_values = {}

        if shape_keys:
            key_names = [key.name for key in shape_keys.key_blocks]
            
            # Directly read the absolute vertex coordinates from each shape key block.
            for key_block in source_obj.data.shape_keys.key_blocks:
                name = key_block.name
                shape_key_values[name] = key_block.value
                vertex_count = len(key_block.data)
                coords = np.empty(vertex_count * 3, dtype=np.float32)
                key_block.data.foreach_get('co', coords)
                shape_key_geometry[name] = coords.reshape(-1, 3)
        else:
            print("INFO: No shape keys found on the selected object. Proceeding without shape key data.")

        print("INFO: Performing the decimation on the duplicated object.")
        # The KDTree is built from the duplicated object with the transforms applied.
        vertex_mapping, decimated_obj = get_decimation_mapping_kdtree(source_copy_obj, decimate_ratio, use_iterative)
        print(f"INFO: Decimation complete! Mapped {len(source_copy_obj.data.vertices)} source vertices to {len(decimated_obj.data.vertices)} decimated vertices.")

        final_obj = rebuild_data_on_decimated_object(source_obj, decimated_obj, shape_key_geometry, key_names, vertex_mapping, shape_key_values)

        print(f"INFO: Advanced decimation complete in {time.time() - start_time:.2f} seconds!")
        self.report({'INFO'}, f"Generated: '{final_obj.name}'")
        source_obj.hide_set(True)
        return {'FINISHED'}

# ============================================================
#  UI PANEL
# ============================================================
class VIEW3D_PT_advanced_decimate(bpy.types.Panel):
    """
    Creates a Panel in the Object properties window.
    """
    bl_label = "Advanced Decimate"
    bl_idname = "VIEW3D_PT_advanced_decimate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Tool'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.label(text="Decimation Ratio:")
        layout.prop(scene, "adv_decimate_ratio", text="")
        layout.prop(scene, "adv_decimate_iterative")

        op = layout.operator("object.advanced_decimate", text="Run Decimation")

# ============================================================
#  REGISTRATION
# ============================================================
classes = (
    OBJECT_OT_advanced_decimate,
    VIEW3D_PT_advanced_decimate,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.adv_decimate_ratio = bpy.props.FloatProperty(
        name="Decimate Ratio",
        description="Target ratio for decimation. 0.5 = 50% of original faces.",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    bpy.types.Scene.adv_decimate_iterative = bpy.props.BoolProperty(
        name="Iterative Decimate (Slow)",
        description="Gradually decimates the mesh for higher quality results in lower poly meshes.",
        default=False,
    )

def unregister():
    # Unregister in reverse order to respect dependencies.
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
            
    if hasattr(bpy.types.Scene, 'adv_decimate_ratio'):
        del bpy.types.Scene.adv_decimate_ratio
    if hasattr(bpy.types.Scene, 'adv_decimate_iterative'):
        del bpy.types.Scene.adv_decimate_iterative

# ============================================================
#  MAIN
# ============================================================
if __name__ == "__main__":
    # For my own sanity, I'm unregistering any existing classes first.
    # This allows for re-running the script from the Text Editor.
    for cls in classes:
        if hasattr(bpy.types, cls.__name__):
            bpy.utils.unregister_class(getattr(bpy.types, cls.__name__))
            
    if hasattr(bpy.types.Scene, 'adv_decimate_ratio'):
        del bpy.types.Scene.adv_decimate_ratio
    if hasattr(bpy.types.Scene, 'adv_decimate_iterative'):
        del bpy.types.Scene.adv_decimate_iterative
    if hasattr(bpy.types.Scene, 'adv_decimate_use_shrinkwrap'):
        del bpy.types.Scene.adv_decimate_use_shrinkwrap

    register()